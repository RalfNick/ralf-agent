import asyncio
import copy
import threading

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError

from .helpers import ScriptedProvider


def engine_for(path, *, scope=None, uncertain=False):
    writes = []
    tools = ToolRegistry()

    def write(args, context):
        writes.append(context.effect_key)
        if uncertain:
            raise ConnectionError("Response lost after business write")
        return {"large": "x" * 2000}

    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, effect="unqueryable_write", requires_approval=True
        ),
        write,
    )
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=(ToolCall("write", {}),)), ModelResponse(output="done")]
    )
    return (
        LocalEngine(
            SQLiteStore(path),
            providers={"default": provider},
            tools=tools,
            scope=Scope() if scope is None else scope,
        ),
        provider,
        writes,
    )


def completed(engine):
    spec = AgentSpec("writer", "Write", ("write",))
    handle = engine.submit(spec, "request", command_id="submit")
    asyncio.run(engine.drive(handle.run_id))
    action = engine.status(handle.run_id).pending[0]
    receipt = engine.approve(
        handle.run_id, action["action_id"], action["digest"], command_id="approve"
    )
    assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
    return spec, handle, action, receipt


def tables(store):
    return {
        name: [
            tuple(row) for row in store.conn.execute("SELECT * FROM " + name + " ORDER BY rowid")
        ]
        for name in ("runs", "events", "commands", "budgets", "reservations")
    }


def test_compaction_preserves_original_receipts_effect_and_cold_recovery(tmp_path):
    path = tmp_path / "runs.sqlite"
    engine, provider, writes = engine_for(path)
    spec, handle, action, approved = completed(engine)
    before = engine.store.run(handle.run_id)
    events = engine.events(handle.run_id)
    receipt = engine.compact_messages(handle.run_id, command_id="compact")
    after = engine.store.run(handle.run_id)
    assert receipt.kind == "compact_messages"
    assert receipt.outcome["removed_messages"] == len(before["messages"]) - 2 > 0
    assert receipt.outcome["removed_bytes"] > 2000
    assert after["messages"] == before["messages"][:2]
    for key in set(before) - {"messages", "revision"}:
        assert after[key] == before[key]
    assert engine.events(handle.run_id)[: len(events)] == events
    assert engine.compact_messages(handle.run_id, command_id="compact") == receipt
    assert (
        engine.compact_messages(handle.run_id, command_id="second").outcome["removed_messages"] == 0
    )
    assert len(writes) == 1 and provider.calls == 2
    engine.close()

    restored, restored_provider, restored_writes = engine_for(path)
    try:
        assert restored.compact_messages(handle.run_id, command_id="compact") == receipt
        assert restored.submit(spec, "request", command_id="submit").run_id == handle.run_id
        assert (
            restored.approve(
                handle.run_id, action["action_id"], action["digest"], command_id="approve"
            )
            == approved
        )
        assert asyncio.run(restored.drive(handle.run_id)).state == "succeeded"
        with pytest.raises(IdempotencyConflict):
            restored.compact_messages(handle.run_id, command_id="submit")
        assert restored_provider.calls == 0 and restored_writes == []
        assert restored.store.run(handle.run_id)["actions"] == before["actions"]
    finally:
        restored.close()


def test_failure_after_save_rolls_back_and_original_run_reopens(tmp_path):
    path = tmp_path / "runs.sqlite"
    engine, _, _ = engine_for(path)
    _, handle, _, _ = completed(engine)
    before = tables(engine.store)
    original_emit = engine.store.emit

    def fail(*args, **kwargs):
        raise RuntimeError("maintenance event unavailable")

    engine.store.emit = fail
    with pytest.raises(RuntimeError):
        engine.compact_messages(handle.run_id, command_id="compact")
    engine.store.emit = original_emit
    assert tables(engine.store) == before
    engine.close()
    restored, _, _ = engine_for(path)
    try:
        assert tables(restored.store) == before
        assert (
            restored.compact_messages(handle.run_id, command_id="compact").outcome["removed_bytes"]
            > 0
        )
    finally:
        restored.close()


def test_real_unknown_write_keeps_every_receipt_and_payload(tmp_path):
    engine, _, writes = engine_for(tmp_path / "runs.sqlite", uncertain=True)
    try:
        handle = engine.submit(
            AgentSpec("writer", "Write", ("write",)), "request", command_id="submit"
        )
        asyncio.run(engine.drive(handle.run_id))
        action = engine.status(handle.run_id).pending[0]
        engine.approve(handle.run_id, action["action_id"], action["digest"], command_id="approve")
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_reconciliation"
        before = tables(engine.store)
        with pytest.raises(ValidationError):
            engine.compact_messages(handle.run_id, command_id="compact")
        assert tables(engine.store) == before and len(writes) == 1
    finally:
        engine.close()


def test_released_coordinator_cannot_authorize_compaction(tmp_path):
    engine, _, _ = engine_for(tmp_path / "runs.sqlite")
    _, handle, _, _ = completed(engine)
    engine.coordinator.release()
    before = tables(engine.store)
    try:
        with pytest.raises(ValidationError):
            engine.compact_messages(handle.run_id, command_id="compact")
        assert tables(engine.store) == before
    finally:
        engine.close()


def test_scope_drift_during_release_check_cannot_compact(tmp_path):
    engine, _, _ = engine_for(tmp_path / "runs.sqlite")
    _, handle, _, _ = completed(engine)
    before = tables(engine.store)
    original = engine._check_release

    def changed(run):
        original(run)
        engine.scope = Scope("other", "principal")

    engine._check_release = changed
    try:
        with pytest.raises(AuthorizationDenied):
            engine.compact_messages(handle.run_id, command_id="compact")
        assert tables(engine.store) == before
    finally:
        engine.scope = Scope()
        engine._check_release = original
        engine.close()


def test_cancelled_waiter_keeps_real_registered_thread_protected(tmp_path):
    engine, _, _ = engine_for(tmp_path / "runs.sqlite")
    _, handle, _, _ = completed(engine)
    before = tables(engine.store)
    release = threading.Event()

    async def run():
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def handler():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise AssertionError("Test handler was not released")

        task = asyncio.create_task(engine._threads.run(handler, group=handle.run_id))
        try:
            async with asyncio.timeout(2):
                await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert engine._threads.has_active_for(handle.run_id)
            with pytest.raises(ValidationError):
                engine.compact_messages(handle.run_id, command_id="compact")
            assert tables(engine.store) == before
        finally:
            release.set()
            await engine.wait_for_threads()

    try:
        asyncio.run(run())
        assert (
            engine.compact_messages(handle.run_id, command_id="compact").outcome["removed_bytes"]
            > 0
        )
    finally:
        release.set()
        engine.close()


@pytest.mark.parametrize(
    "guard",
    [
        "active",
        "drive_user",
        "operation",
        "reservation",
        "foreign",
        "shared_session",
        "extension",
        "parent",
        "failed",
    ],
)
def test_unsafe_or_unsupported_original_run_is_retained(tmp_path, guard):
    engine, _, _ = engine_for(tmp_path / "runs.sqlite")
    _, handle, _, _ = completed(engine)
    original_operation = engine._operation_active
    if guard in {"foreign", "shared_session", "extension", "parent", "failed"}:
        with engine.store.transaction():
            run = engine.store.run(handle.run_id)
            if guard == "foreign":
                run["scope"]["principal"] = "other"
            elif guard == "shared_session":
                run["session_id"] = "shared"
            elif guard == "extension":
                run["memory_stages"] = {}
            elif guard == "parent":
                run["parent_id"] = "parent"
            else:
                run["state"] = "failed"
            engine.store.save_run(run)
    elif guard == "active":
        engine._active.add(handle.run_id)
    elif guard == "drive_user":
        engine._drive_users[handle.run_id] = 1
    elif guard == "operation":
        engine._operation_active = lambda run_id: True
    else:
        engine.store.conn.execute(
            "UPDATE reservations SET state='unknown' WHERE run_id=?", (handle.run_id,)
        )
    before = copy.deepcopy(tables(engine.store))
    try:
        with pytest.raises((AuthorizationDenied, ValidationError)):
            engine.compact_messages(handle.run_id, command_id="compact")
        assert tables(engine.store) == before
    finally:
        engine._active.clear()
        engine._drive_users.clear()
        engine._operation_active = original_operation
        engine.close()
