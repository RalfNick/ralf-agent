"""Original public deployment acceptance/retirement facts; no SDK or scheduling."""

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import (
    _BIND_FIELDS,
    _REQUEST_FIELDS,
    DeploymentAdmissionState,
    _detached,
    _exact,
    _sha,
    _text,
)
from .types import canonical, digest

SUBMISSION_CAPACITY = 1024 * 1024


class PublicDeploymentAdmissionState(DeploymentAdmissionState):
    def __init__(self, admission_policy, namespace, *, capacity):
        super().__init__(admission_policy, namespace, capacity=capacity)
        self.submissions = {}
        self.retirements = {}

    def _submission(self, request):
        metadata = request["root_admission"]
        _exact(metadata, {"version", "manifest_digest", "submission"})
        if type(metadata["version"]) is not int or metadata["version"] != 2:
            raise DefinitionMismatch("Public admission requires protocol 2")
        envelope = metadata["submission"]
        _exact(envelope, {"version", "request", "manifest", "activity_timeout", "task_queue"})
        if type(envelope["version"]) is not int or envelope["version"] != 1:
            raise ValidationError("Invalid original deployment submission version")
        if len(canonical(envelope).encode()) > SUBMISSION_CAPACITY:
            raise ValidationError("Original deployment submission exceeds its allowance")
        from .temporal_bindings import validate_bindings
        from .temporal_deployment_protocol import public_selected
        from .temporal_startup_options import validate_seconds
        from .temporal_state import validate_manifest, validate_request

        validate_seconds(envelope["activity_timeout"])
        _text(envelope["task_queue"])
        if not public_selected(envelope["manifest"]):
            raise DefinitionMismatch("Original submission requires public deployment publication")
        if envelope["manifest"]["deployment_admission_protocol"]["policy"] != self.policy:
            raise DefinitionMismatch("Original deployment submission policy changed")
        if (
            digest(envelope["request"]) != request["payload_digest"]
            or digest(envelope["manifest"]) != metadata["manifest_digest"]
        ):
            raise DefinitionMismatch("Original deployment submission digest changed")
        validate_manifest(envelope["manifest"])
        validate_request(envelope["request"], envelope["manifest"])
        validate_bindings(envelope["request"], envelope["manifest"], request["scope"])
        if any(
            k in envelope["request"]
            for k in ("session_turn", "session_observer", "session_lineage")
        ):
            raise DefinitionMismatch("Deployment Session coordinator is not integrated")
        return _detached(envelope)

    def reserve(self, request):
        if type(request) is not dict:
            raise ValidationError("Original deployment reservation requires plain fields")
        if request.get("kind") != "submit":
            return self._control(request)
        _exact(request, _REQUEST_FIELDS | {"root_admission"})
        self._authority(request)
        for field in ("command_id", "target"):
            _text(request[field])
        _sha(request["payload_digest"])
        key = digest([request["scope"], request["command_id"]])
        previous = self.commands.get(key)
        if previous is not None:
            identity = {field: request[field] for field in ("kind", "target", "payload_digest")}
            if previous["identity"] != identity:
                raise IdempotencyConflict("Original deployment submission identity changed")
            if key not in self.submissions:
                raise DefinitionMismatch("Original acceptance envelope is unavailable")
            saved = self.submissions[key]
            return _detached({**saved["reservation"], "submission": saved["submission"]})
        envelope = self._submission(request)
        legacy = _detached(request)
        legacy["root_admission"] = {
            "version": 1,
            "manifest_digest": request["root_admission"]["manifest_digest"],
        }
        key = digest([request["scope"], request["command_id"]])
        previous = self.submissions.get(key)
        receipt = super().reserve(legacy)
        if previous is None:
            self.submissions[key] = _detached(
                {
                    "reservation": receipt,
                    "submission": envelope,
                    "run_receipt": None,
                    "execution_epoch": None,
                }
            )
        return _detached(
            {
                **self.submissions[key]["reservation"],
                "submission": self.submissions[key]["submission"],
            }
        )

    def _control(self, request):
        _exact(request, _REQUEST_FIELDS)
        scope = self._authority(request)
        if request["kind"] not in {
            "approve",
            "cancel",
            "reconcile",
            "drive",
            "send_input",
            "patch",
        }:
            raise ValidationError("Unsupported public deployment control")
        for field in ("command_id", "target"):
            _text(request[field])
        _sha(request["payload_digest"])
        key = digest([scope, request["command_id"]])
        identity = {field: request[field] for field in ("kind", "target", "payload_digest")}
        previous = self.commands.get(key)
        if previous is not None:
            if previous["identity"] != identity:
                raise IdempotencyConflict("Scoped deployment control identity changed")
            return _detached(previous["receipt"])
        if not any(
            r["scope"] == scope and r["run_id"] == request["target"] for r in self.roots.values()
        ):
            raise AuthorizationDenied("Deployment control requires its active original root")
        if len(self.commands) >= self.capacity:
            raise ValidationError("Temporal deployment command registry capacity exhausted")
        receipt = {
            "command_id": request["command_id"],
            "target": request["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }
        self.commands[key] = _detached({"identity": identity, "receipt": receipt})
        return _detached(receipt)

    def deployment_submission(self, request):
        _exact(
            request,
            {"kind", "scope", "command_id", "payload_digest", "admission_policy", "namespace"},
        )
        if request["kind"] != "deployment_submission":
            raise ValidationError("Unsupported deployment submission query")
        scope = self._authority(request)
        _text(request["command_id"])
        _sha(request["payload_digest"])
        key = digest([scope, request["command_id"]])
        record = self.commands.get(key)
        if record is None:
            return None
        if (
            record["identity"]["kind"] != "submit"
            or record["identity"]["payload_digest"] != request["payload_digest"]
        ):
            raise IdempotencyConflict("Original deployment submission identity changed")
        if key not in self.submissions:
            raise DefinitionMismatch("Original deployment acceptance envelope is unavailable")
        return _detached(self.submissions[key])

    def _original_root(self, request):
        scope = self._authority(request)
        key = digest([scope, request["command_id"]])
        root = self.roots.get(key)
        if root is None:
            root = self.retirements.get(key, {}).get("root")
        if root is None or any(
            root[k] != request[k]
            for k in ("run_id", "request_digest", "manifest_digest", "proof_digest")
        ):
            raise DefinitionMismatch("Original deployment root identity changed")
        _text(request["execution_epoch"])
        if (
            root["execution_epoch"] is not None
            and root["execution_epoch"] != request["execution_epoch"]
        ):
            raise DefinitionMismatch("Original deployment SDK epoch cannot be replaced")
        return key, root

    def record_deployment_submission(self, request):
        _exact(request, _BIND_FIELDS | {"receipt"})
        key, root = self._original_root(request)
        receipt = request["receipt"]
        _exact(receipt, {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"})
        if (
            receipt["command_id"] != root["command_id"]
            or receipt["run_id"] != root["run_id"]
            or receipt["kind"] != "submit"
            or receipt["record_state"] != "durably_recorded"
            or receipt["apply_state"] != "applied"
            or type(receipt["outcome"]) is not dict
        ):
            raise DefinitionMismatch("Original business submission receipt changed")
        record = self.submissions[key]
        if record["run_receipt"] is not None:
            if (
                record["run_receipt"] != receipt
                or record["execution_epoch"] != request["execution_epoch"]
            ):
                raise DefinitionMismatch("Original business receipt and SDK epoch are immutable")
            return _detached(record)
        if key in self.roots:
            self.bind_deployment_root({k: v for k, v in request.items() if k != "receipt"})
        record.update(run_receipt=_detached(receipt), execution_epoch=request["execution_epoch"])
        return _detached(record)

    def prepare_deployment_release(self, request):
        _exact(request, _BIND_FIELDS | {"certificate"})
        key, root = self._original_root(request)
        if root["state"] != "held-bound" or root["execution_epoch"] != request["execution_epoch"]:
            raise DefinitionMismatch("Deployment retirement requires original bound execution")
        certificate = request["certificate"]
        from .temporal_deployment_release_state import CERTIFICATE_FIELDS

        _exact(certificate, CERTIFICATE_FIELDS)
        if certificate["proof_digest"] != digest(
            {k: v for k, v in certificate.items() if k != "proof_digest"}
        ):
            raise DefinitionMismatch("Original closure certificate digest changed")
        expected = {
            "version": 1,
            "scope": root["scope"],
            "run_id": root["run_id"],
            "command_id": root["command_id"],
            "namespace": root["namespace"],
            "execution_epoch": root["execution_epoch"],
            "original_execution_epoch": root["execution_epoch"],
            "request_digest": root["request_digest"],
            "manifest_digest": root["manifest_digest"],
        }
        if any(certificate[k] != value for k, value in expected.items()):
            raise DefinitionMismatch("Original closure certificate belongs to another root")
        if certificate["terminal_state"] not in {"succeeded", "failed", "cancelled"}:
            raise DefinitionMismatch("Original deployment closure is not terminal")
        previous = self.retirements.get(key)
        if previous is not None and previous["certificate"] != certificate:
            raise DefinitionMismatch("Original deployment retirement certificate cannot change")
        submission = self.submissions[key]["submission"]
        return _detached(
            {
                "root": root,
                "certificate": certificate,
                "manifest": submission["manifest"],
                "task_queue": submission["task_queue"],
                "activity_timeout": submission["activity_timeout"],
            }
        )

    def deployment_retirement(self, request):
        self.prepare_deployment_release(request)
        key = digest([request["scope"], request["command_id"]])
        return _detached(self.retirements.get(key)) if key in self.retirements else None

    def commit_deployment_release(self, request, verification):
        prepared = self.prepare_deployment_release(request)
        _exact(verification, {"root", "certificate"})
        if verification != {k: prepared[k] for k in ("root", "certificate")}:
            raise DefinitionMismatch("Original SDK closure verification changed")
        key = digest([request["scope"], request["command_id"]])
        previous = self.retirements.get(key)
        if previous is not None:
            return _detached(previous)
        result = _detached(
            {"root": prepared["root"], "certificate": prepared["certificate"], "released": True}
        )
        self.retirements[key] = result
        del self.roots[key]
        return _detached(result)

    def deployment_admission(self, request):
        result = super().deployment_admission(request)
        result["retired_roots"] = [
            {
                "run_id": r["root"]["run_id"],
                "execution_epoch": r["root"]["execution_epoch"],
                "certificate_digest": r["certificate"]["proof_digest"],
            }
            for r in self.retirements.values()
            if r["root"]["scope"] == request["scope"]
        ]
        return _detached(result)
