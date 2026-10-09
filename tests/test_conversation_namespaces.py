import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, ValidationError

from .composite_session_fixture import definitions, root_messages
from .conversation_namespace_fixture import engine


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_composite_namespace_roots_use_distinct_parent_history_and_final_addresses(tmp_path, kind):
    async def scenario():
        raw = engine(tmp_path / "namespaces.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            agent = runtime.create_agent(definitions()[kind])
            sessions = [
                await agent.open_session("s", namespace=n, command_id="open:" + n)
                for n in ("red", "blue")
            ]
            assert sessions[0].ref.key != sessions[1].ref.key
            for session, want_address in zip(
                sessions,
                ('ralf-session-v1:["red","s"]', 'ralf-session-v1:["blue","s"]'),
                strict=True,
            ):
                for seq in (1, 2):
                    run = await session.submit(
                        "q", command_id=session.ref.key.namespace + str(seq), budget=64
                    )
                    assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
                    assert raw.store.run(run.ref.run_id)["session_id"] == want_address
                    assert (
                        raw.store.conn.execute(
                            "SELECT session FROM memory_session_items WHERE message_id=?",
                            (run.ref.run_id + ":turn:result",),
                        ).fetchone()[0]
                        == want_address
                    )
                    assert len(root_messages(raw, run.ref.run_id)) == 1
                    await runtime._supervisor.drain()
                    assert not (await session.status()).busy
                assert [t.turn_seq for t in await session.turns()] == [1, 2]
            assert raw.sessions.read(raw.scope, "s") == (0, [])
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "4"
            )
            assert runtime.capabilities["conversation_namespaces"]

    asyncio.run(scenario())


def test_omitted_namespace_uses_host_default_and_explicit_none_selects_none(tmp_path):
    async def scenario():
        async with r.Runtime(engine(tmp_path / "defaults.sqlite"), owned=True) as runtime:
            agent = runtime.create_agent(definitions()["team"])
            default = await agent.open_session("s", command_id="default")
            plain = await agent.open_session("s", namespace=None, command_id="plain")
            assert default.ref.key.namespace == "red" and plain.ref.key.namespace is None
            assert default.ref.key.storage_key != plain.ref.key.storage_key
            assert (await agent.open_session("s", command_id="default")).ref == default.ref
            run = await plain.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "succeeded"
            assert runtime.engine.store.run(run.ref.run_id)["session_id"] == "s"

    asyncio.run(scenario())


@pytest.mark.parametrize("namespace", ["unauthorized", "", 1, True, []])
def test_invalid_namespace_refuses_before_schema_activation(tmp_path, namespace):
    async def scenario():
        raw = engine(tmp_path / "invalid.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            with pytest.raises((AuthorizationDenied, ValidationError)):
                await runtime.create_agent(definitions()["team"]).open_session(
                    "s", namespace=namespace, command_id="open"
                )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )
            assert raw.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
            assert raw.providers["default"].calls == 0

    asyncio.run(scenario())


def test_raw_and_selected_aliases_cannot_enter_registered_namespace_address(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "aliases.sqlite")
        catalog = r.BindingCatalog(scope=raw.scope)
        catalog.register("session", "same", "1", raw.conversation_resource)
        raw.binding_catalog = catalog
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", namespace="red", command_id="open"
            )
            with pytest.raises(ValidationError):
                raw.submit(
                    r.AgentSpec("raw", "A"),
                    "q",
                    session_id='ralf-session-v1:["red","s"]',
                    command_id="raw",
                )
            bound = r.AgentDefinition(
                r.AgentSpec("bound", "A"),
                r.AgentBindingDescriptor(
                    session=r.BindingSelection.ref("same", "1", selector={"namespace": "red"})
                ),
            )
            with pytest.raises(ValidationError):
                raw.submit(bound, "q", session_id="s", command_id="selected")
            assert not (await session.status()).busy
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0

    asyncio.run(scenario())


def test_native_namespace_option_refuses_and_default_composite_keeps_legacy_schema(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "native.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                    "s", namespace="red", command_id="native"
                )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )
        from .composite_session_fixture import engine as legacy_engine

        async with r.Runtime(legacy_engine(tmp_path / "legacy.sqlite"), owned=True) as runtime:
            await runtime.create_agent(definitions()["team"]).open_session("s", command_id="legacy")
            assert (
                runtime.engine.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "3"
            )

    asyncio.run(scenario())
