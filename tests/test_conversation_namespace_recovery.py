import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch, ValidationError

from .composite_session_fixture import definitions, root_messages
from .conversation_namespace_fixture import engine


@pytest.mark.parametrize("kind", ["team", "nested", "parallel"])
def test_original_namespace_approval_and_receipts_survive_restart_default_move(tmp_path, kind):
    async def scenario():
        calls = []

        async def write(a, context):
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
        path = tmp_path / "restart.sqlite"
        async with r.Runtime(engine(path, tools=tools), owned=True) as runtime:
            session = await runtime.create_agent(definitions(("write",))[kind]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "waiting_approval"
            ref, run_ref, receipt, turn = session.ref, run.ref, run.receipt, run.turn
            with pytest.raises(r.SessionBusy) as rejected:
                await session.submit("new", command_id="busy", budget=64)
            busy_receipt = rejected.value.receipt
        raw = engine(path, default="blue", tools=tools)
        async with r.Runtime(raw, owned=True) as runtime:
            agent = runtime.create_agent(definitions(("write",))[kind])
            assert (await agent.open_session("s", command_id="open")).ref == ref
            session = runtime.attach_session(ref)
            replay = await session.submit("q", command_id="one", budget=64)
            assert replay.ref == run_ref and replay.receipt == receipt and replay.turn == turn
            await asyncio.sleep(0.02)
            controls = await replay.pending()
            for control in controls:
                raw.approve(
                    control["ref"]["run_id"],
                    control["action_id"],
                    control["digest"],
                    command_id="approve:" + control["action_id"],
                )
            with pytest.raises(DefinitionMismatch):
                await raw.drive(run_ref.run_id)
            assert calls == [] and (await session.status()).busy
            raw.conversation_resource = r.SessionBindingResource(
                raw.conversation_resource.backend,
                namespaces=(None, "red", "blue"),
                default_namespace="red",
            )
            for control in controls:
                owner = await runtime.aattach(r.RunRef.from_dict(control["ref"]))
                first = raw.store.conn.execute(
                    "SELECT receipt FROM commands WHERE id=?", ("approve:" + control["action_id"],)
                ).fetchone()[0]
                again = await owner.approve(
                    control["action_id"],
                    control["digest"],
                    command_id="approve:" + control["action_id"],
                )
                from dataclasses import asdict

                from relf_agent.types import canonical

                assert canonical(asdict(again)) == first
            assert (
                await replay.wait(wait_timeout=2, terminal_only=True)
            ).snapshot.state == "succeeded"
            await runtime._supervisor.drain()
            assert len(calls) == (2 if kind == "parallel" else 1) and len(set(calls)) == len(calls)
            assert (
                raw.store.conn.execute(
                    "SELECT session FROM memory_session_items WHERE message_id=?",
                    (run_ref.run_id + ":turn:result",),
                ).fetchone()[0]
                == 'ralf-session-v1:["red","s"]'
            )
            with pytest.raises(r.SessionBusy) as rejected:
                await session.submit("new", command_id="busy", budget=64)
            assert rejected.value.receipt == busy_receipt

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ["missing", "namespace", "parent-address", "turn-run"])
def test_malformed_original_conversation_record_refuses_before_model_dispatch(tmp_path, corruption):
    async def scenario():
        raw = engine(tmp_path / "malformed.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", namespace="red", command_id="open"
            )
            # Accept without starting a Facade host, then alter persisted evidence.
            receipt = runtime._session_authority().submit(
                session.ref, "q", command_id="one", budget=64
            )
            run_id = receipt.run_id
            with raw.store.transaction():
                state = runtime._session_authority().validate(session.ref)
                run = raw.store.run(run_id)
                if corruption == "missing":
                    del state["bindings"]["1"]["conversation"]
                elif corruption == "namespace":
                    state["bindings"]["1"]["conversation"]["namespace"] = "blue"
                elif corruption == "parent-address":
                    run["session_id"] = "s"
                else:
                    run["session_turn"]["run"]["run_id"] = "other"
                runtime._session_authority().store.save(state, expected_revision=state["revision"])
                raw.store.save_run(run)
            with pytest.raises(DefinitionMismatch):
                await raw.drive(run_id)
            assert raw.providers["default"].calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ["binding-missing", "run-missing", "run-changed"])
def test_configured_none_conversation_cannot_downgrade_to_legacy(tmp_path, corruption):
    async def scenario():
        effects = []

        def write(arguments, context):
            effects.append(context.effect_key)
            return {"accepted": True}

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("write", "Write", {"type": "object"}, effect="idempotent_write"), write
        )
        raw = engine(tmp_path / "none.sqlite", tools=tools)
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions(("write",))["team"]).open_session(
                "s", namespace=None, command_id="open"
            )
            receipt = runtime._session_authority().submit(
                session.ref, "q", command_id="one", budget=64
            )
            with raw.store.transaction():
                state = runtime._session_authority().validate(session.ref)
                run = raw.store.run(receipt.run_id)
                if corruption == "binding-missing":
                    del state["bindings"]["1"]["conversation"]
                    raw.conversation_resource = None
                elif corruption == "run-missing":
                    run.pop("conversation_binding", None)
                else:
                    run["conversation_binding"] = {"namespace": "blue"}
                runtime._session_authority().store.save(state, expected_revision=state["revision"])
                raw.store.save_run(run)
            with pytest.raises(DefinitionMismatch):
                await raw.drive(receipt.run_id)
            assert raw.providers["default"].calls == 0 and effects == []
            assert root_messages(raw, receipt.run_id) == []

    asyncio.run(scenario())


def test_legacy_turn_in_upgraded_database_keeps_original_default_route(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "mixed.sqlite")
        resource, raw.conversation_resource = raw.conversation_resource, None
        async with r.Runtime(raw, owned=True) as runtime:
            agent = runtime.create_agent(definitions()["team"])
            legacy = await agent.open_session("legacy", command_id="legacy-open")
            accepted = runtime._session_authority().submit(
                legacy.ref, "q", command_id="one", budget=64
            )
            raw.conversation_resource = resource
            await agent.open_session("configured", namespace=None, command_id="configured-open")
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "4"
            )
            raw.conversation_resource = None
            assert (await raw.drive(accepted.run_id)).state == "succeeded"
            assert len(root_messages(raw, accepted.run_id)) == 1
            assert "conversation_binding" not in raw.store.run(accepted.run_id)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["lazy", "false", "raise", "old-marker", "foreign"])
def test_failed_conversation_extension_rolls_back_activation_and_acceptance(tmp_path, mode):
    async def scenario():
        raw = engine(tmp_path / "port.sqlite")
        base = raw.store.create_session_admission()

        class Adapter:
            def __getattr__(self, name):
                return getattr(base, name)

            def prepare_conversations(self):
                base.prepare_conversations()
                if mode == "raise":
                    raise ValidationError("prepare failed")
                if mode == "false":
                    return False
                return deferred()

        async def deferred():
            raise AssertionError("never execute lazy prepare")

        adapter = Adapter()
        if mode == "foreign":
            adapter.transaction_owner = object()
        if mode == "old-marker":
            raw.store.session_admission_version = 2
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
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0

    asyncio.run(scenario())


def test_same_namespace_rebind_preserves_route_and_schema4_never_downgrades(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "rebind.sqlite")
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register("session", "root", "1", raw.conversation_resource)
        raw.binding_catalog = catalog
        native = r.AgentDefinition(
            r.AgentSpec("a", "A"),
            r.AgentBindingDescriptor(
                session=r.BindingSelection.ref("root", "1", selector={"namespace": "red"})
            ),
        )
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(native).open_session("s", command_id="native")
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "2"
            )
            composite = await session.rebind(
                definitions()["team"], expected_binding_revision=1, command_id="composite"
            )
            assert composite.ref.key == session.ref.key
            run = await composite.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            await runtime._supervisor.drain()
            updated = await composite.rebind(native, expected_binding_revision=2, command_id="back")
            assert updated.ref.key == session.ref.key
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "4"
            )
            with pytest.raises(r.SessionBindingMismatch):
                await updated.rebind(
                    r.AgentSpec("a", "A"), expected_binding_revision=3, command_id="different-route"
                )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "4"
            )

    asyncio.run(scenario())


def test_late_resource_drift_preserves_actual_tool_observation(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def write(a, context):
            calls.append(context.effect_key)
            started.set()
            await release.wait()
            return {"accepted": True}

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("write", "Write", {"type": "object"}, effect="idempotent_write"), write
        )
        raw = engine(tmp_path / "late.sqlite", tools=tools)
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions(("write",))["team"]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            await asyncio.wait_for(started.wait(), 1)
            raw.conversation_resource = r.SessionBindingResource(
                raw.conversation_resource.backend,
                namespaces=(None, "red", "blue"),
                default_namespace="blue",
            )
            release.set()
            result = await run.wait(wait_timeout=2, terminal_only=True)
            assert result.snapshot.state == "failed"
            assert len(calls) == 1 and root_messages(raw, run.ref.run_id) == []
            child = raw.store.run(run.ref.run_id)["orchestration"]["children"][0]["run_id"]
            assert any(event.kind == "tool_receipt_recorded" for event in raw.events(child))

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["allowlist", "backend", "connection", "scope"])
def test_changed_resource_or_scope_refuses_child_dispatch_and_observation_stays_pure(
    tmp_path, change
):
    async def scenario():
        raw = engine(tmp_path / "drift.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", namespace="red", command_id="open"
            )
            accepted = runtime._session_authority().submit(
                session.ref, "q", command_id="one", budget=64
            )
            resource = raw.conversation_resource
            if change == "allowlist":
                raw.conversation_resource = r.SessionBindingResource(
                    resource.backend, namespaces=("blue",), default_namespace="blue"
                )
            elif change == "backend":
                resource.backend.backend_id = "changed"
            elif change == "connection":
                raw.conversation_resource = r.SessionBindingResource(
                    r.InMemoryMemory(backend_id="remote"),
                    namespaces=("red",),
                    default_namespace="red",
                )
            else:
                raw.scope = r.Scope("other", "principal")
            from relf_agent.errors import AuthorizationDenied

            with pytest.raises((DefinitionMismatch, AuthorizationDenied)):
                await raw.drive(accepted.run_id)
            assert raw.providers["default"].calls == 0
            if change != "scope":
                assert (await session.status()).busy
                assert len(await session.turns()) == 1
                assert raw.providers["default"].calls == 0
            else:
                raw.scope = runtime.scope

    asyncio.run(scenario())


def test_invalid_root_resource_constructor_keeps_borrowed_backend_and_store_usable(tmp_path):
    store = r.SQLiteStore(tmp_path / "main.sqlite")
    borrowed = r.SQLiteMemory(tmp_path / "foreign.sqlite")
    borrowed.session_receipt_version = None
    try:
        with pytest.raises(ValidationError):
            r.LocalEngine(
                store,
                providers={},
                tools=r.ToolRegistry(),
                conversation_resource=r.SessionBindingResource(
                    borrowed, namespaces=("red",), default_namespace="red"
                ),
            )
        assert store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert borrowed.read(r.Scope(), "s") == (0, [])
        # Failed initialization releases only its own acquired Coordinator.
        with r.LocalEngine(store, providers={}, tools=r.ToolRegistry()):
            pass
    finally:
        borrowed.close()
        store.close()
