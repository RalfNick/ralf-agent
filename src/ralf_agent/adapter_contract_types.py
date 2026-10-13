"""Detached, bounded observations from the frozen adapter contract cases.

Report values describe evidence produced by the suite. Constructing a value is
not certification, and neither fixture declarations nor exceptions supply a
verdict. Query, source, configuration and exception text are never report fields.
"""

import copy
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType

from .adapter_contract_catalog import catalog_for, catalog_for_case
from .errors import ValidationError
from .types import digest

KNOWLEDGE_CONTRACT_CASES = (
    ("K01", "identity-and-port"),
    ("K02", "result-and-metering"),
    ("K03", "scope-and-namespace"),
    ("K04", "bounded-retrieval"),
    ("K05", "current-source"),
    ("K06", "tampered-source"),
    ("K07", "expiry-after-await"),
    ("K08", "scoped-binding"),
    ("K09", "component-drift"),
    ("K10", "backend-drift"),
    ("K11", "backend-errors"),
    ("K12", "validation-and-consumer"),
)
CASE_IDS = tuple(case_id for case_id, _ in KNOWLEDGE_CONTRACT_CASES)
CASE_LABELS = MappingProxyType(dict(KNOWLEDGE_CONTRACT_CASES))
_BOOLEAN_OBSERVATIONS = frozenset(
    (
        "runtime_closed",
        "borrowed_closed",
        "handler_finished",
        "cancelled",
        "cleanup_complete",
        "ports_valid",
        "identity_valid",
    )
)
_COUNT_OBSERVATIONS = frozenset(
    (
        "retrieve_calls",
        "validate_calls",
        "model_calls",
        "tool_calls",
        "close_calls",
        "source_checks",
        "rejection_checks",
        "scope_checks",
        "namespace_checks",
        "reference_count",
        "item_count",
        "used_chars",
        "backend_switches",
        "identity_checks",
        "method_checks",
        "consumer_runs",
    )
)
OBSERVATION_KEYS = _BOOLEAN_OBSERVATIONS | _COUNT_OBSERVATIONS
_STATUS_CODES = {
    "passed": frozenset(("verified",)),
    "failed": frozenset(
        (
            "contract_violation",
            "fixture_prepare_failed",
            "invalid_fixture_session",
            "cleanup_failed",
            "invalid_case_result",
            "case_failed",
            "backend_error_unmapped",
        )
    ),
    "not_verified": frozenset(
        ("adapter_not_configured", "missing_fixture_capability", "case_not_verified")
    ),
}
_EVIDENCE_KINDS = frozenset(("fixture-observed", "offline-local", "real-local", "real-service"))
SUITE_DIGEST = digest(
    {
        "schema_version": "1",
        "suite_version": "1",
        "role": "knowledge-retriever",
        "contract_version": "1",
        "cases": [
            dict(case_id=case_id, label=label) for case_id, label in KNOWLEDGE_CONTRACT_CASES
        ],
        "observation_keys": sorted(OBSERVATION_KEYS),
        "status_codes": {key: sorted(values) for key, values in _STATUS_CODES.items()},
    }
)


def _sha256(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError("Contract evidence requires a SHA-256 digest")


def _observations(value, case_id):
    catalog = catalog_for_case(case_id)
    if type(value) is not dict or not set(value) <= catalog.observation_keys:
        raise ValidationError("Contract observations require fixed public fields")
    for key, item in value.items():
        if key in catalog.boolean_observations:
            valid = type(item) is bool
        else:
            valid = type(item) is int and 0 <= item <= 2**63 - 1
        if not valid:
            raise ValidationError("Contract observations require bounded counts and booleans")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class AdapterContractEvidence:
    """A retained, generated relative artifact; never an absolute host path."""

    path: str
    sha256: str
    bytes: int

    def __post_init__(self):
        path = self.path
        if (
            type(path) is not str
            or not 1 <= len(path) <= 128
            or re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)*", path) is None
            or any(part in {".", ".."} for part in PurePosixPath(path).parts)
        ):
            raise ValidationError("Contract evidence requires a safe generated relative path")
        _sha256(self.sha256)
        if type(self.bytes) is not int or not 0 <= self.bytes <= 1048576:
            raise ValidationError("Contract evidence size must be bounded")

    def to_dict(self):
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True)
class AdapterContractCaseResult:
    case_id: str
    status: str
    code: str
    observations: dict = field(default_factory=dict)
    evidence: tuple[AdapterContractEvidence, ...] = ()
    adapter_digest: str | None = field(default=None, kw_only=True)
    configuration_digest: str | None = field(default=None, kw_only=True)
    execution_authority: str = field(default="none", kw_only=True)
    evidence_kind: str = field(default="fixture-observed", kw_only=True)

    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        return copy.deepcopy(value) if name == "observations" else value

    def __post_init__(self):
        if (
            type(self.case_id) is not str
            or type(self.status) is not str
            or self.status not in _STATUS_CODES
            or type(self.code) is not str
            or self.code not in _STATUS_CODES[self.status]
        ):
            raise ValidationError("Contract cases require frozen identities, statuses and codes")
        object.__setattr__(self, "observations", _observations(self.observations, self.case_id))
        if (
            not isinstance(self.evidence, (tuple, list))
            or len(self.evidence) > 4
            or any(type(value) is not AdapterContractEvidence for value in self.evidence)
        ):
            raise ValidationError("Contract cases require bounded evidence references")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        _sha256(self.adapter_digest, optional=True)
        _sha256(self.configuration_digest, optional=True)
        if (
            type(self.execution_authority) is not str
            or self.execution_authority not in {"none", "local"}
            or type(self.evidence_kind) is not str
            or self.evidence_kind not in _EVIDENCE_KINDS
        ):
            raise ValidationError("Contract case evidence labels are unsupported")

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "label": catalog_for_case(self.case_id).labels[self.case_id],
            "status": self.status,
            "code": self.code,
            "observations": self.observations,
            "evidence": [value.to_dict() for value in self.evidence],
            "adapter_digest": self.adapter_digest,
            "configuration_digest": self.configuration_digest,
            "execution_authority": self.execution_authority,
            "evidence_kind": self.evidence_kind,
        }


@dataclass(frozen=True, kw_only=True)
class AdapterContractReport:
    cases: tuple[AdapterContractCaseResult, ...]
    status: str | None = None
    reason: str | None = None
    role: str = "knowledge-retriever"
    profile: str = "core"

    def __post_init__(self):
        catalog = catalog_for(self.role, "1", self.profile)
        if not isinstance(self.cases, (tuple, list)) or any(
            type(value) is not AdapterContractCaseResult for value in self.cases
        ):
            raise ValidationError("Contract reports require actual case result values")
        cases = tuple(self.cases)
        if tuple(value.case_id for value in cases) != catalog.case_ids:
            raise ValidationError("Contract reports preserve every frozen case in order")
        object.__setattr__(self, "cases", cases)
        derived = (
            "failed"
            if any(case.status == "failed" for case in cases)
            else "passed"
            if all(case.status == "passed" for case in cases)
            else "incomplete"
        )
        if self.status is not None and type(self.status) is not str:
            raise ValidationError("Contract report status requires an ordinary string")
        if self.status == "not_run":
            if self.reason != "adapter_not_configured" or any(
                case.status != "not_verified" or case.code != "adapter_not_configured"
                for case in cases
            ):
                raise ValidationError("Not-run reports cannot certify attempted cases")
        elif self.reason is not None or self.status not in {None, derived}:
            raise ValidationError("Contract report status is derived from required cases")
        else:
            object.__setattr__(self, "status", derived)

    def to_dict(self):
        adapters = sorted({case.adapter_digest for case in self.cases if case.adapter_digest})
        configurations = sorted(
            {case.configuration_digest for case in self.cases if case.configuration_digest}
        )
        authorities = sorted({case.execution_authority for case in self.cases})
        evidence_kinds = sorted({case.evidence_kind for case in self.cases})
        catalog = catalog_for(self.role, "1", self.profile)
        value = {
            "schema_version": "1",
            "role": self.role,
            "contract_version": "1",
            "suite_version": "1",
            "suite_digest": catalog.suite_digest,
            "status": self.status,
            "reason": self.reason,
            "total": len(self.cases),
            "passed": sum(case.status == "passed" for case in self.cases),
            "failed": sum(case.status == "failed" for case in self.cases),
            "not_verified": sum(case.status == "not_verified" for case in self.cases),
            "adapter_digest": adapters[0] if len(adapters) == 1 else None,
            "configuration_digest": configurations[0] if len(configurations) == 1 else None,
            "adapter_digests": adapters,
            "configuration_digests": configurations,
            "execution_authority": authorities[0] if len(authorities) == 1 else "mixed",
            "execution_authorities": authorities,
            "evidence_kind": evidence_kinds[0] if len(evidence_kinds) == 1 else "mixed",
            "evidence_kinds": evidence_kinds,
            "model_quality": None,
            "semantic_quality": None,
            "cases": [case.to_dict() for case in self.cases],
        }
        if self.role != "knowledge-retriever":
            value["profile"] = self.profile
        return value


class AdapterContractCleanupPending(Exception):
    """Internal transfer of original cleanup responsibility, never a report DTO.

    The fixed role retains its original BuildContext/Engine in the asynchronous
    cleanup closure. The suite keeps that same owner and workspace for retry.
    """

    def __init__(self, result, cleanup):
        from .ports import is_async_callable

        if (
            type(result) is not AdapterContractCaseResult
            or result.status != "failed"
            or result.code != "cleanup_failed"
            or not is_async_callable(cleanup)
        ):
            raise ValidationError("Incomplete contract cleanup requires its original async owner")
        super().__init__("Adapter contract cleanup remains incomplete")
        self.result, self.cleanup = result, cleanup
