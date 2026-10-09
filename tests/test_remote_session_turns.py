"""Remote Session data remains subordinate to the original local Turn authority."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider
from .remote_session_fixture import RemoteMemory
from .test_agent_runtime import engine
from .test_binding_execution import bound_catalog


def setup(path, data, responses, namespace=None):
    backend = RemoteMemory(data)
    catalog = bound_catalog()
    catalog.register(
        "session",
        "remote",
        "1",
        r.SessionBindingResource(backend, namespaces=(namespace,), default_namespace=namespace),
    )
    provider = ScriptedProvider(responses)
    raw = engine(path, provider, binding_catalog=catalog)
    return r.Runtime(raw, owned=True), backend, provider


def definition(kind="agent"):
    binding = r.AgentBindingDescriptor(session=r.BindingSelection.ref("remote", "1"))
    spec = r.AgentSpec("a", "Answer")
    if kind == "agent":
        return r.AgentDefinition(spec, binding)
    return r.BoundDefinition(
        r.WorkflowSpec("w", [spec, r.AgentSpec("b", "Answer")]),
        {"sequence/steps/0": binding, "sequence/steps/1": binding},
    )


@pytest.mark.parametrize("kind", ["agent", "sequence"])
@pytest.mark.parametrize("namespace", [None, "red"])
def test_remote_turns_namespace_history_and_pure_observation(tmp_path, kind, namespace):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite",
            tmp_path / "data.sqlite",
            [r.ModelResponse(output=f"answer{i}") for i in range(4)],
            namespace,
        )
        try:
            async with runtime:
                session = await runtime.create_agent(definition(kind)).open_session(
                    "s", command_id="open"
                )
                assert (
                    runtime.engine.store.conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    == "5"
                )
                one = await session.submit("q", command_id="one")
                assert (await one.wait(wait_timeout=1)).snapshot.state == "succeeded"
                assert not (await session.status()).busy
                two = await session.submit("next", command_id="two")
                assert (await two.wait(wait_timeout=1)).snapshot.state == "succeeded"
                assert [t.turn_seq for t in await session.turns()] == [1, 2]
                address = session.ref.key.storage_key
                revision, messages = backend.memory.read(r.Scope(), address)
                assert revision == (2 if kind == "agent" else 4)
                assert messages[-1]["task"] == "next"
                assert "answer0" in r.types.canonical(provider.messages[1])
                before = (
                    backend.inspect_calls,
                    backend.read_calls,
                    backend.append_calls,
                    provider.calls,
                )
                await session.status()
                await session.turns()
                assert before == (
                    backend.inspect_calls,
                    backend.read_calls,
                    backend.append_calls,
                    provider.calls,
                )
                assert runtime.engine.sessions.read(r.Scope(), "s") == (0, [])
                assert (await session.submit("q", command_id="one")).receipt == one.receipt
        finally:
            backend.close()

    asyncio.run(scenario())


def test_registered_remote_address_refuses_raw_backend_alias(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(tmp_path / "run.sqlite", tmp_path / "data.sqlite", [])
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                with pytest.raises(ValidationError):
                    runtime.engine.submit(
                        r.AgentSpec("alias", "Answer"), "q", session_id="s", command_id="raw"
                    )
                assert provider.calls == 0 and not (await session.status()).busy
        finally:
            backend.close()

    asyncio.run(scenario())


def test_observe_original_remote_binding_after_current_catalog_disappears(tmp_path):
    async def scenario():
        runtime, backend, _ = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=1)
                runtime.engine.binding_catalog = bound_catalog()
                assert not (await session.status()).busy
                assert len(await session.turns()) == 1
                assert (await session.submit("q", command_id="one")).receipt == one.receipt
                with pytest.raises(DefinitionMismatch):
                    await session.submit("next", command_id="two")
        finally:
            backend.close()

    asyncio.run(scenario())
