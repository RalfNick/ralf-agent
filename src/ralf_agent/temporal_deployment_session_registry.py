"""Internal Registry4 Session facts; transport must verify original SDK History.

No method here authenticates caller JSON. Prepared commits are internal Workflow
operations and must never be exposed as a public Update carrying attestations.
The existing publication/Workflow routing does not enable these operations.
"""

from .errors import (
    AuthorizationDenied,
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from .session_types import SessionKey, SessionRef, integer
from .temporal_deployment_admission import (
    _REQUEST_FIELDS,
    DeploymentAdmissionState,
    _detached,
    _exact,
    _sha,
    _text,
)
from .temporal_deployment_coding_registry import CodingDeploymentAdmissionState
from .temporal_deployment_registry import SUBMISSION_CAPACITY
from .temporal_session_identity import data_resource_id, selected_namespace, selected_source
from .temporal_session_state import HISTORY_CHARS, validate_binding, workflow_id
from .types import canonical, credits, digest

_AUTHORITY = {"scope", "admission_policy", "namespace"}
_LOOKUP = _AUTHORITY | {"kind", "command_id", "payload_digest"}
_KINDS = {"session_open", "session_submit", "session_rebind"}
_PERMANENT_CODES = {
    "validation_error",
    "definition_mismatch",
    "idempotency_conflict",
    "authorization_denied",
}


def _bounded(value):
    _text(value)
    if len(value) > 1024:
        raise ValidationError("Session deployment identity exceeds its allowance")


def _equal(left, right):
    return canonical(left) == canonical(right)


class SessionDeploymentAdmissionState(CodingDeploymentAdmissionState):
    publication_versions = (2, 3, 4)

    def __init__(self, admission_policy, namespace, *, capacity, registry_execution_epoch):
        super().__init__(admission_policy, namespace, capacity=capacity)
        _bounded(registry_execution_epoch)
        self.registry_execution_epoch = registry_execution_epoch
        self.session_commands = {}
        self.session_roots = {}
        self.session_fences = {}
        self.session_closed = set()

    def _command_identity(self, request):
        scope = self._authority(request)
        for field in ("command_id", "target"):
            _bounded(request[field])
        _sha(request["payload_digest"])
        key = digest([scope, request["command_id"]])
        identity = {name: request[name] for name in ("kind", "target", "payload_digest")}
        previous = self.commands.get(key)
        if previous is not None and previous["identity"] != identity:
            raise IdempotencyConflict("Original Session deployment command identity changed")
        return scope, key, identity, previous

    def _session_submission(self, request):
        value = request["session_submission"]
        _exact(value, {"version", "session_key", "payload", "logical_payload", "binding"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValidationError("Invalid original Session submission version")
        if len(canonical(value).encode()) > SUBMISSION_CAPACITY:
            raise ValidationError("Original Session submission exceeds its allowance")
        _exact(
            value["session_key"],
            {"workspace", "principal", "resource_id", "namespace", "session_id", "schema_version"},
        )
        key = SessionKey.from_dict(value["session_key"])
        payload, logical = value["payload"], value["logical_payload"]
        binding = value["binding"]
        validate_binding(binding, request["scope"])
        self._session_manifest(binding["manifest"])
        source = selected_source(binding["request"], binding["manifest"])
        if data_resource_id(self.namespace["id"], source) != key.resource_id:
            raise DefinitionMismatch("Session resource changed its original namespace")
        kind = request["kind"][len("session_") :]
        common = {"kind", "scope", "command_id"}
        payload_fields = common | (
            {"binding"}
            if kind == "open"
            else {"session_ref", "input", "budget"}
            if kind == "submit"
            else {"session_ref", "binding", "expected_binding_revision"}
        )
        logical_fields = common | (
            {"session_namespace", "session_id", "request"}
            if kind == "open"
            else {"session_ref", "input", "budget"}
            if kind == "submit"
            else {"session_ref", "request", "expected_binding_revision"}
        )
        _exact(payload, payload_fields)
        _exact(logical, logical_fields)
        if (
            {"workspace": key.workspace, "principal": key.principal} != request["scope"]
            or request["target"] != workflow_id(key)
            or any(not _equal(payload[name], logical[name]) for name in common)
            or payload["kind"] != kind
            or payload["scope"] != request["scope"]
            or payload["command_id"] != request["command_id"]
            or digest(logical) != request["payload_digest"]
        ):
            raise DefinitionMismatch("Original Session declaration changed")
        if kind != "open":
            ref = SessionRef.from_dict(payload["session_ref"])
            if (
                ref.key != key
                or not _equal(payload["session_ref"], logical["session_ref"])
                or ref.coordination_ref
                != digest(["temporal-session-coordination-v1", key.resource_id, request["scope"]])
            ):
                raise DefinitionMismatch("Original Session reference changed")
            if kind == "submit" and ref.definition_digest != digest(binding):
                raise DefinitionMismatch("Original Session submit binding changed")
            if selected_namespace(source, key.namespace) != key.namespace:
                raise DefinitionMismatch("Original Session namespace changed")
        if kind == "submit":
            if not _equal(logical, payload):
                raise DefinitionMismatch("Original Session submit changed")
            credits(payload["budget"])
            if len(canonical(payload["input"])) > HISTORY_CHARS // 2:
                raise ValidationError("Session input exceeds its conversation allowance")
        else:
            from .temporal_bindings import normalize_request

            if not _equal(payload["binding"], binding):
                raise DefinitionMismatch("Original resolved Session binding changed")
            try:
                declaration = normalize_request(logical["request"], binding["manifest"])
            except (KeyError, TypeError, AttributeError, IndexError):
                raise ValidationError("Malformed original Session declaration") from None
            if not _equal(declaration, binding["request"]):
                raise DefinitionMismatch("Resolved Session binding changed original declaration")
            if kind == "open":
                if (
                    logical["session_id"] != key.session_id
                    or selected_namespace(source, logical["session_namespace"]) != key.namespace
                ):
                    raise DefinitionMismatch(
                        "Resolved Session address changed original declaration"
                    )
            else:
                integer(payload["expected_binding_revision"])
                integer(logical["expected_binding_revision"])
                if (
                    payload["expected_binding_revision"] != logical["expected_binding_revision"]
                    or selected_namespace(source, key.namespace) != key.namespace
                ):
                    raise DefinitionMismatch("Original Session rebind declaration changed")
        return _detached(value)

    def reserve(self, request):
        if type(request) is dict and type(request.get("kind")) is not str:
            raise ValidationError("Invalid Session deployment command kind")
        if type(request) is not dict or request.get("kind") not in _KINDS:
            if (
                type(request) is dict
                and type(request.get("root_admission")) is dict
                and request["root_admission"].get("version") == 4
            ):
                raise AuthorizationDenied("Session root requires original SDK verification")
            return super().reserve(request)
        _exact(request, _REQUEST_FIELDS | {"session_submission"})
        _, key, identity, previous = self._command_identity(request)
        if previous is not None:
            if key not in self.session_commands:
                raise DefinitionMismatch("Original Session envelope is unavailable")
            return _detached(previous["receipt"])
        submission = self._session_submission(request)
        self._session_open(request["scope"], submission["binding"]["manifest"])
        if len(self.commands) >= self.capacity:
            raise ValidationError("Temporal deployment command registry capacity exhausted")
        receipt = {
            "command_id": request["command_id"],
            "target": request["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }
        self.commands[key] = _detached({"identity": identity, "receipt": receipt})
        self.session_commands[key] = _detached(
            {"reservation": receipt, "session_submission": submission, "session_receipt": None}
        )
        return _detached(receipt)

    def _session_open(self, scope, manifest):
        if digest([scope, digest(manifest)]) in self.session_closed:
            raise DefinitionMismatch("Original scoped Session deployment admission has been closed")

    def close_deployment_sessions(self, request):
        _exact(request, _AUTHORITY | {"manifest_digest"})
        scope = self._authority(request)
        _sha(request["manifest_digest"])
        key = digest([scope, request["manifest_digest"]])
        if key not in self.session_closed and len(self.session_closed) >= self.capacity:
            raise ValidationError("Original Session admission close index capacity exhausted")
        self.session_closed.add(key)
        candidates = [
            record
            for record in self.session_commands.values()
            if record["session_submission"]["payload"]["scope"] == scope
            and digest(record["session_submission"]["binding"]["manifest"])
            == request["manifest_digest"]
        ]
        return _detached(
            {
                "manifest_digest": request["manifest_digest"],
                "close_requested": True,
                "candidates": candidates,
            }
        )

    def deployment_session_command(self, request):
        _exact(request, _LOOKUP)
        if request["kind"] != "deployment_session_command":
            raise ValidationError("Unsupported Session deployment query")
        scope = self._authority(request)
        _bounded(request["command_id"])
        _sha(request["payload_digest"])
        key = digest([scope, request["command_id"]])
        previous = self.commands.get(key)
        if previous is None:
            return None
        if (
            previous["identity"]["kind"] not in _KINDS
            or previous["identity"]["payload_digest"] != request["payload_digest"]
        ):
            raise IdempotencyConflict("Original Session deployment command identity changed")
        if key not in self.session_commands:
            raise DefinitionMismatch("Original Session envelope is unavailable")
        return _detached(self.session_commands[key])

    def prepare_session_receipt(self, request):
        _exact(request, _AUTHORITY | {"command_id", "payload_digest", "receipt"})
        saved = self.deployment_session_command(
            {
                "kind": "deployment_session_command",
                **{k: v for k, v in request.items() if k != "receipt"},
            }
        )
        if saved is None:
            raise DefinitionMismatch("Original Session acceptance is unavailable")
        receipt = request["receipt"]
        _exact(receipt, {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"})
        payload = saved["session_submission"]["payload"]
        if (
            receipt["command_id"] != request["command_id"]
            or receipt["kind"] != "session_" + payload["kind"]
            or receipt["run_id"] is not None
            or receipt["record_state"] != "durably_recorded"
            or type(receipt["apply_state"]) is not str
            or receipt["apply_state"] not in {"applied", "rejected"}
            or type(receipt["outcome"]) is not dict
        ):
            raise DefinitionMismatch("Original applied Session receipt changed")
        if saved["session_receipt"] is not None and not _equal(saved["session_receipt"], receipt):
            raise DefinitionMismatch("Original Session receipt is immutable")
        return _detached({"session_submission": saved["session_submission"], "receipt": receipt})

    def commit_session_receipt(self, request, verification):
        prepared = self.prepare_session_receipt(request)
        key = digest([request["scope"], request["command_id"]])
        if self.session_commands[key]["session_receipt"] is None:
            _exact(verification, {"session_submission", "receipt"})
            if not _equal(verification, prepared):
                raise DefinitionMismatch("Original SDK Session receipt verification changed")
            self.session_commands[key]["session_receipt"] = _detached(prepared["receipt"])
        return _detached(self.session_commands[key])

    def _intent(self, value, authority):
        from .temporal_session_deployment_dto import validate_intent

        self._authority(authority)
        if type(value) is not dict:
            raise ValidationError("Original Session intent requires plain fields")
        intent = validate_intent(
            value,
            deployment_id=self.policy["deployment_id"],
            scope=authority["scope"],
            namespace=self.namespace,
            coordinator_execution_epoch=value.get("coordinator_execution_epoch"),
        )
        command_key = digest([intent["scope"], intent["session_command_id"]])
        saved = self.session_commands.get(command_key)
        if saved is None:
            raise DefinitionMismatch("Original Session submit acceptance is unavailable")
        expected = {
            "kind": "submit",
            "scope": intent["scope"],
            "command_id": intent["session_command_id"],
            "session_ref": intent["session_ref"],
            "input": intent["submission"]["request"]["input"],
            "budget": intent["submission"]["request"]["budget"],
        }
        if (
            not _equal(saved["session_submission"]["payload"], expected)
            or not _equal(saved["session_submission"]["binding"], intent["binding"])
            or saved["reservation"]["target"] != intent["coordinator_id"]
        ):
            raise DefinitionMismatch("Original Session intent changed accepted submit")
        return intent

    def _origin(self, intent):
        return _detached(
            {
                "version": 1,
                **{
                    name: intent[name]
                    for name in (
                        "namespace",
                        "coordinator_id",
                        "coordinator_execution_epoch",
                        "session_ref",
                        "session_command_id",
                        "turn_id",
                        "turn_seq",
                        "intent_digest",
                    )
                },
                "coordinator_first_execution_epoch": intent["coordinator_execution_epoch"],
                "coordinator_original_execution_epoch": intent["coordinator_execution_epoch"],
            }
        )

    def _intent_key(self, intent):
        return digest([intent["scope"], intent["intent_digest"]])

    def _root_capacity(self, scope):
        if len(self.commands) >= self.capacity:
            raise ValidationError("Temporal deployment command registry capacity exhausted")
        scope_limit = self.policy["max_active_root_runs_per_scope"]
        if len(self.roots) >= self.policy["max_active_root_runs"] or (
            scope_limit is not None
            and sum(root["scope"] == scope for root in self.roots.values()) >= scope_limit
        ):
            raise CapacityExceeded("Temporal deployment root admission capacity is unavailable")

    def _submission(self, request):
        metadata = request["root_admission"]
        key = digest([request["scope"], request["command_id"]])
        accepted = self.session_roots.get(key)
        if type(metadata) is dict and metadata.get("version") == 2 and accepted is not None:
            # Existing descendant-control preparation reconstructs metadata2.
            # Only this already accepted first envelope can recover its origin.
            _exact(metadata, {"version", "manifest_digest", "submission"})
            intent = accepted["intent"]
            if (
                request["kind"] != "submit"
                or request["target"] != intent["run_id"]
                or request["payload_digest"] != digest(intent["submission"]["request"])
                or metadata["manifest_digest"] != digest(intent["submission"]["manifest"])
                or not _equal(metadata["submission"], intent["submission"])
            ):
                raise DefinitionMismatch("Original accepted Session root envelope changed")
            return self._submission(
                {
                    **request,
                    "root_admission": {
                        **metadata,
                        "version": 4,
                        "session_origin": accepted["session_origin"],
                    },
                }
            )
        if type(metadata) is not dict or metadata.get("version") != 4:
            return super()._submission(request)
        from .temporal_bindings import validate_bindings
        from .temporal_state import validate_manifest, validate_request

        _exact(metadata, {"version", "manifest_digest", "submission", "session_origin"})
        if type(metadata["version"]) is not int:
            raise ValidationError("Session root requires protocol4")
        envelope = metadata["submission"]
        _exact(envelope, {"version", "request", "manifest", "activity_timeout", "task_queue"})
        manifest = envelope["manifest"]
        validate_manifest(manifest)
        self._session_manifest(manifest)
        validate_request(envelope["request"], manifest)
        validate_bindings(envelope["request"], manifest, request["scope"])
        return _detached(envelope)

    def _session_manifest(self, manifest):
        from .temporal_deployment_protocol import public_selected

        if (
            not public_selected(manifest)
            or manifest["deployment_admission_protocol"]["version"] != 4
            or manifest["deployment_admission_protocol"]["policy"] != self.policy
            or "coding_execution_protocol" in manifest
        ):
            raise DefinitionMismatch("Original Session root requires ordinary deployment4")

    def prepare_session_root(self, request, intent):
        _exact(request, _REQUEST_FIELDS | {"root_admission"})
        checked = self._intent(intent, request)
        metadata = request["root_admission"]
        _exact(metadata, {"version", "manifest_digest", "submission", "session_origin"})
        origin = self._origin(checked)
        if (
            type(metadata["version"]) is not int
            or metadata["version"] != 4
            or request["kind"] != "submit"
            or request["command_id"] != checked["run_command_id"]
            or request["target"] != checked["run_id"]
            or request["payload_digest"] != digest(checked["submission"]["request"])
            or metadata["manifest_digest"] != digest(checked["submission"]["manifest"])
            or not _equal(metadata["submission"], checked["submission"])
            or not _equal(metadata["session_origin"], origin)
        ):
            raise DefinitionMismatch("Original Session root changed its intent")
        if self._intent_key(checked) in self.session_fences:
            raise DefinitionMismatch("Original Session intent has a never-claimed fence")
        _, key, _, previous = self._command_identity(request)
        if previous is not None:
            if not _equal(
                self.session_roots.get(key), {"intent": checked, "session_origin": origin}
            ):
                raise IdempotencyConflict("Original root belongs to another Session intent")
            saved = self.submissions[key]
            return _detached(
                {"receipt": {**saved["reservation"], "submission": saved["submission"]}}
            )
        self._submission(request)
        self._session_open(checked["scope"], checked["binding"]["manifest"])
        self._root_capacity(checked["scope"])
        return _detached({"request": request, "intent": checked, "session_origin": origin})

    def commit_session_root(self, request, intent, verification):
        prepared = self.prepare_session_root(request, intent)
        if "receipt" in prepared:
            return prepared["receipt"]
        _exact(verification, {"intent", "session_origin"})
        expected = {name: prepared[name] for name in ("intent", "session_origin")}
        if not _equal(verification, expected):
            raise DefinitionMismatch("Original SDK Session intent verification changed")
        legacy = _detached(request)
        legacy["root_admission"] = {
            "version": 1,
            "manifest_digest": request["root_admission"]["manifest_digest"],
        }
        receipt = DeploymentAdmissionState.reserve(self, legacy)
        key = digest([request["scope"], request["command_id"]])
        self.submissions[key] = _detached(
            {
                "reservation": receipt,
                "submission": prepared["intent"]["submission"],
                "run_receipt": None,
                "execution_epoch": None,
            }
        )
        self.session_roots[key] = _detached(expected)
        return _detached({**receipt, "submission": self.submissions[key]["submission"]})

    def deployment_session_root(self, request):
        _exact(request, _LOOKUP)
        if request["kind"] != "deployment_session_root":
            raise ValidationError("Unsupported Session root query")
        result = self.deployment_submission({**request, "kind": "deployment_submission"})
        if result is None:
            return None
        key = digest([request["scope"], request["command_id"]])
        if key not in self.session_roots:
            raise DefinitionMismatch("Original deployment root is not a Session Turn")
        return _detached({**result, **self.session_roots[key]})

    def _refusal(self, request):
        _exact(request, _AUTHORITY | {"intent", "barrier", "code"})
        checked = self._intent(request["intent"], request)
        barrier = request["barrier"]
        _exact(
            barrier,
            {
                "version",
                "intent_digest",
                "coordinator_execution_epoch",
                "start_issued",
                "code",
                "barrier_digest",
            },
        )
        if (
            type(barrier["version"]) is not int
            or barrier["version"] != 1
            or barrier["intent_digest"] != checked["intent_digest"]
            or barrier["coordinator_execution_epoch"] != checked["coordinator_execution_epoch"]
            or barrier["start_issued"] is not False
            or type(request["code"]) is not str
            or request["code"] not in _PERMANENT_CODES
            or barrier["code"] != request["code"]
            or barrier["barrier_digest"]
            != digest({k: v for k, v in barrier.items() if k != "barrier_digest"})
        ):
            raise DefinitionMismatch(
                "Original Session refusal barrier changed or start is uncertain"
            )
        return checked, barrier

    def prepare_session_never_claimed(self, request):
        checked, barrier = self._refusal(request)
        intent_key = self._intent_key(checked)
        previous = self.session_fences.get(intent_key)
        if previous is not None:
            if (
                previous["start_barrier_digest"] != barrier["barrier_digest"]
                or previous["code"] != request["code"]
            ):
                raise DefinitionMismatch("Original never-claimed certificate is immutable")
            return _detached({"certificate": previous})
        key = digest([checked["scope"], checked["run_command_id"]])
        if _equal(self.session_roots.get(key, {}).get("intent"), checked):
            raise DefinitionMismatch("Original Session intent already accepted a claim")
        # An ordinary claim with the same complete business identity also defeats
        # absence. An unrelated collision retains its first command and capacity.
        record = self.commands.get(key)
        identity = {
            "kind": "submit",
            "target": checked["run_id"],
            "payload_digest": digest(checked["submission"]["request"]),
        }
        if record is not None and record["identity"] == identity:
            raise DefinitionMismatch("Original Session intent already accepted a claim")
        if len(self.session_fences) >= self.capacity:
            raise ValidationError("Original Session refusal fence capacity exhausted")
        return _detached(
            {
                "request": request,
                "intent": checked,
                "session_origin": self._origin(checked),
                "barrier": barrier,
            }
        )

    def commit_session_never_claimed(self, request, verification):
        prepared = self.prepare_session_never_claimed(request)
        if "certificate" in prepared:
            return prepared["certificate"]
        _exact(verification, {"intent", "session_origin", "barrier"})
        if not _equal(
            verification, {k: prepared[k] for k in ("intent", "session_origin", "barrier")}
        ):
            raise DefinitionMismatch("Original SDK Session refusal verification changed")
        intent = prepared["intent"]
        certificate = {
            "version": 1,
            "scope": intent["scope"],
            "namespace": self.namespace,
            "registry_id": self.registry_id,
            "registry_execution_epoch": self.registry_execution_epoch,
            "session_origin": prepared["session_origin"],
            "run_command_id": intent["run_command_id"],
            "run_id": intent["run_id"],
            "request_digest": digest(intent["submission"]["request"]),
            "manifest_digest": digest(intent["submission"]["manifest"]),
            "start_barrier_digest": prepared["barrier"]["barrier_digest"],
            "code": request["code"],
            "never_claimed": True,
        }
        certificate["proof_digest"] = digest(certificate)
        self.session_fences[self._intent_key(intent)] = _detached(certificate)
        return _detached(certificate)

    def deployment_session_never_claimed(self, request):
        _exact(request, _AUTHORITY | {"intent"})
        checked = self._intent(request["intent"], request)
        return _detached(self.session_fences.get(self._intent_key(checked)))
