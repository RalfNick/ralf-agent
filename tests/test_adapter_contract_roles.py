"""Role selection cannot alter published Knowledge evidence or omit Session cases."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from ralf_agent.adapter_contract_types import (
    SUITE_DIGEST,
    AdapterContractCaseResult,
    AdapterContractReport,
)
from ralf_agent.adapter_contracts import AdapterContractSuite
from ralf_agent.errors import ValidationError
from ralf_agent.types import canonical


def session_cases(count=10):
    return tuple(
        AdapterContractCaseResult(f"S{i:02}", "passed", "verified") for i in range(1, count + 1)
    )


def test_knowledge_v1_unconfigured_dictionary_is_byte_compatible():
    value = asyncio.run(AdapterContractSuite().run()).to_dict()
    assert SUITE_DIGEST == "75b02ce8f33a8b8ca99dcdb4a3b9e7f394ceefbf41ea6b31dd22f5c063e56349"
    assert (
        hashlib.sha256(canonical(value).encode()).hexdigest()
        == "8664774fd91072c7a9f3499342530800ca50f10830a3a439176df9a9a68a2ea2"
    )
    assert "profile" not in value


@pytest.mark.parametrize("profile,count", [("core", 10), ("receipts", 14)])
def test_session_report_explicit_profile_and_exact_required_cases(profile, count):
    value = AdapterContractReport(
        role="session-store", profile=profile, cases=session_cases(count)
    ).to_dict()
    assert value["role"] == "session-store"
    assert value["profile"] == profile
    assert value["total"] == value["passed"] == count
    assert value["status"] == "passed"
    assert value["model_quality"] is value["semantic_quality"] is None
    assert value["suite_digest"] != SUITE_DIGEST


@pytest.mark.parametrize(
    "selection", ["missing", "duplicate", "reversed", "foreign", "wrong-profile"]
)
def test_reports_cannot_hide_or_substitute_session_requirements(selection):
    values = session_cases(14)
    cases = {
        "missing": values[:-1],
        "duplicate": (values[0], *values[:-1]),
        "reversed": tuple(reversed(values)),
        "foreign": (AdapterContractCaseResult("K01", "passed", "verified"), *values[1:]),
        "wrong-profile": values[:10],
    }[selection]
    with pytest.raises(ValidationError):
        AdapterContractReport(role="session-store", profile="receipts", cases=cases)


@pytest.mark.parametrize("profile,count", [("core", 10), ("receipts", 14)])
def test_session_missing_fixture_performs_no_testing_io(profile, count, tmp_path, monkeypatch):
    import ralf_agent.adapter_contracts as module

    def forbidden(*args, **kwargs):
        pytest.fail("Unconfigured Session contract performed I/O")

    monkeypatch.setattr(module, "_run_case", forbidden)
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    suite = AdapterContractSuite(role="session-store", profile=profile)
    value = asyncio.run(suite.run(evidence_dir=tmp_path / "absent")).to_dict()
    assert value["status"] == "not_run"
    assert value["not_verified"] == value["total"] == count
    assert [v["case_id"] for v in value["cases"]] == [f"S{i:02}" for i in range(1, count + 1)]


@pytest.mark.parametrize(
    "role,profile",
    [
        ("knowledge-retriever", "receipts"),
        ("session-store", "unknown"),
        ("session-store", True),
        ([], "core"),
    ],
)
def test_invalid_profile_fails_before_testing(role, profile):
    with pytest.raises(ValidationError):
        AdapterContractSuite(role=role, profile=profile)


@pytest.mark.parametrize("profile,count", [("core", 10), ("receipts", 14)])
def test_session_dispatch_remains_suite_owned_redacted_and_complete(profile, count, monkeypatch):
    import ralf_agent.adapter_contracts as module

    calls = []
    secret = "private query and credential body"

    async def dispatch(case_id, fixture, workspace):
        calls.append(case_id)
        if case_id == "S01":
            raise RuntimeError(secret)
        if case_id == "S02":
            return {"status": "passed", "secret": secret}
        if case_id == "S03":
            return AdapterContractCaseResult("K01", "passed", "verified")
        return AdapterContractCaseResult(case_id, "not_verified", "missing_fixture_capability")

    monkeypatch.setattr(module, "_run_case", dispatch)
    value = asyncio.run(
        AdapterContractSuite(role="session-store", profile=profile).run(object())
    ).to_dict()
    assert calls == [f"S{i:02}" for i in range(1, count + 1)]
    assert (value["failed"], value["not_verified"], value["total"]) == (3, count - 3, count)
    assert value["status"] == "failed"
    assert secret not in json.dumps(value)


def test_session_observations_do_not_expand_knowledge_v1_allowlist():
    case = AdapterContractCaseResult("S01", "passed", "verified", {"append_calls": 1})
    assert case.observations == {"append_calls": 1}
    with pytest.raises(ValidationError):
        AdapterContractCaseResult("K01", "passed", "verified", {"append_calls": 1})


@pytest.mark.parametrize("profile", ["core", "receipts"])
def test_session_observer_cancel_drains_actual_case_before_workspace_release(profile, monkeypatch):
    import ralf_agent.adapter_contracts as module

    async def exercise():
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        observed = []

        async def dispatch(case_id, fixture, workspace):
            observed.append((case_id, workspace))
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                assert workspace.is_dir()

        monkeypatch.setattr(module, "_run_case", dispatch)
        observer = asyncio.create_task(
            AdapterContractSuite(role="session-store", profile=profile).run(object())
        )
        await entered.wait()
        observer.cancel()
        await cleaning.wait()
        observer.cancel()
        await asyncio.sleep(0)
        assert not observer.done()
        assert observed[0][1].is_dir()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert observed[0][0] == "S01"
        assert not observed[0][1].exists()

    asyncio.run(exercise())


def test_session_failed_cleanup_retains_selected_complete_catalog_and_original_owner(monkeypatch):
    import ralf_agent.adapter_contracts as module
    from ralf_agent.adapter_contract_types import AdapterContractCleanupPending
    from ralf_agent.errors import CloseIncomplete

    async def exercise():
        calls, retries, workspaces = [], [], []

        async def cleanup():
            retries.append(1)
            assert workspaces[0].is_dir()
            if len(retries) == 1:
                raise RuntimeError("private cleanup")

        async def dispatch(case_id, fixture, workspace):
            calls.append(case_id)
            workspaces.append(workspace)
            raise AdapterContractCleanupPending(
                AdapterContractCaseResult(
                    case_id, "failed", "cleanup_failed", {"cleanup_complete": False}
                ),
                cleanup,
            )

        monkeypatch.setattr(module, "_run_case", dispatch)
        suite = AdapterContractSuite(role="session-store", profile="receipts")
        report = (await suite.run(object())).to_dict()
        assert report["total"] == 14
        assert report["profile"] == "receipts"
        assert report["failed"] == 1 and report["not_verified"] == 13
        assert suite.pending_cleanup
        with pytest.raises(CloseIncomplete):
            await suite.aclose()
        assert workspaces[0].is_dir()
        await suite.aclose()
        assert calls == ["S01"] and len(retries) == 2
        assert not suite.pending_cleanup
        assert not workspaces[0].exists()
        assert report["status"] == "failed"

    asyncio.run(exercise())
