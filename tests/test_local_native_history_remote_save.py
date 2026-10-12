"""Original SQLite Run journal adopts exact native receipts from a borrowed source."""

import asyncio
import copy
import importlib

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.local_session_model_history import freeze_native_history, prepare_native_history
from ralf_agent.types import digest

from .helpers import ScriptedProvider


def api():
    try:
        return importlib.import_module("ralf_agent.local_native_history_save")
    except ModuleNotFoundError:
        pytest.fail("Original Run native remote save helper is missing")


class ReceiptMemory(r.InMemoryMemory):
    def __init__(self):
        super().__init__(backend_id="native-save-test")
        self.writes = 0
        self.inspections = 0
        self.lose_ack = False
        self.inspect_unknown = False
        self.after_write = None
        self.after_inspect = None

    async def append(self, scope, address, message, *, expected_revision, message_id):
        self.writes += 1
        result = super().append(
            scope, address, message, expected_revision=expected_revision, message_id=message_id
        )
        if self.after_write is not None:
            self.after_write()
        if self.lose_ack:
            self.lose_ack = False
            raise RuntimeError("ACK lost after successful actual write")
        return result

    async def inspect_message(self, scope, address, message_id):
        self.inspections += 1
        if self.inspect_unknown:
            raise RuntimeError("Inspection transport unavailable")
        result = super().inspect_message(scope, address, message_id)
        if self.after_inspect is not None:
            self.after_inspect()
        return result


async def frozen(engine, definition=None):
    handle = engine.submit(
        definition or r.AgentSpec("agent", "Answer"),
        "task",
        session_id="session",
        command_id="native-turn",
    )
    await prepare_native_history(engine, handle.run_id)
    assert await engine._model(handle.run_id)
    freeze_native_history(engine, handle.run_id)
    return handle.run_id


def make_engine(tmp_path, backend=None):
    provider = ScriptedProvider([r.ModelResponse(output=' {"answer":"original"} ')])
    engine = r.LocalEngine(
        r.SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": provider},
        tools=r.ToolRegistry(),
        session_store=backend,
        model_continuation=True,
        model_history=r.CompleteModelHistory(scope="session"),
    )
    return engine, provider


def test_remote_native_save_commits_exact_receipt_without_publishing_failed_root(tmp_path):
    async def run():
        backend = ReceiptMemory()
        engine, provider = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            assert await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            record = owner["native_model_history"]["episodes"]["agent"]
            saved = owner["native_model_history"]["saves"]["agent"]
            evidence = api().validate_native_save(owner, "agent", record)
            assert saved["expected_revision"] == 0 and saved["attempts"] == 1
            assert (
                evidence["revision"] == 1
                and evidence["receipt"]["receipt"]["message"] == record["envelope"]
            )
            assert await api().ensure_native_history_saved(engine, run_id)
            assert backend.writes == 1 and provider.calls == 1
            assert (
                engine.store.native_history_publications(engine.scope, record["envelope"]["stream"])
                == []
            )

    asyncio.run(run())


def test_same_connection_sqlite_defers_native_append_to_original_success_transaction(tmp_path):
    async def run():
        engine, _ = make_engine(tmp_path)
        with engine:
            run_id = await frozen(engine)
            assert await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            journal = owner["native_model_history"]
            stage = journal["stages"]["agent"]
            assert engine.sessions.read(engine.scope, stage["address"]) == (0, [])
            assert not journal.get("saves")
            assert api().validate_native_save(owner, "agent", journal["episodes"]["agent"]) is None

    asyncio.run(run())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_same_connection_sqlite_replacement_subclass_runs_actual_managed_append(
    tmp_path, asynchronous
):
    async def run():
        calls = []

        class SyncMemory(r.SQLiteMemory):
            def append(self, scope, address, message, *, expected_revision, message_id):
                calls.append(message_id)
                return super().append(
                    scope,
                    address,
                    message,
                    expected_revision=expected_revision,
                    message_id=message_id,
                )

        class AsyncMemory(r.SQLiteMemory):
            async def append(self, scope, address, message, *, expected_revision, message_id):
                await asyncio.sleep(0)
                calls.append(message_id)
                return super().append(
                    scope,
                    address,
                    message,
                    expected_revision=expected_revision,
                    message_id=message_id,
                )

        store = r.SQLiteStore(tmp_path / "runs.sqlite")
        backend = (AsyncMemory if asynchronous else SyncMemory)(store)
        provider = ScriptedProvider([r.ModelResponse(output="original")])
        with r.LocalEngine(
            store,
            providers={"default": provider},
            tools=r.ToolRegistry(),
            session_store=backend,
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        ) as engine:
            run_id = await frozen(engine)
            assert await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            record = owner["native_model_history"]["episodes"]["agent"]
            assert owner["native_model_history"]["saves"]["agent"]["receipt"] is not None
            assert calls == [record["message_id"]] and provider.calls == 1
            assert api().validate_native_save(owner, "agent", record)["revision"] == 1

    asyncio.run(run())


@pytest.mark.parametrize("window", ["ack", "local-commit"])
def test_remote_native_ack_or_receipt_commit_loss_recovers_only_exact_inspection(tmp_path, window):
    async def run():
        backend = ReceiptMemory()
        engine, provider = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            if window == "ack":
                backend.lose_ack = True
            else:
                commit = engine._commit
                lost = False

                def fail_confirmation(owner, kind, data=None):
                    nonlocal lost
                    commit(owner, kind, data)
                    if kind == "native_history_save_confirmed" and not lost:
                        lost = True
                        raise RuntimeError("Crash before local receipt COMMIT")

                engine._commit = fail_confirmation
            assert not await api().ensure_native_history_saved(engine, run_id)
            assert engine.store.run(run_id)["state"] == "waiting_reconciliation"
            assert backend.writes == 1
            assert await api().ensure_native_history_saved(engine, run_id)
            assert backend.writes == 1 and provider.calls == 1
            owner = engine.store.run(run_id)
            assert api().validate_native_save(
                owner, "agent", owner["native_model_history"]["episodes"]["agent"]
            )

    asyncio.run(run())


def test_native_cas_conflict_never_adopts_latest_revision_or_rewrites(tmp_path):
    async def run():
        backend = ReceiptMemory()
        engine, provider = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            owner = engine.store.run(run_id)
            stage = owner["native_model_history"]["stages"]["agent"]
            r.InMemoryMemory.append(
                backend,
                engine.scope,
                stage["address"],
                {"other": True},
                expected_revision=0,
                message_id="other-candidate",
            )
            assert not await api().ensure_native_history_saved(engine, run_id)
            assert backend.writes == 0
            saved = engine.store.run(run_id)["native_model_history"]["saves"]["agent"]
            assert saved["expected_revision"] == 0 and saved["receipt"] is None
            assert provider.calls == 1

    asyncio.run(run())


def test_native_unknown_inspection_pauses_without_external_write(tmp_path):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            backend.inspect_unknown = True
            assert not await api().ensure_native_history_saved(engine, run_id)
            assert backend.writes == 0
            assert engine.store.run(run_id)["state"] == "waiting_reconciliation"
            backend.inspect_unknown = False
            assert await api().ensure_native_history_saved(engine, run_id)
            assert backend.writes == 1

    asyncio.run(run())


def test_native_dispatch_intent_without_actual_write_retries_original_cas_after_restart(tmp_path):
    async def run():
        backend = ReceiptMemory()
        engine, provider = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            backend.inspect_unknown = True
            assert not await api().ensure_native_history_saved(engine, run_id)
            with engine.store.transaction():
                owner = engine.store.run(run_id)
                journal = owner["native_model_history"]
                journal["saves"]["agent"]["attempts"] = 1
                journal["save_markers"]["agent"] = digest(journal["saves"]["agent"])
                engine._commit(owner, "test_original_dispatch_intent_persisted")
            backend.inspect_unknown = False
            assert await api().ensure_native_history_saved(engine, run_id)
            saved = engine.store.run(run_id)["native_model_history"]["saves"]["agent"]
            assert saved["expected_revision"] == 0 and saved["attempts"] == 2
            assert backend.writes == 1 and provider.calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("dispatched", [False, True])
def test_terminal_native_recovery_only_adopts_exact_receipt_from_original_retired_node(
    tmp_path, dispatched
):
    async def run():
        backend = ReceiptMemory()
        engine, provider = make_engine(tmp_path, backend)
        with engine:
            workflow = r.WorkflowSpec(
                "steps", [r.AgentSpec("first", "Answer"), r.AgentSpec("second", "Answer")]
            )
            run_id = await frozen(engine, workflow)
            if dispatched:
                backend.lose_ack = True
            else:
                backend.inspect_unknown = True
            assert not await api().ensure_native_history_saved(engine, run_id)
            backend.inspect_unknown = False
            with engine.store.transaction():
                owner = engine.store.run(run_id)
                owner["state"], owner["node"] = "cancelled", 1
                engine._commit(owner, "test_original_terminal_retired_node")
            before = backend.writes
            assert api().native_saves_settled(owner) is (not dispatched)
            await api().recover_terminal_native_saves(engine, run_id)
            current = engine.store.run(run_id)
            assert api().native_saves_settled(current)
            assert backend.writes == before and provider.calls == 1
            assert current["state"] == "cancelled"

    asyncio.run(run())


def test_native_settlement_rejects_erased_pending_save_with_original_action_marker(tmp_path):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            backend.lose_ack = True
            assert not await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            owner["native_model_history"]["saves"].clear()
            owner["native_model_history"]["save_markers"].clear()
            with pytest.raises(DefinitionMismatch):
                api().native_saves_settled(owner)

    asyncio.run(run())


def test_native_validator_rechecks_original_adopted_messages_when_all_save_markers_recomputed(
    tmp_path,
):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            assert await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            journal = owner["native_model_history"]
            record, saved = journal["episodes"]["agent"], journal["saves"]["agent"]
            record["envelope"]["history"][-1]["content"] = "changed original response"
            journal["episode_markers"]["agent"] = digest(record)
            saved["episode_digest"] = digest(record)
            saved["envelope"] = copy.deepcopy(record["envelope"])
            saved["receipt"]["receipt"]["message"] = copy.deepcopy(record["envelope"])
            original_intent = {
                key: value for key, value in saved.items() if key not in {"attempts", "receipt"}
            }
            owner["actions"][-1]["native_history_save"]["intent_digest"] = digest(original_intent)
            journal["save_markers"]["agent"] = digest(saved)
            with pytest.raises(DefinitionMismatch):
                api().validate_native_save(owner, "agent", record)

    asyncio.run(run())


@pytest.mark.parametrize("drift", ["stage", "method"])
def test_native_save_rechecks_original_stage_and_method_after_actual_write(tmp_path, drift):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)

            def change():
                if drift == "stage":
                    with engine.store.transaction():
                        owner = engine.store.run(run_id)
                        owner["native_model_history"]["stages"]["agent"]["current_task"] = "changed"
                        engine.store.save_run(owner)
                else:
                    backend.append = ReceiptMemory().append

            backend.after_write = change
            with pytest.raises(DefinitionMismatch):
                await api().ensure_native_history_saved(engine, run_id)
            assert (
                engine.store.run(run_id)["native_model_history"]["saves"]["agent"]["receipt"]
                is None
            )

    asyncio.run(run())


@pytest.mark.parametrize("change", ["receipt", "intent", "episode", "marker", "action"])
def test_native_publication_validator_rejects_save_evidence_tampering(tmp_path, change):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)
            assert await api().ensure_native_history_saved(engine, run_id)
            owner = engine.store.run(run_id)
            journal = owner["native_model_history"]
            record = journal["episodes"]["agent"]
            if change == "receipt":
                journal["saves"]["agent"]["receipt"]["receipt"]["revision"] = 2
            elif change == "intent":
                journal["saves"]["agent"]["expected_revision"] = 2
            elif change == "episode":
                record["envelope"]["history"][-1]["content"] = "changed"
            elif change == "marker":
                journal["save_markers"]["agent"] = "0" * 64
            else:
                owner["actions"][-1].pop("native_history_save")
            with pytest.raises(DefinitionMismatch):
                api().validate_native_save(owner, "agent", record)

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_native_cancel_does_not_dispatch_new_write_but_records_actual_receipt(tmp_path, boundary):
    async def run():
        backend = ReceiptMemory()
        engine, _ = make_engine(tmp_path, backend)
        with engine:
            run_id = await frozen(engine)

            def callback():
                return engine.cancel(run_id, command_id="cancel-during-native-save")

            if boundary == "before":
                backend.after_inspect = callback
            else:
                backend.after_write = callback
            assert not await engine._guarded(
                run_id, api().ensure_native_history_saved(engine, run_id)
            )
            owner = engine.store.run(run_id)
            saved = owner["native_model_history"]["saves"]["agent"]
            assert backend.writes == (0 if boundary == "before" else 1)
            assert (saved["receipt"] is None) is (boundary == "before")

    asyncio.run(run())
