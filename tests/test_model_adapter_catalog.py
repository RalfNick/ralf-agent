"""ModelProvider metadata fixes required cases without changing published suites."""

import asyncio
import hashlib
from dataclasses import FrozenInstanceError

import pytest

import relf_agent.adapter_contract_catalog as catalog_module
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

MODEL_CASES = (
    ("P01", "identity-and-port"),
    ("P02", "response-and-metering"),
    ("P03", "detached-request-and-response"),
    ("P04", "completed-invalid-evidence"),
    ("P05", "provider-errors"),
    ("P06", "component-drift"),
    ("P07", "backend-drift"),
    ("P08", "lifecycle-and-suspension"),
    ("P09", "local-consumer"),
    ("P10", "recorded-response-recovery"),
    ("P11", "tool-proposals-and-schema"),
    ("P12", "authorization-boundary"),
    ("P13", "durable-approval"),
    ("P14", "followup-tool-evidence"),
    ("P15", "duplicate-submit-replay"),
    ("P16", "accepted-call-lost-response"),
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
        "model_calls",
        "request_count",
        "response_count",
        "close_calls",
        "backend_switches",
        "identity_checks",
        "method_checks",
        "consumer_runs",
        "rejection_checks",
        "received_count",
        "adopted_count",
        "tool_calls",
        "write_count",
        "approval_count",
        "duplicate_checks",
        "reservation_checks",
        "settlement_checks",
        "reopen_calls",
    }
)


@pytest.mark.parametrize(
    "profile,count,suite_digest",
    [
        ("core", 10, "1a36404389335cbe6e2ab30f6a92dccd89252f637c8a6cef0289c1e2ee820850"),
        ("tools", 16, "4fc9ef0ca0dbc59924fd5160d4fe8b5590e7f3db17df461feebd1b630becd2b6"),
    ],
)
def test_model_selection_freezes_required_cases_observations_and_digest(
    profile, count, suite_digest
):
    catalog = catalog_for("model-provider", "1", profile)
    assert (catalog.role, catalog.contract_version, catalog.profile) == (
        "model-provider",
        "1",
        profile,
    )
    assert catalog.cases == MODEL_CASES[:count]
    assert catalog.case_ids == tuple(case_id for case_id, _ in MODEL_CASES[:count])
    assert dict(catalog.labels) == dict(MODEL_CASES[:count])
    assert catalog.boolean_observations == BOOLEAN_KEYS
    assert catalog.count_observations == COUNT_KEYS
    assert catalog.observation_keys == BOOLEAN_KEYS | COUNT_KEYS
    assert catalog.suite_digest == suite_digest
    assert catalog_for("model-provider", "1", profile) is catalog


def test_model_case_owner_is_tools_superset_without_expanding_core_selection():
    tools = catalog_for("model-provider", "1", "tools")
    core = catalog_for("model-provider", "1", "core")
    for case_id, label in MODEL_CASES:
        assert catalog_for_case(case_id) is tools
        assert catalog_for_case(case_id).labels[case_id] == label
    assert core.case_ids == tuple(case_id for case_id, _ in MODEL_CASES[:10])
    assert "P11" not in core.labels
    assert catalog_module.MODEL_CONTRACT_CASES == MODEL_CASES
    assert type(catalog_module.MODEL_CONTRACT_CASES) is tuple


@pytest.mark.parametrize("profile", ["core", "tools"])
def test_model_catalog_cannot_be_modified_by_callers(profile):
    catalog = catalog_for("model-provider", "1", profile)
    with pytest.raises(FrozenInstanceError):
        catalog.profile = "core"
    with pytest.raises(TypeError):
        catalog.labels["P01"] = "fixture-claimed-success"
    with pytest.raises(TypeError):
        catalog.cases[0] = ("P01", "fixture-claimed-success")
    assert type(catalog.cases) is tuple
    assert type(catalog.case_ids) is tuple
    assert type(catalog.boolean_observations) is frozenset
    assert type(catalog.count_observations) is frozenset
    assert type(catalog.observation_keys) is frozenset


class NonordinaryString(str):
    pass


@pytest.mark.parametrize(
    "role,version,profile",
    [
        ("model-provider", "2", "core"),
        ("model-provider", "1", "managed"),
        ("model-provider", "1", "receipts"),
        ("model-provider", "1", "unknown"),
        ("model-provider", "1", ""),
        ("model-provider", "1", None),
        ("model-provider", "1", ["core"]),
        ("model-provider", "1", True),
        ("model-provider", "1", b"core"),
        ("model-provider", "1", NonordinaryString("core")),
        ("model-provider", True, "core"),
        ("model-provider", 1, "core"),
        ("model-provider", NonordinaryString("1"), "core"),
        (["model-provider"], "1", "core"),
        (NonordinaryString("model-provider"), "1", "core"),
        ("model", "1", "core"),
        ("knowledge-retriever", "1", "tools"),
        ("session-store", "1", "tools"),
        ("facts-store", "1", "tools"),
    ],
)
def test_model_selection_never_infers_unknown_or_foreign_profile(role, version, profile):
    with pytest.raises(ValidationError):
        catalog_for(role, version, profile)


@pytest.mark.parametrize(
    "case_id", ["P00", "P17", "p01", "P1", None, ["P01"], True, NonordinaryString("P01")]
)
def test_model_case_lookup_rejects_unknown_and_nonordinary_id(case_id):
    with pytest.raises(ValidationError):
        catalog_for_case(case_id)


@pytest.mark.parametrize("profile,count", [("core", 10), ("tools", 16)])
def test_model_report_consumer_requires_every_selected_case_and_exact_order(profile, count):
    cases = tuple(
        AdapterContractCaseResult(case_id, "passed", "verified")
        for case_id, _ in MODEL_CASES[:count]
    )
    report = AdapterContractReport(role="model-provider", profile=profile, cases=cases).to_dict()
    assert (report["role"], report["profile"], report["status"]) == (
        "model-provider",
        profile,
        "passed",
    )
    assert report["total"] == report["passed"] == count
    assert report["model_quality"] is report["semantic_quality"] is None
    assert (
        tuple((case["case_id"], case["label"]) for case in report["cases"]) == MODEL_CASES[:count]
    )
    foreign = AdapterContractCaseResult("K01", "passed", "verified")
    for invalid in (
        cases[:-1],
        (cases[0], *cases[:-1]),
        tuple(reversed(cases)),
        (foreign, *cases[1:]),
        cases[:10]
        if profile == "tools"
        else (*cases, AdapterContractCaseResult("P11", "passed", "verified")),
    ):
        with pytest.raises(ValidationError):
            AdapterContractReport(role="model-provider", profile=profile, cases=invalid)


@pytest.mark.parametrize("key", sorted(BOOLEAN_KEYS | COUNT_KEYS))
def test_model_result_consumer_accepts_only_typed_public_observations(key):
    value = True if key in BOOLEAN_KEYS else 1
    result = AdapterContractCaseResult("P01", "passed", "verified", {key: value})
    assert result.observations == {key: value}
    wrong_type = 1 if key in BOOLEAN_KEYS else True
    with pytest.raises(ValidationError):
        AdapterContractCaseResult("P01", "passed", "verified", {key: wrong_type})


@pytest.mark.parametrize(
    "observations",
    [
        {"request_count": -1},
        {"request_count": 2**63},
        {"request_count": float("nan")},
        {"prompt": "private prompt"},
        {"output": "private output"},
        {"error": "supplier error or credential"},
        {"read_calls": 1},
        {"retrieve_calls": 1},
        {"facts_calls": 1},
    ],
)
def test_model_allowlist_rejects_private_values_and_foreign_counts(observations):
    with pytest.raises(ValidationError):
        AdapterContractCaseResult("P01", "passed", "verified", observations)


@pytest.mark.parametrize("case_id", ["K01", "S01", "F01"])
def test_model_counts_do_not_expand_published_role_allowlists(case_id):
    with pytest.raises(ValidationError):
        AdapterContractCaseResult(case_id, "passed", "verified", {"request_count": 1})


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
        (
            "facts-store",
            "core",
            "804de8257a8d85015d95163951e08ccaf3f383e359bd3e668ec37cce82c3bb95",
            "126dd08cdebbe5733c07df8c95fd904ee102cfdef88dd5161e3d6ea28b841a85",
        ),
        (
            "facts-store",
            "managed",
            "da4a9fe8660d5629ffeab856398cb66abeb749564a6bd656693e8f0b65aaca01",
            "b777fe996d31f0bee53793cdd74a9cb4cfa4607b1d06957428954ade3b7cf9dd",
        ),
    ],
)
def test_published_suites_keep_literal_metadata_and_canonical_report_bytes(
    role, profile, suite_digest, report_digest
):
    assert catalog_for(role, "1", profile).suite_digest == suite_digest
    report = asyncio.run(AdapterContractSuite(role=role, profile=profile).run()).to_dict()
    assert hashlib.sha256(canonical(report).encode()).hexdigest() == report_digest


def test_model_extension_preserves_knowledge_defaults_aliases_and_status_codes():
    knowledge = catalog_for("knowledge-retriever", "1", "core")
    assert CASE_IDS == knowledge.case_ids
    assert dict(CASE_LABELS) == dict(knowledge.labels)
    assert OBSERVATION_KEYS == knowledge.observation_keys
    assert SUITE_DIGEST == "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349"
    default = asyncio.run(AdapterContractSuite().run()).to_dict()
    assert default["role"] == "knowledge-retriever"
    assert "profile" not in default
    assert hashlib.sha256(canonical(default).encode()).hexdigest() == (
        "8664774fd91072c7a9f3499342530800ca50f10830a3a439176df9a9a68a2ea2"
    )
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
