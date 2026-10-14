"""Original no-submit evidence is cleanup only, never a second native attempt."""

import asyncio
import copy
import hashlib
import inspect

import pytest

from ralf_agent import AgentSpec
from ralf_agent import coding_execution_rules as rules
from ralf_agent import postgres_coding_resources as resources
from ralf_agent.errors import RalfError
from ralf_agent.types import canonical, digest
from tests.test_coding_execution_rules import intent as native_intent
from tests.test_dev106_native_resources import intent as resource_intent
from tests.test_dev106_native_resources import receipt
from tests.test_local_delegated_coding import LifecycleRunner, coding_engine


def environment(value):
    return {
        **value,
        "create_operation_version": 2,
        "create_supervision_version": 1,
        "retire_on_stop": True,
    }


def no_create(env, **changes):
    proof = {
        "version": 1,
        "identity": copy.deepcopy(env),
        "generation": env["expected_generation"],
        "create_operation_digest": "a" * 64,
        "supervision_declaration_digest": "b" * 64,
        "supervision_receipt_digest": "c" * 64,
        "gate_sealed": True,
        "cli_gate_accepted": False,
        "cli_exec_started": False,
        "helpers_ended": True,
        "control_drained": True,
        "metadata_present": True,
        "namespace_query_succeeded": True,
        "namespace_confirmed": True,
        "container_present": False,
    }
    proof.update(changes)
    proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})
    return proof


def prepared_intent():
    state, runner, binding = native_intent()
    binding["environment"] = environment(binding["environment"])
    rules.grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)
    state["effect_case"] = "unknown"
    return state, runner, binding


def resource():
    key, request, runner, binding = resource_intent()
    binding["environment"] = environment(binding["environment"])
    return key, resources.new_resource(key, request, runner, binding), binding


def test_original_pure_adoption_preserves_unknown_and_grant():
    state, runner, binding = prepared_intent()
    before = copy.deepcopy(state["grants"])
    proof = no_create(binding["environment"])
    rules.adopt_create_not_dispatched(state, runner, proof)
    assert state["create_not_dispatched"] == proof
    assert state["fenced"] is True and state["pending_stop"] is False
    assert state["effect_case"] == "unknown" and state["grants"] == before
    assert "stop" not in state and "prepared" not in state and "binding" not in state
    rules.adopt_create_not_dispatched(state, runner, proof)
    with pytest.raises(RalfError):
        rules.grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("generation", "f" * 32),
        ("create_operation_digest", "x" * 64),
        ("supervision_declaration_digest", ""),
        ("supervision_receipt_digest", "f" * 63),
        ("gate_sealed", False),
        ("cli_gate_accepted", True),
        ("cli_exec_started", True),
        ("helpers_ended", False),
        ("control_drained", False),
        ("metadata_present", False),
        ("namespace_query_succeeded", False),
        ("namespace_confirmed", False),
        ("container_present", True),
        ("container_id", None),
        ("pid", 0),
    ],
)
def test_negative_proofs_fail_without_mutation(field, value):
    state, runner, binding = prepared_intent()
    before = copy.deepcopy(state)
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(
            state, runner, no_create(binding["environment"], **{field: value})
        )
    assert state == before


@pytest.mark.parametrize(
    "field", ["prepared", "binding", "thread", "turn", "stop", "namespace_absent", "unprepared"]
)
def test_original_native_locator_or_old_tombstone_contradicts_no_submit(field):
    state, runner, binding = prepared_intent()
    state[field] = {"old": "receipt"}
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, runner, no_create(binding["environment"]))


def test_proof_digest_and_original_eligible_environment_are_required():
    state, runner, binding = prepared_intent()
    proof = no_create(binding["environment"])
    proof["supervision_receipt_digest"] = "e" * 64
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, runner, proof)
    for flag, value in [
        ("create_supervision_version", True),
        ("create_supervision_version", 0),
        ("create_operation_version", 1),
        ("retire_on_stop", False),
    ]:
        env = {**binding["environment"], flag: value}
        with pytest.raises(RalfError):
            rules.validate_create_not_dispatched(no_create(env), env)


def test_identity_canonical_types_cannot_replace_original_integer_fields():
    state, runner, binding = prepared_intent()
    env = binding["environment"]
    changed = {**env, "create_supervision_version": True}
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, runner, no_create(changed))


def test_pg_prepared_original_cannot_be_relabelled_as_no_submit():
    key, record, binding = resource()
    prepared = resources.receive_resource(record, "prepared", receipt(binding))
    with pytest.raises(RalfError):
        resources.receive_resource(
            prepared, "create_not_dispatched", no_create(binding["environment"])
        )
    tampered = copy.deepcopy(record)
    tampered["create_not_dispatched"] = no_create(binding["environment"])
    with pytest.raises(RalfError):
        resources.validate_resource(canonical(tampered), key)


def test_pg_no_submit_cannot_be_relabelled_as_old_namespace_absence():
    _, record, binding = resource()
    proof = no_create(binding["environment"])
    adopted = resources.receive_resource(record, "create_not_dispatched", proof)
    with pytest.raises(RalfError):
        resources.receive_resource(adopted, "namespace_absent", {})


def test_no_grant_or_foreign_runner_cannot_adopt_no_submit():
    state, runner, binding = prepared_intent()
    proof = no_create(binding["environment"])
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, {"foreign": True}, proof)
    state["grants"].clear()
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, runner, proof)


@pytest.mark.parametrize(
    "field,value", [("method", "turn/start"), ("params", {"task": "foreign"}), ("execute", True)]
)
def test_no_submit_requires_the_original_consumed_prepare_grant(field, value):
    state, runner, binding = prepared_intent()
    state["grants"]["prepare"][field] = value
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(state, runner, no_create(binding["environment"]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("create_operation_version", 1),
        ("create_supervision_version", True),
        ("create_supervision_version", 0),
    ],
)
def test_pg_explicit_supervision_record_versions_cannot_be_coerced(field, value):
    key, request, runner, binding = resource_intent()
    binding["environment"] = environment(binding["environment"])
    binding["environment"][field] = value
    with pytest.raises(RalfError):
        resources.new_resource(key, request, runner, binding)


@pytest.mark.parametrize(
    "kind", ["prepared", "thread", "turn", "stop", "observation", "result_candidate"]
)
def test_late_native_callbacks_cannot_replace_sealed_no_submit(kind):
    state, runner, binding = prepared_intent()
    proof = no_create(binding["environment"])
    rules.adopt_create_not_dispatched(state, runner, proof)
    with pytest.raises(RalfError):
        rules.adopt(
            state,
            runner,
            kind,
            {
                "identity": binding["environment"],
                "generation": proof["generation"],
                "container_id": "d" * 64,
            },
        )
    with pytest.raises(RalfError):
        rules.adopt_create_not_dispatched(
            state, runner, no_create(binding["environment"], supervision_receipt_digest="e" * 64)
        )


def test_pg_versioned_receipt_roundtrip_is_immutable_and_does_not_settle_effect():
    key, record, binding = resource()
    assert record["version"] == "2" and record["create_not_dispatched"] is None
    proof = no_create(binding["environment"])
    adopted = resources.receive_resource(record, "create_not_dispatched", proof)
    assert (
        adopted["pending_stop"] is False and adopted["prepared"] is None and adopted["stop"] is None
    )
    assert "effect_state" not in adopted and "effect_case" not in adopted
    assert resources.validate_resource(canonical(adopted), key) == adopted
    assert resources.receive_resource(adopted, "create_not_dispatched", proof) == adopted
    with pytest.raises(RalfError):
        resources.receive_resource(
            adopted,
            "create_not_dispatched",
            no_create(binding["environment"], create_operation_digest="f" * 64),
        )
    with pytest.raises(RalfError):
        resources.receive_resource(adopted, "prepared", receipt(binding))
    with pytest.raises(RalfError):
        resources.receive_resource(
            adopted, "unprepared", {"namespace_binding": binding, "prepare_granted": False}
        )


def test_pg_old_record_cannot_receive_new_metadata_present_negative_proof():
    key, request, runner, binding = resource_intent()
    record = resources.new_resource(key, request, runner, binding)
    with pytest.raises(RalfError):
        resources.receive_resource(
            record, "create_not_dispatched", no_create(environment(binding["environment"]))
        )
    assert resources.validate_resource(canonical(record), key) == record
    assert (
        hashlib.sha256(canonical(record).encode()).hexdigest()
        == "8d2d08e232abf6d1ac2a3eaaaa8a8d2ed96ae3668d5e5ea4bd44367434e54aff"
    )
    assert (
        hashlib.sha256(inspect.getsource(rules.grant).encode()).hexdigest()
        == "8b126747a1e6896892c196e9395815cb820a32b469a5adfbf4e420dd4c49a784"
    )


def test_history_original_claim_adopts_without_replacing_action_attempt_or_budget():
    from tests.test_temporal_coding_state import OWNER, RUNNER, bind, coding_admission, ready
    from tests.test_temporal_tool_execution import admission

    state, action, request = ready()
    binding = bind(request)
    binding["environment"] = environment(binding["environment"])
    state.admit_tool_dispatch(coding_admission(request))
    state.coding_receipt({**admission(request), "kind": "owner", "evidence": OWNER})
    state.admit_coding_phase(
        {**admission(request), "method": "prepare", "params": {}, "binding": binding}
    )
    native = action["delegated_execution"]
    before = copy.deepcopy(
        (action["id"], action["attempts"], native["request"], state.reservations)
    )
    proof = no_create(binding["environment"])
    state.coding_receipt({**admission(request), "kind": "create_not_dispatched", "evidence": proof})
    assert native["create_not_dispatched"] == proof and native["fenced"] is True
    assert (action["id"], action["attempts"], native["request"], state.reservations) == before
    assert native["runner"] == RUNNER and set(native["grants"]) == {"prepare"}
    assert native["pending_stop"] is False and "stop" not in native
    with pytest.raises(RalfError):
        state.coding_receipt({**admission(request), "kind": "namespace_absent", "evidence": {}})


def test_history_cold_stop_adopts_no_submit_then_waits_for_original_worker_end():
    from tests.test_temporal_coding_state import (
        OWNER,
        bind,
        coding_admission,
        owner_dead_payload,
        ready,
    )
    from tests.test_temporal_tool_execution import admission

    state, action, request = ready()
    binding = bind(request)
    binding["environment"] = environment(binding["environment"])
    state.admit_tool_dispatch(coding_admission(request))
    state.coding_receipt({**admission(request), "kind": "owner", "evidence": OWNER})
    state.admit_coding_phase(
        {**admission(request), "method": "prepare", "params": {}, "binding": binding}
    )
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "original Worker lost")
    recovery = admission(request, "c" * 32)
    state.admit_coding_stop(recovery)
    proof = no_create(binding["environment"])
    state.coding_receipt({**recovery, "kind": "create_not_dispatched", "evidence": proof})
    assert state.state == "cancelling" and state.budget["unknown"] == 1
    assert state.coding_state(recovery)["state"]["create_not_dispatched"] == proof
    assert (
        state.tool_executions[action["id"]]["invocation_id"] == admission(request)["invocation_id"]
    )
    state.coding_owner_stopped(owner_dead_payload(request))
    assert state.state == "cancelled" and state.budget["unknown"] == 1
    assert len(action["attempts"]) == 1 and set(action["delegated_execution"]["grants"]) == {
        "prepare"
    }
    with pytest.raises(RalfError):
        state.admit_coding_phase(
            {**recovery, "method": "prepare", "params": {}, "binding": binding}
        )


@pytest.mark.parametrize(
    "fault",
    ["not_admitted", "missing_prepare", "foreign_namespace", "foreign_generation", "native_bound"],
)
def test_history_no_submit_rejects_foreign_or_ungranted_cleanup(fault):
    from tests.test_temporal_coding_state import OWNER, bind, coding_admission, ready
    from tests.test_temporal_tool_execution import admission

    state, action, request = ready()
    binding = bind(request)
    binding["environment"] = environment(binding["environment"])
    state.admit_tool_dispatch(coding_admission(request))
    state.coding_receipt({**admission(request), "kind": "owner", "evidence": OWNER})
    if fault != "missing_prepare":
        state.admit_coding_phase(
            {**admission(request), "method": "prepare", "params": {}, "binding": binding}
        )
    proof = no_create(binding["environment"])
    invocation = "c" * 32 if fault == "not_admitted" else admission(request)["invocation_id"]
    if fault == "foreign_namespace":
        proof = no_create({**binding["environment"], "root": {"path": "/foreign"}})
    if fault == "foreign_generation":
        proof = no_create(binding["environment"], generation="f" * 32)
    if fault == "native_bound":
        action["delegated_execution"]["binding"] = binding
    before = copy.deepcopy(action["delegated_execution"])
    with pytest.raises(RalfError):
        state.coding_receipt(
            {**admission(request, invocation), "kind": "create_not_dispatched", "evidence": proof}
        )
    assert action["delegated_execution"] == before


class NoSubmitRunner(LifecycleRunner):
    async def execute(self, envelope, authority):
        self.envelope, self.authority = envelope, authority
        native = authority.check(envelope, self.identity)
        env = environment(
            {
                "expected_generation": digest(
                    {"dispatch": native["dispatch"], "runner": self.identity}
                )[:32]
            }
        )
        binding = {
            "request": native,
            "runner": self.identity,
            "dispatch": native["dispatch"],
            "environment": env,
        }
        assert authority.authorize("prepare", {}, binding)["execute"]
        authority.adopt("create_not_dispatched", no_create(env))
        raise RuntimeError("original CREATE was never dispatched; business outcome unknown")

    async def stop_existing(self, envelope, authority):
        authority.check(envelope, self.identity)
        return None


def test_local_original_action_adopts_no_submit_but_preserves_unknown_effect(tmp_path):
    async def exercise():
        runner = NoSubmitRunner()
        runtime, _ = coding_engine(tmp_path, runner)
        try:
            handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
            await runtime.drive(handle.run_id)
            original = runtime.store.run(handle.run_id)["actions"][-1]
            runtime.approve(handle.run_id, original["id"], original["digest"], command_id="approve")
            await runtime.drive(handle.run_id)
            run = runtime.store.run(handle.run_id)
            action = next(a for a in run["actions"] if a["kind"] == "tool")
            native = action["delegated_execution"]
            assert action["id"] == original["id"] and len(action["attempts"]) == 1
            assert action["status"] == "outcome_unknown" and native["effect_case"] == "unknown"
            assert native["create_not_dispatched"]["metadata_present"] is True
            assert native["pending_stop"] is False and native["fenced"] is True
            assert set(native["grants"]) == {"prepare"} and "prepared" not in native
            assert runtime.store.budget(handle.run_id)["held"] == 1
            observed = runner.authority.resource_state(runner.envelope, runner.identity)
            assert observed["create_not_dispatched"] == native["create_not_dispatched"]
            assert observed["prepared"] is None and observed["binding"] is None
            with pytest.raises(RalfError):
                runner.authority.adopt(
                    "create_not_dispatched",
                    no_create(
                        native["create_not_dispatched"]["identity"],
                        supervision_receipt_digest="f" * 64,
                    ),
                )
        finally:
            runtime.close()

    asyncio.run(exercise())
