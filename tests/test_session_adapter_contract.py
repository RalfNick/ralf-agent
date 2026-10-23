import asyncio
import dataclasses
import importlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from relf_agent import InMemoryMemory, Scope, SQLiteMemory
from relf_agent.adapter_contract_types import AdapterContractCleanupPending
from relf_agent.errors import CloseIncomplete
from relf_agent.session_adapter_contract_reference import offline_session_fixture
from relf_agent.types import canonical


def api():
    return importlib.import_module("relf_agent.session_adapter_contract")


@pytest.mark.parametrize("case_id", [f"S{number:02}" for number in range(1, 15)])
def test_frozen_session_case_uses_independent_actual_store(case_id, tmp_path):
    result = asyncio.run(api().run_session_case(case_id, offline_session_fixture(), tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    assert result.adapter_digest and result.configuration_digest
    assert result.observations["cleanup_complete"] is True
    if case_id in {"S10", "S14"}:
        assert result.execution_authority == "local"
        assert result.observations["consumer_runs"] == result.observations["model_calls"] == 1


class ChangedFixture:
    def __init__(self, transform):
        self.transform, self.prepared = transform, None

    def prepare(self, case_id, workspace):
        self.prepared = offline_session_fixture().prepare(case_id, workspace)
        self.prepared = self.transform(self.prepared)
        return self.prepared


@pytest.mark.parametrize(
    "case_id,missing",
    [
        ("S01", "audit"),
        ("S07", "inject_fault"),
        ("S08", "inject_fault"),
        ("S09", "pause"),
        ("S12", "reopen"),
        ("S13", "inject_fault"),
        ("S14", "inject_fault"),
    ],
)
def test_missing_hook_is_not_certified_and_original_owner_closes(case_id, missing, tmp_path):
    fixture = ChangedFixture(lambda value: dataclasses.replace(value, **{missing: None}))
    result = asyncio.run(api().run_session_case(case_id, fixture, tmp_path))
    assert (result.status, result.code) == ("not_verified", "missing_fixture_capability")
    assert fixture.prepared.store._original_source._closed


@pytest.mark.parametrize("case_id", ["S11", "S12", "S13", "S14"])
def test_receipt_case_cannot_pass_a_core_only_store(case_id, tmp_path):
    def change(session):
        session.store.session_receipt_version = None
        return session

    fixture = ChangedFixture(change)
    result = asyncio.run(api().run_session_case(case_id, fixture, tmp_path))
    assert (result.status, result.code) == ("not_verified", "missing_fixture_capability")


@pytest.mark.parametrize(
    "value", [(True, []), (0.0, []), [0, []], (1, [[]]), (0, {}), (1, [{"content": float("nan")}])]
)
def test_contract_does_not_repair_malformed_raw_read(value, tmp_path):
    def change(session):
        async def read(*args):
            return value

        session.store.read = read
        return session

    result = asyncio.run(api().run_session_case("S01", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


@pytest.mark.parametrize("ack", [True, 1.0, None, 0, -1, 500])
def test_contract_refuses_malformed_raw_ack_after_actual_write(ack, tmp_path):
    def change(session):
        original = session.store.append

        async def append(*args, **kwargs):
            await original(*args, **kwargs)
            return ack

        session.store.append = append
        return session

    result = asyncio.run(api().run_session_case("S02", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


def test_false_backend_switch_counter_cannot_supply_a_verdict(tmp_path):
    def change(session):
        async def ignore(kind):
            return None

        return dataclasses.replace(
            session, inject_fault=ignore, audit=lambda: {"backend_switches": 10, "close_calls": 0}
        )

    result = asyncio.run(api().run_session_case("S08", ChangedFixture(change), tmp_path))
    assert result.status == "failed"


def test_fake_pause_that_never_suspends_actual_append_cannot_pass(tmp_path):
    def change(session):
        def complete():
            return None

        return dataclasses.replace(
            session, pause=lambda operation: api().SessionContractPause(complete, complete)
        )

    result = asyncio.run(api().run_session_case("S09", ChangedFixture(change), tmp_path))
    assert result.status == "failed"


def test_non_none_management_result_is_not_a_pass(tmp_path):
    def change(session):
        return dataclasses.replace(
            session, inject_fault=lambda kind: None if kind == "reset" else True
        )

    result = asyncio.run(api().run_session_case("S07", ChangedFixture(change), tmp_path))
    assert result.status == "failed"
    assert result.observations["cleanup_complete"]


def test_backend_faults_must_cover_actual_append_as_well_as_read(tmp_path):
    def change(session):
        async def append(scope, session_id, message, **kwargs):
            return session.store._original_source.append(scope, session_id, message, **kwargs)

        session.store.append = append
        return session

    result = asyncio.run(api().run_session_case("S07", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


def test_direct_borrowed_adapter_is_not_closed(tmp_path):
    fixture = ChangedFixture(lambda session: dataclasses.replace(session, resources=()))
    result = asyncio.run(api().run_session_case("S02", fixture, tmp_path))
    assert result.status == "passed" and not result.observations["borrowed_closed"]
    assert not fixture.prepared.store._original_source._closed
    fixture.prepared.store._original_source.close()


def test_owned_cleanup_failure_transfers_original_owner_and_redacts_error(tmp_path):
    allowed = False

    def change(session):
        original = session.store._original_source.aclose

        async def close():
            if not allowed:
                raise OSError("PRIVATE token=must-not-leak")
            await original()

        session.store._original_source.aclose = close
        return session

    fixture = ChangedFixture(change)

    async def run():
        nonlocal allowed
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await api().run_session_case("S02", fixture, tmp_path)
        pending = captured.value
        assert pending.result.code == "cleanup_failed"
        assert "PRIVATE" not in canonical(pending.result.to_dict())
        assert not fixture.prepared.store._original_source._closed
        allowed = True
        await pending.cleanup()
        assert fixture.prepared.store._original_source._closed

    asyncio.run(run())


def test_failed_pause_release_retains_actual_call_before_close_and_retries(tmp_path):
    allowed = False

    def change(session):
        original = session.pause

        def pause(operation):
            gate = original(operation)

            async def release():
                if not allowed:
                    raise OSError("PRIVATE release failed")
                result = gate.release()
                if asyncio.iscoroutine(result):
                    await result

            return api().SessionContractPause(gate.wait_entered, release)

        return dataclasses.replace(session, pause=pause)

    fixture = ChangedFixture(change)

    async def run():
        nonlocal allowed
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await api().run_session_case("S09", fixture, tmp_path)
        assert not fixture.prepared.store._original_source._closed
        with pytest.raises(OSError):
            await captured.value.cleanup()
        assert not fixture.prepared.store._original_source._closed
        allowed = True
        await captured.value.cleanup()
        assert fixture.prepared.store._original_source._closed
        assert fixture.prepared.store._original_source.audit()["message_count"] == 1

    asyncio.run(run())


def test_repeated_observer_cancellation_retains_real_pause_and_resource(tmp_path):
    release_entered, allow_release = asyncio.Event(), asyncio.Event()

    def change(session):
        original = session.pause

        def pause(operation):
            gate = original(operation)

            async def release():
                release_entered.set()
                await allow_release.wait()
                gate.release()

            return api().SessionContractPause(gate.wait_entered, release)

        return dataclasses.replace(session, pause=pause)

    fixture = ChangedFixture(change)

    async def run():
        task = asyncio.create_task(api().run_session_case("S09", fixture, tmp_path))
        await asyncio.wait_for(release_entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not fixture.prepared.store._original_source._closed
        allow_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audit = fixture.prepared.store._original_source.audit()
        assert audit["message_count"] == audit["save_count"] == audit["close_calls"] == 1

    asyncio.run(run())


def test_cancelled_prepare_drains_original_preparation_then_closes_once(tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()

    class Fixture:
        session = None

        async def prepare(self, case_id, workspace):
            self.session = offline_session_fixture().prepare(case_id, workspace)
            entered.set()
            await finish.wait()
            return self.session

    fixture = Fixture()

    async def run():
        task = asyncio.create_task(api().run_session_case("S01", fixture, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not fixture.session.store._original_source._closed
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audit = fixture.session.store._original_source.audit()
        assert audit["close_calls"] == 1 and audit["read_calls"] == audit["append_calls"] == 0

    asyncio.run(run())


def test_suite_retains_failed_owner_workspace_and_retries_same_cleanup(tmp_path):
    from relf_agent.adapter_contracts import AdapterContractSuite

    allowed = False

    def change(session):
        source = session.store._original_source
        original = source.aclose

        async def close():
            if not allowed:
                raise OSError("PRIVATE original owner must remain")
            await original()

        source.aclose = close
        return session

    fixture = ChangedFixture(change)

    async def run():
        nonlocal allowed
        suite = AdapterContractSuite("session-store")
        report = await suite.run(fixture)
        source = fixture.prepared.store._original_source
        workspace = Path(source.path).parent
        assert report.status == "failed" and suite.pending_cleanup
        assert workspace.exists() and not source._closed
        with pytest.raises(CloseIncomplete):
            await suite.aclose()
        assert suite.pending_cleanup and workspace.exists() and not source._closed
        allowed = True
        await suite.aclose()
        assert source._closed and not suite.pending_cleanup and not workspace.exists()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [("revision", True), ("revision", 2.0), ("session_id", "other"), ("message_id", "other")],
)
def test_receipt_profile_refuses_malformed_raw_evidence(field, value, tmp_path):
    def change(session):
        original = session.store.inspect_message

        async def inspect(*args):
            receipt = await original(*args)
            receipt[field] = value
            return receipt

        session.store.inspect_message = inspect
        return session

    result = asyncio.run(api().run_session_case("S11", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


def test_lost_ack_refusal_before_commit_does_not_certify_accepted_write(tmp_path):
    def change(session):
        original = session.store.append

        async def append(*args, **kwargs):
            if session.store._fault == "append-ack-lost":
                raise ConnectionError("PRIVATE no accepted write")
            return await original(*args, **kwargs)

        session.store.append = append
        return session

    result = asyncio.run(api().run_session_case("S13", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


def test_core_requires_no_receipt_pagination_or_database_attributes(tmp_path):
    from relf_agent.session_adapter_contract_reference import ReferenceSQLiteSessionStore

    def change(session):
        core = ReferenceSQLiteSessionStore(session.store._original_source)
        assert not hasattr(core, "inspect_message") and not hasattr(core, "read_page")
        assert not hasattr(core, "connection") and not hasattr(core, "path")
        return dataclasses.replace(session, store=core)

    result = asyncio.run(api().run_session_case("S10", ChangedFixture(change), tmp_path))
    assert result.status == "passed", result.to_dict()


@pytest.mark.parametrize("case_id", [None, True, "K01", "S00", "S15", ["S01"]])
def test_role_runner_rejects_foreign_case_without_preparation(case_id, tmp_path):
    class Fixture:
        def prepare(self, *args):
            pytest.fail("invalid case cannot prepare a resource")

    from relf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        asyncio.run(api().run_session_case(case_id, Fixture(), tmp_path))


class DefaultFixture:
    def __init__(self, kind):
        self.kind = kind

    def prepare(self, case_id, workspace):
        store = (
            InMemoryMemory()
            if self.kind == "memory"
            else SQLiteMemory(Path(workspace) / "native.sqlite")
        )
        addresses = tuple(
            api().SessionContractAddress(scope, address)
            for scope in (
                Scope(workspace, principal)
                for workspace in ("w", "other-w")
                for principal in ("a", "b")
            )
            for address in ("red", "blue")
        )
        return api().SessionContractSession(
            store, addresses, resources=(api().SessionContractResource(store),), audit=lambda: {}
        )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("case_id", ["S01", "S02", "S03", "S04", "S05", "S06", "S10", "S11"])
def test_actual_default_typed_domain_without_caller_prevalidation(kind, case_id, tmp_path):
    result = asyncio.run(api().run_session_case(case_id, DefaultFixture(kind), tmp_path))
    assert result.status == "passed", result.to_dict()


@pytest.mark.parametrize("dropped", ["workspace", "principal"])
def test_scope_oracle_rejects_an_actual_store_ignoring_each_scope_component(dropped, tmp_path):
    def change(session):
        # Put the omitted component last in iteration order. The first two full
        # Scope values then vary only the retained component, reproducing the
        # original oracle's blind spot while supplying the complete matrix.
        scopes = (
            [Scope(w, p) for w in ("left", "right") for p in ("alice", "bob")]
            if dropped == "workspace"
            else [Scope(w, p) for p in ("alice", "bob") for w in ("left", "right")]
        )
        addresses = tuple(
            api().SessionContractAddress(scope, address)
            for scope in scopes
            for address in ("first", "second")
        )
        read, append = session.store.read, session.store.append

        def omitted(scope):
            return (
                Scope("left", scope.principal)
                if dropped == "workspace"
                else Scope(scope.workspace, "alice")
            )

        async def actual_read(scope, address):
            return await read(omitted(scope), address)

        async def actual_append(scope, address, message, **kwargs):
            return await append(omitted(scope), address, message, **kwargs)

        session.store.read, session.store.append = actual_read, actual_append
        return dataclasses.replace(session, addresses=addresses)

    fixture = ChangedFixture(change)
    result = asyncio.run(api().run_session_case("S03", fixture, tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")
    assert fixture.prepared.store._original_source._closed


@pytest.mark.parametrize("missing", ["workspace", "principal", "product"])
def test_incomplete_independent_scope_matrix_remains_unverified(missing, tmp_path):
    def change(session):
        scopes = (Scope("left", "alice"), Scope("right", "bob"))
        if missing == "workspace":
            scopes = (Scope("left", "alice"), Scope("left", "bob"))
        elif missing == "principal":
            scopes = (Scope("left", "alice"), Scope("right", "alice"))
        addresses = tuple(
            api().SessionContractAddress(scope, address)
            for scope in scopes
            for address in ("first", "second")
        )
        return dataclasses.replace(session, addresses=addresses)

    fixture = ChangedFixture(change)
    result = asyncio.run(api().run_session_case("S03", fixture, tmp_path))
    assert (result.status, result.code) == ("not_verified", "missing_fixture_capability")
    assert fixture.prepared.store._original_source.audit()["save_count"] == 0


@pytest.mark.parametrize("case_id", ["S02", "S10"])
def test_cancelled_first_seed_drains_it_without_later_writes_or_consumer(case_id, tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()

    def change(session):
        original = session.store.append

        async def append(*args, **kwargs):
            if kwargs["message_id"] == "contract-message-1":
                entered.set()
                await finish.wait()
            return await original(*args, **kwargs)

        session.store.append = append
        return session

    fixture = ChangedFixture(change)

    async def run():
        task = asyncio.create_task(api().run_session_case(case_id, fixture, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        source = fixture.prepared.store._original_source
        descriptor = source._file_descriptor
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not source._closed
        assert not (tmp_path / "consumer.sqlite").exists()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audit = source.audit()
        assert audit["append_calls"] == audit["message_count"] == audit["save_count"] == 1
        assert audit["close_calls"] == 1 and not (tmp_path / "consumer.sqlite").exists()
        assert source._file_descriptor is None
        with pytest.raises(OSError):
            os.fstat(descriptor)

    asyncio.run(run())


def test_cancelled_admitted_turn_setup_cancels_that_run_before_any_model_drive(tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()

    def change(session):
        original = session.inject_fault

        async def fault(kind):
            if kind == "append-ack-lost":
                entered.set()
                await finish.wait()
            original(kind)

        return dataclasses.replace(session, inject_fault=fault)

    fixture = ChangedFixture(change)

    async def run():
        task = asyncio.create_task(api().run_session_case("S14", fixture, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        source = fixture.prepared.store._original_source
        descriptor = source._file_descriptor
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not source._closed
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert source._closed and source._file_descriptor is None
        with pytest.raises(OSError):
            os.fstat(descriptor)
        with sqlite3.connect(tmp_path / "consumer.sqlite") as connection:
            runs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM runs")]
        assert len(runs) == 1
        assert runs[0]["state"] == "cancelled" and runs[0]["actions"] == []
        assert "session_turn" in runs[0]
        audit = source.audit()
        assert audit["append_calls"] == audit["save_count"] == 0 and audit["close_calls"] == 1
        assert fixture.prepared.store._fault is None

    asyncio.run(run())
