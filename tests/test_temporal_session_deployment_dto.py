"""Pure proposed S1 DTOs; this does not select or authorize publication4."""

import copy
import json

import pytest

from ralf_agent import AgentSpec, ToolRegistry
from ralf_agent import temporal_session_deployment_dto as dto
from ralf_agent.errors import RalfError
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.session_types import SessionKey, SessionRef
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.temporal_session_state import SESSION_ACTIVITY, resource_id, workflow_id
from ralf_agent.types import canonical, digest, submission_request

DEPLOYMENT = "original-deployment"
REGISTRY_EPOCH = "original-registry-epoch"
MANIFEST = TemporalRuntime(
    providers={"default": EchoProvider("dto-fixture")},
    tools=ToolRegistry(),
    enable_sessions=True,
).manifest
SCOPE = {"workspace": "workspace", "principal": "owner"}
NAMESPACE = {"name": "original", "id": "11111111-1111-4111-8111-111111111111"}


def seal(value, name="intent_digest"):
    value[name] = digest({k: v for k, v in value.items() if k != name})
    return value


def intent():
    key = SessionKey(
        **SCOPE,
        resource_id=resource_id(NAMESPACE["id"]),
        namespace=None,
        session_id="chat",
    )
    binding = {
        "request": submission_request(AgentSpec("ordinary", "Answer"), None),
        "manifest": copy.deepcopy(MANIFEST),
        "activity_timeout": 30,
        "task_queue": "original-queue",
    }
    ref = SessionRef(
        key,
        digest(["temporal-session-coordination-v1", key.resource_id, SCOPE]),
        1,
        digest(binding),
    ).to_dict()
    command = "session-submit-1"
    turn_id = "ralf-turn-" + digest([key.to_dict(), command])
    run_command = "ralf-session-run:" + digest([key.to_dict(), command])
    request = {
        **copy.deepcopy(binding["request"]),
        "input": {"task": [1, 2]},
        "budget": 7,
        "session_history": [],
        "session_turn": {
            "session_ref": ref,
            "turn_id": turn_id,
            "turn_seq": 1,
            "coordinator_id": workflow_id(key),
        },
    }
    result = seal(
        {
            "version": 1,
            "scope": copy.deepcopy(SCOPE),
            "namespace": copy.deepcopy(NAMESPACE),
            "coordinator_id": workflow_id(key),
            "coordinator_execution_epoch": "original-session-epoch",
            "session_ref": ref,
            "binding": binding,
            "session_command_id": command,
            "turn_id": turn_id,
            "turn_seq": 1,
            "run_command_id": run_command,
            "run_id": root_run_id(DEPLOYMENT, SCOPE, run_command),
            "submission": {
                "version": 1,
                "request": request,
                **{
                    k: copy.deepcopy(binding[k])
                    for k in ("manifest", "task_queue", "activity_timeout")
                },
            },
        }
    )
    return json.loads(canonical(result))


def checked(value):
    return dto.validate_intent(
        value,
        deployment_id=DEPLOYMENT,
        scope=SCOPE,
        namespace=NAMESPACE,
        coordinator_execution_epoch="original-session-epoch",
    )


def origin(value):
    return {
        "version": 1,
        **{
            k: copy.deepcopy(value[k])
            for k in dto.ORIGIN_FIELDS
            - {
                "version",
                "coordinator_first_execution_epoch",
                "coordinator_original_execution_epoch",
            }
        },
        "coordinator_first_execution_epoch": value["coordinator_execution_epoch"],
        "coordinator_original_execution_epoch": value["coordinator_execution_epoch"],
    }


def refusal(value):
    return seal(
        {
            "version": 1,
            "scope": value["scope"],
            "namespace": value["namespace"],
            "registry_id": registry_id(DEPLOYMENT),
            "registry_execution_epoch": REGISTRY_EPOCH,
            "session_origin": origin(value),
            "run_command_id": value["run_command_id"],
            "run_id": value["run_id"],
            "request_digest": digest(value["submission"]["request"]),
            "manifest_digest": digest(value["submission"]["manifest"]),
            "start_barrier_digest": "b" * 64,
            "code": "definition_mismatch",
            "never_claimed": True,
        },
        "proof_digest",
    )


def reservation(value):
    root = {
        "version": 1,
        "registry_id": registry_id(DEPLOYMENT),
        "scope": value["scope"],
        "command_id": value["run_command_id"],
        "run_id": value["run_id"],
        "namespace": value["namespace"],
        "request_digest": digest(value["submission"]["request"]),
        "manifest_digest": digest(value["submission"]["manifest"]),
    }
    root["proof_digest"] = digest(root)
    root.update(state="held-unbound", execution_epoch=None)
    return {
        "command_id": value["run_command_id"],
        "target": value["run_id"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
        "root_admission": root,
    }


def start(value, phase):
    result = {
        "version": 1,
        "intent": value,
        "phase": phase,
        "reservation": None,
        "execution_epoch": None,
        "run_receipt": None,
        "last_error": None,
        "start_refusal": None,
    }
    if phase in {"held-unbound", "start-uncertain", "started"}:
        result["reservation"] = reservation(value)
    if phase == "started":
        result["execution_epoch"] = "original-business-epoch"
        result["run_receipt"] = {
            "command_id": value["run_command_id"],
            "run_id": value["run_id"],
            "kind": "submit",
            "record_state": "durably_recorded",
            "apply_state": "applied",
            "outcome": {},
        }
    if phase == "start-refused":
        result["start_refusal"] = refusal(value)
        result["last_error"] = {"code": "definition_mismatch"}
    return result


def validate_start(value, original):
    return dto.validate_start_view(
        value,
        intent=original,
        deployment_id=DEPLOYMENT,
        registry_execution_epoch=REGISTRY_EPOCH,
        execution_epoch="original-business-epoch",
    )


def call(value):
    return {
        "version": 1,
        **{
            k: copy.deepcopy(value[k])
            for k in (
                "scope",
                "namespace",
                "coordinator_id",
                "coordinator_execution_epoch",
                "session_command_id",
                "turn_id",
                "intent_digest",
            )
        },
        "mode": "observe",
        "activity_id": "session-observe-1",
        "activity_name": SESSION_ACTIVITY,
        "attempt": 1,
        "invocation_id": "original-invocation",
        "request_digest": "c" * 64,
        "manifest_digest": digest(value["binding"]["manifest"]),
    }


def test_valid_intent_is_detached_and_origin_has_no_digest_cycle():
    value = intent()
    result = checked(value)
    assert result == value and result is not value
    assert dto.validate_origin(origin(value), intent=value, deployment_id=DEPLOYMENT) == origin(
        value
    )
    result["submission"]["request"]["input"]["task"].append(3)
    assert value["submission"]["request"]["input"] == {"task": [1, 2]}
    assert "session_origin" not in value["submission"]


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("version", True),
        ("turn_seq", True),
        ("turn_seq", 0),
        ("run_command_id", "replacement"),
        ("run_id", "replacement"),
        ("coordinator_id", "replacement"),
        ("coordinator_execution_epoch", "replacement"),
        ("session_command_id", "replacement"),
        ("turn_id", "replacement"),
    ],
)
def test_resigned_intent_still_refuses_changed_identity(field, replacement):
    value = intent()
    value[field] = replacement
    seal(value)
    with pytest.raises(RalfError):
        checked(value)


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "namespace",
        "binding",
        "queue",
        "timeout",
        "budget",
        "turn",
        "origin",
        "extra",
        "nan",
        "digest",
    ],
)
def test_intent_crossmatches_and_finite_exact_envelope(change):
    value = intent()
    if change == "scope":
        value["scope"]["principal"] = "foreign"
    elif change == "namespace":
        value["namespace"]["id"] = "22222222-2222-4222-8222-222222222222"
    elif change == "binding":
        value["binding"]["manifest"]["changed"] = True
    elif change == "queue":
        value["submission"]["task_queue"] = "foreign"
    elif change == "timeout":
        value["submission"]["activity_timeout"] = True
    elif change == "budget":
        value["submission"]["request"]["budget"] = True
    elif change == "turn":
        value["submission"]["request"]["session_turn"]["turn_seq"] = 2
    elif change == "origin":
        value["submission"]["session_origin"] = origin(value)
    elif change == "extra":
        value["extra"] = None
    elif change == "nan":
        value["submission"]["request"]["input"] = float("nan")
    else:
        value["intent_digest"] = "0" * 64
    with pytest.raises(RalfError):
        if change not in {"nan", "digest"}:
            seal(value)
        checked(value)


@pytest.mark.parametrize(
    "phase",
    [
        "intent-accepted",
        "capacity-deferred",
        "reserve-unknown",
        "held-unbound",
        "start-uncertain",
        "started",
        "start-refused",
    ],
)
def test_exact_phase_nullability_and_terminal_retry_identity(phase):
    value = intent()
    view = start(value, phase)
    assert validate_start(view, value) == view
    view["execution_epoch"] = None if phase == "started" else "replacement-epoch"
    with pytest.raises(RalfError):
        validate_start(view, value)


@pytest.mark.parametrize("phase", ["started", "held-unbound", "start-refused"])
def test_start_view_rejects_another_original_intent_even_resigned(phase):
    value = intent()
    view = start(value, phase)
    view["intent"] = copy.deepcopy(value)
    view["intent"]["submission"]["request"]["input"] = "changed"
    seal(view["intent"])
    with pytest.raises(RalfError):
        validate_start(view, value)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("never_claimed", 1),
        ("registry_execution_epoch", "replacement"),
        ("registry_id", "replacement"),
        ("request_digest", "0" * 64),
        ("code", "secret code text"),
    ],
)
def test_never_claimed_is_correlated_not_caller_attestation(field, replacement):
    value = intent()
    certificate = refusal(value)
    certificate[field] = replacement
    seal(certificate, "proof_digest")
    with pytest.raises(RalfError):
        dto.validate_never_claimed(
            certificate,
            intent=value,
            deployment_id=DEPLOYMENT,
            registry_execution_epoch=REGISTRY_EPOCH,
        )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("attempt", True),
        ("mode", "recover"),
        ("mode", []),
        ("activity_name", "ralf.temporal.tool.v1"),
        ("coordinator_execution_epoch", "replacement"),
        ("manifest_digest", "0" * 64),
        ("request_digest", "0" * 64),
    ],
)
def test_call_identity_is_only_original_session_control(field, replacement):
    value = intent()
    identity = call(value)
    identity[field] = replacement
    with pytest.raises(RalfError):
        dto.validate_call_identity(
            identity, intent=value, deployment_id=DEPLOYMENT, request_digest="c" * 64
        )


def test_call_end_hashes_separate_body_and_keeps_original_invocation():
    value = intent()
    identity = call(value)
    body = {"original": True}
    assert (
        dto.validate_call_identity(
            identity, intent=value, deployment_id=DEPLOYMENT, request_digest="c" * 64
        )
        == identity
    )
    ack = {
        "identity": identity,
        "body_result_digest": digest(body),
        "body_stopped": True,
        "recorded": True,
    }
    assert dto.validate_call_end(ack, identity=identity, body_result=body) == ack
    for field, changed in (
        ("body_stopped", 1),
        ("recorded", 1),
        ("body_result_digest", "0" * 64),
    ):
        wrong = copy.deepcopy(ack)
        wrong[field] = changed
        with pytest.raises(RalfError):
            dto.validate_call_end(wrong, identity=identity, body_result=body)
    wrong = copy.deepcopy(ack)
    wrong["identity"]["invocation_id"] = "replacement"
    with pytest.raises(RalfError):
        dto.validate_call_end(wrong, identity=identity, body_result=body)


@pytest.mark.parametrize(
    "change", ["input-limit", "malformed-binding", "malformed-history", "cyclic"]
)
def test_existing_session_limits_and_malformed_data_are_typed_refusals(change):
    from ralf_agent.temporal_session_state import HISTORY_CHARS

    value = intent()
    if change == "input-limit":
        value["submission"]["request"]["input"] = "x" * (HISTORY_CHARS // 2 + 1)
    elif change == "malformed-binding":
        value["binding"]["request"].pop("definition")
        value["session_ref"]["definition_digest"] = digest(value["binding"])
    elif change == "malformed-history":
        value["submission"]["request"]["session_history"] = [
            {"role": "user", "content": "unpaired"}
        ]
    else:
        value["submission"]["request"]["input"] = value
    with pytest.raises(RalfError):
        seal(value)
        checked(value)


@pytest.mark.parametrize("kind", ["intent", "origin", "start", "refusal", "call", "end"])
def test_all_dtos_reject_extra_fields(kind):
    value = intent()
    identity = call(value)
    body = {"original": True}
    if kind == "intent":
        data = value
        validate = checked
    elif kind == "origin":
        data = origin(value)

        def validate(d):
            return dto.validate_origin(d, intent=value, deployment_id=DEPLOYMENT)
    elif kind == "start":
        data = start(value, "intent-accepted")

        def validate(d):
            return validate_start(d, value)
    elif kind == "refusal":
        data = refusal(value)

        def validate(d):
            return dto.validate_never_claimed(
                d,
                intent=value,
                deployment_id=DEPLOYMENT,
                registry_execution_epoch=REGISTRY_EPOCH,
            )
    elif kind == "call":
        data = identity

        def validate(d):
            return dto.validate_call_identity(
                d, intent=value, deployment_id=DEPLOYMENT, request_digest="c" * 64
            )
    else:
        data = {
            "identity": identity,
            "body_result_digest": digest(body),
            "body_stopped": True,
            "recorded": True,
        }

        def validate(d):
            return dto.validate_call_end(d, identity=identity, body_result=body)

    data["caller_claim"] = True
    with pytest.raises(RalfError):
        validate(data)


@pytest.mark.parametrize(
    "change",
    [
        "root-request",
        "bound-reservation",
        "receipt",
        "refused-claim",
        "refused-receipt",
        "started-refusal",
        "epoch",
    ],
)
def test_phase_claim_receipt_and_terminal_nullable_mismatches(change):
    value = intent()
    view = start(value, "start-refused" if change.startswith("refused") else "started")
    if change == "root-request":
        root = view["reservation"]["root_admission"]
        root["request_digest"] = "0" * 64
        root["proof_digest"] = digest(
            {k: v for k, v in root.items() if k not in {"state", "execution_epoch", "proof_digest"}}
        )
    elif change == "bound-reservation":
        view["reservation"]["root_admission"].update(
            state="held-bound", execution_epoch="original-business-epoch"
        )
    elif change == "receipt":
        view["run_receipt"]["command_id"] = "foreign"
    elif change == "refused-claim":
        view["reservation"] = reservation(value)
    elif change == "refused-receipt":
        view["run_receipt"] = {}
    elif change == "started-refusal":
        view["start_refusal"] = refusal(value)
    else:
        view["execution_epoch"] = "replacement-business-epoch"
    with pytest.raises(RalfError):
        validate_start(view, value)


def test_started_cannot_use_its_own_unverified_epoch_as_default():
    value = intent()
    with pytest.raises(RalfError):
        dto.validate_start_view(
            start(value, "started"),
            intent=value,
            deployment_id=DEPLOYMENT,
            registry_execution_epoch=REGISTRY_EPOCH,
        )
