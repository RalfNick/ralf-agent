"""Application Sessions share durable authority, not facade memory locks."""

import asyncio
from dataclasses import replace

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider
from .test_agent_runtime import engine


def api():
    assert hasattr(r.Agent, "open_session"), "Missing durable Agent Session entry"
    return r.Runtime


@pytest.mark.parametrize("kind", ["agent", "sequence", "bound"])
def test_ordered_turns_keep_history_and_original_receipts(kind, tmp_path):
    async def scenario():
        provider = ScriptedProvider(
            [r.ModelResponse(output="first answer"), r.ModelResponse(output="second answer")]
        )
        spec = r.AgentSpec("a", "Answer")
        definition = {
            "agent": spec,
            "sequence": r.WorkflowSpec("w", [spec]),
            "bound": r.AgentDefinition(spec, r.AgentBindingDescriptor()),
        }[kind]
        async with api()(engine(tmp_path / "turns.sqlite", provider), owned=True) as runtime:
            agent = runtime.create_agent(definition)
            session = await agent.open_session("customer", command_id="open")
            first = await session.submit("first task", command_id="one")
            assert (await first.wait(wait_timeout=1)).snapshot.state == "succeeded"
            again = await session.submit("first task", command_id="one")
            assert (
                again.ref == first.ref
                and again.receipt == first.receipt
                and again.turn == first.turn
            )
            second = await session.submit("second task", command_id="two")
            assert (await second.wait(wait_timeout=1)).snapshot.state == "succeeded"
            assert first.turn.turn_seq == 1 and second.turn.turn_seq == 2
            assert [turn.turn_seq for turn in await session.turns()] == [1, 2]
            assert "first answer" in r.types.canonical(provider.messages[1])
            assert not (await session.status()).busy
            before = (
                provider.calls,
                runtime.engine.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0],
                runtime.engine.store.conn.execute("SELECT count(*) FROM events").fetchone()[0],
            )
            await session.status()
            await session.turns(after=1, limit=1)
            after = (
                provider.calls,
                runtime.engine.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0],
                runtime.engine.store.conn.execute("SELECT count(*) FROM events").fetchone()[0],
            )
            assert before == after

    asyncio.run(scenario())


def test_open_and_submit_replay_before_current_configuration_resolution(tmp_path):
    async def scenario():
        original = ScriptedProvider([r.ModelResponse(output="ok")])
        raw = engine(tmp_path / "drift.sqlite", original)
        async with api()(raw, owned=True) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "Answer"))
            session = await agent.open_session("s", command_id="open")
            run = await session.submit("q", command_id="one")
            await run.wait(wait_timeout=1)
            raw.providers.clear()
            assert (await agent.open_session("s", command_id="open")).ref == session.ref
            assert (await session.submit("q", command_id="one")).receipt == run.receipt
            with pytest.raises(DefinitionMismatch):
                await session.submit("next", command_id="two")
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
            raw.providers["default"] = original

    asyncio.run(scenario())


def test_idle_cas_rebind_preserves_history_and_refuses_stale_handle(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(output="one"), r.ModelResponse(output="two")])
        async with api()(engine(tmp_path / "rebind.sqlite", provider), owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "Old instructions")).open_session(
                "s", command_id="open"
            )
            first = await session.submit("q", command_id="one")
            await first.wait(wait_timeout=1)
            changed = await session.rebind(
                r.AgentSpec("b", "New instructions"),
                expected_binding_revision=1,
                command_id="rebind",
            )
            assert changed.ref.binding_revision == 2
            assert (
                await session.rebind(
                    r.AgentSpec("b", "New instructions"),
                    expected_binding_revision=1,
                    command_id="rebind",
                )
            ).ref == changed.ref
            with pytest.raises(r.SessionBindingMismatch):
                await session.submit("new", command_id="stale")
            assert (await session.submit("q", command_id="one")).receipt == first.receipt
            second = await changed.submit("new", command_id="two")
            await second.wait(wait_timeout=1)
            assert second.turn.turn_seq == 2 and first.turn.session.binding_revision == 1
            assert runtime.engine.diagnostics(first.ref.run_id).snapshot.result == "one"
            assert provider.messages[1][0]["content"] == "New instructions"
            with pytest.raises(r.SessionBindingMismatch):
                await changed.rebind(
                    r.AgentSpec("c", "C"), expected_binding_revision=1, command_id="conflict"
                )
            assert len(await changed.turns()) == 2

    asyncio.run(scenario())


def test_wrong_scope_coordination_or_declared_binding_refuses_attach(tmp_path):
    async def scenario():
        async with api()(
            engine(tmp_path / "ref.sqlite", ScriptedProvider([])), owned=True
        ) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "s", command_id="open"
            )
            assert (
                runtime.attach_session(r.SessionRef.from_dict(session.ref.to_dict())).ref
                == session.ref
            )
            with pytest.raises(AuthorizationDenied):
                runtime.attach_session(
                    replace(session.ref, key=replace(session.ref.key, principal="other"))
                )
            for bad in [
                replace(session.ref, coordination_ref="f" * 64),
                replace(session.ref, definition_digest="f" * 64),
            ]:
                with pytest.raises(DefinitionMismatch):
                    runtime.attach_session(bad)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic"])
def test_composite_sessions_explicitly_refuse_without_route_or_run(kind, tmp_path):
    async def scenario():
        spec = r.AgentSpec("a", "A")
        definition = {
            "graph": r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=spec)]),
            "team": r.TeamSpec("t", {"a": spec}),
            "dynamic": r.DynamicWorkflowSpec("d", {"a": spec}),
        }[kind]
        async with api()(
            engine(tmp_path / "refuse.sqlite", ScriptedProvider([])), owned=True
        ) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(definition).open_session("s", command_id="open")
            assert runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            assert (
                runtime.engine.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )

    asyncio.run(scenario())


def test_remote_or_separate_session_database_refuses_before_activation(tmp_path):
    async def scenario():
        from ralf_agent import InMemoryMemory

        for backend in [InMemoryMemory(), r.SQLiteMemory(tmp_path / "other.sqlite")]:
            async with api()(
                engine(tmp_path / "remote.sqlite", ScriptedProvider([]), session_store=backend),
                owned=True,
            ) as runtime:
                with pytest.raises(ValidationError):
                    await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                        "s", command_id="open"
                    )
                assert (
                    runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0]
                    == 0
                )
                assert (
                    runtime.engine.store.conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    == "1"
                )
            if isinstance(backend, r.SQLiteMemory):
                backend.close()

    asyncio.run(scenario())


def test_raw_submit_cannot_bypass_idle_or_busy_registered_session(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "raw.sqlite", ScriptedProvider([r.ModelResponse(output="ok")]))
        async with api()(raw, owned=True) as runtime:
            spec = r.AgentSpec("a", "A")
            session = await runtime.create_agent(spec).open_session("s", command_id="open")
            with pytest.raises(ValidationError):
                raw.submit(spec, "q", command_id="raw", session_id="s")
            run = await session.submit("q", command_id="turn")
            await run.wait(wait_timeout=1)
            with pytest.raises(ValidationError):
                raw.submit(spec, "q", command_id="raw2", session_id="s")
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1

    asyncio.run(scenario())


def test_namespace_address_alias_does_not_register_another_session(tmp_path):
    async def scenario():
        from ralf_agent.binding_sessions import session_storage_key

        raw = engine(tmp_path / "alias.sqlite", ScriptedProvider([]))
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register(
            "session",
            "scoped",
            "1",
            r.SessionBindingResource(
                raw.sessions, namespaces=("orders",), default_namespace="orders"
            ),
        )
        raw.binding_catalog = catalog
        scoped = r.AgentDefinition(
            r.AgentSpec("a", "A"),
            r.AgentBindingDescriptor(session=r.BindingSelection.ref("scoped", "1")),
        )
        async with api()(raw, owned=True) as runtime:
            await runtime.create_agent(scoped).open_session("s", command_id="scoped")
            with pytest.raises(r.SessionBindingMismatch):
                await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                    session_storage_key("orders", "s"), command_id="alias"
                )
            assert raw.store.conn.execute("SELECT count(*) FROM agent_sessions").fetchone()[0] == 1

    asyncio.run(scenario())


def test_session_entry_close_only_detaches_from_shared_runtime(tmp_path):
    async def scenario():
        async with api()(
            engine(tmp_path / "close.sqlite", ScriptedProvider([r.ModelResponse(output="ok")])),
            owned=True,
        ) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            session = await agent.open_session("s", command_id="open")
            run = await session.submit("q", command_id="one")
            await session.aclose()
            await agent.aclose()
            assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"
            with pytest.raises(r.RuntimeClosed):
                await session.submit("x", command_id="closed")
            assert not (await runtime.attach_session(session.ref).status()).busy

    asyncio.run(scenario())


def test_mixed_namespaces_in_sequence_refuse_before_activation(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "mixed.sqlite", ScriptedProvider([]))
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register(
            "session",
            "one",
            "1",
            r.SessionBindingResource(raw.sessions, namespaces=("one",), default_namespace="one"),
        )
        catalog.register(
            "session",
            "two",
            "1",
            r.SessionBindingResource(raw.sessions, namespaces=("two",), default_namespace="two"),
        )
        raw.binding_catalog = catalog
        spec = r.AgentSpec("a", "A")
        bound = r.BoundDefinition(
            r.WorkflowSpec("w", [spec, spec]),
            {
                f"sequence/steps/{index}": r.AgentBindingDescriptor(
                    session=r.BindingSelection.ref(name, "1")
                )
                for index, name in enumerate(["one", "two"])
            },
        )
        async with api()(raw, owned=True) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(bound).open_session("s", command_id="open")
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )

    asyncio.run(scenario())


def test_injected_admission_adapter_can_rollback_after_real_turn_insert(tmp_path):
    async def scenario():
        class Adapter:
            def __init__(self, base, owner):
                self.base, self.owner = base, owner

            def __getattr__(self, name):
                return getattr(self.base, name)

            def insert_turn(self, data):
                self.base.insert_turn(data)
                self.owner.turn_inserts += 1
                if self.owner.fail:
                    raise RuntimeError("after actual Turn insert")

        class Store(r.SQLiteStore):
            fail = False
            turn_inserts = 0

            def create_session_admission(self):
                return Adapter(super().create_session_admission(), self)

        provider = ScriptedProvider([r.ModelResponse(output="ok")])
        raw = r.LocalEngine(
            Store(tmp_path / "adapter.sqlite"),
            providers={"default": provider},
            tools=r.ToolRegistry(),
        )
        async with api()(raw, owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "s", command_id="open"
            )
            raw.store.fail = True
            with pytest.raises(RuntimeError):
                await session.submit("q", command_id="one")
            assert provider.calls == 0 and await session.turns() == []
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            raw.store.fail = False
            run = await session.submit("q", command_id="one")
            await run.wait(wait_timeout=1)
            assert run.turn.turn_seq == 1 and raw.store.turn_inserts == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [None, object()])
def test_invalid_admission_factory_returns_explicit_validation_without_acceptance(
    invalid, tmp_path
):
    async def scenario():
        class Store(r.SQLiteStore):
            def create_session_admission(self):
                return invalid

        raw = r.LocalEngine(
            Store(tmp_path / "factory.sqlite"),
            providers={"default": ScriptedProvider([])},
            tools=r.ToolRegistry(),
        )
        async with api()(raw, owned=True) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                    "s", command_id="open"
                )
            assert raw.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0] == 0

    asyncio.run(scenario())
