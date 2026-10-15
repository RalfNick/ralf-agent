"""Pure original Coding closure and narrowly associated deployment call fencing.

Only an original Workflow may adopt SDK-owned verification. Caller Update data
contains just Scope and call identity; this module performs no SDK or process I/O.
"""

import copy

from .errors import DefinitionMismatch, RalfError
from .temporal_deployment_admission import _exact
from .types import canonical, digest

CANDIDATE_FIELDS = {
    "version",
    "identity",
    "action_id",
    "tool_request_digest",
    "owner",
    "owner_stop_proof",
    "runner",
    "namespace",
    "execution_epoch",
}
ATTESTATION_FIELDS = CANDIDATE_FIELDS | {"process_present", "native_fenced"}
COMPOSITION_FIELDS = (
    "composition_namespace",
    "composition_original_epoch",
    "composition_admission",
    "composition_stop_intent",
)


def selected(manifest):
    value = manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
    return (
        type(value) is dict
        and type(value.get("version")) is int
        and (
            value["version"] == 3
            or value["version"] == 4
            and "coding_execution_protocol" in manifest
        )
    )


def guard_mutation(state, previous, requested):
    """Return True only for a sealed, exact existing fact; otherwise refuse new work."""
    if not selected(state.manifest) or getattr(state, "deployment_seal", None) is None:
        return False
    if previous is not None and canonical(previous) == canonical(requested):
        return True
    raise DefinitionMismatch("Original Coding deployment closure is irreversible")


def closure_reasons(state):
    if not selected(state.manifest):
        return []
    from . import temporal_coding_composition_state as composition
    from . import temporal_coding_state as native
    from . import temporal_deployment_execution_state as deployment

    reasons = []
    try:
        if not native.enabled(state.manifest) or not native.stopped(state):
            reasons.append("coding_native_not_stopped")
        for action in state.actions:
            value = action.get("delegated_execution")
            if (
                value is not None
                and value.get("native_unknown")
                and not (
                    value.get("effect_case") == "confirmed"
                    and action.get("status") == "completed"
                    and native.accepts_result(state, action, action.get("result"))
                )
            ):
                reasons.append("coding_native_unknown")
        if composition.enabled(state.manifest):
            proof = deployment.view(state)
            if (
                state.composition_namespace != proof["namespace"]
                or state.composition_original_epoch != proof["original_execution_epoch"]
                or state.composition_original_epoch != state.epoch
            ):
                reasons.append("coding_composition_identity_changed")
            if state.request["definition"]["kind"] in {"graph", "team", "dynamic"}:
                receipt = state.composition_admission
                if (
                    type(receipt) is not dict
                    or set(receipt) != {"namespace", "execution_epoch", "admitted"}
                    or receipt["namespace"] != proof["namespace"]
                    or receipt["execution_epoch"] != state.epoch
                    or type(receipt["admitted"]) is not bool
                ):
                    reasons.append("coding_composition_not_admitted")
            for call in getattr(state, "children", []):
                if call.get("physical_no_start") is True:
                    if (
                        call.get("dispatch_started")
                        or call.get("started")
                        or call.get("child_execution") is not None
                        or call.get("deployment_execution_epoch") is not None
                    ):
                        reasons.append("coding_child_no_start_changed")
                    continue
                physical = call.get("physical_stop_proof")
                if type(physical) is not dict or physical.get("physical_stopped") is not True:
                    reasons.append("coding_child_not_stopped")
                    continue
                composition._child(state, call["run_id"], physical)
                epoch = call.get("deployment_execution_epoch")
                if (
                    not epoch
                    or call.get("child_execution")
                    != {
                        "namespace": proof["namespace"],
                        "execution_epoch": epoch,
                        "original_execution_epoch": epoch,
                    }
                    or physical["execution_epoch"] != epoch
                ):
                    reasons.append("coding_child_execution_changed")
            if composition.physical_stop_view(state)["physical_stopped"] is not True:
                reasons.append("coding_composition_not_stopped")
    except (RalfError, KeyError, TypeError, AttributeError):
        reasons.append("coding_physical_proof_unavailable")
    return sorted(set(reasons))


def _call(state, identity):
    from . import temporal_deployment_release_state as release

    if not selected(state.manifest):
        raise DefinitionMismatch("Original Coding deployment publication required")
    proof = release._require(state)
    key = release._identity(state, identity)
    record = state.deployment_calls.get(key)
    if (
        type(record) is not dict
        or set(record) != {"identity", "allowed", "stopped", "end_proof", "fence_proof"}
        or record["identity"] != identity
        or record["allowed"] is not True
        or type(record["stopped"]) is not bool
        or record["stopped"]
        and record["fence_proof"] is None
    ):
        raise DefinitionMismatch("Original unended Coding deployment call is unavailable")
    return proof, record


def _activity_matches(identity, action):
    from .temporal_state import TOOL_ACTIVITY

    return (
        identity["activity_name"] == TOOL_ACTIVITY
        and identity["attempt"] == 1
        and len(action["attempts"]) == 1
        and identity["activity_id"] == action["attempts"][0]["id"]
    )


def coding_call_candidate(state, identity):
    """Read fixed native owner evidence for this exact original SDK call only."""
    from . import temporal_coding_state as native

    try:
        proof, _ = _call(state, identity)
        if not native.enabled(state.manifest):
            raise DefinitionMismatch("Original native Coding publication required")
        matches = []
        for action in state.actions:
            value = action.get("delegated_execution")
            if action.get("kind") != "tool" or type(value) is not dict:
                continue
            body = value["tool_request"]
            carrier = {"scope": state.scope, "_deployment_activity_request": body}
            if digest(carrier) == identity["request_digest"] and _activity_matches(
                identity, action
            ):
                matches.append((action, value, body))
        if len(matches) != 1:
            raise DefinitionMismatch("Deployment call lacks its unique original Coding action")
        action, value, body = matches[0]
        tool = state.tool_executions[action["id"]]
        owner = value["owner"]
        native.validate_owner(owner, tool["invocation_id"])
        stop = tool["coding_owner_stop_proof"]
        native._record(state, stop, extra=("evidence",), recovery=True)
        _exact(stop["evidence"], {"owner", "process_present", "native_fenced"})
        if (
            body["runtime_manifest"] != state.manifest
            or digest(body) != tool["request_digest"]
            or stop["invocation_id"] not in value["stop_invocations"]
            or stop["evidence"]["owner"] != owner
            or stop["evidence"]["process_present"] is not False
            or stop["evidence"]["native_fenced"] is not True
            or not native.stopped_action(state, action)
        ):
            raise DefinitionMismatch("Original native owner and complete stop proof are required")
        return copy.deepcopy(
            {
                "version": 1,
                "identity": identity,
                "action_id": action["id"],
                "tool_request_digest": digest(body),
                "owner": owner,
                "owner_stop_proof": stop,
                "runner": value["runner"],
                "namespace": proof["namespace"],
                "execution_epoch": state.epoch,
            }
        )
    except (KeyError, TypeError, AttributeError, ValueError):
        raise DefinitionMismatch("Original Coding call closure evidence is unavailable") from None


def adopt_call_fence(state, request, attestation):
    """Adopt only the original Workflow's SDK-owned verifier result after recheck."""
    _exact(request, {"scope", "identity"})
    if request["scope"] != state.scope:
        raise DefinitionMismatch("Coding call fence belongs to another original Scope")
    _exact(attestation, ATTESTATION_FIELDS)
    candidate = coding_call_candidate(state, request["identity"])
    if (
        any(
            canonical(attestation[field]) != canonical(candidate[field])
            for field in CANDIDATE_FIELDS
        )
        or attestation["process_present"] is not False
        or attestation["native_fenced"] is not True
    ):
        raise DefinitionMismatch("SDK Coding call stop changed its original candidate")
    _, record = _call(state, request["identity"])
    previous = record["fence_proof"]
    if previous is not None:
        if canonical(previous) != canonical(attestation):
            raise DefinitionMismatch("Original Coding deployment fence cannot change")
    else:
        from .temporal_deployment_release_state import check_unsealed

        check_unsealed(state)
        record["fence_proof"] = copy.deepcopy(attestation)
        record["stopped"] = True
        record["end_proof"] = copy.deepcopy(request["identity"])
    identity = request["identity"]
    return {
        "activity_id": identity["activity_id"],
        "attempt": identity["attempt"],
        "invocation_id": identity["invocation_id"],
        "recorded": True,
    }


def check_guard_registration(manifest):
    """Validate selected Coding callables and their actual native guard aliases."""
    value = manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
    if (
        type(value) is not dict
        or type(value.get("version")) is not int
        or value["version"] != 3
        and not (value["version"] == 4 and "coding_execution_protocol" in manifest)
    ):
        return
    for name, function, code, defaults, keyword_defaults in _GUARD_FUNCTION_PINS:
        if (
            globals().get(name) is not function
            or function.__code__ is not code
            or function.__defaults__ is not defaults
            or function.__kwdefaults__ is not keyword_defaults
        ):
            raise DefinitionMismatch("Original deployment Coding guard implementation changed")
    from . import temporal_coding_composition_state as composition
    from . import temporal_coding_state as native

    original_guard = _GUARD_FUNCTION_PINS[1][1]
    if (
        native.guard_mutation is not original_guard
        or composition.guard_mutation is not original_guard
    ):
        raise DefinitionMismatch("Original Coding History guard binding changed")


_GUARD_FUNCTION_PINS = tuple(
    (name, function, function.__code__, function.__defaults__, function.__kwdefaults__)
    for name, function in (
        ("selected", selected),
        ("guard_mutation", guard_mutation),
        ("closure_reasons", closure_reasons),
        ("_call", _call),
        ("_activity_matches", _activity_matches),
        ("coding_call_candidate", coding_call_candidate),
        ("adopt_call_fence", adopt_call_fence),
        ("check_guard_registration", check_guard_registration),
    )
)
