"""Configured root resources reuse the real authority and its lifecycle."""

import asyncio
import json
import sqlite3

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, ValidationError

from .composite_session_fixture import definitions, root_messages
from .runtime_profile_fixture import Provider, business_tools


def profile(*, default="red", version="1", config=None, business=False):
    components = {
        "conversation_resource": {
            "adapter": "colocated-session",
            "config": config
            if config is not None
            else {"namespaces": [None, "red", "blue"], "default_namespace": default},
        }
    }
    if business:
        components["tools"] = {"adapter": "business", "config": {"version": "1"}}
    return r.RuntimeProfile(
        "app",
        version,
        {"default": {"adapter": "fixture" if business else "offline-echo"}},
        components=components,
    )


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("extension", ["json", "toml"])
def test_configured_facade_is_colocated_and_preserves_member_defaults(tmp_path, mode, extension):
    async def scenario():
        declaration = {
            "schema_version": 1,
            "default": {"name": "app", "version": "1"},
            "profiles": [
                {
                    "name": "app",
                    "version": "1",
                    "providers": {"default": {"adapter": "offline-echo"}},
                    "components": {
                        "conversation_resource": {
                            "adapter": "colocated-session",
                            "config": {"namespaces": ["red", "blue"], "default_namespace": "red"},
                        }
                    },
                }
            ],
        }
        config = tmp_path / ("runtime." + extension)
        config.write_text(
            json.dumps(declaration)
            if extension == "json"
            else """schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.conversation_resource]
adapter = "colocated-session"
[profiles.components.conversation_resource.config]
namespaces = ["red", "blue"]
default_namespace = "red"
"""
        )
        selected = r.load_catalog(config).default
        path = tmp_path / "roots.sqlite"
        runtime = (
            r.Runtime.from_profile(selected, path)
            if mode == "sync"
            else await r.Runtime.afrom_profile(selected, path)
        )
        async with runtime:
            raw = runtime._local
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "1"
            )
            assert raw.conversation_resource.backend.store is raw.store
            assert type(raw.sessions) is r.SQLiteMemory
            worker = runtime.create_agent(definitions()["team"])
            red = await worker.open_session("customer", command_id="open-red")
            blue = await worker.open_session("customer", namespace="blue", command_id="open-blue")
            assert red.ref.key.namespace == "red" and blue.ref.key.namespace == "blue"
            for session, input_value, address in (
                (red, "red question", 'ralf-session-v1:["red","customer"]'),
                (blue, "blue question", 'ralf-session-v1:["blue","customer"]'),
            ):
                run = await session.submit(input_value, command_id="turn:" + input_value, budget=64)
                done = await run.wait(wait_timeout=2, terminal_only=True)
                assert done.snapshot.state == "succeeded"
                await runtime._supervisor.drain()
                assert root_messages(raw, run.ref.run_id)[0]["task"] == input_value
                assert (
                    raw.store.conn.execute(
                        "SELECT session FROM memory_session_items WHERE message_id=?",
                        (run.ref.run_id + ":turn:result",),
                    ).fetchone()[0]
                    == address
                )
                assert (
                    raw.store.run(run.ref.run_id)["manifest"]["runtime_profile"]
                    == selected.identity
                )
        with r.SQLiteStore(path) as store:
            lease = store.create_coordinator()
            lease.acquire()
            lease.release()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "config",
    [
        {"namespaces": []},
        {"namespaces": ["red"], "default_namespace": "blue"},
        {"namespaces": ["red", "red"], "default_namespace": "red"},
        {"namespaces": [False]},
        {"namespaces": [""]},
        {"namespaces": ["x" * 129]},
        {"namespaces": "red"},
        {"backend": {"adapter": "sqlite"}},
        {"path": "another.sqlite"},
        {"extra": True},
    ],
)
def test_invalid_root_config_refuses_before_database_creation(tmp_path, config):
    selected = profile(config=config)
    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        r.RuntimeBuilder().build(selected, path)
    assert not path.exists()


def test_configured_none_and_approval_recovery_keep_original_profile(tmp_path):
    async def scenario():
        registry = r.ComponentRegistry()
        registry.register("provider", "fixture", lambda c, ctx: Provider("original"))
        registry.register("tools", "business", business_tools)
        builder = r.RuntimeBuilder(registry)
        original = profile(business=True)
        path = tmp_path / "approval.sqlite"
        async with r.Runtime.from_profile(original, path, builder=builder) as runtime:
            session = await runtime.create_agent(definitions(("write",))["team"]).open_session(
                "s", namespace=None, command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            assert (await run.wait(wait_timeout=2)).snapshot.state == "waiting_approval"
            session_ref, run_ref, turn, receipt = session.ref, run.ref, run.turn, run.receipt
        moved = profile(default="blue", version="2", business=True)
        async with r.Runtime.from_profile(moved, path, builder=builder) as runtime:
            # Replay the receipt without hosting on deliberately wrong components.
            replay = runtime._session_authority().submit(
                session_ref, "q", command_id="one", budget=64
            )
            assert replay == receipt and replay.outcome["turn"] == turn.to_dict()
            controls = await runtime.attach(run_ref).pending()
            for item in controls:
                runtime._local.approve(
                    item["ref"]["run_id"], item["action_id"], item["digest"], command_id="approve"
                )
            with pytest.raises(DefinitionMismatch):
                await runtime._local.drive(run_ref.run_id)
        with sqlite3.connect(str(path) + ".effects.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 0
        async with await r.Runtime.afrom_profile(original, path, builder=builder) as runtime:
            resumed = await runtime.resume(run_ref)
            assert (
                await resumed.wait(wait_timeout=2, terminal_only=True)
            ).snapshot.state == "succeeded"
            assert runtime.attach_session(session_ref).ref == session_ref
        with sqlite3.connect(str(path) + ".effects.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_foreign_custom_root_does_not_close_borrowed_store_or_leak_authority(tmp_path, mode):
    async def scenario():
        registry = r.ComponentRegistry()
        foreign = r.SQLiteStore(tmp_path / "foreign.sqlite")
        backend = r.SQLiteMemory(foreign)
        backend.session_receipt_version = None
        borrowed = r.SessionBindingResource(backend)

        async def construct(config, context):
            return borrowed

        if mode == "async":
            registry.register_async("conversation_resource", "foreign", construct)
        else:
            registry.register("conversation_resource", "foreign", lambda c, ctx: borrowed)
        selected = r.RuntimeProfile(
            "app",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components={"conversation_resource": {"adapter": "foreign"}},
        )
        path = tmp_path / "rejected.sqlite"
        try:
            with pytest.raises(ValidationError):
                if mode == "async":
                    await r.RuntimeBuilder(registry).abuild(selected, path)
                else:
                    r.RuntimeBuilder(registry).build(selected, path)
            assert foreign.conn.execute("SELECT 1").fetchone()[0] == 1
            with r.SQLiteStore(path) as store:
                lease = store.create_coordinator()
                lease.acquire()
                lease.release()
        finally:
            foreign.close()

    asyncio.run(scenario())
