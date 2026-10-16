"""Original public deployment acceptance/retirement facts; no SDK or scheduling."""

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import (
    _BIND_FIELDS,
    _REQUEST_FIELDS,
    DeploymentAdmissionState,
    _detached,
    _exact,
    _namespace,
    _scope,
    _sha,
    _text,
    root_run_id,
)
from .types import canonical, digest

SUBMISSION_CAPACITY = 1024 * 1024
CONTROL_BINDING_FIELDS = {
    "version",
    "scope",
    "namespace",
    "target",
    "target_execution_epoch",
    "root_run_id",
    "root_execution_epoch",
}
_CONTROL_KINDS = {"approve", "cancel", "reconcile", "drive", "send_input", "patch"}


class PublicDeploymentAdmissionState(DeploymentAdmissionState):
    publication_versions = (2,)

    def __init__(self, admission_policy, namespace, *, capacity):
        super().__init__(admission_policy, namespace, capacity=capacity)
        self.submissions = {}
        self.retirements = {}
        self.control_bindings = {}
        self.recovery_controls = {}

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
        if (
            envelope["manifest"]["deployment_admission_protocol"]["version"]
            not in self.publication_versions
        ):
            raise DefinitionMismatch(
                "Original Registry does not accept this deployment publication"
            )
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

    def _control_request(self, request):
        if type(request) is not dict or set(request) not in (
            _REQUEST_FIELDS,
            _REQUEST_FIELDS | {"descendant"},
        ):
            raise ValidationError("Invalid public deployment control fields")
        scope = self._authority(request)
        if type(request["kind"]) is not str or request["kind"] not in _CONTROL_KINDS:
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
        return scope, key, identity, previous

    def _control_receipt(self, key):
        receipt = self.commands[key]["receipt"]
        binding = self.control_bindings.get(key)
        return _detached(receipt if binding is None else {**receipt, "control_binding": binding})

    def _drive_command(self, scope, target):
        saved = self.recovery_controls.get(digest([scope, target, "drive"]))
        if saved is not None:
            return saved["command_id"]
        identity = {
            "kind": "drive",
            "target": target,
            "payload_digest": digest({"scope": scope, "kind": "drive"}),
        }
        # An old legal command can occupy the usual derived ID. At most N
        # existing keys can collide, so N+1 deterministic candidates suffice.
        for index in range(len(self.commands) + 1):
            candidate = "drive:" + digest([scope, target] if index == 0 else [scope, target, index])
            previous = self.commands.get(digest([scope, candidate]))
            if previous is None or previous["identity"] == identity:
                return candidate
        raise ValidationError("Temporal recovery command identity is unavailable")

    def _control(self, request):
        scope, key, identity, previous = self._control_request(request)
        if previous is not None:
            return self._control_receipt(key)
        if "descendant" in request:
            raise AuthorizationDenied("Descendant control requires original SDK verification")
        root = next(
            (
                r
                for r in self.roots.values()
                if r["scope"] == scope and r["run_id"] == request["target"]
            ),
            None,
        )
        if root is None:
            raise AuthorizationDenied("Deployment control requires its active original root")
        recovery_slot = None
        if len(self.commands) >= self.capacity:
            recovery_slot = digest([scope, request["target"], request["kind"]])
            if (
                request["kind"] not in {"cancel", "drive"}
                or request["payload_digest"] != digest({"scope": scope, "kind": request["kind"]})
                or recovery_slot in self.recovery_controls
                or request["kind"] == "drive"
                and request["command_id"] != self._drive_command(scope, request["target"])
            ):
                raise ValidationError("Temporal deployment command registry capacity exhausted")
            from .temporal_deployment_execution_state import _root

            _root(root, bound=True)
        receipt = {
            "command_id": request["command_id"],
            "target": request["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }
        self.commands[key] = _detached({"identity": identity, "receipt": receipt})
        if recovery_slot is not None:
            # At most two immutable records per accepted root, hence <=2*capacity.
            # Normal submissions never consume this allowance. No ID is evicted.
            self.recovery_controls[recovery_slot] = _detached(
                {
                    "scope": scope,
                    "run_id": root["run_id"],
                    "execution_epoch": root["execution_epoch"],
                    "kind": request["kind"],
                    "command_id": request["command_id"],
                }
            )
        return _detached(receipt)

    def deployment_control(self, request):
        _exact(request, _REQUEST_FIELDS | {"command_kind"})
        if request["kind"] != "deployment_control":
            raise ValidationError("Invalid public deployment control query")
        control = {
            **{name: value for name, value in request.items() if name != "command_kind"},
            "kind": request["command_kind"],
        }
        _, key, _, previous = self._control_request(control)
        return None if previous is None else self._control_receipt(key)

    def prepare_deployment_control(self, request):
        scope, _, _, previous = self._control_request(request)
        if previous is not None:
            return {"receipt": self._control_receipt(digest([scope, request["command_id"]]))}
        descendant = request.get("descendant")
        _exact(descendant, {"root_command_id", "execution_epoch"})
        for value in descendant.values():
            _text(value)
            if len(value) > 1024:
                raise ValidationError("Original descendant control identity exceeds its allowance")
        root_key = digest([scope, descendant["root_command_id"]])
        root = self.roots.get(root_key)
        if root is None:
            raise DefinitionMismatch("Descendant control requires its held original root")
        from .temporal_deployment_execution_state import _root

        _root(root, bound=True)
        if (
            root["scope"] != scope
            or root["namespace"] != self.namespace
            or root["registry_id"] != self.registry_id
            or root["command_id"] != descendant["root_command_id"]
            or root["run_id"]
            != root_run_id(self.policy["deployment_id"], scope, root["command_id"])
            or request["target"] == root["run_id"]
        ):
            raise DefinitionMismatch("Descendant control changed its original root identity")
        record = self.submissions.get(root_key)
        _exact(record, {"reservation", "submission", "run_receipt", "execution_epoch"})
        reservation = record["reservation"]
        _exact(
            reservation, {"command_id", "target", "record_state", "apply_state", "root_admission"}
        )
        expected = {
            "command_id": root["command_id"],
            "target": root["run_id"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
            "root_admission": {**root, "state": "held-unbound", "execution_epoch": None},
        }
        original_command = self.commands.get(root_key)
        if (
            reservation != expected
            or original_command
            != {
                "identity": {
                    "kind": "submit",
                    "target": root["run_id"],
                    "payload_digest": root["request_digest"],
                },
                "receipt": reservation,
            }
            or record["execution_epoch"] not in (None, root["execution_epoch"])
        ):
            raise DefinitionMismatch("Original root first acceptance changed")
        submission = self._submission(
            {
                "scope": scope,
                "command_id": root["command_id"],
                "kind": "submit",
                "target": root["run_id"],
                "payload_digest": root["request_digest"],
                "admission_policy": self.policy,
                "namespace": self.namespace,
                "root_admission": {
                    "version": 2,
                    "manifest_digest": root["manifest_digest"],
                    "submission": record["submission"],
                },
            }
        )
        if len(self.commands) >= self.capacity:
            raise ValidationError("Temporal deployment command registry capacity exhausted")
        return _detached(
            {
                "request": {name: request[name] for name in _REQUEST_FIELDS},
                "root": root,
                "submission": submission,
                "target_execution_epoch": descendant["execution_epoch"],
            }
        )

    def commit_deployment_control(self, request, verification):
        prepared = self.prepare_deployment_control(request)
        if "receipt" in prepared:
            return prepared["receipt"]
        _exact(verification, CONTROL_BINDING_FIELDS)
        if type(verification["version"]) is not int or verification["version"] != 1:
            raise ValidationError("Invalid original descendant control binding version")
        _scope(verification["scope"])
        _namespace(verification["namespace"])
        for name in ("target", "target_execution_epoch", "root_run_id", "root_execution_epoch"):
            _text(verification[name])
        root = prepared["root"]
        expected = {
            "version": 1,
            "scope": prepared["request"]["scope"],
            "namespace": root["namespace"],
            "target": prepared["request"]["target"],
            "target_execution_epoch": prepared["target_execution_epoch"],
            "root_run_id": root["run_id"],
            "root_execution_epoch": root["execution_epoch"],
        }
        if verification != expected:
            raise DefinitionMismatch("SDK descendant control binding changed its original target")
        base = prepared["request"]
        key = digest([base["scope"], base["command_id"]])
        receipt = {
            "command_id": base["command_id"],
            "target": base["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }
        command = _detached(
            {
                "identity": {name: base[name] for name in ("kind", "target", "payload_digest")},
                "receipt": receipt,
            }
        )
        binding = _detached(verification)
        # Preparation rechecked the held root and capacity after SDK verification.
        self.commands[key] = command
        self.control_bindings[key] = binding
        return self._control_receipt(key)

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
        hints = []
        for root in result["held_roots"]:
            if root["execution_epoch"] is None:
                continue
            command_id = self._drive_command(request["scope"], root["run_id"])
            if command_id != "drive:" + digest([request["scope"], root["run_id"]]):
                hints.append(
                    {
                        "run_id": root["run_id"],
                        "execution_epoch": root["execution_epoch"],
                        "command_id": command_id,
                        "durable": False,
                    }
                )
        if hints:
            result["recovery_drive_hints"] = hints
        recovery = [
            {k: v for k, v in record.items() if k != "scope"}
            for record in self.recovery_controls.values()
            if record["scope"] == request["scope"]
        ]
        if recovery:
            result["recovery_controls"] = recovery
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
