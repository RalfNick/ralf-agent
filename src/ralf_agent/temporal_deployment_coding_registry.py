"""Scoped Coding close indexes the same deployment acceptance; no Run authority."""

from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _REQUEST_FIELDS, _detached, _exact, _sha, _text
from .temporal_deployment_registry import PublicDeploymentAdmissionState
from .types import digest

_AUTHORITY = {"scope", "admission_policy", "namespace"}
_ADMISSION = _AUTHORITY | {"command_id", "run_id", "request_digest", "manifest_digest"}


class CodingDeploymentAdmissionState(PublicDeploymentAdmissionState):
    publication_versions = (2, 3)

    def __init__(self, admission_policy, namespace, *, capacity):
        super().__init__(admission_policy, namespace, capacity=capacity)
        self.coding_index = {}
        self.coding_closed = set()

    def reserve(self, request):
        if type(request) is not dict or request.get("kind") != "submit":
            return super().reserve(request)
        _exact(request, _REQUEST_FIELDS | {"root_admission"})
        scope = self._authority(request)
        key = digest([scope, request["command_id"]])
        if key in self.commands:
            return super().reserve(request)
        envelope = self._submission(request)
        selected = envelope["manifest"]["deployment_admission_protocol"]["version"] == 3
        if selected and digest([scope, digest(envelope["manifest"])]) in self.coding_closed:
            raise DefinitionMismatch("Original scoped Coding admission has been closed")
        result = super().reserve(request)
        if selected:
            self.coding_index[key] = {"close_requested": False}
        return result

    def _candidate(self, key):
        root = self.roots.get(key) or self.retirements.get(key, {}).get("root")
        record = self.submissions.get(key)
        if root is None or record is None or key not in self.coding_index:
            raise DefinitionMismatch("Original Coding deployment acceptance is unavailable")
        epoch = root["execution_epoch"]
        return _detached(
            {
                "command_id": root["command_id"],
                "run_id": root["run_id"],
                "request_digest": root["request_digest"],
                "manifest_digest": root["manifest_digest"],
                "close_requested": self.coding_index[key]["close_requested"],
                "execution_epoch": epoch,
                "namespace": root["namespace"] if epoch is not None else None,
            }
        )

    def deployment_coding_validation(self, request):
        from .temporal_deployment_control_projection import registry

        return registry(self, request)

    def coding_candidates(self, request):
        _exact(request, _AUTHORITY | {"kind", "manifest_digest"})
        if request["kind"] != "coding_composition_candidates":
            raise ValidationError("Invalid Coding deployment candidates query")
        scope = self._authority(request)
        _sha(request["manifest_digest"])
        result = []
        for key in self.coding_index:
            root = self.roots.get(key) or self.retirements.get(key, {}).get("root")
            if (
                root is not None
                and root["scope"] == scope
                and root["manifest_digest"] == request["manifest_digest"]
            ):
                result.append(self._candidate(key))
        return result

    def coding_admission(self, request):
        _exact(request, _ADMISSION | {"kind"})
        if request["kind"] != "coding_composition_admission":
            raise ValidationError("Invalid Coding deployment admission query")
        scope = self._authority(request)
        for field in ("command_id", "run_id"):
            _text(request[field])
        for field in ("request_digest", "manifest_digest"):
            _sha(request[field])
        candidate = self._candidate(digest([scope, request["command_id"]]))
        if any(
            candidate[field] != request[field]
            for field in ("command_id", "run_id", "request_digest", "manifest_digest")
        ):
            raise DefinitionMismatch("Original scoped Coding acceptance changed")
        return {**candidate, "admitted": not candidate["close_requested"]}

    def bind_coding_submission(self, request):
        _exact(request, _ADMISSION | {"execution_epoch"})
        candidate = self.coding_admission(
            {
                **{k: v for k, v in request.items() if k != "execution_epoch"},
                "kind": "coding_composition_admission",
            }
        )
        key = digest([request["scope"], request["command_id"]])
        root = self.roots.get(key) or self.retirements.get(key, {}).get("root")
        _text(request["execution_epoch"])
        if len(request["execution_epoch"]) > 1024:
            raise DefinitionMismatch("Original SDK epoch exceeds its allowance")
        if (
            candidate["execution_epoch"] is not None
            and candidate["execution_epoch"] != request["execution_epoch"]
        ):
            raise DefinitionMismatch("Original Coding SDK execution cannot be replaced")
        if candidate["execution_epoch"] is None:
            self.bind_deployment_root({**request, "proof_digest": root["proof_digest"]})
        return self.coding_admission(
            {
                **{k: v for k, v in request.items() if k != "execution_epoch"},
                "kind": "coding_composition_admission",
            }
        )

    def close_coding_submissions(self, request):
        _exact(request, _AUTHORITY | {"manifest_digest"})
        scope = self._authority(request)
        _sha(request["manifest_digest"])
        query = {**request, "kind": "coding_composition_candidates"}
        candidates = self.coding_candidates(query)
        close_key = digest([scope, request["manifest_digest"]])
        if close_key not in self.coding_closed and len(self.coding_closed) >= self.capacity:
            raise ValidationError("Original Coding admission close index capacity exhausted")
        self.coding_closed.add(close_key)
        for candidate in candidates:
            self.coding_index[digest([scope, candidate["command_id"]])]["close_requested"] = True
        return {
            "manifest_digest": request["manifest_digest"],
            "close_requested": True,
            "candidates": self.coding_candidates(query),
        }
