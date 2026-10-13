"""Finite mocked pending-query boundaries; no claim of native or service recovery."""

import asyncio

import pytest

from ralf_agent import Scope, TemporalProfile
from ralf_agent.errors import CloseIncomplete, ValidationError
from ralf_agent.runtime_lifecycle import BuildContext
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
from ralf_agent.temporal_coding_factories import build
from ralf_agent.temporal_journal import PostgresEffectJournal
from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
from tests.test_temporal_engine import Provider


async def owned_assembly(tmp_path, events):
    scope = Scope()
    context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
    connection = Connection(events)
    connection.pending_fault, connection.pending_calls, connection.pending_records = False, [], []
    connection.pending_entered, connection.pending_finish = None, None
    effect = context.own_async(PostgresEffectJournal(connection, owns_connection=True))
    context.coding_execution, context.effect_journal = True, effect
    context.tools = await build(entry(tmp_path), context)
    profile = TemporalProfile(
        "boundary",
        "1",
        {"default": {"adapter": "offline-echo"}},
        execution={"coding_execution": True},
    )
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=context.tools,
        journal=effect,
        coding_execution=True,
    )
    return TemporalRuntimeAssembly(runtime, context, profile, scope)


def assert_retained_and_quarantined(assembly, ledger):
    assert assembly._closing is True and assembly._closed is False and assembly._aclosing is False
    assert assembly._context._resources == ledger
    assert all(not owned.resource._closed for owned in ledger if hasattr(owned.resource, "_closed"))
    assert assembly._runtime._tool_execution_closing is True
    with pytest.raises(ValidationError, match="closing"):
        assembly.create_engine(object(), task_queue="refused")


async def boundary_pending(self, scope):
    """Fixed test port; mutable finite transport state lives in the mock connection."""
    assert scope == Scope()
    connection = self._effect.connection
    connection.pending_calls.append((self, scope))
    if connection.pending_fault:
        raise OSError("controlled pending query fault")
    if connection.pending_entered is not None:
        connection.pending_entered.set()
        await connection.pending_finish.wait()
    return tuple(connection.pending_records)


def test_pending_query_fault_retains_exact_ledger_and_retry_closes_same_resources(
    tmp_path, monkeypatch
):
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    events = []
    publish_initialization(monkeypatch, events)
    monkeypatch.setattr(PostgresRunnerJournal, "pending_resources", boundary_pending)

    async def run():
        assembly = await owned_assembly(tmp_path, events)
        connection = assembly._runtime.journal.connection
        connection.pending_fault = True
        ledger = list(assembly._context._resources)
        with pytest.raises(OSError, match="pending query fault"):
            await assembly.aclose()
        assert_retained_and_quarantined(assembly, ledger)
        connection.pending_fault = False
        await assembly.aclose()
        assert assembly._closed is True and assembly._context._resources == []
        assert all(
            journal is ledger[1].resource and scope == Scope()
            for journal, scope in connection.pending_calls
        )
        assert len(connection.pending_calls) == 3

    asyncio.run(run())
    assert events == ["initialize-view", "connection"]


def test_persistent_pending_without_original_client_retains_ledger_until_pending_clears(
    tmp_path, monkeypatch
):
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    events = []
    publish_initialization(monkeypatch, events)
    monkeypatch.setattr(PostgresRunnerJournal, "pending_resources", boundary_pending)

    async def run():
        assembly = await owned_assembly(tmp_path, events)
        connection = assembly._runtime.journal.connection
        ledger = list(assembly._context._resources)
        runner = assembly._runtime.tools.get("coding").handler.runner
        connection.pending_records.append(
            {
                "runner": runner.identity,
                "request": {
                    "dispatch": {"run_id": "existing-original", "execution_epoch": "existing-epoch"}
                },
            }
        )
        with pytest.raises(CloseIncomplete):
            await assembly.aclose()
        assert_retained_and_quarantined(assembly, ledger)
        assert assembly._client is None
        connection.pending_records.clear()
        await assembly.aclose()
        assert assembly._closed is True and assembly._context._resources == []

    asyncio.run(run())
    assert events == ["initialize-view", "connection"]


def test_caller_cancellation_during_pending_query_retains_same_loop_retry(tmp_path, monkeypatch):
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    events = []
    publish_initialization(monkeypatch, events)
    monkeypatch.setattr(PostgresRunnerJournal, "pending_resources", boundary_pending)

    async def run():
        assembly = await owned_assembly(tmp_path, events)
        connection = assembly._runtime.journal.connection
        connection.pending_entered, connection.pending_finish = asyncio.Event(), asyncio.Event()
        ledger = list(assembly._context._resources)
        task = asyncio.create_task(assembly.aclose())
        await connection.pending_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_retained_and_quarantined(assembly, ledger)
        connection.pending_finish.set()
        await assembly.aclose()
        assert assembly._closed is True and assembly._context._resources == []

    asyncio.run(run())
    assert events == ["initialize-view", "connection"]


def test_pending_query_timeout_retains_the_exact_stop_task_for_retry(tmp_path, monkeypatch):
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    events = []
    publish_initialization(monkeypatch, events)
    monkeypatch.setattr(PostgresRunnerJournal, "pending_resources", boundary_pending)

    async def run():
        assembly = await owned_assembly(tmp_path, events)
        connection = assembly._runtime.journal.connection
        connection.pending_entered, connection.pending_finish = asyncio.Event(), asyncio.Event()
        ledger = list(assembly._context._resources)
        call = asyncio.create_task(assembly.aclose(wait_timeout=0.01))
        await connection.pending_entered.wait()
        with pytest.raises(CloseIncomplete):
            await asyncio.wait_for(call, timeout=1)
        assert_retained_and_quarantined(assembly, ledger)
        original = assembly._coding_stop_task
        assert not original.done()
        connection.pending_finish.set()
        await assembly.aclose()
        assert assembly._coding_stop_task is original
        assert assembly._closed and not assembly._context._resources

    asyncio.run(run())
