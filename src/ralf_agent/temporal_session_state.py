"""Pure History-owned Session admission; business Actions remain in Run History."""

import copy

from .agent_run import RunRef
from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .session_types import SessionKey, SessionRef, TurnAdmission, integer
from .types import Scope, canonical, credits, digest

SESSION_WORKFLOW = "ralf.temporal.sessions.v1"
SESSION_ACTIVITY = "ralf.temporal.session-control.v1"
CAPACITY = 4096
HISTORY_CHARS = 262144
TERMINAL = {"succeeded", "failed", "cancelled"}


def detached(value):
    import json

    return json.loads(canonical(value))


def resource_id(namespace_id):
    if type(namespace_id) is not str or not namespace_id.strip() or len(namespace_id) > 256:
        raise ValidationError("Sessions require their actual Temporal namespace UUID")
    return digest(["temporal-history-session-resource-v1", namespace_id])


def locator(namespace_id):
    return "temporal-session-" + resource_id(namespace_id)


def workflow_id(key):
    return "ralf-temporal-session-" + key.key_id


def validate_protocol(manifest):
    if "session_protocol" in manifest and (
        type(manifest["session_protocol"]) is not int
        or manifest["session_protocol"] != 1
        or manifest.get("dispatch_admission") != "history-1"
    ):
        raise DefinitionMismatch("Unsupported Temporal Session protocol")


def validate_history(request, manifest, scope=None):
    if not any(k in request for k in ("session_history", "session_turn", "session_observer")):
        return
    if manifest.get("session_protocol") != 1:
        raise DefinitionMismatch("Session History requires its original published protocol")
    history = request.get("session_history")
    if type(history) is not list or len(history) > 128 or len(canonical(history)) > HISTORY_CHARS:
        raise ValidationError("Session History exceeds its bounded allowance")
    for i, message in enumerate(history):
        if (
            type(message) is not dict
            or set(message) != {"role", "content"}
            or message["role"] != ("user" if i % 2 == 0 else "assistant")
            or type(message["content"]) is not str
        ):
            raise ValidationError("Session History requires complete plain conversation pairs")
    if len(history) % 2:
        raise ValidationError("Session History contains an incomplete Turn")
    turn = request.get("session_turn")
    if turn is not None:
        if type(turn) is not dict or set(turn) != {
            "session_ref",
            "turn_id",
            "turn_seq",
            "coordinator_id",
        }:
            raise ValidationError("Session Turn requires exact original identity fields")
        ref = SessionRef.from_dict(turn["session_ref"])
        integer(turn["turn_seq"])
        if scope is not None and (ref.key.workspace, ref.key.principal) != (
            scope["workspace"],
            scope["principal"],
        ):
            raise AuthorizationDenied("Session Turn belongs to another trusted Scope")
        if (
            turn["coordinator_id"] != workflow_id(ref.key)
            or type(turn["turn_id"]) is not str
            or not turn["turn_id"].strip()
        ):
            raise ValidationError("Session Turn differs from its original coordinator")
    observer = request.get("session_observer")
    if observer is not None and (
        type(observer) is not dict
        or set(observer) != {"coordinator_id"}
        or type(observer["coordinator_id"]) is not str
        or not observer["coordinator_id"].startswith("ralf-temporal-session-")
        or len(observer["coordinator_id"]) != len("ralf-temporal-session-") + 64
        or any(c not in "0123456789abcdef" for c in observer["coordinator_id"][-64:])
    ):
        raise ValidationError("Session observer requires a stable coordinator identity")


def quiet(proof):
    flow, budget, snapshot = proof["workflow"], proof["budget"], proof["snapshot"]
    if (
        flow.get("backend") not in {"temporal", "temporal-parent"}
        or any(
            type(flow.get(name)) is not bool
            for name in (
                "quiescent",
                "remote_stop_confirmed",
                "unknown_remote_execution",
                "reconciliation_pending",
                "evidence_ack_pending",
            )
        )
        or any(
            type(budget.get(name)) is not int or budget[name] < 0
            for name in ("reserved", "unknown")
        )
        or type(flow.get("deferred_evidence_acks", 0)) is not int
        or flow.get("deferred_evidence_acks", 0) < 0
    ):
        raise ValidationError("Session completion requires typed execution evidence")
    return (
        snapshot["state"] in TERMINAL
        and flow["quiescent"]
        and flow["remote_stop_confirmed"]
        and budget["reserved"] == budget["unknown"] == 0
        and not flow["unknown_remote_execution"]
        and not flow["reconciliation_pending"]
        and not flow["evidence_ack_pending"]
        and not flow.get("deferred_evidence_acks", 0)
    )


def context_evidence(request):
    """Conversation is evidence beside Knowledge/Facts, not the current task."""
    if "session_history" not in request:
        return {}
    history = request["session_history"]
    return {
        "session_references": []
        if not history
        else [
            {
                "key": "session:history",
                "version": 1,
                "session": detached(history),
                "source_digest": digest(history),
            }
        ]
    }


def validate_context_evidence(snapshot, request):
    expected = context_evidence(request)
    if expected and snapshot.get("session_references") != expected["session_references"]:
        raise DefinitionMismatch("Session context changed original Conversation evidence")


def validate_binding(binding, scope):
    from .temporal_bindings import validate_bindings
    from .temporal_state import validate_manifest, validate_request

    if type(binding) is not dict or set(binding) != {
        "request",
        "manifest",
        "task_queue",
        "activity_timeout",
    }:
        raise ValidationError("Session binding requires exact execution identity fields")
    manifest = validate_manifest(binding["manifest"])
    if manifest.get("session_protocol") != 1:
        raise DefinitionMismatch("Session binding requires its original protocol")
    validate_request(binding["request"], manifest)
    validate_bindings(binding["request"], manifest, scope)
    from .temporal_bindings import selected_session_data

    if selected_session_data(binding["request"], manifest):
        raise ValidationError("Temporal external Session completion writes are not implemented")
    if any(
        k in binding["request"] for k in ("session_turn", "session_history", "session_observer")
    ):
        raise ValidationError("Session binding cannot import another Turn")
    if type(binding["task_queue"]) is not str or not binding["task_queue"].strip():
        raise ValidationError("Session requires its fixed worker queue")
    timeout = binding["activity_timeout"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
        raise ValidationError("Session requires bounded positive Activity timeout")


class TemporalSessionState:
    """One bounded Session. No clocks, I/O, provider calls or lock leases."""

    def __init__(self, accepted):
        accepted = detached(accepted)
        self.scope = accepted["scope"]
        Scope(**self.scope)
        self.namespace_id = accepted["namespace_id"]
        self.key = SessionKey(
            **self.scope,
            resource_id=resource_id(self.namespace_id),
            namespace=accepted["session_namespace"],
            session_id=accepted["session_id"],
        )
        self.coordination_ref = digest(
            ["temporal-session-coordination-v1", self.key.resource_id, self.scope]
        )
        self.binding = {
            k: accepted[k] for k in ("request", "manifest", "task_queue", "activity_timeout")
        }
        validate_binding(self.binding, self.scope)
        self.binding_revision = 1
        self.receipts, self.identities, self.records = {}, {}, []
        self.history, self.active, self.error = [], None, None
        self.started_runs = set()
        self.command(
            {
                "kind": "open",
                "scope": self.scope,
                "command_id": accepted["command_id"],
                "binding": self.binding,
            }
        )

    @property
    def ref(self):
        return SessionRef(
            self.key, self.coordination_ref, self.binding_revision, digest(self.binding)
        )

    def _check_ref(self, value):
        ref = SessionRef.from_dict(value)
        if (ref.key.workspace, ref.key.principal) != (self.key.workspace, self.key.principal):
            raise AuthorizationDenied("Session reference belongs to another trusted Scope")
        if ref.key != self.key or ref.coordination_ref != self.coordination_ref:
            raise DefinitionMismatch("Session reference belongs to another resource or authority")
        return ref == self.ref

    def _receipt(self, command, kind, outcome, *, rejected=False):
        return {
            "command_id": command,
            "kind": "session_" + kind,
            "run_id": None,
            "record_state": "durably_recorded",
            "apply_state": "rejected" if rejected else "applied",
            "outcome": detached(outcome),
        }

    def command(self, request):
        request = detached(request)
        if request.get("scope") != self.scope:
            raise AuthorizationDenied("Session command belongs to another trusted Scope")
        command, kind = request.get("command_id"), request.get("kind")
        if type(command) is not str or not command.strip() or len(command) > 1024:
            raise ValidationError("Session command requires a bounded stable ID")
        if kind not in {"open", "submit", "rebind"}:
            raise ValidationError("Unsupported Session command")
        identity = detached(request)
        if kind in {"open", "rebind"}:
            # The first accepted binding fixes the resolved release. Replays do
            # not re-identify the caller's declaration using newly resolved defaults.
            identity["binding"] = {"request": request["binding"]["request"]}
        fingerprint = digest(identity)
        if command in self.identities:
            if self.identities[command] != fingerprint:
                raise IdempotencyConflict("Session command ID identifies different content")
            return detached(self.receipts[command])
        if len(self.receipts) >= CAPACITY:
            raise ValidationError("Session command capacity exhausted")
        if kind == "open":
            outcome = {"session_ref": self.ref.to_dict()}
            if request["binding"] != self.binding:
                outcome["error"] = "session_binding_mismatch"
        else:
            current = self._check_ref(request["session_ref"])
            outcome = {}
            if not current:
                outcome["error"] = "session_binding_mismatch"
            elif self.active is not None:
                outcome.update(error="session_busy", active_run=self.active["turn"]["run"])
            elif kind == "rebind":
                integer(request["expected_binding_revision"])
                if request["expected_binding_revision"] != self.binding_revision:
                    outcome["error"] = "session_binding_mismatch"
                else:
                    binding = request["binding"]
                    validate_binding(binding, self.scope)
                    self.binding, self.binding_revision = (
                        detached(binding),
                        self.binding_revision + 1,
                    )
                    outcome["session_ref"] = self.ref.to_dict()
            else:
                credits(request["budget"])
                if len(canonical(request["input"])) > HISTORY_CHARS // 2:
                    raise ValidationError("Session input exceeds its conversation allowance")
                from .temporal_bindings import request_release_digest

                seq = len(self.records) + 1
                turn_id = "ralf-turn-" + digest([self.key.to_dict(), command])
                run_command = "ralf-session-run:" + digest([self.key.to_dict(), command])
                run_id = "ralf-temporal-" + digest([self.scope, run_command])
                run_request = {
                    **self.binding["request"],
                    "input": request["input"],
                    "budget": request["budget"],
                    "session_history": detached(self.history),
                    "session_turn": {
                        "session_ref": self.ref.to_dict(),
                        "turn_id": turn_id,
                        "turn_seq": seq,
                        "coordinator_id": workflow_id(self.key),
                    },
                }
                turn = TurnAdmission(
                    turn_id,
                    seq,
                    self.ref,
                    RunRef(
                        locator(self.namespace_id),
                        self.key.workspace,
                        self.key.principal,
                        run_id,
                        request_release_digest(run_request, self.binding["manifest"]),
                    ),
                    digest(request["input"]),
                    command,
                )
                self.active = {
                    "turn": turn.to_dict(),
                    "run_id": run_id,
                    "command_id": run_command,
                    "request": run_request,
                    **{
                        k: detached(self.binding[k])
                        for k in ("manifest", "task_queue", "activity_timeout")
                    },
                    "started": False,
                }
                self.records.append(turn.to_dict())
                self.error = None
                outcome["turn"] = turn.to_dict()
        receipt = self._receipt(command, kind, outcome, rejected="error" in outcome)
        self.identities[command], self.receipts[command] = fingerprint, receipt
        return detached(receipt)

    def start_intent(self):
        return detached(self.active)

    def mark_started(self):
        if self.active is not None:
            self.active["started"] = True
            self.started_runs.add(self.active["run_id"])

    def adopt_observation(self, proof):
        if self.active is None:
            return False
        proof = detached(proof)
        turn = self.active
        if (
            proof["scope"] != self.scope
            or proof["snapshot"]["run_id"] != turn["run_id"]
            or proof["request"] != turn["request"]
            or proof["manifest"] != turn["manifest"]
            or proof["release_digest"] != turn["turn"]["run"]["release_digest"]
        ):
            raise DefinitionMismatch("Session observation differs from its original accepted Run")
        if not quiet(proof):
            return False
        from .temporal_bindings import request_release_digest

        descendants = proof.get("descendants", [])
        if type(descendants) is not list or len(descendants) > 4096:
            raise ValidationError("Invalid Session descendant evidence")
        by_id = {item["snapshot"]["run_id"]: item for item in descendants}
        if len(by_id) != len(descendants):
            raise ValidationError("Repeated Session descendant evidence")
        pending, seen = [proof], {turn["run_id"]}
        while pending:
            parent = pending.pop()
            children = parent["workflow"].get("children", [])
            if type(children) is not list:
                raise ValidationError("Invalid original Session child records")
            for child in children:
                if not child.get("dispatch_started"):
                    continue
                run_id = child["run_id"]
                if run_id in seen or len(seen) >= 4096 or run_id not in by_id:
                    raise DefinitionMismatch("Session child evidence is missing or cyclic")
                seen.add(run_id)
                actual = by_id[run_id]
                if (
                    actual["scope"] != self.scope
                    or actual["request"] != child["request"]
                    or actual["manifest"] != turn["manifest"]
                    or actual["release_digest"]
                    != request_release_digest(child["request"], turn["manifest"])
                ):
                    raise DefinitionMismatch("Session child differs from original ownership")
                if not quiet(actual):
                    return False
                pending.append(actual)
        if len(seen) != len(descendants) + 1:
            raise DefinitionMismatch("Session contains unrelated descendant evidence")
        snapshot = proof["snapshot"]
        if snapshot["state"] == "succeeded":

            def text(value):
                return value if isinstance(value, str) else canonical(value)

            pair = [
                {"role": "user", "content": text(turn["request"]["input"])},
                {"role": "assistant", "content": text(snapshot["result"])},
            ]
            if len(canonical(pair)) > HISTORY_CHARS:
                self.error = {"code": "session_history_capacity"}
                return False
            history = [*self.history, *pair]
            while len(history) > 128 or len(canonical(history)) > HISTORY_CHARS:
                history = history[2:]
            self.history = history
        self.active, self.error = None, None
        return True

    def snapshot(self):
        return {
            "ref": self.ref.to_dict(),
            "binding_revision": self.binding_revision,
            "last_turn_seq": len(self.records),
            "active_run": None if self.active is None else self.active["turn"]["run"],
            "busy": self.active is not None,
            "error": detached(self.error),
        }

    def turns(self, *, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError("Turns require a nonnegative cursor and limit1..100")
        return copy.deepcopy([turn for turn in self.records if turn["turn_seq"] > after][:limit])
