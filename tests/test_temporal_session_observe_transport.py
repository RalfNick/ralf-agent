"""Coding4 observer read groups keep local checks and terminal SDK freshness."""

import asyncio
import copy

import pytest

from relf_agent import temporal_deployment_execution as execution
from relf_agent import temporal_session_deployment_control as control
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_deployment_verification import SessionControlValidation
from tests import test_temporal_session_deployment_dto as dto_fixture
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest
from tests.test_temporal_session_deployment_control import positive_observation


class CountedValidation(SessionControlValidation):
    def __init__(self, *args, **options):
        self.validations, self.full_checks = 0, 0
        super().__init__(*args, **options)

    def _check(self, *, full=True):
        self.full_checks += full
        return super()._check(full=full)

    async def validate(self):
        self.validations += 1
        return await super().validate()


def environment(monkeypatch, *, coding=True, composition=False):
    if coding:
        monkeypatch.setattr(
            dto_fixture, "MANIFEST", coding_session_manifest(composition=composition)
        )
    original, client = positive_observation()
    runtime = original.runtime
    runtime.rebuilds = 0
    validate_release = runtime.validate_release

    def counted(manifest=None):
        runtime.rebuilds += 1
        return validate_release(manifest)

    runtime.validate_release = counted
    proof = CountedValidation(
        runtime,
        client,
        original.value,
        original.info,
        deployment_id=original.deployment_id,
    )
    return proof, client


@pytest.mark.parametrize("kind", ["native", "composition", "ordinary"])
def test_actual_coding_observer_aggregates_runtime_checks_around_readonly_group(monkeypatch, kind):
    async def run():
        proof, client = environment(
            monkeypatch, coding=kind != "ordinary", composition=kind == "composition"
        )
        original = execution._proof
        sampled = []

        async def collect(runtime, readonly, policy, scope, run_id, epoch, **options):
            before, checked = proof.validations, proof.full_checks
            rebuilt = runtime.rebuilds
            await readonly.get_workflow_handle(run_id, run_id=epoch).describe()
            assert proof.validations == before + (kind == "ordinary")
            if kind == "ordinary":
                assert proof.full_checks >= checked + 2 and runtime.rebuilds > rebuilt
            else:
                assert runtime.rebuilds == rebuilt
                assert proof.full_checks == checked
            assert not hasattr(readonly.get_workflow_handle(run_id), "execute_update")
            sampled.append(True)
            return await original(runtime, readonly, policy, scope, run_id, epoch, **options)

        monkeypatch.setattr(execution, "_proof", collect)
        result = await control._observe(proof)
        assert sampled and all(sampled)
        assert result["advance"]["retirement"] == client.business_retirement
        assert proof.validations > 0  # Group exits retain complete SDK verification.

    asyncio.run(run())


@pytest.mark.parametrize("value", [None, 0, 1])
def test_aggregate_transport_requires_strict_internal_boolean(monkeypatch, value):
    proof, _ = environment(monkeypatch)
    with pytest.raises(DefinitionMismatch):
        control._CheckedClient(proof, _aggregate=value)


def test_ordinary_transport_cannot_select_coding_aggregation(monkeypatch):
    proof, _ = environment(monkeypatch, coding=False)
    with pytest.raises(DefinitionMismatch):
        control._CheckedClient(proof, _aggregate=True)


@pytest.mark.parametrize("original,changed", [(False, True), (True, False), (True, 1)])
def test_transport_cannot_change_selected_read_boundary_during_sdk_await(
    monkeypatch, original, changed
):
    async def run():
        proof, client = environment(monkeypatch)
        readonly = control._CheckedClient(proof, _aggregate=original)

        def mutate(name):
            if name == "business_describe":
                readonly._aggregate = changed

        client.mutate = mutate
        with pytest.raises(DefinitionMismatch):
            await readonly.get_workflow_handle(proof.intent["run_id"]).describe()
        assert proof.validations == 0

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["source", "activity", "port", "request"])
def test_aggregate_post_read_local_check_refuses_drift_before_read_can_be_used(monkeypatch, fault):
    async def run():
        proof, client = environment(monkeypatch)
        readonly = control._CheckedClient(proof, _aggregate=True)
        fired = False

        def changed(name):
            nonlocal fired
            if name != "business_describe" or fired:
                return
            fired = True
            if fault == "source":
                monkeypatch.setattr(SessionControlValidation, "_namespace", lambda self: None)
            elif fault == "activity":
                proof.info.attempt += 1
            elif fault == "port":
                monkeypatch.setattr(client, "get_workflow_handle", lambda *a, **k: None)
            else:
                proof.value["mode"] = "register"

        client.mutate = changed
        with pytest.raises(DefinitionMismatch):
            await readonly.get_workflow_handle(proof.intent["run_id"]).describe()
        assert fired and proof.validations == 0

    asyncio.run(run())


def test_actual_observe_full_group_exit_refuses_runtime_drift_before_advance(monkeypatch):
    async def run():
        proof, client = environment(monkeypatch)
        original = execution._proof
        collected, returned = [], []

        async def read_group(runtime, readonly, policy, scope, run_id, epoch, **options):
            verified = await original(runtime, readonly, policy, scope, run_id, epoch, **options)
            rebuilt = runtime.rebuilds

            def changed(name):
                if name == "business_describe":
                    runtime.manifest = {"changed": True}

            client.mutate = changed
            await readonly.get_workflow_handle(run_id, run_id=epoch).describe()
            assert runtime.rebuilds == rebuilt
            collected.append(proof.validations)
            return verified  # The enclosing actual _observe must verify its exit.

        monkeypatch.setattr(execution, "_proof", read_group)
        with pytest.raises(DefinitionMismatch):
            returned.append(await control._observe(proof))
        assert collected and proof.validations > collected[-1]
        assert not returned

    asyncio.run(run())


def test_history_every_item_and_default_transport_keep_original_read_boundaries(monkeypatch):
    from tests.test_temporal_session_deployment_control import BusinessHandle

    original = BusinessHandle.fetch_history_events

    def two_items(handle, **options):
        async def events():
            first = await anext(original(handle, **options))
            yield first
            await asyncio.sleep(0)
            second = copy.deepcopy(first)
            second.event_id = 2
            yield second

        return events()

    monkeypatch.setattr(BusinessHandle, "fetch_history_events", two_items)

    async def run():
        proof, _ = environment(monkeypatch)
        for aggregate in (False, True):
            readonly = control._CheckedClient(proof, _aggregate=aggregate)
            before, checked = proof.validations, proof.full_checks
            handle = readonly.get_workflow_handle(proof.intent["run_id"])
            assert not hasattr(handle, "execute_update")
            events = handle.fetch_history_events()
            assert (await anext(events)).event_id == 1
            assert proof.validations == before + (not aggregate)
            assert (await anext(events)).event_id == 2
            assert proof.validations == before + 2 * (not aggregate)
            if aggregate:
                assert proof.full_checks == checked
            else:
                assert proof.full_checks >= checked + 3
            await events.aclose()
            # Namespace/query/describe all use the same explicit local boundary.
            await readonly.workflow_service.describe_namespace(object())
            await handle.query(
                "view", {"kind": "deployment_closure", "scope": proof.intent["scope"]}
            )
            await handle.describe()
            assert proof.validations == before + 5 * (not aggregate)
            rebuilt = proof.runtime.rebuilds
            await proof.validate()  # A collected read set becomes usable only after this boundary.
            assert proof.runtime.rebuilds > rebuilt

    asyncio.run(run())


def test_each_aggregate_history_item_rechecks_original_request_pins(monkeypatch):
    from tests.test_temporal_session_deployment_control import BusinessHandle

    original = BusinessHandle.fetch_history_events

    def two_items(handle, **options):
        async def events():
            first = await anext(original(handle, **options))
            yield first
            await asyncio.sleep(0)
            proof.value["mode"] = "register"
            yield copy.deepcopy(first)

        return events()

    monkeypatch.setattr(BusinessHandle, "fetch_history_events", two_items)

    async def run():
        nonlocal proof
        proof, _ = environment(monkeypatch)
        readonly = control._CheckedClient(proof, _aggregate=True)
        events = readonly.get_workflow_handle(proof.intent["run_id"]).fetch_history_events()
        assert (await anext(events)).event_id == 1
        with pytest.raises(DefinitionMismatch):
            await anext(events)
        assert proof.validations == 0
        await events.aclose()

    proof = None
    asyncio.run(run())
