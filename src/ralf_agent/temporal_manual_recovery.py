"""Pure original Action evidence for bounded public manual recovery admission."""

import re

from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _exact, _sha, _text
from .types import canonical, digest

PROOF_FIELDS = {
    "version",
    "scope",
    "run_id",
    "execution_epoch",
    "manifest_digest",
    "action_id",
    "action_digest",
    "tool_request_digest",
    "call_digest",
    "proof_digest",
}


def manual_payload(payload, scope):
    _exact(payload, {"kind", "scope", "action_id", "query", "result"})
    if payload["kind"] != "reconcile" or payload["scope"] != scope or payload["query"] is not False:
        raise DefinitionMismatch("Manual recovery requires original scoped evidence")
    _text(payload["action_id"])
    if len(payload["action_id"]) > 1024 or len(canonical(payload).encode()) > 1024 * 1024:
        raise ValidationError("Manual recovery evidence exceeds its allowance")
    return payload


def validate_proof(proof, *, scope, run_id, epoch, manifest_digest, action_id):
    _exact(proof, PROOF_FIELDS)
    if (
        type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["scope"] != scope
        or proof["run_id"] != run_id
        or proof["execution_epoch"] != epoch
        or proof["manifest_digest"] != manifest_digest
        or proof["action_id"] != action_id
        or proof["proof_digest"] != digest({k: v for k, v in proof.items() if k != "proof_digest"})
    ):
        raise DefinitionMismatch("Manual evidence differs from its original admitted Action")
    for name in ("action_digest", "tool_request_digest", "call_digest", "proof_digest"):
        _sha(proof[name])


def action_proof(state, payload):
    from . import temporal_deployment_execution_state as deployment
    from . import temporal_deployment_release_state as calls
    from .temporal_state import TOOL_ACTIVITY, detached

    manual_payload(payload, state.scope)
    state.authorize(payload["scope"])
    original = calls._require(state)
    calls.check_unsealed(state)
    if not deployment.admitted(state):
        raise DefinitionMismatch("Manual recovery requires original deployment admission")
    action = next((a for a in state.actions if a["id"] == payload["action_id"]), None)
    if (
        action is None
        or action["kind"] != "tool"
        or action["status"] != "outcome_unknown"
        or "delegated_execution" in action
        or not action["attempts"]
    ):
        raise DefinitionMismatch("Manual protection requires an unknown ordinary Tool Action")
    request = state.envelope(action)
    if "tool_execution_protocol" in state.manifest:
        owner = state.tool_executions.get(action["id"], {})
        if (
            owner.get("grant_allowed") is not True
            or owner.get("action_id") != action["id"]
            or owner.get("execution_epoch") != state.epoch
            or owner.get("request_digest") != digest(request)
            or type(owner.get("invocation_id")) is not str
            or re.fullmatch("[a-f0-9]{32}", owner["invocation_id"]) is None
        ):
            raise DefinitionMismatch("Manual protection requires its original Tool dispatch grant")
    carrier_digest = digest({"scope": state.scope, "_deployment_activity_request": request})
    matches = []
    for record in state.deployment_calls.values():
        identity = record["identity"]
        if (
            record["allowed"] is True
            and identity["activity_name"] == TOOL_ACTIVITY
            and identity["activity_id"] == action["attempts"][0]["id"]
            and identity["request_digest"] == carrier_digest
        ):
            calls._identity(state, identity)
            matches.append(identity)
    if not matches:
        raise DefinitionMismatch("Manual protection requires the original actual-call ledger")
    # Multiple SDK retries still map to the same immutable Action, never extra slots.
    proof = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "manifest_digest": original["manifest_digest"],
        "action_id": action["id"],
        "action_digest": action["digest"],
        "tool_request_digest": digest(request),
        "call_digest": digest(matches[0]),
    }
    return detached({**proof, "proof_digest": digest(proof)})
