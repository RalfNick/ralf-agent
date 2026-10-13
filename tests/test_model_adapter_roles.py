"""Additive public ModelProvider selections retain the accepted data-role bytes."""

import asyncio
import hashlib

import pytest

from ralf_agent import AdapterContractCaseResult, AdapterContractReport, AdapterContractSuite
from ralf_agent.errors import ValidationError
from ralf_agent.types import canonical


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("tools", 16)])
def test_unconfigured_model_role_does_no_testing_io(profile, count, monkeypatch, tmp_path):
    import ralf_agent.adapter_contracts as module

    def forbidden(*args, **kwargs):
        raise AssertionError("no fixture must not allocate or invoke a case")

    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(module, "_run_case", forbidden)
    report = asyncio.run(
        AdapterContractSuite(role="model-provider", profile=profile).run(
            evidence_dir=tmp_path / "must-not-exist"
        )
    ).to_dict()
    assert report["status"] == "not_run" and report["reason"] == "adapter_not_configured"
    assert report["profile"] == profile and report["total"] == report["not_verified"] == count
    assert report["passed"] == report["failed"] == 0
    assert report["model_quality"] is report["semantic_quality"] is None
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("tools", 16)])
def test_every_selected_model_case_is_required(profile, count):
    cases = tuple(
        AdapterContractCaseResult(f"P{n:02d}", "passed", "verified") for n in range(1, count + 1)
    )
    for incomplete in (cases[:-1], cases[1:] + cases[:1], cases + cases[:1]):
        with pytest.raises(ValidationError):
            AdapterContractReport(role="model-provider", profile=profile, cases=incomplete)
    one_missing = (
        *cases[:-1],
        AdapterContractCaseResult(cases[-1].case_id, "not_verified", "missing_fixture_capability"),
    )
    value = AdapterContractReport(
        role="model-provider", profile=profile, cases=one_missing
    ).to_dict()
    assert value["status"] == "incomplete" and value["not_verified"] == 1


def test_model_role_keeps_original_unconfigured_knowledge_report_bytes():
    report = asyncio.run(AdapterContractSuite().run()).to_dict()
    assert "profile" not in report
    assert hashlib.sha256(canonical(report).encode()).hexdigest() == (
        "8664774fd91072c7a9f3499342530800ca50f10830a3a439176df9a9a68a2ea2"
    )


@pytest.mark.parametrize(
    ("role", "profile", "expected"),
    [
        (
            "session-store",
            "core",
            "b37cdc0626c7a5ad826cf42456674240d5aa3f053f7161038e06c2faea4c4eaa",
        ),
        (
            "session-store",
            "receipts",
            "2477d0250679d77270f3768f88c9fae691a0cc0e52b16f4d1551f4809281cca9",
        ),
        ("facts-store", "core", "804de8257a8d85015d95163951e08ccaf3f383e359bd3e668ec37cce82c3bb95"),
        (
            "facts-store",
            "managed",
            "da4a9fe8660d5629ffeab856398cb66abeb749564a6bd656693e8f0b65aaca01",
        ),
    ],
)
def test_model_role_keeps_accepted_data_catalogs(role, profile, expected):
    value = asyncio.run(AdapterContractSuite(role=role, profile=profile).run()).to_dict()
    assert value["suite_digest"] == expected and value["profile"] == profile


def test_model_observations_have_no_payload_or_unbounded_counts():
    for fields in (
        {"raw_output": "supplier private value"},
        {"request_count": True},
        {"response_count": float("nan")},
        {"write_count": -1},
    ):
        with pytest.raises(ValidationError):
            AdapterContractCaseResult("P02", "passed", "verified", fields)


def test_public_model_fixture_construction_is_lazy(monkeypatch):
    import ralf_agent as sdk
    from ralf_agent.model_adapter_contract_reference import ReferenceModelSource

    def forbidden(*args, **kwargs):
        raise AssertionError("constructing a fixture must not open the source")

    monkeypatch.setattr(ReferenceModelSource, "__init__", forbidden)
    names = (
        "ModelAdapterFixture",
        "ModelContractSession",
        "ModelContractResource",
        "ModelContractPause",
        "offline_model_fixture",
    )
    assert all(name in sdk.__all__ and hasattr(sdk, name) for name in names)
    assert callable(sdk.offline_model_fixture().prepare)
