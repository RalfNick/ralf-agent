"""Remote final-result recovery bypasses composite reasoning and children."""

import asyncio
import copy

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch

from .composite_session_fixture import definitions, engine
from .remote_session_fixture import RemoteMemory
from .test_remote_session_recovery import settled


def raw_at(path, backend, namespace=None, **opts):
    return engine(
        path,
        conversation_resource=r.SessionBindingResource(
            backend, namespaces=(namespace,), default_namespace=namespace
        ),
        **opts,
    )


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
@pytest.mark.parametrize("namespace", [None, "red"])
def test_lost_remote_root_ack_restart_reuses_accepted_result(tmp_path, kind, namespace):
    async def scenario():
        path, data = tmp_path / "run.sqlite", tmp_path / "data.sqlite"
        backend = RemoteMemory(data)
        backend.fail_after_append = 1
        try:
            async with r.Runtime(raw_at(path, backend, namespace), owned=True) as runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one", budget=128)
                assert (await one.wait(wait_timeout=2)).snapshot.state == "waiting_reconciliation"
                await settled(runtime)
                assert (await session.status()).busy
                before = runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[
                    0
                ]
                last = (await one.events())[-1].seq
                ref, sref = one.ref, session.ref
                assert backend.append_calls == 1
        finally:
            backend.close()
        backend = RemoteMemory(data)
        try:
            async with r.Runtime(raw_at(path, backend, namespace), owned=True) as runtime:
                session = runtime.attach_session(sref)
                one = await runtime.resume(ref)
                assert (
                    await one.wait(wait_timeout=2, terminal_only=True)
                ).snapshot.state == "succeeded"
                await settled(runtime)
                assert not (await session.status()).busy
                assert runtime.engine.providers["default"].calls == backend.append_calls == 0
                assert (
                    runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0]
                    == before
                )
                events = await one.events(after=last)
                assert {e.kind for e in events} <= {
                    "run_resumed",
                    "remote_session_save_confirmed",
                    "session_turn_result_committed",
                    "run_succeeded",
                    "workflow_quiesced",
                }
                assert any(e.kind == "session_turn_result_committed" for e in events)
                assert backend.memory.read(r.Scope(), sref.key.storage_key)[0] == 1
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_cancelled_unknown_root_recovery_only_queries(tmp_path, kind):
    async def scenario():
        backend = RemoteMemory(tmp_path / "data.sqlite")
        backend.fail_after_append = 1
        try:
            async with r.Runtime(raw_at(tmp_path / "run.sqlite", backend), owned=True) as runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one", budget=128)
                await one.wait(wait_timeout=2)
                await settled(runtime)
                backend.receipt_override = lambda value: {**value, "receipt": None}
                await one.cancel(command_id="cancel")
                await settled(runtime)
                assert (await one.status()).state == "cancelled" and (await session.status()).busy
                calls = runtime.engine.providers["default"].calls
                backend.receipt_override = None
                await one.resume()
                await settled(runtime)
                assert (await one.status()).state == "cancelled" and not (
                    await session.status()
                ).busy
                assert (
                    backend.append_calls == 1 and runtime.engine.providers["default"].calls == calls
                )
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["missing", "empty", "marker"])
@pytest.mark.parametrize("kind", ["graph", "team"])
def test_terminal_root_metadata_loss_refuses_capacity_release(tmp_path, damage, kind):
    async def scenario():
        backend = RemoteMemory(tmp_path / "data.sqlite")
        backend.fail_after_append = 1
        try:
            async with r.Runtime(raw_at(tmp_path / "run.sqlite", backend), owned=True) as runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one", budget=128)
                await one.wait(wait_timeout=2)
                await settled(runtime)
                backend.receipt_override = lambda value: {**value, "receipt": None}
                await one.cancel(command_id="cancel")
                await settled(runtime)
                store = runtime.engine.store
                with store.transaction():
                    run = store.run(one.ref.run_id)
                    original = copy.deepcopy(run)
                    if damage == "missing":
                        del run["remote_session_saves"]
                    elif damage == "empty":
                        run["remote_session_saves"] = {}
                    else:
                        del run["workflow" if kind == "graph" else "orchestration"][
                            "remote_session_result"
                        ]
                    store.save_run(run)
                try:
                    with pytest.raises(DefinitionMismatch):
                        await session.status()
                    with pytest.raises(DefinitionMismatch):
                        await one.pending()
                    with pytest.raises(DefinitionMismatch):
                        await runtime.engine.drive(one.ref.run_id)
                finally:
                    with store.transaction():
                        original["revision"] = store.run(one.ref.run_id)["revision"]
                        store.save_run(original)
                assert backend.append_calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "team", "plan", "dag", "nested"])
def test_remote_root_approval_restart_and_single_business_effect(tmp_path, kind):
    async def scenario():
        import sqlite3

        path, data = tmp_path / "run.sqlite", tmp_path / "data.sqlite"
        business = tmp_path / "business.sqlite"
        with sqlite3.connect(business) as c:
            c.execute("CREATE TABLE effects (id TEXT PRIMARY KEY)")
        tools = r.ToolRegistry()

        def handler(args, ctx):
            with sqlite3.connect(business) as c:
                c.execute("INSERT INTO effects VALUES (?)", (ctx.action_id,))
            return {"applied": True}

        tools.register(
            r.ToolSpec(
                "write",
                "Write",
                {"type": "object"},
                effect="idempotent_write",
                requires_approval=True,
            ),
            handler,
        )
        backend = RemoteMemory(data)
        try:
            async with r.Runtime(raw_at(path, backend, tools=tools), owned=True) as runtime:
                session = await runtime.create_agent(definitions(("write",))[kind]).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one", budget=128)
                assert (await one.wait(wait_timeout=2)).snapshot.state == "waiting_approval"
                await settled(runtime)
                ref, sref = one.ref, session.ref
                approval = (await one.pending())[0]
                assert backend.append_calls == 0 and (await session.status()).busy
        finally:
            backend.close()
        backend = RemoteMemory(data)
        backend.fail_after_append = 1
        try:
            async with r.Runtime(raw_at(path, backend, tools=tools), owned=True) as runtime:
                session = runtime.attach_session(sref)
                one = runtime.attach(ref)
                owner = runtime.attach(r.RunRef.from_dict(approval["ref"]))
                original = await owner.approve(
                    approval["action_id"], approval["digest"], command_id="approve"
                )
                await settled(runtime)
                assert (await one.status()).state == "waiting_reconciliation"
                await one.resume()
                assert (
                    await one.wait(wait_timeout=2, terminal_only=True)
                ).snapshot.state == "succeeded"
                await settled(runtime)
                assert backend.append_calls == 1 and not (await session.status()).busy
                assert (
                    await owner.approve(
                        approval["action_id"], approval["digest"], command_id="approve"
                    )
                    == original
                )
                with sqlite3.connect(business) as c:
                    assert c.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
        finally:
            backend.close()

    asyncio.run(scenario())


def test_remote_native_composite_idle_rebind_preserves_one_address(tmp_path):
    async def scenario():
        from ralf_agent.binding_catalog import BindingCatalog

        backend = RemoteMemory(tmp_path / "data.sqlite")
        catalog = BindingCatalog(scope=r.Scope())
        resource = r.SessionBindingResource(backend, namespaces=("red",), default_namespace="red")
        catalog.register("session", "history", "1", resource)
        native = r.AgentDefinition(
            r.AgentSpec("a", "Answer"),
            r.AgentBindingDescriptor(session=r.BindingSelection.ref("history", "1")),
        )
        try:
            async with r.Runtime(
                raw_at(tmp_path / "run.sqlite", backend, "red", binding_catalog=catalog), owned=True
            ) as runtime:
                session = await runtime.create_agent(native).open_session("s", command_id="open")
                first = await session.submit("q", command_id="one")
                await first.wait(wait_timeout=2)
                await settled(runtime)
                changed = await session.rebind(
                    definitions()["team"], expected_binding_revision=1, command_id="rebind"
                )
                assert changed.ref.key == session.ref.key and changed.ref.binding_revision == 2
                second = await changed.submit("next", command_id="two")
                await second.wait(wait_timeout=2)
                await settled(runtime)
                native_again = await changed.rebind(
                    native, expected_binding_revision=2, command_id="rebind-back"
                )
                third = await native_again.submit("last", command_id="three")
                await third.wait(wait_timeout=2)
                await settled(runtime)
                assert third.turn.turn_seq == 3 and not (await native_again.status()).busy
                assert backend.memory.read(r.Scope(), session.ref.key.storage_key)[0] == 3
                assert len(await session.turns()) == 3
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
@pytest.mark.parametrize("failure", [False, True])
def test_cancellation_during_frozen_root_recovery_finishes_authoritatively(tmp_path, kind, failure):
    async def scenario():
        from ralf_agent.errors import MemoryBackendError

        backend = RemoteMemory(tmp_path / "data.sqlite")
        backend.fail_after_append = 1
        runtime = r.Runtime(raw_at(tmp_path / "run.sqlite", backend), owned=True)
        release = asyncio.Event()
        started = asyncio.Event()
        try:
            async with runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one", budget=128)
                await one.wait(wait_timeout=2)
                await settled(runtime)
                inspect = backend.inspect_message

                async def gate(*args):
                    started.set()
                    await release.wait()
                    if failure:
                        raise MemoryBackendError("Inspection unavailable")
                    return await inspect(*args)

                backend.inspect_message = gate
                await one.resume()
                await asyncio.wait_for(started.wait(), 1)
                try:
                    await one.cancel(command_id="cancel-during-recovery")
                finally:
                    release.set()
                await settled(runtime)
                assert (await one.status()).state == "cancelled"
                assert (await session.status()).busy == failure
                assert backend.append_calls == 1
        finally:
            release.set()
            if runtime.state != "closed":
                runtime.engine._fail(one.ref.run_id, "fixture-cleanup")
                await runtime.aclose()
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("concurrency", [1, 2])
def test_frozen_root_recovery_preserves_final_skipped_decisions(tmp_path, concurrency):
    async def scenario():
        backend = RemoteMemory(tmp_path / "data.sqlite")
        backend.fail_after_append = 1
        try:
            async with r.Runtime(raw_at(tmp_path / "run.sqlite", backend), owned=True) as runtime:
                graph = r.GraphWorkflowSpec(
                    "skip",
                    [
                        r.GraphNode(
                            "a",
                            transform="identity",
                            when=r.BranchCondition(r.ValueRef(), "different"),
                        )
                    ],
                    max_concurrency=concurrency,
                )
                session = await runtime.create_agent(graph).open_session("s", command_id="open")
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=2)
                await settled(runtime)
                await one.resume()
                assert (
                    await one.wait(wait_timeout=2, terminal_only=True)
                ).snapshot.state == "succeeded"
                await settled(runtime)
                assert (await one.diagnostics()).workflow["nodes"]["a"]["state"] == "skipped"
                events = await one.events()
                assert (
                    len(
                        [
                            e
                            for e in events
                            if e.kind == "workflow_node_skipped" and e.data["node_id"] == "a"
                        ]
                    )
                    == 1
                )
                assert backend.append_calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())
