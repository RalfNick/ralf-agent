"""The suite owns dispatch and observation lifetime, never fixture verdicts."""

import asyncio
import importlib
import importlib.util
import json
from functools import wraps
from pathlib import Path

import pytest

from ralf_agent.adapter_contract_types import CASE_IDS, AdapterContractCaseResult
from ralf_agent.errors import ValidationError


def async_test(method):
    @wraps(method)
    def run(*args, **kwargs):
        return asyncio.run(method(*args, **kwargs))

    return run


def api():
    assert importlib.util.find_spec("ralf_agent.adapter_contracts") is not None
    return importlib.import_module("ralf_agent.adapter_contracts")


@async_test
async def test_missing_fixture_never_opens_a_directory_or_calls_dispatch(tmp_path, monkeypatch):
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail("Unconfigured observation performed I/O")

    monkeypatch.setattr(module, "_run_case", forbidden)
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    result = await module.AdapterContractSuite().run(evidence_dir=tmp_path / "not-created")
    report = result.to_dict()
    assert report["status"] == "not_run"
    assert report["reason"] == "adapter_not_configured"
    assert report["not_verified"] == report["total"] == 12
    assert report["adapter_digest"] is report["configuration_digest"] is None
    assert [item["case_id"] for item in report["cases"]] == list(CASE_IDS)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize(
    "role,version",
    [
        ("unknown", "1"),
        ("knowledge-retriever", "2"),
        (None, "1"),
        (["knowledge-retriever"], "1"),
        ("knowledge-retriever", True),
    ],
)
def test_unknown_contracts_fail_without_fixture_construction(role, version):
    with pytest.raises(ValidationError):
        api().AdapterContractSuite(role=role, contract_version=version)


@async_test
async def test_every_fixed_case_dispatches_once_and_fixture_verdict_is_never_read(monkeypatch):
    module = api()
    calls = []

    class Fixture:
        def run_case(self, *args):
            pytest.fail("Fixture-controlled verdict was accepted")

    fixture = Fixture()

    async def case_runner(case_id, seen, workspace):
        assert seen is fixture
        assert workspace.is_dir()
        calls.append((case_id, workspace))
        return AdapterContractCaseResult(case_id, "passed", "verified")

    monkeypatch.setattr(module, "_run_case", case_runner)
    result = await module.AdapterContractSuite().run(fixture)
    assert [case_id for case_id, _ in calls] == list(CASE_IDS)
    assert len({path for _, path in calls}) == 12
    assert result.to_dict()["passed"] == 12
    assert not any(path.exists() for _, path in calls)
    assert all(not value["evidence"] for value in result.to_dict()["cases"])


@async_test
async def test_role_exceptions_and_malformed_results_do_not_leak_or_omit_cases(monkeypatch):
    module = api()
    private = "sk-private-query-source-path"

    async def case_runner(case_id, fixture, workspace):
        if case_id == "K01":
            raise RuntimeError(private)
        if case_id == "K02":
            return {"case_id": case_id, "status": "passed", "query": private}
        if case_id == "K03":
            return AdapterContractCaseResult("K04", "passed", "verified")
        return AdapterContractCaseResult(case_id, "not_verified", "missing_fixture_capability")

    monkeypatch.setattr(module, "_run_case", case_runner)
    report = (await module.AdapterContractSuite().run(object())).to_dict()
    assert report["status"] == "failed"
    assert (report["failed"], report["not_verified"], report["total"]) == (3, 9, 12)
    assert [value["code"] for value in report["cases"][:3]] == [
        "case_failed",
        "invalid_case_result",
        "invalid_case_result",
    ]
    assert private not in json.dumps(report)


@async_test
async def test_retained_evidence_is_exclusive_generated_and_matches_actual_bytes(
    tmp_path, monkeypatch
):
    module = api()

    async def case_runner(case_id, fixture, workspace):
        return AdapterContractCaseResult(case_id, "passed", "verified", {"retrieve_calls": 1})

    monkeypatch.setattr(module, "_run_case", case_runner)
    destination = tmp_path / "private-evidence"
    report = (await module.AdapterContractSuite().run(object(), evidence_dir=destination)).to_dict()
    assert destination.is_dir()
    import hashlib

    for case in report["cases"]:
        assert len(case["evidence"]) == 1
        reference = case["evidence"][0]
        path = destination / reference["path"]
        data = path.read_bytes()
        assert reference["bytes"] == len(data)
        assert reference["sha256"] == hashlib.sha256(data).hexdigest()
        assert json.loads(data)["case_id"] == case["case_id"]
        assert str(destination) not in data.decode()
    with pytest.raises(ValidationError):
        await module.AdapterContractSuite().run(object(), evidence_dir=destination)


@async_test
async def test_cancel_waits_for_real_case_cleanup_and_keeps_its_workspace(monkeypatch):
    module = api()
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    workspaces, completed = [], []

    async def case_runner(case_id, fixture, workspace):
        workspaces.append(workspace)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            assert workspace.is_dir()
            completed.append(case_id)

    monkeypatch.setattr(module, "_run_case", case_runner)
    observer = asyncio.create_task(module.AdapterContractSuite().run(object()))
    await entered.wait()
    observer.cancel()
    await cleaning.wait()
    observer.cancel()
    await asyncio.sleep(0)
    assert not observer.done()
    assert workspaces[0].is_dir()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await observer
    assert completed == ["K01"]
    assert not workspaces[0].exists()


@async_test
async def test_no_fixture_still_rejects_malformed_evidence_arguments():
    with pytest.raises(ValidationError):
        await api().AdapterContractSuite().run(evidence_dir=["private"])


@async_test
async def test_evidence_rejects_replaced_actual_case_directory(tmp_path, monkeypatch):
    module = api()

    async def case_runner(case_id, fixture, workspace):
        workspace.rename(workspace.with_name(f"{case_id}-replaced"))
        workspace.mkdir()
        return AdapterContractCaseResult(case_id, "passed", "verified")

    monkeypatch.setattr(module, "_run_case", case_runner)
    destination = tmp_path / "private-evidence"
    with pytest.raises(ValidationError):
        await module.AdapterContractSuite().run(object(), evidence_dir=destination)
    assert not (destination / "K01" / "result.json").exists()


@async_test
async def test_evidence_rejects_symlink_workspace_without_writing_target(tmp_path, monkeypatch):
    module = api()
    outside = tmp_path / "outside"
    outside.mkdir()

    async def case_runner(case_id, fixture, workspace):
        workspace.rmdir()
        workspace.symlink_to(outside, target_is_directory=True)
        return AdapterContractCaseResult(case_id, "passed", "verified")

    monkeypatch.setattr(module, "_run_case", case_runner)
    with pytest.raises(ValidationError):
        await module.AdapterContractSuite().run(
            object(), evidence_dir=tmp_path / "private-evidence"
        )
    assert not (outside / "result.json").exists()


@async_test
async def test_failed_owned_cleanup_keeps_original_owner_and_workspace_until_retry(monkeypatch):
    module = api()
    types = importlib.import_module("ralf_agent.adapter_contract_types")
    assert hasattr(types, "AdapterContractCleanupPending")
    from ralf_agent.errors import CloseIncomplete
    from ralf_agent.runtime_lifecycle import BuildContext
    from ralf_agent.types import Scope

    calls, workspaces = [], []

    class Failing:
        def close(self):
            calls.append("failing")
            if calls.count("failing") <= 2:
                raise RuntimeError("private-close-error")

    class Completed:
        def close(self):
            calls.append("completed")

    async def case_runner(case_id, fixture, workspace):
        workspaces.append(workspace)
        owner = BuildContext(None, "unused", Scope(), workspace, allow_async=True)
        owner.own(Failing())
        owner.own(Completed())

        async def cleanup():
            assert workspace.is_dir()
            await owner.cleanup_async()

        try:
            await cleanup()
        except Exception:
            raise types.AdapterContractCleanupPending(
                AdapterContractCaseResult(
                    case_id, "failed", "cleanup_failed", {"cleanup_complete": False}
                ),
                cleanup,
            ) from None

    monkeypatch.setattr(module, "_run_case", case_runner)
    suite = module.AdapterContractSuite()
    report = (await suite.run(object())).to_dict()
    assert report["failed"] == 1 and report["not_verified"] == 11
    assert suite.pending_cleanup
    assert workspaces[0].is_dir()
    with pytest.raises(ValidationError):
        await suite.run(object())
    with pytest.raises(CloseIncomplete) as failure:
        await suite.aclose()
    assert "private-close-error" not in json.dumps(failure.value.report)
    assert suite.pending_cleanup and workspaces[0].is_dir()
    await suite.aclose()
    assert not suite.pending_cleanup
    assert not workspaces[0].exists()
    assert calls == ["completed", "failing", "failing", "failing"]
    await suite.aclose()
    assert calls == ["completed", "failing", "failing", "failing"]
    assert report["status"] == "failed"


@async_test
async def test_cancelled_case_with_failed_cleanup_retains_original_retry(monkeypatch):
    module = api()
    types = importlib.import_module("ralf_agent.adapter_contract_types")
    assert hasattr(types, "AdapterContractCleanupPending")
    entered, released = asyncio.Event(), asyncio.Event()
    workspaces, cleaned = [], []

    async def case_runner(case_id, fixture, workspace):
        workspaces.append(workspace)

        async def cleanup():
            assert workspace.is_dir()
            cleaned.append(case_id)

        entered.set()
        try:
            await released.wait()
        finally:
            raise types.AdapterContractCleanupPending(
                AdapterContractCaseResult(case_id, "failed", "cleanup_failed"),
                cleanup,
            )

    monkeypatch.setattr(module, "_run_case", case_runner)
    suite = module.AdapterContractSuite()
    task = asyncio.create_task(suite.run(object()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert suite.pending_cleanup and workspaces[0].is_dir()
    await suite.aclose()
    assert cleaned == ["K01"] and not workspaces[0].exists()


@async_test
async def test_cleanup_observer_cancellation_waits_for_actual_exit(monkeypatch):
    module = api()
    types = importlib.import_module("ralf_agent.adapter_contract_types")
    assert hasattr(types, "AdapterContractCleanupPending")
    entered, release = asyncio.Event(), asyncio.Event()
    workspaces, completed = [], []

    async def case_runner(case_id, fixture, workspace):
        workspaces.append(workspace)

        async def cleanup():
            entered.set()
            await release.wait()
            assert workspace.is_dir()
            completed.append(case_id)

        raise types.AdapterContractCleanupPending(
            AdapterContractCaseResult(case_id, "failed", "cleanup_failed"),
            cleanup,
        )

    monkeypatch.setattr(module, "_run_case", case_runner)
    suite = module.AdapterContractSuite()
    await suite.run(object())
    closer = asyncio.create_task(suite.aclose())
    await entered.wait()
    closer.cancel()
    closer.cancel()
    await asyncio.sleep(0)
    assert not closer.done() and workspaces[0].is_dir()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closer
    assert completed == ["K01"]
    assert not suite.pending_cleanup and not workspaces[0].exists()
