import asyncio
from dataclasses import replace

import pytest

import relf_agent as r
from relf_agent.errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    RuntimeClosed,
    ValidationError,
)

from .helpers import ScriptedProvider
from .temporal_agent_fixture import StateClient, engine, worker_runtime
from .test_agent_runtime import engine as local_engine


@pytest.mark.parametrize("sequence", [False, True])
def test_common_agent_entry_preserves_remote_approval_and_original_receipts(monkeypatch, sequence):
    async def scenario():
        raw = engine(monkeypatch)
        spec = r.AgentSpec("a", "Answer", ("lookup",))
        definition = (
            r.WorkflowSpec("sequence", [spec, r.AgentSpec("b", "Finish")]) if sequence else spec
        )
        async with r.Runtime.from_temporal(raw) as runtime:
            agent = runtime.create_agent(definition)
            run = await agent.submit("q", command_id="submit")
            observed = await run.wait(wait_timeout=1)
            assert observed.snapshot.state == "waiting_approval"
            assert raw.client.tool_calls == 0
            assert (await agent.submit("q", command_id="submit")).receipt == run.receipt
            controls = await run.pending()
            assert len(controls) == 1 and controls[0]["ref"] == run.ref.to_dict()
            item = controls[0]
            receipt = await run.approve(item["action_id"], item["digest"], command_id="approve")
            assert (
                await run.approve(item["action_id"], item["digest"], command_id="approve")
                == receipt
            )
            assert (await run.wait(wait_timeout=1)).snapshot.result == "done"
            assert raw.client.tool_calls == 1
            assert await runtime.areference(run.ref.run_id) == run.ref
            attached = await runtime.aattach(r.RunRef.from_dict(run.ref.to_dict()))
            assert (await attached.status()).state == "succeeded"
            assert await run.events()
            assert (await run.diagnostics()).release_digest == run.ref.release_digest
            await agent.aclose()
            assert (await run.status()).state == "succeeded"
        assert not raw._closed and not raw.client.closed
        with pytest.raises(RuntimeClosed):
            await run.status()

    asyncio.run(scenario())


def test_additive_async_local_attachment_keeps_reference_and_observation_pure(tmp_path):
    async def scenario():
        raw = local_engine(
            tmp_path / "local.sqlite", ScriptedProvider([r.ModelResponse(output="ok")])
        )
        async with r.Runtime(raw, owned=True) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            await run.wait(wait_timeout=1)
            before = len(raw.events(run.ref.run_id))
            assert await runtime.areference(run.ref.run_id) == run.ref
            assert (await (await runtime.aattach(run.ref)).status()).result == "ok"
            assert len(raw.events(run.ref.run_id)) == before

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "definition",
    [
        r.TeamSpec("t", {"a": r.AgentSpec("a", "A")}),
        r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=r.AgentSpec("a", "A"))]),
        r.AgentDefinition(r.AgentSpec("a", "A"), r.AgentBindingDescriptor()),
    ],
)
def test_remote_facade_refuses_unsupported_definitions_before_rpc(monkeypatch, definition):
    async def scenario():
        raw = engine(monkeypatch, release=worker_runtime().manifest)
        async with r.Runtime.from_temporal(raw) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(definition).submit("q", command_id="s")
            assert not raw.client.states and not raw.client.registries

    asyncio.run(scenario())


@pytest.mark.parametrize("options", [{"session_id": "s"}, {"queue": True}, {"deadline_at": 1}])
def test_remote_facade_refuses_unimplemented_lifecycle_before_rpc(monkeypatch, options):
    async def scenario():
        raw = engine(monkeypatch)
        async with r.Runtime.from_temporal(raw) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            with pytest.raises(ValidationError):
                await agent.submit("q", command_id="s", **options)
            with pytest.raises(ValidationError):
                await agent.open_session("s", command_id="open")
            assert not raw.client.states and not raw.client.registries

    asyncio.run(scenario())


def test_remote_refs_validate_scope_resource_release_and_current_client(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            before = len(raw.client.states[run.ref.run_id].command_digests)
            for ref, error in [
                (replace(run.ref, principal="other"), AuthorizationDenied),
                (replace(run.ref, authority_locator="other"), DefinitionMismatch),
                (replace(run.ref, release_digest="1" * 64), DefinitionMismatch),
            ]:
                with pytest.raises(error):
                    await runtime.aattach(ref)
            with pytest.raises(ValidationError):
                runtime.attach(run.ref)
            with pytest.raises(ValidationError):
                runtime.reference(run.ref.run_id)
            assert len(raw.client.states[run.ref.run_id].command_digests) == before
            old_client = raw.client
            raw.client = StateClient("elsewhere:7233")
            with pytest.raises(DefinitionMismatch):
                await run.cancel(command_id="wrong-route")
            raw.client = old_client
        other = engine(monkeypatch, client=StateClient("elsewhere:7233"))
        async with r.Runtime.from_temporal(other) as runtime:
            with pytest.raises(DefinitionMismatch):
                await runtime.aattach(run.ref)

    asyncio.run(scenario())


def test_remote_original_submit_release_survives_default_move(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        spec = r.AgentSpec("a", "A")
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(spec).submit("q", command_id="s")
            raw._release = {**raw.release, "policy": {"kind": "moved"}}
            replay = await runtime.create_agent(spec).submit("q", command_id="s")
            assert replay.receipt == run.receipt and replay.ref == run.ref
            assert len(raw.client.states) == 1

    asyncio.run(scenario())
