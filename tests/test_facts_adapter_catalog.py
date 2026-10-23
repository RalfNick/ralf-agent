"""Facts requirements remain fixed and distinct from published Knowledge/Session suites."""

import asyncio
import hashlib
from dataclasses import FrozenInstanceError

import pytest

from relf_agent.adapter_contract_catalog import STATUS_CODES, catalog_for, catalog_for_case
from relf_agent.adapter_contract_types import (
    CASE_IDS,
    CASE_LABELS,
    OBSERVATION_KEYS,
    SUITE_DIGEST,
    AdapterContractCaseResult,
    AdapterContractReport,
)
from relf_agent.adapter_contracts import AdapterContractSuite
from relf_agent.errors import ValidationError
from relf_agent.types import canonical

FACTS_CASES = (
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
BOOLEAN_KEYS = frozenset(
    {
        "runtime_closed",
        "borrowed_closed",
        "handler_finished",
        "cancelled",
        "cleanup_complete",
        "ports_valid",
        "identity_valid",
    }
)
COUNT_KEYS = frozenset(
    {
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
    }
)


@pytest.mark.parametrize(
    "profile,count,suite_digest",
    [
        ("core", 10, "804de8257a8d85015d95163951e08ccaf3f383e359bd3e668ec37cce82c3bb95"),
        ("managed", 16, "da4a9fe8660d5629ffeab856398cb66abeb749564a6bd656693e8f0b65aaca01"),
    ],
)
def test_facts_selection_freezes_required_cases_observations_and_digest(
    profile, count, suite_digest
):
    catalog = catalog_for("facts-store", "1", profile)
    assert (catalog.role, catalog.contract_version, catalog.profile) == (
        "facts-store",
        "1",
        profile,
    )
    assert catalog.cases == FACTS_CASES[:count]
    assert catalog.case_ids == tuple(case_id for case_id, _ in FACTS_CASES[:count])
    assert dict(catalog.labels) == dict(FACTS_CASES[:count])
    assert catalog.boolean_observations == BOOLEAN_KEYS
    assert catalog.count_observations == COUNT_KEYS
    assert catalog.observation_keys == BOOLEAN_KEYS | COUNT_KEYS
    assert catalog.suite_digest == suite_digest
    assert catalog_for("facts-store", "1", profile) is catalog


def test_facts_case_owner_is_managed_superset_without_changing_core_selection():
    managed = catalog_for("facts-store", "1", "managed")
    core = catalog_for("facts-store", "1", "core")
    for case_id, label in FACTS_CASES:
        assert catalog_for_case(case_id) is managed
        assert catalog_for_case(case_id).labels[case_id] == label
    assert core.case_ids == tuple(case_id for case_id, _ in FACTS_CASES[:10])
    assert "F11" not in core.labels


@pytest.mark.parametrize("profile", ["core", "managed"])
def test_facts_catalog_cannot_be_modified_by_callers(profile):
    catalog = catalog_for("facts-store", "1", profile)
    with pytest.raises(FrozenInstanceError):
        catalog.profile = "core"
    with pytest.raises(TypeError):
        catalog.labels["F01"] = "fixture-claimed-success"
    with pytest.raises(TypeError):
        catalog.cases[0] = ("F01", "fixture-claimed-success")
    assert type(catalog.cases) is tuple
    assert type(catalog.case_ids) is tuple
    assert type(catalog.boolean_observations) is frozenset
    assert type(catalog.count_observations) is frozenset
    assert type(catalog.observation_keys) is frozenset


@pytest.mark.parametrize(
    "role,version,profile",
    [
        ("facts-store", "2", "core"),
        ("facts-store", "1", "receipts"),
        ("facts-store", "1", "unknown"),
        ("facts-store", "1", ""),
        ("facts-store", "1", None),
        ("facts-store", "1", ["core"]),
        ("facts-store", "1", True),
        ("facts-store", "1", b"core"),
        ("facts-store", True, "core"),
        ("facts-store", 1, "core"),
        (["facts-store"], "1", "core"),
        ("knowledge-retriever", "1", "managed"),
        ("session-store", "1", "managed"),
    ],
)
def test_facts_selection_never_infers_unknown_or_foreign_profile(role, version, profile):
    with pytest.raises(ValidationError):
        catalog_for(role, version, profile)


@pytest.mark.parametrize("case_id", ["F00", "F17", "f01", "F1", None, ["F01"], True])
def test_facts_case_lookup_rejects_unknown_and_nonordinary_id(case_id):
    with pytest.raises(ValidationError):
        catalog_for_case(case_id)


@pytest.mark.parametrize("profile,count", [("core", 10), ("managed", 16)])
def test_facts_report_consumer_requires_every_selected_case_and_exact_order(profile, count):
    cases = tuple(
        AdapterContractCaseResult(case_id, "passed", "verified")
        for case_id, _ in FACTS_CASES[:count]
    )
    report = AdapterContractReport(role="facts-store", profile=profile, cases=cases).to_dict()
    assert (report["role"], report["profile"], report["status"]) == (
        "facts-store",
        profile,
        "passed",
    )
    assert report["total"] == report["passed"] == count
    assert report["model_quality"] is report["semantic_quality"] is None
    assert (
        tuple((case["case_id"], case["label"]) for case in report["cases"]) == (FACTS_CASES[:count])
    )
    foreign = AdapterContractCaseResult("S01", "passed", "verified")
    for invalid in (
        cases[:-1],
        (cases[0], *cases[:-1]),
        tuple(reversed(cases)),
        (foreign, *cases[1:]),
    ):
        with pytest.raises(ValidationError):
            AdapterContractReport(role="facts-store", profile=profile, cases=invalid)


@pytest.mark.parametrize("key", sorted(BOOLEAN_KEYS | COUNT_KEYS))
def test_facts_result_consumer_accepts_only_typed_public_observations(key):
    value = True if key in BOOLEAN_KEYS else 1
    result = AdapterContractCaseResult("F01", "passed", "verified", {key: value})
    assert result.observations == {key: value}
    wrong_type = 1 if key in BOOLEAN_KEYS else True
    with pytest.raises(ValidationError):
        AdapterContractCaseResult("F01", "passed", "verified", {key: wrong_type})


@pytest.mark.parametrize(
    "observations",
    [
        {"put_calls": -1},
        {"put_calls": 2**63},
        {"put_calls": float("nan")},
        {"value": "private fact value"},
        {"provenance": 1},
        {"read_calls": 1},
        {"retrieve_calls": 1},
    ],
)
def test_facts_allowlist_cannot_adopt_secrets_or_session_knowledge_counts(observations):
    with pytest.raises(ValidationError):
        AdapterContractCaseResult("F01", "passed", "verified", observations)


def test_facts_counts_do_not_expand_knowledge_or_session_allowlists():
    for case_id in ("K01", "S01"):
        with pytest.raises(ValidationError):
            AdapterContractCaseResult(case_id, "passed", "verified", {"facts_calls": 1})


@pytest.mark.parametrize(
    "role,profile,suite_digest,report_digest",
    [
        (
            "knowledge-retriever",
            "core",
            "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349",
            "8664774fd91072c7a9f3499342530800ca50f10830a3a439176df9a9a68a2ea2",
        ),
        (
            "session-store",
            "core",
            "b37cdc0626c7a5ad826cf42456674240d5aa3f053f7161038e06c2faea4c4eaa",
            "05665a1ab4eb3c724e4c953f03209774a28b1310d1ec912eefce03cfa8eb2d21",
        ),
        (
            "session-store",
            "receipts",
            "2477d0250679d77270f3768f88c9fae691a0cc0e52b16f4d1551f4809281cca9",
            "9ed432f0e4cf120919ebc09e5d1bf61d6cc3c486d65b79ad380a6deb06a52eb1",
        ),
    ],
)
def test_published_suites_keep_literal_metadata_and_canonical_bytes(
    role, profile, suite_digest, report_digest
):
    assert catalog_for(role, "1", profile).suite_digest == suite_digest
    report = asyncio.run(AdapterContractSuite(role=role, profile=profile).run()).to_dict()
    assert hashlib.sha256(canonical(report).encode()).hexdigest() == report_digest


def test_facts_extension_preserves_original_knowledge_aliases_and_status_codes():
    knowledge = catalog_for("knowledge-retriever", "1", "core")
    assert CASE_IDS == knowledge.case_ids
    assert dict(CASE_LABELS) == dict(knowledge.labels)
    assert OBSERVATION_KEYS == knowledge.observation_keys
    assert SUITE_DIGEST == "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349"
    assert dict(STATUS_CODES) == {
        "passed": frozenset({"verified"}),
        "failed": frozenset(
            {
                "contract_violation",
                "fixture_prepare_failed",
                "invalid_fixture_session",
                "cleanup_failed",
                "invalid_case_result",
                "case_failed",
                "backend_error_unmapped",
            }
        ),
        "not_verified": frozenset(
            {"adapter_not_configured", "missing_fixture_capability", "case_not_verified"}
        ),
    }
    with pytest.raises(TypeError):
        STATUS_CODES["passed"] = frozenset({"fixture-claimed-success"})
