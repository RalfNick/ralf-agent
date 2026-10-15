"""Pure original Session lifecycle; no SDK attestation, root quota or business ledger."""

import re

from . import temporal_session_deployment_dto as dto
from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _exact, _sha
from .temporal_session_state import CAPACITY, detached
from .types import canonical, digest

PERMANENT_REFUSALS = frozenset(
    {"validation_error", "definition_mismatch", "idempotency_conflict", "authorization_denied"}
)
REFUSAL_BARRIER_FIELDS = frozenset(
    {
        "version",
        "intent_digest",
        "coordinator_execution_epoch",
        "start_issued",
        "code",
        "barrier_digest",
    }
)
START_SELECTOR_FIELDS = frozenset(
    {
        "scope",
        "namespace",
        "coordinator_execution_epoch",
        "session_command_id",
        "turn_id",
        "intent_digest",
    }
)


def selected(manifest):
    protocol = manifest.get("deployment_admission_protocol", {})
    return (
        type(protocol) is dict
        and type(protocol.get("version")) is int
        and protocol["version"] == 4
        and type(manifest.get("session_deployment_protocol")) is int
        and manifest["session_deployment_protocol"] == 1
    )


def _reject():
    raise DefinitionMismatch("Session deployment evidence differs from its original intent")


def build_intent(active, binding, *, deployment_id, namespace, coordinator_execution_epoch):
    from .session_types import SessionRef
    from .temporal_session_state import workflow_id

    ref = SessionRef.from_dict(active["turn"]["session"])
    value = {
        "version": 1,
        "scope": {"workspace": ref.key.workspace, "principal": ref.key.principal},
        "namespace": detached(namespace),
        "coordinator_id": workflow_id(ref.key),
        "coordinator_execution_epoch": coordinator_execution_epoch,
        "session_ref": ref.to_dict(),
        "binding": detached(binding),
        "session_command_id": active["turn"]["command_id"],
        "turn_id": active["turn"]["turn_id"],
        "turn_seq": active["turn"]["turn_seq"],
        "run_command_id": active["command_id"],
        "run_id": active["run_id"],
        "submission": {
            "version": 1,
            **{
                name: detached(active[name])
                for name in ("request", "manifest", "task_queue", "activity_timeout")
            },
        },
    }
    value["intent_digest"] = digest(value)
    return dto.validate_intent(
        value,
        deployment_id=deployment_id,
        scope=value["scope"],
        namespace=namespace,
        coordinator_execution_epoch=coordinator_execution_epoch,
    )


class TemporalSessionDeploymentState:
    """One immutable Turn intent plus separate mechanical call ownership."""

    def __init__(self, intent, *, deployment_id):
        self.deployment_id = deployment_id
        self._intent = dto.validate_intent(
            intent,
            deployment_id=deployment_id,
            scope=intent["scope"],
            namespace=intent["namespace"],
            coordinator_execution_epoch=intent["coordinator_execution_epoch"],
        )
        self.start = {
            "version": 1,
            "intent": detached(self.intent),
            "phase": "intent-accepted",
            "reservation": None,
            "execution_epoch": None,
            "run_receipt": None,
            "last_error": None,
            "start_refusal": None,
        }
        self.registry_execution_epoch = None
        self.start_issued = False
        self.refusal_barrier = None
        self.calls = {}
        self.body_results = {}
        self.consumed_results = set()
        self.published = False

    @property
    def intent(self):
        return detached(self._intent)

    def view(self):
        return detached(self.start)

    def lifecycle(self):
        return {
            "start": self.view(),
            "start_issued": self.start_issued,
            "refusal_barrier": detached(self.refusal_barrier),
        }

    def check_selector(self, request):
        _exact(request, START_SELECTOR_FIELDS)
        intent = self.intent
        if any(request[name] != intent[name] for name in START_SELECTOR_FIELDS):
            _reject()
        return True

    def reserve_issued(self):
        if self.start["phase"] not in {"intent-accepted", "capacity-deferred", "reserve-unknown"}:
            _reject()
        if self.refusal_barrier is not None or self.start_issued:
            _reject()
        self.start["phase"] = "reserve-unknown"

    def record_error(self, code):
        if type(code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None:
            raise ValidationError("Session error requires a bounded sanitized code")
        if self.start["phase"] != "start-refused":
            self.start["last_error"] = {"code": code}

    def adopt_registration(self, body):
        _exact(body, {"start", "registry_execution_epoch", "execution_epoch"})
        epoch = body["registry_execution_epoch"]
        if type(epoch) is not str or not epoch.strip() or len(epoch) > 1024:
            _reject()
        if self.registry_execution_epoch is not None and epoch != self.registry_execution_epoch:
            _reject()
        candidate = dto.validate_start_view(
            body["start"],
            intent=self.intent,
            deployment_id=self.deployment_id,
            registry_execution_epoch=epoch,
            execution_epoch=body["execution_epoch"],
        )
        phase, previous = candidate["phase"], self.start["phase"]
        claimed = {"held-unbound", "start-uncertain", "started"}
        if previous == "start-refused" and candidate != self.start:
            _reject()
        if previous == "started" and candidate != self.start:
            _reject()
        if previous in claimed and phase not in claimed:
            _reject()
        if self.start_issued and phase not in {"start-uncertain", "started"}:
            _reject()
        if (
            self.start["reservation"] is not None
            and candidate["reservation"] != self.start["reservation"]
        ):
            _reject()
        if phase == "start-refused":
            if (
                self.refusal_barrier is None
                or self.start_issued
                or candidate["start_refusal"]["start_barrier_digest"]
                != self.refusal_barrier["barrier_digest"]
                or candidate["start_refusal"]["code"] != self.refusal_barrier["code"]
            ):
                _reject()
        elif self.refusal_barrier is not None:
            # A committed original claim wins over the provisional no-start barrier.
            if phase not in claimed:
                _reject()
            self.refusal_barrier = None
        self.start = candidate
        self.registry_execution_epoch = epoch

    def issue_start(self):
        if self.start_issued or self.start["phase"] in {"started", "start-refused"}:
            return False
        if self.start["phase"] != "held-unbound" or self.refusal_barrier is not None:
            _reject()
        self.start_issued = True
        self.start["phase"] = "start-uncertain"
        return True

    def install_refusal_barrier(self, code):
        if code not in PERMANENT_REFUSALS:
            raise ValidationError("Session refusal is not a permanent prebusiness refusal")
        if self.start_issued or self.start["reservation"] is not None:
            _reject()
        barrier = {
            "version": 1,
            "intent_digest": self.intent["intent_digest"],
            "coordinator_execution_epoch": self.intent["coordinator_execution_epoch"],
            "start_issued": False,
            "code": code,
        }
        barrier["barrier_digest"] = digest(barrier)
        if self.refusal_barrier is not None and self.refusal_barrier != barrier:
            _reject()
        self.refusal_barrier = barrier
        self.record_error(code)
        return detached(barrier)

    def retry(self):
        return self.start["phase"] != "start-refused"

    def control_request(self, mode):
        if mode not in {"register", "observe"}:
            raise ValidationError("Unsupported Session mechanical control")
        return {
            "version": 1,
            "mode": mode,
            **{
                name: detached(self.intent[name])
                for name in ("scope", "namespace", "coordinator_id", "coordinator_execution_epoch")
            },
            "intent": detached(self.intent),
        }

    def _call_identity(self, identity):
        return dto.validate_call_identity(
            identity,
            intent=self.intent,
            deployment_id=self.deployment_id,
            request_digest=digest(self.control_request(identity.get("mode"))),
        )

    def begin_call(self, identity):
        identity = self._call_identity(identity)
        key = digest([identity["activity_id"], identity["attempt"]])
        previous = self.calls.get(key)
        if previous is not None:
            if previous["identity"] != identity:
                _reject()
            return {"identity": detached(identity), "allowed": previous["end"] is None}
        if len(self.calls) >= CAPACITY:
            raise ValidationError("Session mechanical call allowance exhausted")
        if any(
            call["end"] is None and call["identity"]["mode"] == identity["mode"]
            for call in self.calls.values()
        ):
            _reject()
        self.calls[key] = {"identity": identity, "end": None}
        return {"identity": detached(identity), "allowed": True}

    def end_call(self, payload):
        _exact(payload, {"identity", "body_result_digest", "body_stopped", "body_result"})
        identity = self._call_identity(payload["identity"])
        _sha(payload["body_result_digest"])
        if payload["body_stopped"] is not True:
            _reject()
        key = digest([identity["activity_id"], identity["attempt"]])
        original = self.calls.get(key)
        if original is None or original["identity"] != identity:
            _reject()
        body = dto.decode_control_body(
            payload["body_result"], self.intent["submission"]["manifest"]
        )
        if digest(body) != payload["body_result_digest"]:
            _reject()
        self._validate_body(identity, body)
        ack = {
            **{
                name: detached(payload[name])
                for name in ("identity", "body_result_digest", "body_stopped")
            },
            "recorded": True,
        }
        if original["end"] is not None and original["end"] != ack:
            _reject()
        # Positive original results are retained once by body digest, never in
        # the observed Run ledger. Null/error bodies close debt without a loop.
        if body["ok"] and (identity["mode"] == "register" or body["result"]["advance"] is not None):
            self.body_results.setdefault(payload["body_result_digest"], {"body": body, "ack": ack})
        original["end"] = ack
        return detached(ack)

    def _validate_body(self, identity, body):
        if len(canonical(body).encode()) > dto.SUBMISSION_CAPACITY * 8:
            raise ValidationError("Original Session control result exceeds its bounded allowance")
        if type(body) is not dict or type(body.get("ok")) is not bool:
            _reject()
        _exact(body, {"ok", "result"} if body["ok"] else {"ok", "code"})
        if not body["ok"]:
            if (
                type(body["code"]) is not str
                or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", body["code"]) is None
            ):
                _reject()
            return
        result = body["result"]
        if identity["mode"] == "register":
            _exact(result, {"start", "registry_execution_epoch", "execution_epoch"})
            epoch = result["registry_execution_epoch"]
            if (
                type(epoch) is not str
                or not epoch.strip()
                or len(epoch) > 1024
                or self.registry_execution_epoch not in (None, epoch)
            ):
                _reject()
            dto.validate_start_view(
                result["start"],
                intent=self.intent,
                deployment_id=self.deployment_id,
                registry_execution_epoch=epoch,
                execution_epoch=result["execution_epoch"],
            )
        else:
            _exact(result, {"advance", "registry_execution_epoch", "execution_epoch"})
            self._observation_body(body)

    def recovered_result(self):
        if self.published or any(call["end"] is None for call in self.calls.values()):
            return None
        for key, result in self.body_results.items():
            if key in self.consumed_results:
                continue
            mode = result["ack"]["identity"]["mode"]
            if mode == "register" and self.start["phase"] == "started":
                continue
            if mode == "observe" and self.start["phase"] != "started":
                continue
            return detached(result)
        return None

    def consume_result(self, body):
        self.consumed_results.add(digest(body))

    def call_ended(self, ack, body_result):
        identity = self._call_identity(ack["identity"])
        dto.validate_call_end(ack, identity=identity, body_result=body_result)
        original = self.calls.get(digest([identity["activity_id"], identity["attempt"]]))
        if original is None or original["end"] != ack:
            _reject()
        return True

    def validate_observation(self, body, ack):
        """Correlate positive original closure/retirement after our own body ACK."""
        self.call_ended(ack, body)
        if ack["identity"]["mode"] != "observe" or body.get("ok") is not True:
            _reject()
        if any(call["end"] is None for call in self.calls.values()):
            _reject()
        return self._observation_body(body)

    def _observation_body(self, body):
        result = body["result"]
        _exact(result, {"advance", "registry_execution_epoch", "execution_epoch"})
        if self.start["phase"] != "started" or (
            result["registry_execution_epoch"] != self.registry_execution_epoch
            or result["execution_epoch"] != self.start["execution_epoch"]
        ):
            _reject()
        if result["advance"] is None:
            return None
        advance = result["advance"]
        _exact(
            advance,
            {"version", "intent_digest", "run_proof", "descendants", "closure", "retirement"},
        )
        if (
            type(advance["version"]) is not int
            or advance["version"] != 1
            or advance["intent_digest"] != self.intent["intent_digest"]
        ):
            _reject()
        closure = advance["closure"]
        _exact(closure, {"version", "deployment", "ready", "reasons", "calls", "seal"})
        if (
            type(closure["version"]) is not int
            or closure["version"] != 1
            or closure["ready"] is not True
            or closure["reasons"] != []
            or type(closure["calls"]) is not dict
        ):
            _reject()
        deployment = closure["deployment"]
        from .temporal_deployment_execution import _PROOF_FIELDS
        from .temporal_deployment_release_state import CALL_FIELDS, CERTIFICATE_FIELDS

        _exact(deployment, _PROOF_FIELDS)
        if deployment["proof_digest"] != digest(
            {k: v for k, v in deployment.items() if k != "proof_digest"}
        ):
            _reject()
        original = self.intent
        for name, expected in {
            "scope": original["scope"],
            "namespace": original["namespace"],
            "run_id": original["run_id"],
            "command_id": original["run_command_id"],
            "execution_epoch": self.start["execution_epoch"],
            "original_execution_epoch": self.start["execution_epoch"],
            "request": original["submission"]["request"],
            "manifest": original["submission"]["manifest"],
            "request_digest": digest(original["submission"]["request"]),
            "manifest_digest": digest(original["submission"]["manifest"]),
        }.items():
            if deployment[name] != expected:
                _reject()
        metadata = deployment["admission"]
        _exact(metadata, {"version", "root", "lineage", "session_origin"})
        if (
            type(metadata["version"]) is not int
            or metadata["version"] != 2
            or metadata["lineage"] != []
            or metadata["root"] != self.start["reservation"]["root_admission"]
        ):
            _reject()
        dto.validate_origin(
            metadata["session_origin"], intent=original, deployment_id=self.deployment_id
        )
        bound = {
            **metadata["root"],
            "state": "held-bound",
            "execution_epoch": self.start["execution_epoch"],
        }
        if (
            type(deployment["admission_receipt"]) is not dict
            or deployment["admission_receipt"].get("root") != bound
        ):
            _reject()
        from .temporal_deployment_coding_state import ATTESTATION_FIELDS
        from .temporal_deployment_coding_state import selected as coding_selected
        from .temporal_state import TOOL_ACTIVITY

        coding = coding_selected(original["submission"]["manifest"])
        for record in closure["calls"].values():
            _exact(
                record,
                {"identity", "allowed", "stopped", "end_proof"}
                | ({"fence_proof"} if coding else set()),
            )
            _exact(record["identity"], CALL_FIELDS)
            identity = record["identity"]
            if (
                type(record["allowed"]) is not bool
                or type(record["stopped"]) is not bool
                or record["allowed"]
                and (record["stopped"] is not True or record["end_proof"] != identity)
                or identity["scope"] != original["scope"]
                or identity["run_id"] != original["run_id"]
                or identity["execution_epoch"] != self.start["execution_epoch"]
                or identity["manifest_digest"] != digest(original["submission"]["manifest"])
            ):
                _reject()
            if coding and record["fence_proof"] is not None:
                fence = record["fence_proof"]
                _exact(fence, ATTESTATION_FIELDS)
                if (
                    type(fence["version"]) is not int
                    or fence["version"] != 1
                    or record["allowed"] is not True
                    or record["stopped"] is not True
                    or record["end_proof"] != identity
                    or identity["activity_name"] != TOOL_ACTIVITY
                    or fence["identity"] != identity
                    or fence["namespace"] != original["namespace"]
                    or fence["execution_epoch"] != self.start["execution_epoch"]
                    or fence["process_present"] is not False
                    or fence["native_fenced"] is not True
                ):
                    _reject()
        seal = closure["seal"]
        _exact(seal, CERTIFICATE_FIELDS)
        if (
            type(seal["version"]) is not int
            or seal["version"] != 1
            or seal["proof_digest"]
            != digest({k: v for k, v in seal.items() if k != "proof_digest"})
        ):
            _reject()
        for name in (
            "scope",
            "namespace",
            "run_id",
            "command_id",
            "execution_epoch",
            "original_execution_epoch",
            "request_digest",
            "manifest_digest",
        ):
            if seal[name] != deployment[name]:
                _reject()
        for name in ("admission_digest", "receipt_digest", "closure_digest", "proof_digest"):
            _sha(seal[name])
        if (
            seal["admission_digest"] != digest(metadata)
            or seal["receipt_digest"] != digest(deployment["admission_receipt"])
            or seal["terminal_state"] not in {"succeeded", "failed", "cancelled"}
        ):
            _reject()
        from types import SimpleNamespace

        from .temporal_deployment_release_state import _children

        _children(SimpleNamespace(children=deployment["children"]), seal["children"])
        retirement = advance["retirement"]
        _exact(retirement, {"root", "certificate", "released"})
        if (
            retirement != {"root": bound, "certificate": seal, "released": True}
            or retirement["released"] is not True
        ):
            _reject()
        proof = advance["run_proof"]
        if (
            type(proof) is not dict
            or proof.get("snapshot", {}).get("state") != seal["terminal_state"]
            or proof.get("snapshot", {}).get("run_id") != original["run_id"]
            or proof.get("scope") != original["scope"]
            or proof.get("request") != original["submission"]["request"]
            or proof.get("manifest") != original["submission"]["manifest"]
            or proof.get("workflow", {}).get("children", []) != deployment["children"]
        ):
            _reject()
        if type(advance["descendants"]) is not list or len(advance["descendants"]) > CAPACITY:
            _reject()
        return detached({**proof, "descendants": advance["descendants"]})
