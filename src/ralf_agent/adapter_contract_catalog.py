"""Frozen adapter requirements selected by role, contract version and profile.

Catalogs supply metadata, never fixture capabilities or verdicts. Knowledge v1
retains its original digest input; explicit Session and Facts profiles have
separate case requirements and include their profile in the suite digest.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

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
SESSION_CONTRACT_CASES = (
    ("S01", "identity-and-port"),
    ("S02", "ordered-read-and-append"),
    ("S03", "scope-and-address"),
    ("S04", "compare-and-swap"),
    ("S05", "message-idempotency"),
    ("S06", "detached-finite-messages"),
    ("S07", "backend-errors"),
    ("S08", "backend-drift"),
    ("S09", "lifecycle-and-suspension"),
    ("S10", "local-consumer"),
    ("S11", "exact-message-receipts"),
    ("S12", "reopened-receipts"),
    ("S13", "accepted-write-lost-ack"),
    ("S14", "managed-save-recovery"),
)
FACTS_CONTRACT_CASES = (
    ("F01", "identity-and-port"),
    ("F02", "current-read-and-version"),
    ("F03", "scope-and-namespace"),
    ("F04", "compare-and-swap"),
    ("F05", "expiry-and-currentness"),
    ("F06", "detached-finite-values"),
    ("F07", "backend-errors"),
    ("F08", "backend-drift"),
    ("F09", "lifecycle-and-suspension"),
    ("F10", "local-consumer"),
    ("F11", "bounded-recall-and-cursors"),
    ("F12", "validation-and-scoped-binding"),
    ("F13", "exact-inspection-and-reopen"),
    ("F14", "pipeline-partial-replay"),
    ("F15", "accepted-write-lost-ack"),
    ("F16", "receipt-and-settlement-recovery"),
)
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
_KNOWLEDGE_COUNTS = frozenset(
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
_SESSION_COUNTS = frozenset(
    (
        "read_calls",
        "append_calls",
        "inspection_calls",
        "message_count",
        "revision",
        "close_calls",
        "backend_switches",
        "consumer_runs",
        "model_calls",
        "save_count",
        "receipt_checks",
        "reopen_calls",
        "rejection_checks",
        "scope_checks",
        "address_checks",
    )
)
_FACTS_COUNTS = frozenset(
    (
        "facts_calls",
        "put_calls",
        "recall_calls",
        "validate_calls",
        "inspection_calls",
        "fact_count",
        "version",
        "close_calls",
        "backend_switches",
        "consumer_runs",
        "model_calls",
        "write_count",
        "receipt_checks",
        "reopen_calls",
        "rejection_checks",
        "scope_checks",
        "namespace_checks",
        "used_chars",
        "scanned",
        "skipped",
        "duplicate_checks",
        "settlement_checks",
    )
)
STATUS_CODES = MappingProxyType(
    {
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
)


@dataclass(frozen=True)
class AdapterContractCatalog:
    """Immutable metadata for one explicitly selected frozen suite."""

    role: str
    contract_version: str
    profile: str
    cases: tuple[tuple[str, str], ...]
    boolean_observations: frozenset[str]
    count_observations: frozenset[str]
    case_ids: tuple[str, ...] = field(init=False)
    labels: MappingProxyType = field(init=False)
    observation_keys: frozenset[str] = field(init=False)
    suite_digest: str = field(init=False)

    def __post_init__(self):
        cases = tuple((case_id, label) for case_id, label in self.cases)
        booleans = frozenset(self.boolean_observations)
        counts = frozenset(self.count_observations)
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "boolean_observations", booleans)
        object.__setattr__(self, "count_observations", counts)
        object.__setattr__(self, "case_ids", tuple(case_id for case_id, _ in cases))
        object.__setattr__(self, "labels", MappingProxyType(dict(cases)))
        object.__setattr__(self, "observation_keys", booleans | counts)
        record = {
            "schema_version": "1",
            "suite_version": "1",
            "role": self.role,
            "contract_version": self.contract_version,
            "cases": [dict(case_id=case_id, label=label) for case_id, label in cases],
            "observation_keys": sorted(self.observation_keys),
            "status_codes": {key: sorted(values) for key, values in STATUS_CODES.items()},
        }
        if self.role != "knowledge-retriever":
            record["profile"] = self.profile
        object.__setattr__(self, "suite_digest", digest(record))


_KNOWLEDGE = AdapterContractCatalog(
    "knowledge-retriever",
    "1",
    "core",
    KNOWLEDGE_CONTRACT_CASES,
    _BOOLEAN_OBSERVATIONS,
    _KNOWLEDGE_COUNTS,
)
_SESSION_CORE = AdapterContractCatalog(
    "session-store",
    "1",
    "core",
    SESSION_CONTRACT_CASES[:10],
    _BOOLEAN_OBSERVATIONS,
    _SESSION_COUNTS,
)
_SESSION_RECEIPTS = AdapterContractCatalog(
    "session-store",
    "1",
    "receipts",
    SESSION_CONTRACT_CASES,
    _BOOLEAN_OBSERVATIONS,
    _SESSION_COUNTS,
)
_FACTS_CORE = AdapterContractCatalog(
    "facts-store",
    "1",
    "core",
    FACTS_CONTRACT_CASES[:10],
    _BOOLEAN_OBSERVATIONS,
    _FACTS_COUNTS,
)
_FACTS_MANAGED = AdapterContractCatalog(
    "facts-store",
    "1",
    "managed",
    FACTS_CONTRACT_CASES,
    _BOOLEAN_OBSERVATIONS,
    _FACTS_COUNTS,
)
_CATALOGS = MappingProxyType(
    {
        (catalog.role, catalog.contract_version, catalog.profile): catalog
        for catalog in (
            _KNOWLEDGE,
            _SESSION_CORE,
            _SESSION_RECEIPTS,
            _FACTS_CORE,
            _FACTS_MANAGED,
        )
    }
)
_CASE_CATALOGS = MappingProxyType(
    {
        case_id: catalog
        for catalog in (_KNOWLEDGE, _SESSION_RECEIPTS, _FACTS_MANAGED)
        for case_id in catalog.case_ids
    }
)


def catalog_for(role, contract_version, profile):
    """Select exact requirements; unknown or nonordinary selectors are invalid."""
    if any(type(value) is not str for value in (role, contract_version, profile)):
        raise ValidationError("Unknown adapter contract selection")
    selected = _CATALOGS.get((role, contract_version, profile))
    if selected is None:
        raise ValidationError("Unknown adapter contract selection")
    return selected


def catalog_for_case(case_id):
    """Resolve unique case metadata without inferring a report's profile."""
    if type(case_id) is not str:
        raise ValidationError("Unknown adapter contract case")
    selected = _CASE_CATALOGS.get(case_id)
    if selected is None:
        raise ValidationError("Unknown adapter contract case")
    return selected
