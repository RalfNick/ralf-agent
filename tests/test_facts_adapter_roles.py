"""Public Facts role selection and retained canonical Knowledge/Session bytes."""

import asyncio
import hashlib
import json

import pytest

from relf_agent import AdapterContractCaseResult, AdapterContractReport, AdapterContractSuite
from relf_agent.errors import ValidationError
from relf_agent.types import canonical


def facts_cases(count, status="passed", code="verified"):
    return tuple(
        AdapterContractCaseResult(f"F{index:02d}", status, code) for index in range(1, count + 1)
    )


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("managed", 16)])
def test_exact_selected_facts_catalog_is_required(profile, count):
    report = AdapterContractReport(role="facts-store", profile=profile, cases=facts_cases(count))
    value = report.to_dict()
    assert value["role"] == "facts-store" and value["profile"] == profile
    assert value["status"] == "passed" and value["total"] == value["passed"] == count
    assert value["semantic_quality"] is value["model_quality"] is None
    assert [item["case_id"] for item in value["cases"]] == [
        f"F{n:02d}" for n in range(1, count + 1)
    ]


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("managed", 16)])
def test_partial_mixed_or_extended_facts_reports_cannot_pass(profile, count):
    for cases in (
        facts_cases(count - 1),
        facts_cases(count) + (AdapterContractCaseResult("K01", "passed", "verified"),),
        facts_cases(count)[1:] + (facts_cases(count)[0],),
        facts_cases(count - 1) + (AdapterContractCaseResult("S01", "passed", "verified"),),
    ):
        with pytest.raises(ValidationError):
            AdapterContractReport(role="facts-store", profile=profile, cases=cases)


@pytest.mark.parametrize("profile", ["core", "managed"])
def test_unconfigured_facts_suite_does_no_testing_io(profile, monkeypatch, tmp_path):
    import relf_agent.adapter_contracts as module

    def forbidden(*args, **kwargs):
        raise AssertionError("unconfigured checks must not prepare a workspace or case")

    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(module, "_run_case", forbidden)
    report = asyncio.run(
        AdapterContractSuite(role="facts-store", profile=profile).run(
            evidence_dir=tmp_path / "never-created"
        )
    )
    value = report.to_dict()
    assert value["status"] == "not_run" and value["reason"] == "adapter_not_configured"
    assert value["passed"] == value["failed"] == 0
    assert value["not_verified"] == value["total"] == (10 if profile == "core" else 16)
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("profile", ["receipts", "indexed-source", "", True, None])
def test_invalid_facts_profile_fails_before_case_work(profile):
    with pytest.raises(ValidationError):
        AdapterContractSuite(role="facts-store", profile=profile)


@pytest.mark.parametrize("profile", ["core", "managed"])
def test_missing_management_evidence_cannot_be_passing_skip(profile):
    count = 10 if profile == "core" else 16
    cases = list(facts_cases(count))
    cases[8] = AdapterContractCaseResult("F09", "not_verified", "missing_fixture_capability")
    value = AdapterContractReport(role="facts-store", profile=profile, cases=tuple(cases)).to_dict()
    assert value["status"] == "incomplete"
    assert value["passed"] == count - 1 and value["not_verified"] == 1
    assert value["cases"][8]["status"] == "not_verified"


def test_facts_observations_cannot_serialize_messages_or_nonfinite_counts():
    for observations in (
        {"raw_message": "private seeded value"},
        {"put_calls": True},
        {"write_count": float("nan")},
        {"fact_count": -1},
    ):
        with pytest.raises(ValidationError):
            AdapterContractCaseResult("F02", "passed", "verified", observations)


def test_facts_suites_do_not_change_literal_knowledge_v1_report():
    value = asyncio.run(AdapterContractSuite().run()).to_dict()
    assert "profile" not in value
    assert (
        value["suite_digest"] == "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349"
    )
    assert (
        hashlib.sha256(canonical(value).encode()).hexdigest()
        == "8664774fd91072c7a9f3499342530800ca50f10830a3a439176df9a9a68a2ea2"
    )
    assert json.loads(canonical(value)) == value


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("core", "b37cdc0626c7a5ad826cf42456674240d5aa3f053f7161038e06c2faea4c4eaa"),
        ("receipts", "2477d0250679d77270f3768f88c9fae691a0cc0e52b16f4d1551f4809281cca9"),
    ],
)
def test_facts_suites_keep_literal_session_v1_catalog(profile, expected):
    value = asyncio.run(AdapterContractSuite(role="session-store", profile=profile).run()).to_dict()
    assert value["suite_digest"] == expected and value["profile"] == profile
    assert all(item["case_id"].startswith("S") for item in value["cases"])


def test_facts_fixture_api_is_exported_and_construction_is_lazy(monkeypatch):
    import relf_agent as sdk
    from relf_agent.facts_adapter_contract_reference import ReferenceFactsSource

    def forbidden(*args, **kwargs):
        raise AssertionError("fixture construction cannot open a source")

    monkeypatch.setattr(ReferenceFactsSource, "__init__", forbidden)
    names = (
        "FactsAdapterFixture",
        "FactsContractAddress",
        "FactsContractPause",
        "FactsContractResource",
        "FactsContractSession",
        "offline_facts_fixture",
    )
    assert all(name in sdk.__all__ and hasattr(sdk, name) for name in names)
    fixture = sdk.offline_facts_fixture()
    assert callable(fixture.prepare)
