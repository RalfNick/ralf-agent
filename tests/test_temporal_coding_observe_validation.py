"""One pinned read-only Coding4 CONTROL keeps all SDK facts without cold full-check repetition."""

import asyncio
import copy
from collections import Counter
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus

from ralf_agent import temporal_coding_composition_control as composition_control
from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_coding_validation as validation
from ralf_agent import temporal_deployment_control_projection as projection
from ralf_agent import temporal_deployment_control_transport as transport
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_parent_state import CONTROL_ACTIVITY
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME
from ralf_agent.types import digest
from tests.test_temporal_deployment_session_registry import root_lookup, state, verified
from tests.test_temporal_session_deployment_dto import origin
from tests.test_temporal_session_tree_reading import tree_environment


def environment(monkeypatch, *, nested_depth=1):
    v, client, parent, _ = tree_environment(monkeypatch, nested_depth=nested_depth)
    runtime = v.runtime
    intent = v.intent
    reg = state()
    policy = reg.policy
    scope = parent.scope
    ns = intent["namespace"]
    rid = reg.registry_id
    payload = {
        "kind": "submit",
        "scope": scope,
        "command_id": intent["session_command_id"],
        "session_ref": intent["session_ref"],
        "input": intent["submission"]["request"]["input"],
        "budget": intent["submission"]["request"]["budget"],
    }
    reg.reserve(
        {
            "scope": scope,
            "admission_policy": policy,
            "namespace": ns,
            "command_id": intent["session_command_id"],
            "kind": "session_submit",
            "target": intent["coordinator_id"],
            "payload_digest": digest(payload),
            "session_submission": {
                "version": 1,
                "session_key": intent["session_ref"]["key"],
                "payload": payload,
                "logical_payload": payload,
                "binding": intent["binding"],
            },
        }
    )
    req = {
        "scope": scope,
        "admission_policy": policy,
        "namespace": ns,
        "command_id": intent["run_command_id"],
        "kind": "submit",
        "target": intent["run_id"],
        "payload_digest": digest(intent["submission"]["request"]),
        "root_admission": {
            "version": 4,
            "manifest_digest": digest(parent.manifest),
            "submission": intent["submission"],
            "session_origin": origin(intent),
        },
    }
    reg.commit_session_root(req, intent, verified(intent, req))
    root = parent.deployment_admission["root"]
    reg.bind_deployment_root(
        {
            "scope": scope,
            "admission_policy": policy,
            "namespace": ns,
            **{
                k: root[k]
                for k in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": parent.epoch,
        }
    )
    reg.deployment_registry_execution_epoch = "registry-original"
    reg.deployment_configuration_version = 4
    client.record = reg.deployment_session_root(root_lookup(req))
    base = client.get_workflow_handle
    counts = Counter()
    probe = SimpleNamespace(before_query=None, writes=[])
    for s in client.states.values():
        s.deployment_task_queue = intent["submission"]["task_queue"]
        s.deployment_activity_timeout = intent["submission"]["activity_timeout"]

    class Port:
        def __init__(self, identity, epoch):
            self.identity, self.epoch = identity, epoch
            self.inner = base(identity, run_id=epoch)

        async def describe(self):
            counts[("describe", self.identity)] += 1
            if self.identity == rid:
                return SimpleNamespace(
                    id=rid,
                    run_id="registry-original",
                    namespace=client.namespace,
                    task_queue=intent["submission"]["task_queue"],
                    workflow_type=COMMAND_REGISTRY_NAME,
                    parent_id=None,
                    parent_run_id=None,
                    raw_info=SimpleNamespace(first_run_id="registry-original"),
                    status=WorkflowExecutionStatus.RUNNING,
                )
            result = await self.inner.describe()
            result.status = WorkflowExecutionStatus.RUNNING
            return result

        def fetch_history_events(self, **kw):
            return self.inner.fetch_history_events(**kw)

        async def query(self, name, q):
            kind = q["kind"]
            counts[("query", kind)] += 1
            if probe.before_query is not None:
                probe.before_query(self.identity, kind)
            if self.identity == rid:
                if kind == "deployment_configuration":
                    return {"version": 4, "registry_id": rid, "policy": policy, "namespace": ns}
                if kind == "deployment_session_root":
                    return reg.deployment_session_root(q)
                if kind == "deployment_admission":
                    return {
                        "version": 1,
                        "registry_id": rid,
                        "scope": scope,
                        "namespace": ns,
                        "policy": policy,
                        "held_roots": list(reg.roots.values()),
                    }
                if kind == "deployment_coding_validation":
                    return projection.registry(reg, q)
                if kind == "coding_composition_candidates":
                    return reg.coding_candidates(q)
                if kind == "coding_composition_admission":
                    return reg.coding_admission(q)
            if self.identity in client.states:
                s = client.states[self.identity]
                if kind == "deployment_coding_validation":
                    return projection.node(s, q)
                if kind == "coding_composition_proof":
                    return composition.physical_stop_view(s)
                if kind == "coding_composition_children":
                    return copy.deepcopy(getattr(s, "children", []))
                if kind == "diagnostics":
                    return s.diagnostics()
            return await self.inner.query(name, q)

        async def execute_update(self, *a, **k):
            probe.writes.append((self.identity, a, k))
            raise AssertionError("unexpected write")

    def handle(identity, *, run_id=None):
        return Port(identity, run_id)

    client.get_workflow_handle = handle
    info = SimpleNamespace(
        workflow_id=parent.run_id,
        workflow_run_id=parent.epoch,
        workflow_namespace=client.namespace,
        task_queue=intent["submission"]["task_queue"],
        activity_id="control",
        activity_type=CONTROL_ACTIVITY,
        attempt=1,
    )
    full = Counter()
    original = runtime.validate_release

    def release(manifest=None):
        full["runtime"] += 1
        return original(manifest)

    runtime.validate_release = release
    return SimpleNamespace(
        runtime=runtime,
        client=client,
        parent=parent,
        call=parent.children[0],
        intent=intent,
        info=info,
        counts=counts,
        full=full,
        registry=reg,
        probe=probe,
    )


def test_pinned_readonly_observe_keeps_original_node_facts_and_independent_session_exit(
    monkeypatch,
):
    async def run():
        e = environment(monkeypatch)
        result = await transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
        )
        child = e.client.states[e.call["run_id"]]
        expected = {
            **child.diagnostics(),
            "scope": e.parent.scope,
            "coding_composition_proof": composition.physical_stop_view(child),
        }
        assert result == transport.pack_response(e.parent, e.call, expected)
        assert Counter({k[1]: v for k, v in e.counts.items() if k[0] == "query"}) == Counter(
            {
                "deployment_admission": 4,
                "deployment_session_root": 4,
                "deployment_start": 4,
                "deployment_session_intent": 2,
                "deployment_session_command": 2,
                "coding_composition_proof": 3,
                "deployment_configuration": 1,
                "deployment_coding_validation": 4,
                "coding_composition_children": 1,
                "diagnostics": 1,
            }
        )
        assert Counter(e.client.events) == Counter(
            namespace=25,
            describe=4,
            deployment_session_intent=2,
            deployment_session_command=2,
            history=2,
        )
        # Original non-Session reads stay identical. Session sampling now spans
        # the complete closed observation, with independent full entry/exit.
        assert e.full["runtime"] < 76

    asyncio.run(run())


def original_validator(e, cls=None):
    if cls is None:
        cls = getattr(validation, "_ObservationValidation", None)
        assert isinstance(cls, type), "Missing private readonly observation validator"
    return cls(
        e.runtime,
        e.client,
        {
            "scope": e.parent.scope,
            "run_id": e.parent.run_id,
            "execution_epoch": e.parent.epoch,
            "runtime_manifest": e.parent.manifest,
        },
        e.info,
    )


def test_register_uses_one_complete_permission_readset_on_each_side(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        e.parent.state = "running"
        e.parent.deployment_seal = None
        result = await transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "register"), e.info
        )
        assert result == {"run_id": e.call["run_id"], "registered": True}
        # Each side refreshes both the original root and Registry permission;
        # permission itself also performs the complete identity validation.
        assert e.counts[("query", "deployment_coding_validation")] == 4
        assert not e.probe.writes and not e.client.writes

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["runtime", "activity", "client", "source", "base_class", "base_check"]
)
def test_full_transport_rejects_drift_during_the_cold_readset(monkeypatch, fault):
    async def run():
        e = environment(monkeypatch)
        changed = []
        delegated = []

        def fake_check(self, *, full):
            delegated.append(True)
            return None

        def change(identity, kind):
            if kind != "deployment_coding_validation" or changed:
                return
            changed.append(True)
            if fault == "runtime":
                e.runtime.manifest = {**e.runtime.manifest, "changed": True}
            elif fault == "activity":
                e.info.activity_id = "foreign-activity"
            elif fault == "client":
                e.client.workflow_service = SimpleNamespace()
            elif fault == "base_class":

                class ForeignBase:
                    _check = fake_check

                monkeypatch.setattr(validation, "CodingValidation", ForeignBase)
            elif fault == "base_check":
                monkeypatch.setattr(validation.CodingValidation, "_check", fake_check)
            else:

                async def foreign(*args, **kwargs):
                    raise AssertionError("Changed source was used before checking its pin")

                monkeypatch.setattr(composition_control, "_proof", foreign)

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        assert changed and e.counts[("query", "diagnostics")] == 0
        assert delegated == []
        assert e.probe.writes == []

    asyncio.run(run())


def test_default_public_validation_and_permission_retain_full_checks(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        validator = original_validator(e, validation.CodingValidation)
        await validator.validate()
        for operation in (validator.validate, validator.permission):
            e.full.clear()
            await operation()
            assert e.full["runtime"] == 6
        with pytest.raises(DefinitionMismatch):
            validator._check(full=1)

    asyncio.run(run())


def test_readonly_request_pin_is_checked_after_original_sdk_reads(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        validator = original_validator(e)
        changed = []

        def change(identity, kind):
            if kind == "deployment_coding_validation" and not changed:
                changed.append(True)
                validator._request["scope"]["principal"] = "foreign"

        e.probe.before_query = change
        with pytest.raises(DefinitionMismatch):
            await validator.validate()
        assert changed and validator._snapshot is None and validator._snapshot_digest is None
        assert e.probe.writes == []

    asyncio.run(run())


def test_unpinned_observe_retains_the_default_full_path(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        e.call["child_execution"] = None
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
            )
        # The incomplete original pin is never promoted to the readonly type.
        assert e.full["runtime"] >= 50

    asyncio.run(run())


@pytest.mark.parametrize("activity_type", [None, "ralf.temporal.tool.v1"])
def test_other_activity_contexts_retain_original_full_observation(monkeypatch, activity_type):
    async def run():
        e = environment(monkeypatch)
        if activity_type is None:
            del e.info.activity_type
        else:
            e.info.activity_type = activity_type
        result = await transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
        )
        assert result["version"] == 1
        assert e.full["runtime"] == 50
        assert e.client.events.count("history") == 6
        assert e.probe.writes == []

    asyncio.run(run())


def test_private_readonly_validator_cannot_issue_native_permission(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        validator = original_validator(e)
        await validator.validate()
        before = e.counts.copy()
        for operation in (validator.permission, validator._validate_readset):
            with pytest.raises(DefinitionMismatch):
                await operation()
        assert e.counts == before
        with pytest.raises(DefinitionMismatch):
            validator._check(full=1)

    asyncio.run(run())


def test_cancelled_readonly_collection_clears_bootstrap_without_permission(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        validator = original_validator(e)
        cancelled = []

        def cancel(identity, kind):
            if kind == "deployment_coding_validation" and not cancelled:
                assert validator._snapshot is not None
                cancelled.append(True)
                asyncio.current_task().cancel()

        e.probe.before_query = cancel
        with pytest.raises(asyncio.CancelledError):
            await validator.validate()
        assert cancelled and validator._snapshot is None and validator._snapshot_digest is None
        before = e.counts.copy()
        with pytest.raises(DefinitionMismatch):
            await validator.permission()
        assert e.counts == before and e.probe.writes == []

    asyncio.run(run())


def test_bootstrap_cannot_turn_an_unexpected_sdk_update_into_observation(monkeypatch):
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        e = environment(monkeypatch)

        async def attempted_write(runtime, client, *args, **kwargs):
            # This is a negative write-injection test, never performance evidence
            # from a substituted validation result. No original proof is returned.
            await client.get_workflow_handle(e.parent.run_id, run_id=e.parent.epoch).execute_update(
                "unexpected", {}
            )
            raise AssertionError("Readonly bootstrap accepted a write")

        monkeypatch.setattr(execution, "_proof", attempted_write)
        validator = original_validator(e)
        with pytest.raises(DefinitionMismatch):
            await validator.validate()
        assert validator._snapshot is None and validator._snapshot_digest is None
        assert e.probe.writes == []

    asyncio.run(run())
