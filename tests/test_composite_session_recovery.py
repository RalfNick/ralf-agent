import asyncio
import copy
import threading

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch, ValidationError

from .composite_session_fixture import Provider, definitions, engine, root_messages


@pytest.mark.parametrize("kind", ["team", "nested", "parallel"])
def test_real_cancelled_thread_and_unknown_effect_retain_whole_turn_after_restart(tmp_path, kind):
    async def scenario():
        started, release = threading.Event(), threading.Event()
        calls = []

        def write(arguments, context):
            calls.append(context.effect_key)
            started.set()
            release.wait(4)
            raise RuntimeError("lost effect receipt")

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("write", "Write", {"type": "object"}, effect="idempotent_write"), write
        )
        path = tmp_path / "recover.sqlite"
        raw = engine(path, tools=tools)
        runtime = r.Runtime(raw, owned=True)
        try:
            session = await runtime.create_agent(definitions(("write",))[kind]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            assert await asyncio.to_thread(started.wait, 1)
            await run.cancel(command_id="stop")
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="active", budget=64)
            release.set()
            await raw.wait_for_threads()
            await run.wait(wait_timeout=2, terminal_only=True)
            await asyncio.sleep(0.03)
            assert (await run.status()).state == "cancelled"
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="unknown", budget=64)
            session_ref, run_ref = session.ref, run.ref
        finally:
            release.set()
            await runtime.aclose()
        async with r.Runtime(engine(path, tools=tools), owned=True) as restored:
            session = restored.attach_session(session_ref)
            root = await restored.aattach(run_ref)
            assert (await session.status()).busy
            controls = await root.pending()
            assert controls and all(c["kind"] == "reconciliation" for c in controls)
            before = len(calls)
            for control in controls:
                owner = await restored.aattach(r.RunRef.from_dict(control["ref"]))
                await owner.reconcile(
                    control["action_id"],
                    {"accepted": True},
                    command_id="evidence:" + control["action_id"],
                )
            await root.wait(wait_timeout=1)
            await asyncio.sleep(0.03)
            assert not (await session.status()).busy
            assert len(calls) == before and root_messages(restored.engine, run_ref.run_id) == []
            # A new explicit Turn can now enter; no cancelled result is fabricated.
            rebound = await session.rebind(
                definitions()[kind], expected_binding_revision=1, command_id="rebind"
            )
            following = await rebound.submit("next", command_id="next", budget=64)
            assert following.turn.turn_seq == 2
            assert (await following.wait(wait_timeout=2)).snapshot.state == "succeeded"

    asyncio.run(scenario())


def test_real_async_handler_and_observer_cancellation_preserve_turn_ownership(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def write(arguments, context):
            started.set()
            await release.wait()
            return {"accepted": True}

        tools = r.ToolRegistry()
        tools.register(r.ToolSpec("write", "Read", {"type": "object"}, effect="read_only"), write)
        raw = engine(tmp_path / "async.sqlite", tools=tools)
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions(("write",))["team"]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            await asyncio.wait_for(started.wait(), 1)
            try:
                observer = asyncio.create_task(run.wait(wait_timeout=2))
                await asyncio.sleep(0)
                observer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await observer
                assert (await run.status()).state == "running"
                assert (await run.wait(wait_timeout=0.01)).wait_reason == "observation_timeout"
                await run.cancel(command_id="stop")
                with pytest.raises(r.SessionBusy):
                    await session.submit("next", command_id="active", budget=64)
                children = raw.store.run(run.ref.run_id)["orchestration"]["children"]
                assert any(raw._operation_active(child["run_id"]) for child in children)
                assert (await session.status()).busy
            finally:
                release.set()
            await run.wait(wait_timeout=2, terminal_only=True)
            deadline = asyncio.get_running_loop().time() + 2
            while (await session.status()).busy:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            assert not (await session.status()).busy
            assert (await run.status()).state == "cancelled"
            assert root_messages(raw, run.ref.run_id) == []

    asyncio.run(scenario())


@pytest.mark.parametrize("rejection", ["busy", "revision", "namespace", "remote"])
def test_rejected_composite_rebind_or_open_does_not_enable_schema3(tmp_path, rejection):
    async def scenario():
        raw = engine(tmp_path / "refusal.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            native = r.AgentSpec("a", "A")
            session = await runtime.create_agent(native).open_session("s", command_id="open")
            if rejection == "busy":
                tools = r.ToolRegistry()
                tools.register(
                    r.ToolSpec("write", "Write", {"type": "object"}, requires_approval=True),
                    lambda a, c: None,
                )
                raw.tools = tools
                session = await session.rebind(
                    r.AgentSpec("a", "A", ("write",)),
                    expected_binding_revision=1,
                    command_id="native",
                )
                pending = await session.submit("q", command_id="one")
                assert (await pending.wait(wait_timeout=2)).snapshot.state == "waiting_approval"
                with pytest.raises(r.SessionBusy):
                    await session.rebind(
                        definitions()["team"], expected_binding_revision=2, command_id="reject"
                    )
            elif rejection == "revision":
                with pytest.raises(r.SessionBindingMismatch):
                    await session.rebind(
                        definitions()["team"], expected_binding_revision=2, command_id="reject"
                    )
            else:
                if rejection == "remote":
                    raw.sessions = r.InMemoryMemory()
                else:
                    resource = r.SessionBindingResource(
                        raw.sessions, namespaces=("private",), default_namespace="private"
                    )
                    raw.sessions = resource.select({}, raw.scope)
                with pytest.raises(ValidationError):
                    await runtime.create_agent(definitions()["team"]).open_session(
                        "composite", command_id="reject"
                    )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "2"
            )

    asyncio.run(scenario())


def test_success_without_confirmed_root_message_cannot_release_turn(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "result.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            raw.store.conn.execute(
                "DELETE FROM memory_session_items WHERE message_id=?",
                (run.ref.run_id + ":turn:result",),
            )
            assert (await session.status()).busy
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="next", budget=64)

    asyncio.run(scenario())


def test_approval_busy_and_original_binding_receipts_survive_restart_and_alias_move(tmp_path):
    async def scenario():
        calls = []

        async def write(arguments, context):
            calls.append(context.effect_key)
            return {"accepted": True}

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec(
                "write",
                "Write",
                {"type": "object"},
                effect="idempotent_write",
                requires_approval=True,
            ),
            write,
        )
        path = tmp_path / "approval.sqlite"
        definition = definitions(("write",))["nested"]
        async with r.Runtime(engine(path, tools=tools), owned=True) as runtime:
            session = await runtime.create_agent(definition).open_session("s", command_id="open")
            original = await session.submit("q", command_id="one", budget=64)
            assert (await original.wait(wait_timeout=2)).snapshot.state == "waiting_approval"
            with pytest.raises(r.SessionBusy) as busy:
                await session.submit("new", command_id="busy", budget=64)
            ref, run_ref, receipt, turn = session.ref, original.ref, original.receipt, original.turn
            rejected = busy.value.receipt
        raw = engine(path, tools=tools)
        async with r.Runtime(raw, owned=True) as runtime:
            session = runtime.attach_session(ref)
            raw.providers.clear()
            replay = await session.submit("q", command_id="one", budget=64)
            assert replay.ref == run_ref and replay.receipt == receipt and replay.turn == turn
            with pytest.raises(r.SessionBusy) as busy:
                await session.submit("new", command_id="busy", budget=64)
            assert busy.value.receipt == rejected
            raw.providers["default"] = Provider()
            owner_ref = (await replay.pending())[0]
            owner = await runtime.aattach(r.RunRef.from_dict(owner_ref["ref"]))
            approval = await owner.approve(
                owner_ref["action_id"], owner_ref["digest"], command_id="approve"
            )
            assert (
                await owner.approve(
                    owner_ref["action_id"], owner_ref["digest"], command_id="approve"
                )
                == approval
            )
            assert (
                await replay.wait(wait_timeout=2, terminal_only=True)
            ).snapshot.state == "succeeded"
            with pytest.raises(r.SessionBusy) as busy:
                await session.submit("new", command_id="busy", budget=64)
            assert busy.value.receipt == rejected and len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "team", "dag", "nested"])
def test_idle_native_composite_rebind_is_cas_and_schema_upgrade_monotonic(tmp_path, kind):
    async def scenario():
        raw = engine(tmp_path / "rebind.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "s", command_id="open"
            )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "2"
            )
            composite = await session.rebind(
                definitions()[kind], expected_binding_revision=1, command_id="composite"
            )
            assert composite.ref.binding_revision == 2
            run = await composite.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            await asyncio.sleep(0.02)
            native = await composite.rebind(
                r.AgentSpec("a", "A"), expected_binding_revision=2, command_id="native"
            )
            assert native.ref.binding_revision == 3
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "3"
            )
            another = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "other", command_id="open-other"
            )
            assert another.ref.binding_revision == 1
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "3"
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["lazy", "raise", "foreign", "float-version"])
def test_composite_preparation_refuses_bad_extension_and_rolls_back_schema(tmp_path, mode):
    async def scenario():
        raw = engine(tmp_path / "prepare.sqlite")
        base = raw.store.create_session_admission()

        class Adapter:
            def __getattr__(self, name):
                return getattr(base, name)

            def prepare_composites(self):
                base.prepare_composites()
                if mode == "raise":
                    raise ValidationError("prepare failed")
                return deferred()

        async def deferred():
            raise AssertionError("never execute lazy prepare")

        adapter = Adapter()
        if mode == "foreign":
            adapter.transaction_owner = object()
        if mode == "float-version":
            raw.store.session_admission_version = 2.0
        else:
            raw.store.create_session_admission = lambda: adapter
        async with r.Runtime(raw, owned=True) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(definitions()["team"]).open_session(
                    "s", command_id="open"
                )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )
            assert raw.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ["parent", "call", "duplicate", "cycle"])
def test_malformed_persisted_descendant_ownership_cannot_release_turn(tmp_path, corruption):
    async def scenario():
        raw = engine(tmp_path / "ownership.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["nested"]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            await run.wait(wait_timeout=2)
            await asyncio.sleep(0.02)
            with raw.store.transaction():
                parent = raw.store.run(run.ref.run_id)
                call = parent["orchestration"]["children"][0]
                child = raw.store.run(call["run_id"])
                if corruption == "parent":
                    child["parent_id"] = "other"
                elif corruption == "call":
                    child["call_id"] = "other"
                elif corruption == "duplicate":
                    parent["orchestration"]["children"].append(copy.deepcopy(call))
                else:
                    call["run_id"] = parent["id"]
                raw.store.save_run(child)
                raw.store.save_run(parent)
            with pytest.raises(DefinitionMismatch):
                await session.status()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,path",
    [
        ("graph", "graph/nodes/a"),
        ("team", "team/members/worker"),
        ("dag", "dynamic/members/worker"),
        ("nested", "team/members/inner/graph/nodes/a"),
    ],
)
def test_composite_member_provider_binding_remains_selected_inside_shared_turn(
    tmp_path, kind, path
):
    async def scenario():
        default, selected = Provider(), Provider()
        raw = engine(tmp_path / "bound.sqlite", provider=default)
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register("provider", "selected", "1", selected)
        raw.binding_catalog = catalog
        bound = r.BoundDefinition(
            definitions()[kind],
            {path: r.AgentBindingDescriptor(provider=r.BindingSelection.ref("selected", "1"))},
        )
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(bound).open_session("s", command_id="open")
            run = await session.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            assert selected.calls == 1 and default.calls == 0
            assert len(root_messages(raw, run.ref.run_id)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "team"])
def test_composite_member_namespace_bindings_keep_original_addresses(tmp_path, kind):
    async def scenario():
        from relf_agent.binding_sessions import session_storage_key

        raw = engine(tmp_path / "member.sqlite")
        agent = r.AgentSpec("worker", "Answer")
        definition = (
            r.GraphWorkflowSpec(
                "graph", [r.GraphNode(name, agent=agent) for name in ("red", "blue")]
            )
            if kind == "graph"
            else r.TeamSpec("team", {name: agent for name in ("red", "blue")})
        )
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register(
            "session",
            "history",
            "1",
            r.SessionBindingResource(
                raw.sessions, namespaces=("red", "blue"), default_namespace="red"
            ),
        )
        raw.binding_catalog = catalog
        base = "graph/nodes/" if kind == "graph" else "team/members/"
        bound = r.BoundDefinition(
            definition,
            {
                base + name: r.AgentBindingDescriptor(
                    session=r.BindingSelection.ref("history", "1", selector={"namespace": name})
                )
                for name in ("red", "blue")
            },
        )
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(bound).open_session("s", command_id="open")
            run = await session.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            assert len(root_messages(raw, run.ref.run_id)) == 1
            root = raw.store.run(run.ref.run_id)
            if kind == "team":
                addresses = [
                    raw.store.run(call["run_id"])["session_id"]
                    for call in root["orchestration"]["children"]
                ]
                assert len(set(addresses)) == 2 and all(address != "s" for address in addresses)
            else:
                addresses = ["s", "s"]
            for name, address in zip(("red", "blue"), addresses, strict=True):
                revision, messages = raw.sessions.read(
                    raw.scope, session_storage_key(name, address)
                )
                assert revision == 1 and len(messages) == 1

    asyncio.run(scenario())
