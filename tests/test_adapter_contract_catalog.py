"""Frozen role/profile requirements cannot silently change certification."""

import importlib
from dataclasses import FrozenInstanceError

import pytest

KNOWLEDGE_CASES = (
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
SESSION_CASES = (
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
BOOLEAN_OBSERVATIONS = frozenset(
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


def api():
    try:
        return importlib.import_module("ralf_agent.adapter_contract_catalog")
    except ModuleNotFoundError:
        pytest.fail("The installed SDK has no frozen role/profile contract catalog")


def test_knowledge_catalog_retains_original_literal_requirements_and_digest():
    catalog = api().catalog_for("knowledge-retriever", "1", "core")
    assert (catalog.role, catalog.contract_version, catalog.profile) == (
        "knowledge-retriever",
        "1",
        "core",
    )
    assert catalog.cases == KNOWLEDGE_CASES
    assert catalog.case_ids == (
        "K01",
        "K02",
        "K03",
        "K04",
        "K05",
        "K06",
        "K07",
        "K08",
        "K09",
        "K10",
        "K11",
        "K12",
    )
    assert dict(catalog.labels) == dict(KNOWLEDGE_CASES)
    assert (
        catalog.suite_digest == "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349"
    )
    assert catalog.boolean_observations == BOOLEAN_OBSERVATIONS
    assert catalog.count_observations == {
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
    }
    assert catalog.observation_keys == (catalog.boolean_observations | catalog.count_observations)


def test_session_profile_selection_keeps_receipt_requirements_explicit():
    module = api()
    core = module.catalog_for("session-store", "1", "core")
    receipts = module.catalog_for("session-store", "1", "receipts")
    assert (core.role, core.contract_version, core.profile) == ("session-store", "1", "core")
    assert receipts.profile == "receipts"
    assert core.cases == SESSION_CASES[:10]
    assert receipts.cases == SESSION_CASES
    assert core.case_ids == ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")
    assert receipts.case_ids == (
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
        "S09",
        "S10",
        "S11",
        "S12",
        "S13",
        "S14",
    )
    assert dict(core.labels) == dict(SESSION_CASES[:10])
    assert dict(receipts.labels) == dict(SESSION_CASES)
    assert len(core.suite_digest) == len(receipts.suite_digest) == 64
    assert core.suite_digest != receipts.suite_digest
    assert core.suite_digest != module.catalog_for("knowledge-retriever", "1", "core").suite_digest


def test_session_observations_are_finite_public_fields_without_knowledge_fields():
    core = api().catalog_for("session-store", "1", "core")
    receipts = api().catalog_for("session-store", "1", "receipts")
    assert core.boolean_observations == receipts.boolean_observations == BOOLEAN_OBSERVATIONS
    assert (
        core.count_observations
        == receipts.count_observations
        == {
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
        }
    )
    assert core.observation_keys == core.boolean_observations | core.count_observations
    assert "retrieve_calls" not in core.observation_keys
    assert "message_text" not in core.observation_keys


@pytest.mark.parametrize(
    "role,version,profile",
    [
        ("unknown", "1", "core"),
        ("knowledge-retriever", "2", "core"),
        ("session-store", "2", "core"),
        ("knowledge-retriever", "1", "receipts"),
        ("session-store", "1", "unknown"),
        (None, "1", "core"),
        (["session-store"], "1", "core"),
        ("session-store", True, "core"),
        ("session-store", 1, "core"),
        ("session-store", "1", None),
        ("session-store", "1", ["core"]),
        ("session-store", "1", b"core"),
    ],
)
def test_unknown_and_nonordinary_selections_fail_with_public_validation(role, version, profile):
    module = api()
    from ralf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        module.catalog_for(role, version, profile)


@pytest.mark.parametrize("case_id", ["K00", "K13", "S00", "S15", "unknown", None, ["S01"], True])
def test_unknown_and_nonordinary_cases_fail_with_public_validation(case_id):
    module = api()
    from ralf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        module.catalog_for_case(case_id)


def test_case_lookup_preserves_the_role_and_case_metadata():
    module = api()
    knowledge = module.catalog_for("knowledge-retriever", "1", "core")
    receipts = module.catalog_for("session-store", "1", "receipts")
    for case_id, label in KNOWLEDGE_CASES:
        selected = module.catalog_for_case(case_id)
        assert selected is knowledge
        assert selected.labels[case_id] == label
    for case_id, label in SESSION_CASES:
        selected = module.catalog_for_case(case_id)
        assert selected is receipts
        assert selected.labels[case_id] == label


def test_catalog_and_nested_requirements_cannot_be_modified_by_callers():
    module = api()
    for role, profile in (
        ("knowledge-retriever", "core"),
        ("session-store", "core"),
        ("session-store", "receipts"),
    ):
        catalog = module.catalog_for(role, "1", profile)
        with pytest.raises(FrozenInstanceError):
            catalog.profile = "receipts"
        with pytest.raises(TypeError):
            catalog.labels[catalog.case_ids[0]] = "private-source-text"
        with pytest.raises(TypeError):
            catalog.cases[0] = ("X01", "forged")
        assert isinstance(catalog.observation_keys, frozenset)
        assert isinstance(catalog.boolean_observations, frozenset)
        assert isinstance(catalog.count_observations, frozenset)
        assert module.catalog_for(role, "1", profile) is catalog


def test_stable_status_codes_are_immutable_and_keep_original_public_codes():
    codes = api().STATUS_CODES
    assert dict(codes) == {
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
            {
                "adapter_not_configured",
                "missing_fixture_capability",
                "case_not_verified",
            }
        ),
    }
    with pytest.raises(TypeError):
        codes["passed"] = frozenset({"fixture_claimed_success"})
