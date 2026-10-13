import asyncio
import dataclasses
import importlib
from pathlib import Path

import pytest

from ralf_agent.adapter_contract_types import AdapterContractCleanupPending
from ralf_agent.errors import ValidationError
from ralf_agent.types import Scope, canonical


def api():
    try:
        return importlib.import_module("ralf_agent.facts_adapter_contract")
    except ModuleNotFoundError:
        pytest.fail("The fixed Facts contract cases are missing")


def fixture():
    try:
        reference = importlib.import_module("ralf_agent.facts_adapter_contract_reference")
    except ModuleNotFoundError:
        pytest.fail("The independent Facts fixture is missing")
    return reference.offline_facts_fixture()


@pytest.mark.parametrize("case_id", [f"F{number:02}" for number in range(1, 17)])
def test_frozen_facts_case_checks_original_store_and_run_evidence(case_id, tmp_path):
    result = asyncio.run(api().run_facts_case(case_id, fixture(), tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    assert result.adapter_digest and result.configuration_digest
    assert result.observations["cleanup_complete"] is True
    if case_id in {"F10", "F12", "F14", "F15", "F16"}:
        assert result.execution_authority == "local"
        assert result.observations["consumer_runs"] == 1
    if case_id in {"F15", "F16"}:
        assert result.observations["model_calls"] == 1
        assert result.observations["write_count"] == 1
        assert result.observations["settlement_checks"] >= 1


class ChangedFixture:
    def __init__(self, transform):
        self.transform, self.prepared = transform, None

    def prepare(self, case_id, workspace):
        self.prepared = self.transform(fixture().prepare(case_id, workspace))
        return self.prepared


@pytest.mark.parametrize(
    "case_id,missing",
    [
        ("F01", "audit"),
        ("F07", "inject_fault"),
        ("F08", "inject_fault"),
        ("F09", "pause"),
        ("F12", "mutate_fact"),
        ("F12", "pause"),
        ("F13", "reopen"),
        ("F14", "inject_fault"),
        ("F15", "inject_fault"),
        ("F15", "reopen"),
        ("F16", "reopen"),
    ],
)
def test_missing_management_cannot_certify_a_case(case_id, missing, tmp_path):
    changed = ChangedFixture(lambda session: dataclasses.replace(session, **{missing: None}))
    result = asyncio.run(api().run_facts_case(case_id, changed, tmp_path))
    assert (result.status, result.code) == ("not_verified", "missing_fixture_capability")
    assert result.observations["cleanup_complete"]


@pytest.mark.parametrize("case_id", ["F13", "F15", "F16"])
def test_exact_inspection_requires_literal_v1_capability(case_id, tmp_path):
    def change(session):
        session.store.fact_inspection_version = True
        return session

    result = asyncio.run(api().run_facts_case(case_id, ChangedFixture(change), tmp_path))
    assert result.status == "not_verified"


@pytest.mark.parametrize(
    "value",
    [
        {},
        (),
        [dict(key="x", value=1, version=True, expires_at=None)],
        [dict(key="x", value=float("nan"), version=1, expires_at=None)],
    ],
)
def test_malformed_completed_fact_records_fail_actual_read(value, tmp_path):
    def change(session):
        async def facts(*args):
            return value

        session.store.facts = facts
        return session

    result = asyncio.run(api().run_facts_case("F01", ChangedFixture(change), tmp_path))
    assert (result.status, result.code) == ("failed", "contract_violation")


@pytest.mark.parametrize("ack", [True, 1.0, None, 0, 2])
def test_ack_must_be_exact_completed_next_version_after_actual_put(ack, tmp_path):
    def change(session):
        original = session.store.put_fact

        async def put(*args, **kwargs):
            await original(*args, **kwargs)
            return ack

        session.store.put_fact = put
        return session

    result = asyncio.run(api().run_facts_case("F01", ChangedFixture(change), tmp_path))
    assert result.status == "failed"


def test_full_partition_case_cannot_omit_one_principal(tmp_path):
    changed = ChangedFixture(lambda s: dataclasses.replace(s, addresses=s.addresses[:4]))
    result = asyncio.run(api().run_facts_case("F03", changed, tmp_path))
    assert result.status == "not_verified"


def test_raw_cas_retry_acceptance_is_not_message_idempotency(tmp_path):
    def change(session):
        original = session.store.put_fact

        async def dedupe(scope, namespace, key, value, **kwargs):
            found = await session.store.inspect_fact(scope, namespace, key)
            if found is not None and canonical(found["value"]) == canonical(value):
                return found["version"]
            return await original(scope, namespace, key, value, **kwargs)

        session.store.put_fact = dedupe
        return session

    result = asyncio.run(api().run_facts_case("F04", ChangedFixture(change), tmp_path))
    assert result.status == "failed"


def test_fixture_counter_and_ignored_backend_fault_cannot_supply_verdict(tmp_path):
    changed = ChangedFixture(
        lambda s: dataclasses.replace(
            s,
            inject_fault=lambda kind: None,
            audit=lambda: {"backend_switches": 99, "close_calls": 0},
        )
    )
    result = asyncio.run(api().run_facts_case("F08", changed, tmp_path))
    assert result.status == "failed"


def test_fake_pause_that_completes_without_suspended_put_cannot_pass(tmp_path):
    changed = ChangedFixture(
        lambda s: dataclasses.replace(
            s, pause=lambda name: api().FactsContractPause(lambda: None, lambda: None)
        )
    )
    result = asyncio.run(api().run_facts_case("F09", changed, tmp_path))
    assert result.status == "failed"


@pytest.mark.parametrize("case_id", ["F02", "F09"])
def test_borrowed_store_remains_usable_after_case(case_id, tmp_path):
    changed = ChangedFixture(lambda s: dataclasses.replace(s, resources=()))

    async def run():
        result = await api().run_facts_case(case_id, changed, tmp_path)
        assert result.status == "passed" and not result.observations["borrowed_closed"]
        address = changed.prepared.addresses[0]
        assert len(await changed.prepared.store.facts(address.scope, address.namespace)) >= 1
        for entry in fixture_resources:
            await entry.resource.aclose()

    fixture_resources = []
    original = changed.transform

    def save(session):
        fixture_resources.extend(session.resources)
        return original(session)

    changed.transform = save
    asyncio.run(run())


def test_failed_owned_close_retains_original_owner_loop_and_redacts_error(tmp_path):
    allowed, cleanup_loops = False, []

    def change(session):
        resource = session.resources[0].resource
        original = resource.aclose

        async def close():
            cleanup_loops.append(asyncio.get_running_loop())
            if not allowed:
                raise OSError("PRIVATE credential must not appear")
            await original()

        resource.aclose = close
        return session

    async def run():
        nonlocal allowed
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await api().run_facts_case("F02", ChangedFixture(change), tmp_path)
        pending = captured.value
        assert pending.result.code == "cleanup_failed"
        assert "PRIVATE" not in canonical(pending.result.to_dict())
        allowed = True
        await pending.cleanup()
        assert cleanup_loops == [asyncio.get_running_loop()] * 2

    asyncio.run(run())


def test_cancellation_during_preparation_drains_original_and_starts_no_case_io(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Preparing:
            async def prepare(self, case_id, workspace):
                self.session = fixture().prepare(case_id, workspace)
                entered.set()
                await release.wait()
                return self.session

        preparing = Preparing()
        task = asyncio.create_task(api().run_facts_case("F02", preparing, tmp_path))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audited = preparing.session.audit()
        if hasattr(audited, "__await__"):
            audited = await audited
        assert audited["facts_calls"] == audited["put_calls"] == 0
        assert audited["close_calls"] == 1

    asyncio.run(run())


def test_invalid_concrete_session_reports_failure_without_admitting_resources(tmp_path):
    class Invalid:
        def prepare(self, case_id, workspace):
            return True

    result = asyncio.run(api().run_facts_case("F01", Invalid(), tmp_path))
    assert (result.status, result.code) == ("failed", "invalid_fixture_session")


def test_failed_pause_release_retains_actual_handler_before_close_and_retries(tmp_path):
    allowed = False

    def change(session):
        original = session.pause

        def pause(name):
            gate = original(name)

            async def release():
                if not allowed:
                    raise OSError("PRIVATE original release failed")
                result = gate.release()
                if hasattr(result, "__await__"):
                    await result

            return api().FactsContractPause(gate.wait_entered, release)

        return dataclasses.replace(session, pause=pause)

    changed = ChangedFixture(change)

    async def run():
        nonlocal allowed
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await api().run_facts_case("F09", changed, tmp_path)
        assert (
            await changed.prepared.store.inspect_fact(
                changed.prepared.addresses[0].scope,
                changed.prepared.addresses[0].namespace,
                "paused",
            )
        ) is None
        assert changed.prepared.audit()["close_calls"] == 0
        with pytest.raises(OSError):
            await captured.value.cleanup()
        assert changed.prepared.audit()["close_calls"] == 0
        allowed = True
        await captured.value.cleanup()
        assert changed.prepared.audit()["write_count"] == 1
        assert changed.prepared.audit()["close_calls"] == 1

    asyncio.run(run())


def test_repeated_cancellation_retains_suspended_original_handler_until_release(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()

        def change(session):
            original = session.pause

            def pause(name):
                gate = original(name)

                async def release():
                    entered.set()
                    await allowed.wait()
                    value = gate.release()
                    if hasattr(value, "__await__"):
                        await value

                return api().FactsContractPause(gate.wait_entered, release)

            return dataclasses.replace(session, pause=pause)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F09", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and changed.prepared.audit()["close_calls"] == 0
        allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audited = changed.prepared.audit()
        assert audited["write_count"] == audited["close_calls"] == 1
        # Initial empty read only; cancellation prevents the follow-up read.
        assert audited["facts_calls"] == 1

    asyncio.run(run())


def test_cancelled_fault_setup_performs_reset_without_later_read_or_put(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()

        def change(session):
            original = session.inject_fault

            async def fault(kind):
                original(kind)
                if kind == "backend-error":
                    entered.set()
                    await allowed.wait()

            return dataclasses.replace(session, inject_fault=fault)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F07", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        audited = changed.prepared.audit()
        assert audited["facts_calls"] == 1 and audited["put_calls"] == 0
        assert audited["close_calls"] == 1 and changed.prepared.store._fault is None

    asyncio.run(run())


def test_cancelled_managed_setup_retains_and_cancels_already_admitted_original_run(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()

        def change(session):
            original = session.inject_fault

            async def fault(kind):
                original(kind)
                if kind == "put-ack-lost":
                    entered.set()
                    await allowed.wait()

            return dataclasses.replace(session, inject_fault=fault)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F15", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        import json
        import sqlite3

        with sqlite3.connect(tmp_path / "consumer.sqlite") as connection:
            rows = list(connection.execute("SELECT data FROM runs"))
        assert len(rows) == 1
        original_run = json.loads(rows[0][0])
        assert original_run["state"] in {"cancelling", "cancelled"}
        assert original_run["actions"] == []
        assert changed.prepared.audit()["put_calls"] == 0

    asyncio.run(run())


def test_suite_transfers_failed_original_owner_workspace_and_retries_cleanup(tmp_path):
    from ralf_agent.adapter_contracts import AdapterContractSuite
    from ralf_agent.errors import CloseIncomplete

    allowed = False

    def change(session):
        owner = session.resources[0].resource
        original = owner.aclose

        async def close():
            if not allowed:
                raise OSError("PRIVATE original owner")
            await original()

        owner.aclose = close
        return session

    changed = ChangedFixture(change)

    async def run():
        nonlocal allowed
        suite = AdapterContractSuite("facts-store")
        result = await suite.run(changed)
        owner = changed.prepared.resources[0].resource
        workspace = Path(owner.path).parent
        assert result.status == "failed" and suite.pending_cleanup and workspace.exists()
        with pytest.raises(CloseIncomplete):
            await suite.aclose()
        assert workspace.exists() and changed.prepared.audit()["close_calls"] == 0
        allowed = True
        await suite.aclose()
        assert owner._closed and not workspace.exists()

    asyncio.run(run())


def test_cancelled_pipeline_foreground_cannot_start_second_actual_write(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()
        attempted = []

        def change(session):
            original = session.store.put_fact

            async def put(scope, namespace, key, value, **kwargs):
                observation = not namespace.endswith(":commands")
                if observation:
                    attempted.append(key)
                result = await original(scope, namespace, key, value, **kwargs)
                if observation:
                    entered.set()
                    await allowed.wait()
                return result

            session.store.put_fact = put
            return session

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F14", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(attempted) == 1
        assert changed.prepared.audit()["write_count"] == 2  # command and one observation
        assert changed.prepared.audit()["close_calls"] == 1

    asyncio.run(run())


def test_failed_original_validation_run_does_not_wait_forever_for_unentered_pause(tmp_path):
    def change(session):
        async def recall(*args):
            raise ValidationError("actual source recall refused")

        session.store.recall = recall
        return session

    async def run():
        result = await asyncio.wait_for(
            api().run_facts_case("F12", ChangedFixture(change), tmp_path), 2
        )
        assert result.status == "failed" and result.observations["cleanup_complete"]

    asyncio.run(run())


def test_completed_put_does_not_wait_forever_for_fake_unentered_pause(tmp_path):
    async def run():
        never = asyncio.Event()

        async def wait():
            await never.wait()

        changed = ChangedFixture(
            lambda session: dataclasses.replace(
                session, pause=lambda name: api().FactsContractPause(wait, lambda: None)
            )
        )
        result = await asyncio.wait_for(api().run_facts_case("F09", changed, tmp_path), 2)
        assert result.status == "failed" and result.observations["cleanup_complete"]

    asyncio.run(run())


def test_cancel_during_unreturned_entry_ack_releases_actual_handler_and_closes(tmp_path):
    async def run():
        entered, never = asyncio.Event(), asyncio.Event()

        def change(session):
            original = session.pause

            def pause(name):
                gate = original(name)

                async def wait():
                    await gate.wait_entered()
                    entered.set()
                    await never.wait()

                return api().FactsContractPause(wait, gate.release)

            return dataclasses.replace(session, pause=pause)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F09", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert changed.prepared.audit()["write_count"] == 1
        assert changed.prepared.audit()["close_calls"] == 1

    asyncio.run(run())


def test_repeated_cancellation_during_final_audit_keeps_failed_cleanup_owner(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()
        close_allowed = False

        def change(session):
            owner = session.resources[0].resource
            original = owner.aclose
            closing = False

            async def close():
                nonlocal closing
                closing = True
                if not close_allowed:
                    raise OSError("private cleanup failure")
                await original()

            owner.aclose = close

            async def audit():
                if closing:
                    entered.set()
                    await allowed.wait()
                return session.resources[0].resource.audit()

            return dataclasses.replace(session, audit=audit)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F02", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        allowed.set()
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await task
        close_allowed = True
        await captured.value.cleanup()
        assert changed.prepared.resources[0].resource._closed

    asyncio.run(run())


def test_cancelled_pipeline_drains_original_engine_backing_thread_before_owned_close(tmp_path):
    import threading

    from ralf_agent.facts_adapter_contract_reference import ReferenceSQLiteManagedFactsStore
    from ralf_agent.memory import ThreadedMemoryAdapter

    async def run():
        entered, allowed, finished = threading.Event(), threading.Event(), threading.Event()
        attempted = []

        def change(session):
            class Slow(ReferenceSQLiteManagedFactsStore):
                def put_fact(self, scope, namespace, key, value, **kwargs):
                    observation = not namespace.endswith(":commands")
                    if observation:
                        attempted.append(key)
                    result = super().put_fact(scope, namespace, key, value, **kwargs)
                    if observation:
                        entered.set()
                        allowed.wait(5)
                        finished.set()
                    return result

            store = Slow(session.resources[0].resource)
            original = session.inject_fault

            def fault(kind):
                original(kind)
                if kind == "reset":
                    store._fault, store._fault_puts = None, 0
                else:
                    store._fault, store._fault_puts = kind, 0

            return dataclasses.replace(
                session, store=ThreadedMemoryAdapter(store), inject_fault=fault
            )

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F14", changed, tmp_path))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():  # noqa: ASYNC110 -- actual backing thread event
                    await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and changed.prepared.audit()["close_calls"] == 0
            allowed.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set() and len(attempted) == 1
            assert changed.prepared.audit()["close_calls"] == 1
        finally:
            allowed.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_failed_cancel_cleanup_reset_preserves_original_case_owner_until_retry(tmp_path):
    async def run():
        entered, allowed = asyncio.Event(), asyncio.Event()
        reset_allowed = False

        def change(session):
            original = session.inject_fault

            async def fault(kind):
                if kind == "reset" and not reset_allowed:
                    raise OSError("PRIVATE original reset failed")
                original(kind)
                if kind == "backend-error":
                    entered.set()
                    await allowed.wait()

            return dataclasses.replace(session, inject_fault=fault)

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F07", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        allowed.set()
        with pytest.raises(AdapterContractCleanupPending) as captured:
            await task
        assert changed.prepared.audit()["close_calls"] == 0
        assert changed.prepared.store._fault == "backend-error"
        reset_allowed = True
        await captured.value.cleanup()
        assert changed.prepared.audit()["close_calls"] == 1
        assert changed.prepared.store._fault is None

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("case_id", ["F01", "F02", "F03", "F04", "F05", "F06", "F10", "F11"])
def test_native_default_data_contracts_remain_compatible(kind, case_id, tmp_path):
    from ralf_agent import InMemoryMemory, SQLiteMemory

    class Native:
        def prepare(self, case_id, workspace):
            store = (
                InMemoryMemory() if kind == "memory" else SQLiteMemory(workspace / "native.sqlite")
            )
            addresses = tuple(
                api().FactsContractAddress(Scope(w, principal), namespace)
                for w in ("alpha", "beta")
                for principal in ("one", "two")
                for namespace in ("first", "second")
            )
            return api().FactsContractSession(
                store, addresses, resources=(api().FactsContractResource(store),), audit=lambda: {}
            )

    result = asyncio.run(api().run_facts_case(case_id, Native(), tmp_path))
    assert result.status == "passed", result.to_dict()


def test_core_case_uses_a_store_without_managed_ports_or_database_attributes(tmp_path):
    from ralf_agent.facts_adapter_contract_reference import ReferenceSQLiteFactsStore

    def change(session):
        core = ReferenceSQLiteFactsStore(session.resources[0].resource)
        assert not hasattr(core, "recall") and not hasattr(core, "inspect_fact")
        assert not hasattr(core, "connection") and not hasattr(core, "path")
        return dataclasses.replace(session, store=core)

    result = asyncio.run(api().run_facts_case("F10", ChangedFixture(change), tmp_path))
    assert result.status == "passed", result.to_dict()


@pytest.mark.parametrize("case_id", [None, True, "K01", "S01", "F00", "F17", ["F01"]])
def test_foreign_case_is_rejected_before_fixture_preparation(case_id, tmp_path):
    class Never:
        def prepare(self, *args):
            pytest.fail("invalid identity must not prepare a resource")

    with pytest.raises(ValidationError):
        asyncio.run(api().run_facts_case(case_id, Never(), tmp_path))


def test_real_delayed_recall_establishes_original_post_validation_expiry_window(tmp_path):
    def change(session):
        original = session.store.recall

        async def recall(*args):
            await asyncio.sleep(0.5)
            return await original(*args)

        session.store.recall = recall
        return session

    changed = ChangedFixture(change)
    result = asyncio.run(api().run_facts_case("F12", changed, tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    assert result.observations["model_calls"] == 0
    assert result.observations["handler_finished"] and result.observations["cleanup_complete"]
    assert changed.prepared.resources[0].resource._closed


@pytest.mark.parametrize("case_id", ["F10", "F11", "F13", "F14"])
def test_valid_maximum_namespace_runs_original_consumers_and_pipeline_command(case_id, tmp_path):
    import sqlite3

    def change(session):
        addresses = tuple(
            api().FactsContractAddress(
                address.scope, ("n" if address.namespace == "first" else "m") * 128
            )
            for address in session.addresses
        )
        return dataclasses.replace(session, addresses=addresses)

    changed = ChangedFixture(change)
    result = asyncio.run(api().run_facts_case(case_id, changed, tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    source = changed.prepared.resources[0].resource
    assert source._closed and result.observations["cleanup_complete"]
    with sqlite3.connect(source.path) as connection:
        rows = list(connection.execute("SELECT namespace,key,version FROM facts"))
    assert all(len(namespace) <= 128 for namespace, _, _ in rows)
    if case_id == "F14":
        command = [
            (namespace, version) for namespace, key, version in rows if key.startswith("command:")
        ]
        assert command == [("n" * 119 + ":commands", 1)]
        assert (
            result.observations["model_calls"] == 1 and result.observations["duplicate_checks"] == 3
        )


@pytest.mark.parametrize("case_id", ["F02", "F09", "F15", "F16"])
def test_borrowed_reopened_dataset_uses_actual_case_close_delta(case_id, tmp_path):
    from ralf_agent.facts_adapter_contract_reference import ReferenceFactsSource

    class Borrowed:
        def prepare(self, case_id, workspace):
            prior = ReferenceFactsSource(workspace / "facts.sqlite")
            prior.close()
            session = fixture().prepare(case_id, workspace)
            self.source = session.resources[0].resource
            self.session = dataclasses.replace(session, resources=())
            self.before = self.session.audit()["close_calls"]
            return self.session

    borrowed = Borrowed()
    try:
        result = asyncio.run(api().run_facts_case(case_id, borrowed, tmp_path))
        assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
        assert borrowed.before == borrowed.session.audit()["close_calls"] == 1
        assert result.observations["borrowed_closed"] is False
        assert not borrowed.source._closed
    finally:
        borrowed.source.close()


def test_changed_real_latency_leaves_expiry_window_unverified_without_false_failure(tmp_path):
    import time

    def change(session):
        expiry = None
        original_put, original_recall = session.store.put_fact, session.store.recall

        async def put(*args, **kwargs):
            nonlocal expiry
            result = await original_put(*args, **kwargs)
            if args[2] == "await-expiry":
                expiry = kwargs["expires_at"]
            return result

        async def recall(*args):
            if expiry is not None:
                await asyncio.sleep(max(0, expiry - time.time()) + 0.02)
            return await original_recall(*args)

        session.store.put_fact, session.store.recall = put, recall
        return session

    changed = ChangedFixture(change)
    result = asyncio.run(api().run_facts_case("F12", changed, tmp_path))
    assert (result.status, result.code) == ("not_verified", "case_not_verified"), result.to_dict()
    assert result.observations["consumer_runs"] == 1 and result.observations["model_calls"] == 0
    assert (
        result.observations["cleanup_complete"] and changed.prepared.resources[0].resource._closed
    )


def test_cancellation_during_real_read_calibration_retains_admitted_run_and_seeds_no_deadline(
    tmp_path,
):
    import json
    import sqlite3

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()

        def change(session):
            original = session.store.recall

            async def recall(*args):
                result = await original(*args)
                entered.set()
                await released.wait()
                return result

            session.store.recall = recall
            return session

        changed = ChangedFixture(change)
        task = asyncio.create_task(api().run_facts_case("F12", changed, tmp_path))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        source = changed.prepared.resources[0].resource
        assert source._closed
        with sqlite3.connect(source.path) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM facts WHERE key='await-expiry'"
                ).fetchone()[0]
                == 0
            )
        with sqlite3.connect(tmp_path / "consumer.sqlite") as connection:
            rows = list(connection.execute("SELECT data FROM runs"))
        assert len(rows) == 1
        original = json.loads(rows[0][0])
        assert original["state"] in {"cancelling", "cancelled"} and original["actions"] == []

    asyncio.run(run())


def test_borrowed_close_count_absence_does_not_invent_lifecycle_proof(tmp_path):
    def change(session):
        return dataclasses.replace(session, resources=(), audit=lambda: {})

    changed = ChangedFixture(change)
    resources = []
    original = changed.transform

    def retain(session):
        resources.extend(session.resources)
        return original(session)

    changed.transform = retain
    try:
        result = asyncio.run(api().run_facts_case("F02", changed, tmp_path))
        assert (result.status, result.code) == ("not_verified", "case_not_verified")
        assert "borrowed_closed" not in result.observations
        assert not resources[0].resource._closed
    finally:
        resources[0].resource.close()


def test_reset_actual_lifecycle_counter_leaves_borrowed_evidence_unverified(tmp_path):
    from ralf_agent.facts_adapter_contract_reference import ReferenceFactsSource

    class Borrowed:
        def prepare(self, case_id, workspace):
            prior = ReferenceFactsSource(workspace / "facts.sqlite")
            prior.close()
            session = fixture().prepare(case_id, workspace)
            self.source = session.resources[0].resource
            original = session.store.facts
            reset = False

            async def facts(*args):
                nonlocal reset
                result = await original(*args)
                if not reset:
                    with self.source._connection(write=True) as connection:
                        connection.execute("UPDATE audit SET count=0 WHERE kind='close_calls'")
                    reset = True
                return result

            session.store.facts = facts
            return dataclasses.replace(session, resources=())

    borrowed = Borrowed()
    try:
        result = asyncio.run(api().run_facts_case("F02", borrowed, tmp_path))
        assert (result.status, result.code) == ("not_verified", "case_not_verified")
        assert "borrowed_closed" not in result.observations and not borrowed.source._closed
    finally:
        borrowed.source.close()


def test_shared_actual_audit_dictionary_cannot_hide_borrowed_source_close(tmp_path):
    class LiveCounters:
        def prepare(self, case_id, workspace):
            session = fixture().prepare(case_id, workspace)
            self.source = session.resources[0].resource
            original = session.store.facts

            async def facts(*args):
                records = await original(*args)
                if records:
                    self.source.close()
                return records

            session.store.facts = facts
            counters = {}

            def audit():
                counters.clear()
                counters.update(self.source.audit())
                return counters

            return dataclasses.replace(session, resources=(), audit=audit)

    live = LiveCounters()
    try:
        result = asyncio.run(api().run_facts_case("F02", live, tmp_path))
        assert (result.status, result.code) == ("failed", "contract_violation")
        assert result.observations["borrowed_closed"] is True
        assert live.source._closed and live.source.audit()["close_calls"] == 1
    finally:
        live.source.close()


def test_derived_pipeline_namespace_retains_nonwhitespace_at_valid_bound(tmp_path):
    import sqlite3

    def change(session):
        addresses = tuple(
            api().FactsContractAddress(
                address.scope, " " * 127 + ("n" if address.namespace == "first" else "m")
            )
            for address in session.addresses
        )
        return dataclasses.replace(session, addresses=addresses)

    changed = ChangedFixture(change)
    result = asyncio.run(api().run_facts_case("F14", changed, tmp_path))
    assert (result.status, result.code) == ("passed", "verified"), result.to_dict()
    source = changed.prepared.resources[0].resource
    assert source._closed
    with sqlite3.connect(source.path) as connection:
        namespaces = [row[0] for row in connection.execute("SELECT DISTINCT namespace FROM facts")]
    assert len(namespaces) == 2
    assert all(namespace.strip() and len(namespace) <= 128 for namespace in namespaces)
    assert any(namespace.endswith(":commands") for namespace in namespaces)
    assert result.observations["model_calls"] == 1 and result.observations["duplicate_checks"] == 3


@pytest.mark.parametrize("address", [(object(), "n"), (Scope(), " "), (Scope(), "x" * 129)])
def test_fixture_address_requires_trusted_bounded_scope_namespace(address):
    with pytest.raises(ValidationError):
        api().FactsContractAddress(*address)
