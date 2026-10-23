"""Internal deterministic admission in the original Temporal Registry History.

Held claims have no release path. SDK binding pins identity only, and never
asserts that a root was dispatched or that its effects have completed.
"""

import copy
import re
from uuid import UUID

from .errors import (
    AuthorizationDenied,
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from .governance import DeploymentAdmissionPolicy
from .types import canonical, digest

_POLICY_FIELDS = frozenset(
    {
        "kind",
        "deployment_id",
        "version",
        "max_active_root_runs",
        "max_active_root_runs_per_scope",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "scope",
        "command_id",
        "kind",
        "target",
        "payload_digest",
        "admission_policy",
        "namespace",
    }
)
_BIND_FIELDS = frozenset(
    {
        "scope",
        "admission_policy",
        "namespace",
        "command_id",
        "run_id",
        "request_digest",
        "manifest_digest",
        "proof_digest",
        "execution_epoch",
    }
)
_CONTROLS = frozenset({"approve", "cancel", "reconcile", "drive", "send_input"})


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Invalid Temporal deployment admission fields")


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValidationError("Temporal deployment admission requires nonempty text")


def _sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise ValidationError("Temporal deployment admission requires SHA-256 digests")


def _scope(value):
    _exact(value, {"workspace", "principal"})
    for item in value.values():
        _text(item)
    return copy.deepcopy(value)


def _policy(value):
    _exact(value, _POLICY_FIELDS)
    policy = DeploymentAdmissionPolicy.from_identity(value)
    return policy.identity


def _namespace(value):
    _exact(value, {"name", "id"})
    _text(value["name"])
    if len(value["name"]) > 256:
        raise ValidationError("Temporal deployment namespace exceeds its allowance")
    try:
        if type(value["id"]) is not str or str(UUID(value["id"])) != value["id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Temporal deployment namespace requires a canonical UUID") from None
    return copy.deepcopy(value)


def _detached(value):
    canonical(value)
    return copy.deepcopy(value)


def registry_id(deployment_id):
    """Stable per-deployment Registry address, independent of mutable policy."""
    _text(deployment_id)
    return "ralf-temporal-deployment-" + digest(deployment_id)


def root_run_id(deployment_id, scope, command_id):
    """Stable original root address for one deployment and scoped command."""
    _text(deployment_id)
    _text(command_id)
    return "ralf-temporal-" + digest([deployment_id, _scope(scope), command_id])


class DeploymentAdmissionState:
    """Atomic registry-held roots; callers cannot select foreign observations."""

    def __init__(self, admission_policy, namespace, *, capacity):
        self.policy = _policy(admission_policy)
        self.namespace = _namespace(namespace)
        self.registry_id = registry_id(self.policy["deployment_id"])
        self.capacity = capacity
        self.commands = {}
        self.roots = {}

    def _authority(self, request):
        scope = _scope(request["scope"])
        policy = _policy(request["admission_policy"])
        namespace = _namespace(request["namespace"])
        if policy != self.policy or namespace != self.namespace:
            raise DefinitionMismatch("Original deployment policy and namespace cannot change")
        return scope

    def reserve(self, request):
        if type(request) is not dict:
            raise ValidationError("Invalid Temporal deployment admission request")
        kind = request.get("kind")
        if type(kind) is not str or (kind != "submit" and kind not in _CONTROLS):
            raise ValidationError("Unsupported Temporal deployment command")
        fields = _REQUEST_FIELDS | {"root_admission"} if kind == "submit" else _REQUEST_FIELDS
        _exact(request, fields)
        scope = self._authority(request)
        for field in ("command_id", "target"):
            _text(request[field])
        _sha(request["payload_digest"])
        if kind == "submit":
            metadata = request["root_admission"]
            _exact(metadata, {"version", "manifest_digest"})
            if type(metadata["version"]) is not int or metadata["version"] != 1:
                raise ValidationError("Invalid Temporal root admission protocol")
            _sha(metadata["manifest_digest"])
        key = digest([scope, request["command_id"]])
        identity = {field: request[field] for field in ("kind", "target", "payload_digest")}
        previous = self.commands.get(key)
        if previous is not None:
            if previous["identity"] != identity:
                raise IdempotencyConflict(
                    "Scoped command already identifies different content or target"
                )
            return _detached(previous["receipt"])
        if len(self.commands) >= self.capacity:
            raise ValidationError("Temporal deployment command registry capacity exhausted")
        if kind == "submit":
            run_id = root_run_id(self.policy["deployment_id"], scope, request["command_id"])
            if request["target"] != run_id:
                raise DefinitionMismatch("Original deployment root ID does not match its command")
            own_count = sum(root["scope"] == scope for root in self.roots.values())
            scope_limit = self.policy["max_active_root_runs_per_scope"]
            if len(self.roots) >= self.policy["max_active_root_runs"] or (
                scope_limit is not None and own_count >= scope_limit
            ):
                raise CapacityExceeded("Temporal deployment root admission capacity is unavailable")
            proof = {
                "version": 1,
                "registry_id": self.registry_id,
                "scope": scope,
                "command_id": request["command_id"],
                "run_id": run_id,
                "request_digest": request["payload_digest"],
                "manifest_digest": metadata["manifest_digest"],
                "namespace": self.namespace,
            }
            root = {
                **proof,
                "proof_digest": digest(proof),
                "state": "held-unbound",
                "execution_epoch": None,
            }
        elif not any(
            item["scope"] == scope and item["run_id"] == request["target"]
            for item in self.roots.values()
        ):
            raise AuthorizationDenied("Control requires an original root in its trusted scope")
        receipt = {
            "command_id": request["command_id"],
            "target": request["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }
        if kind == "submit":
            receipt["root_admission"] = root
        # All validation and capacity checks precede both writes.
        self.commands[key] = _detached({"identity": identity, "receipt": receipt})
        if kind == "submit":
            self.roots[key] = _detached(root)
        return _detached(receipt)

    def bind_deployment_root(self, request):
        _exact(request, _BIND_FIELDS)
        scope = self._authority(request)
        for field in ("command_id", "run_id", "execution_epoch"):
            _text(request[field])
        if len(request["execution_epoch"]) > 1024:
            raise ValidationError("Original SDK execution epoch exceeds its allowance")
        for field in ("request_digest", "manifest_digest", "proof_digest"):
            _sha(request[field])
        root = self.roots.get(digest([scope, request["command_id"]]))
        if root is None or any(
            root[field] != request[field]
            for field in ("run_id", "request_digest", "manifest_digest", "proof_digest")
        ):
            raise DefinitionMismatch("Original deployment root reservation proof does not match")
        if (
            root["execution_epoch"] is not None
            and root["execution_epoch"] != request["execution_epoch"]
        ):
            raise DefinitionMismatch("Original root SDK execution cannot be replaced")
        root.update(state="held-bound", execution_epoch=request["execution_epoch"])
        return _detached(root)

    def deployment_admission(self, request):
        _exact(request, {"kind", "scope", "admission_policy", "namespace"})
        if request["kind"] != "deployment_admission":
            raise ValidationError("Unsupported Temporal deployment admission query")
        scope = self._authority(request)
        own = [root for root in self.roots.values() if root["scope"] == scope]
        return _detached(
            {
                "version": 1,
                "registry_id": self.registry_id,
                "policy": self.policy,
                "namespace": self.namespace,
                "scope": scope,
                "held_roots": own,
                "counts": {
                    "held_root_runs": len(self.roots),
                    "held_root_runs_for_scope": len(own),
                    "command_records": len(self.commands),
                },
            }
        )
