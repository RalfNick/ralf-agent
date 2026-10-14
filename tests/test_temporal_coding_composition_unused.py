"""Unused owned objects may release their ledger without claiming root stop."""

import asyncio

import pytest

from ralf_agent import Scope
from ralf_agent.errors import CloseIncomplete
from ralf_agent.postgres_runner_journal import PostgresRunnerJournal
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
from tests.test_temporal_coding_close_boundary import owned_assembly
from tests.test_temporal_coding_factories import publish_initialization


@pytest.mark.parametrize("records", [(), ({"pending_stop": False},)])
def test_never_attached_selected_constructor_closes_only_without_original_native_rows(
    tmp_path, monkeypatch, records
):
    events = []
    publish_initialization(monkeypatch, events)

    async def original_rows(self, scope):
        assert scope == Scope()
        return records

    monkeypatch.setattr(PostgresRunnerJournal, "composition_resources", original_rows)

    async def run():
        original = await owned_assembly(tmp_path, events)
        selected = TemporalRuntime(
            providers=original._runtime.providers,
            tools=original._runtime.tools,
            journal=original._runtime.journal,
            coding_execution=True,
            coding_composition=True,
        )
        assembly = TemporalRuntimeAssembly(
            selected, original._context, original._profile, original._scope
        )
        ledger = list(assembly._context._resources)
        if records:
            with pytest.raises(CloseIncomplete):
                await assembly.aclose()
            assert assembly._closed is False and assembly._context._resources == ledger
        else:
            await assembly.aclose()
            assert assembly._closed is True and assembly._context._resources == []

    asyncio.run(run())


def test_attached_owned_engine_cannot_use_constructor_only_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace

    events = []
    publish_initialization(monkeypatch, events)

    async def original_rows(self, scope):
        return ()

    monkeypatch.setattr(PostgresRunnerJournal, "composition_resources", original_rows)

    async def run():
        original = await owned_assembly(tmp_path, events)
        selected = TemporalRuntime(
            providers=original._runtime.providers,
            tools=original._runtime.tools,
            journal=original._runtime.journal,
            coding_execution=True,
            coding_composition=True,
        )
        assembly = TemporalRuntimeAssembly(
            selected, original._context, original._profile, original._scope
        )
        assembly._engines.append(SimpleNamespace(_closed=False))
        ledger = list(assembly._context._resources)
        with pytest.raises(CloseIncomplete):
            await assembly.aclose()
        assert assembly._context._resources == ledger and assembly._closed is False

    asyncio.run(run())
