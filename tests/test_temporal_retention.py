"""Original full closure proof gates maintenance; no SQL simulator."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_journal import PostgresEffectJournal
from tests.test_temporal_deployment_release import environment


def configured(monkeypatch):
    runtime, client, state, proof, info = environment(monkeypatch)
    journal = object.__new__(PostgresEffectJournal)
    journal.connection = object()
    journal.backend_id = "original-effects"
    journal._closed = False
    journal._table_schemas = {
        "ralf_temporal_effects": "original",
        "ralf_temporal_effect_evidence": "original",
    }
    runtime.journal = journal
    calls = []

    async def compact(scope, run_id, *, limit, after_effect_key, verify, namespace_check=None):
        verify()
        if namespace_check is not None:
            await namespace_check()
        calls.append((scope, run_id, limit, after_effect_key))
        return {
            "scanned_records": 1,
            "removed_records": 1,
            "removed_payload_bytes": 30,
            "next_after_effect_key": None,
        }

    journal._compact_adopted_evidence = compact

    async def status(run_id):
        assert asdict(engine.scope) == state.scope
        return SimpleNamespace(state=state.state)

    engine = SimpleNamespace(
        client=client,
        namespace=client.namespace,
        scope=Scope(**state.scope),
        release=copy.deepcopy(runtime.manifest),
        _closed=False,
        status=status,
    )
    return engine, runtime, client, state, proof, info, calls


async def seal(runtime, client, state, info):
    from ralf_agent.temporal_deployment_release import execute

    await execute(
        runtime,
        client,
        {
            "mode": "release",
            "scope": state.scope,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
        },
        info,
    )


def test_full_original_seal_is_read_only_and_preserves_authority(monkeypatch):
    async def run():
        from ralf_agent.temporal_retention import compact_effect_evidence

        engine, runtime, client, state, proof, info, calls = configured(monkeypatch)
        await seal(runtime, client, state, info)
        updates = copy.deepcopy(client.updates)
        result = await compact_effect_evidence(
            engine, state.run_id, runtime=runtime, limit=1, after_effect_key="earlier"
        )
        assert result["removed_records"] == 1
        assert result["execution_epoch"] == state.epoch
        assert result["root_run_id"] == state.run_id
        assert result["root_execution_epoch"] == state.epoch
        assert calls == [(engine.scope, state.run_id, 1, "earlier")]
        assert client.updates == updates

    asyncio.run(run())


@pytest.mark.parametrize(
    "condition",
    [
        "no_seal",
        "active",
        "unknown",
        "epoch",
        "namespace",
        "journal",
        "uninitialized",
        "split_schema",
    ],
)
def test_original_obligations_or_wrong_binding_prevent_sql(monkeypatch, condition):
    async def run():
        from ralf_agent.temporal_retention import compact_effect_evidence

        engine, runtime, client, state, proof, info, calls = configured(monkeypatch)
        if condition != "no_seal":
            await seal(runtime, client, state, info)
        if condition == "active":
            state.state = "running"
        elif condition == "unknown":
            state.state = "outcome_unknown"
        elif condition == "epoch":
            client.descriptions[state.run_id].run_id = "wrong-epoch"
        elif condition == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif condition == "journal":
            runtime.journal = object()
        elif condition == "uninitialized":
            runtime.journal._table_schemas = {}
        elif condition == "split_schema":
            runtime.journal._table_schemas["ralf_temporal_effects"] = "foreign"
        with pytest.raises((DefinitionMismatch, ValidationError)):
            await compact_effect_evidence(engine, state.run_id, runtime=runtime)
        assert calls == []

    asyncio.run(run())


def test_scope_change_during_sdk_await_is_rejected_before_pruning(monkeypatch):
    async def run():
        from ralf_agent.temporal_retention import compact_effect_evidence

        engine, runtime, client, state, proof, info, calls = configured(monkeypatch)
        await seal(runtime, client, state, info)
        original = engine.status

        async def changed(run_id):
            value = await original(run_id)
            engine.scope = Scope("other", "owner")
            return value

        engine.status = changed
        with pytest.raises(DefinitionMismatch):
            await compact_effect_evidence(engine, state.run_id, runtime=runtime)
        assert calls == []

    asyncio.run(run())


def test_namespace_uuid_change_during_compaction_is_rejected(monkeypatch):
    async def run():
        from ralf_agent.temporal_retention import compact_effect_evidence

        engine, runtime, client, state, proof, info, calls = configured(monkeypatch)
        await seal(runtime, client, state, info)
        original = runtime.journal._compact_adopted_evidence

        async def changed(*args, **kwargs):
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
            return await original(*args, **kwargs)

        runtime.journal._compact_adopted_evidence = changed
        with pytest.raises(DefinitionMismatch):
            await compact_effect_evidence(engine, state.run_id, runtime=runtime)
        assert calls == []

    asyncio.run(run())


@pytest.mark.parametrize("limit", [True, 0, 1001, 1.5])
def test_bad_limit_precedes_all_io(monkeypatch, limit):
    from ralf_agent.temporal_retention import compact_effect_evidence

    engine, runtime, client, state, proof, info, calls = configured(monkeypatch)
    with pytest.raises(ValidationError):
        asyncio.run(compact_effect_evidence(engine, state.run_id, runtime=runtime, limit=limit))
    assert calls == []
