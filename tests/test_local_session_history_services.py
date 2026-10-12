"""Actual independently replaceable Redis/PostgreSQL native member histories."""

import asyncio
from collections import defaultdict

import pytest

import ralf_agent as r
from ralf_agent.binding_paths import agent_paths
from ralf_agent.spec_codec import encode_spec
from tests.test_local_session_history_compositions import MemberProvider, definition
from tests.test_local_session_model_history import tools
from tests.test_native_history_remote import endpoint as endpoint
from tests.test_native_history_remote import remote


@pytest.mark.parametrize(
    "kind", ["agent", "sequence", "graph", "parallel", "team", "nested", "dynamic", "dynamic-dag"]
)
@pytest.mark.parametrize("facade", [False, True])
def test_actual_remote_two_turns_publish_original_member_history(tmp_path, endpoint, kind, facade):
    async def scenario():
        async with remote(endpoint) as (backend, scope, _):
            await backend.initialize_session_identity()
            namespace = "native-red"
            resource = r.SessionBindingResource(
                backend, namespaces=(namespace,), default_namespace=namespace
            )
            requests, roots = [], []
            spec = (
                r.AgentSpec("a", "member-a", ("lookup",), max_context_chars=24000)
                if kind == "agent"
                else definition(kind)
            )
            catalog = r.BindingCatalog(scope=scope)
            catalog.register("session", "native", "1", resource)
            binding = r.AgentBindingDescriptor(session=r.BindingSelection.ref("native", "1"))
            spec = (
                r.AgentDefinition(spec, binding)
                if kind == "agent"
                else r.BoundDefinition(
                    spec, {path: binding for path in agent_paths(encode_spec(spec))}
                )
            )

            def make():
                return r.LocalEngine(
                    r.SQLiteStore(tmp_path / "runs.sqlite"),
                    providers={"default": MemberProvider(requests)},
                    tools=tools(),
                    scope=scope,
                    session_store=backend,
                    binding_catalog=catalog,
                    conversation_resource=resource,
                    model_continuation=True,
                    model_history=r.CompleteModelHistory(scope="session"),
                )

            if facade:
                session_ref = None
                for seq, task in enumerate(("first-task", "second-task")):
                    engine = make()
                    async with r.Runtime(engine, owned=True) as runtime:
                        session = (
                            await runtime.create_agent(spec).open_session("same", command_id="open")
                            if session_ref is None
                            else runtime.attach_session(session_ref)
                        )
                        handle = await session.submit(task, command_id=f"turn-{seq}", budget=64)
                        waited = await handle.wait(wait_timeout=20)
                        assert waited.snapshot.state == "succeeded", engine.store.run(
                            handle.ref.run_id
                        ).get("error")
                        async with asyncio.timeout(5):
                            while (await session.status()).busy:  # noqa: ASYNC110 -- original actual save ownership
                                await asyncio.sleep(0.01)
                        roots.append(engine.store.run(handle.ref.run_id))
                        session_ref = session.ref
            else:
                for seq, task in enumerate(("first-task", "second-task")):
                    with make() as engine:
                        handle = engine.submit(
                            spec, task, session_id="same", command_id=f"turn-{seq}", budget=64
                        )
                        snapshot = await engine.drive(handle.run_id)
                        assert snapshot.state == "succeeded", engine.store.run(handle.run_id).get(
                            "error"
                        )
                        roots.append(engine.store.run(handle.run_id))
            by_member = defaultdict(list)
            for request in requests:
                by_member[request[0]["content"]].append(request)
            assert len(by_member) == (1 if kind == "agent" else 2)
            for member, actual in by_member.items():
                assert len(actual) == 4
                assert [m["role"] for m in actual[2][:6]] == [
                    "system",
                    "user",
                    "assistant",
                    "tool",
                    "assistant",
                    "user",
                ]
                assert actual[2][4]["model_continuation"]["data"]["signature"] == "final-" + member
            assert roots[0]["result"] == roots[1]["result"]

    asyncio.run(scenario())
