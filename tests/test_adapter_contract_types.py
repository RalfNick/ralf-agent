"""Public report values preserve bounded, detached observations."""

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError

import pytest

from ralf_agent.errors import ValidationError


def api():
    assert importlib.util.find_spec("ralf_agent.adapter_contract_types") is not None
    return importlib.import_module("ralf_agent.adapter_contract_types")


def cases(*, status="passed", code="verified", **kwargs):
    cls = api().AdapterContractCaseResult
    return tuple(cls(f"K{index:02}", status, code, **kwargs) for index in range(1, 13))


def test_report_counts_follow_all_required_case_results():
    module = api()
    report = module.AdapterContractReport(cases=cases())
    value = report.to_dict()
    assert value["status"] == "passed"
    assert value["total"] == value["passed"] == 12
    assert value["failed"] == value["not_verified"] == 0
    assert value["model_quality"] is value["semantic_quality"] is None
    assert value["role"] == "knowledge-retriever"
    assert value["contract_version"] == value["suite_version"] == "1"
    assert len(value["suite_digest"]) == 64
    json.dumps(value, allow_nan=False)


def test_report_failure_and_incomplete_are_derived():
    module = api()
    partial = list(cases())
    partial[0] = module.AdapterContractCaseResult(
        "K01", "not_verified", "missing_fixture_capability"
    )
    incomplete = module.AdapterContractReport(cases=partial).to_dict()
    assert (incomplete["status"], incomplete["passed"], incomplete["not_verified"]) == (
        "incomplete",
        11,
        1,
    )
    partial[1] = module.AdapterContractCaseResult("K02", "failed", "contract_violation")
    failed = module.AdapterContractReport(cases=partial).to_dict()
    assert (failed["status"], failed["passed"], failed["failed"], failed["not_verified"]) == (
        "failed",
        10,
        1,
        1,
    )


def test_values_are_frozen_and_nested_observations_detached():
    module = api()
    observations = {"retrieve_calls": 1, "handler_finished": True}
    case = module.AdapterContractCaseResult("K01", "passed", "verified", observations)
    observations["retrieve_calls"] = 90
    observed = case.observations
    observed["retrieve_calls"] = 91
    assert case.observations["retrieve_calls"] == 1
    report = module.AdapterContractReport(cases=(case, *cases()[1:]))
    value = report.to_dict()
    value["cases"][0]["observations"]["retrieve_calls"] = 92
    assert report.to_dict()["cases"][0]["observations"]["retrieve_calls"] == 1
    with pytest.raises(FrozenInstanceError):
        case.status = "failed"


@pytest.mark.parametrize(
    "observations",
    [
        {"source_text": 1},
        {"retrieve_calls": "private query"},
        {"retrieve_calls": float("nan")},
        {"retrieve_calls": -1},
        {"retrieve_calls": 2**63},
        {"handler_finished": []},
        {"sk_secret": True},
        [],
        None,
    ],
)
def test_observations_reject_nonpublic_or_unbounded_values(observations):
    with pytest.raises(ValidationError):
        api().AdapterContractCaseResult("K01", "passed", "verified", observations)


@pytest.mark.parametrize(
    "case_id,status,code",
    [
        ("K00", "passed", "verified"),
        ("K13", "passed", "verified"),
        ("K01", "passed", "missing_fixture_capability"),
        ("K01", "failed", "verified"),
        ("K01", "not_verified", "verified"),
        ("K01", "failed", "private-secret-text"),
        ("K01", "skipped", "case_not_verified"),
    ],
)
def test_case_rejects_inconsistent_or_unfrozen_codes(case_id, status, code):
    with pytest.raises(ValidationError):
        api().AdapterContractCaseResult(case_id, status, code)


def test_report_rejects_missing_duplicate_or_reordered_requirements():
    module = api()
    values = cases()
    for selection in [values[:-1], (values[0], *values[:-1]), tuple(reversed(values))]:
        with pytest.raises(ValidationError):
            module.AdapterContractReport(cases=selection)


def test_report_cannot_override_observed_status_or_quality():
    module = api()
    with pytest.raises(ValidationError):
        module.AdapterContractReport(
            cases=cases(), status="not_run", reason="adapter_not_configured"
        )
    with pytest.raises(TypeError):
        module.AdapterContractReport(cases=cases(), model_quality=1.0)
    not_run = module.AdapterContractReport(
        cases=cases(status="not_verified", code="adapter_not_configured"),
        status="not_run",
        reason="adapter_not_configured",
    ).to_dict()
    assert not_run["status"] == "not_run"
    assert not_run["not_verified"] == 12


def test_actual_case_digests_aggregate_without_fabricating_single_identity():
    module = api()
    first, second = "a" * 64, "b" * 64
    values = list(cases(adapter_digest=first, configuration_digest=first))
    values[1] = module.AdapterContractCaseResult(
        "K02",
        "passed",
        "verified",
        adapter_digest=second,
        configuration_digest=second,
        execution_authority="local",
    )
    report = module.AdapterContractReport(cases=values).to_dict()
    assert report["adapter_digests"] == report["configuration_digests"] == [first, second]
    assert report["adapter_digest"] is report["configuration_digest"] is None
    assert report["execution_authority"] == "mixed"
    single = module.AdapterContractReport(cases=cases(adapter_digest=first)).to_dict()
    assert single["adapter_digest"] == first


@pytest.mark.parametrize(
    "path",
    [
        "../secret.json",
        "/private/secret.json",
        "a/../../x",
        "x\\y",
        ".",
        "",
        "x\n.json",
        "a//x.json",
    ],
)
def test_evidence_ref_rejects_escaping_or_unsafe_paths(path):
    with pytest.raises(ValidationError):
        api().AdapterContractEvidence(path, "a" * 64, 1)


def test_evidence_ref_is_finite_and_ordinary_json():
    module = api()
    reference = module.AdapterContractEvidence("K01/result.json", "a" * 64, 10)
    case = module.AdapterContractCaseResult("K01", "passed", "verified", evidence=(reference,))
    assert case.to_dict()["evidence"] == [
        {"path": "K01/result.json", "sha256": "a" * 64, "bytes": 10}
    ]
    for sha, size in [("secret", 1), ("a" * 64, True), ("a" * 64, -1), ("a" * 64, 1048577)]:
        with pytest.raises(ValidationError):
            module.AdapterContractEvidence("K01/result.json", sha, size)


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("execution_authority", []),
        ("execution_authority", True),
        ("evidence_kind", {}),
        ("evidence_kind", None),
    ],
)
def test_case_metadata_rejects_nonordinary_values_with_public_validation_error(keyword, value):
    with pytest.raises(ValidationError):
        api().AdapterContractCaseResult("K01", "passed", "verified", **{keyword: value})


def test_report_metadata_rejects_nonordinary_status():
    with pytest.raises(ValidationError):
        api().AdapterContractReport(cases=cases(), status=[])


def test_frozen_case_labels_cannot_be_changed_by_external_callers():
    with pytest.raises(TypeError):
        api().CASE_LABELS["K01"] = "private-source-text"
