"""The installed reference executes real inventory tools and runtime gates."""

import asyncio
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from ralf_agent.types import ModelResponse, ToolCall


def run(**options):
    from ralf_agent.parent_completion_starter import run_reference

    return asyncio.run(run_reference(**options))


@pytest.mark.parametrize("kind", ["plan", "team"])
@pytest.mark.parametrize("model", [False, True])
def test_reference_real_receipts_gate_and_separate_verifier_child(tmp_path, kind, model):
    report = run(kind=kind, model_verification=model, db_path=tmp_path / "reference.sqlite")
    assert report["state"] == "succeeded"
    assert report["result"] == {"status": "completed", "total": 1275}
    assert report["parent_id"]
    assert report["gate_verdict"]["status"] == "accept"
    assert report["adopted_verdict"]["status"] == "accept"
    assert [tool["tool"] for tool in report["receipts"]] == ["inventory_lookup", "calculator"]
    assert all(tool["consumed_by"] for tool in report["receipts"])
    assert report["receipts"][1]["arguments"] == {"quantity": 3, "unit_price_cents": 425}
    assert report["receipts"][1]["result"] == {"total": 1275}
    assert [item["role"] for item in report["children"]] == (
        ["worker", "worker", "verifier"] if model else ["worker", "worker"]
    )
    if model:
        assert report["children"][-1]["key"] == "r0.verifier.verdict"
        assert report["children"][-1]["provider"] == "reviewer"
    assert report["budget"] == {
        "unit": "credits",
        "is_usd": False,
        "limit": 12,
        "spent": 7 if model else 6,
        "held": 0,
    }
    assert report["model_quality"] is None
    assert report["offline"] == {"business": True, "verification": True, "all": True}


@pytest.mark.parametrize("kind", ["plan", "team"])
@pytest.mark.parametrize(
    "task,expected,tools",
    [
        ({"dataset_id": "warehouse-a", "target": None, "quantity": 3}, "needs_input", []),
        ({"dataset_id": "warehouse-a", "target": "wire", "quantity": None}, "needs_input", []),
        (
            {"dataset_id": "warehouse-a", "target": "unknown-sku", "quantity": 3},
            "not_found",
            ["inventory_lookup"],
        ),
        (
            {"dataset_id": "warehouse-a", "target": "wire", "quantity": 41},
            "needs_input",
            ["inventory_lookup"],
        ),
    ],
)
def test_reference_stop_outcomes_are_verified_without_forbidden_tools(kind, task, expected, tools):
    report = run(kind=kind, task=task)
    assert report["state"] == "succeeded"
    assert report["result"] == {"status": expected, "total": None}
    assert report["gate_verdict"]["status"] == "accept"
    assert [tool["tool"] for tool in report["receipts"]] == tools
    assert report["model_quality"] is None


class FaultBusinessProvider:
    identity = {"kind": "reference-fault-fixture", "version": "1"}

    def __init__(self, fault):
        self.fault = fault

    async def complete(self, messages, tools):
        from ralf_agent.parent_completion_starter import OfflineInventoryProvider

        proposed = await OfflineInventoryProvider().complete(messages, tools)
        writer = any(tool["function"]["name"] == "calculator" for tool in tools)
        if writer and self.fault == "false-total" and proposed.output is not None:
            return ModelResponse({"status": "completed", "total": 999})
        if writer and self.fault == "wrong-price" and proposed.tool_calls:
            return ModelResponse(
                tool_calls=(ToolCall("calculator", {"quantity": 3, "unit_price_cents": 1}),)
            )
        return proposed


@pytest.mark.parametrize("kind", ["plan", "team"])
@pytest.mark.parametrize("fault", ["false-total", "wrong-price"])
def test_schema_valid_false_success_is_rejected_by_runtime_gate(kind, fault):
    report = run(kind=kind, model_verification=True, business_provider=FaultBusinessProvider(fault))
    assert report["state"] == "failed"
    assert report["gate_verdict"]["status"] == "reject"
    assert report["adopted_verdict"]["status"] == "reject"
    assert all(child["role"] == "worker" for child in report["children"])
    assert report["offline"] == {"business": False, "verification": True, "all": False}


def test_independent_borrowed_reviewer_can_tighten_a_pure_accept():
    class RejectReviewer:
        identity = {"kind": "borrowed-reference-reviewer", "version": "1"}

        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

        async def complete(self, messages, tools):
            assert not self.closed, "The reference must not close borrowed clients"
            assert tools == []
            source = json.loads(messages[1]["content"])
            return ModelResponse(
                {
                    "status": "reject",
                    "feedback": "Declared domain review rejected it",
                    "evidence_ids": [source["receipts"][0]["id"]],
                }
            )

    provider = RejectReviewer()
    report = run(model_verification=True, verification_provider=provider)
    assert report["gate_verdict"]["status"] == "accept"
    assert report["adopted_verdict"]["status"] == "reject"
    assert report["state"] == "failed"
    assert report["offline"] == {"business": True, "verification": False, "all": False}
    # Borrowed clients remain usable after all owned runtime resources close.
    assert run(model_verification=True, verification_provider=provider)["state"] == "failed"


def test_owned_temporary_directory_is_removed_after_detached_evidence(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    report = run(model_verification=True)
    assert report["state"] == "succeeded"
    assert list(tmp_path.iterdir()) == []
    assert json.loads(json.dumps(report))["receipts"][1]["result"] == {"total": 1275}


def test_default_does_not_read_environment_or_construct_network_clients(monkeypatch):
    import os
    import tempfile

    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline reference must not read env or construct network clients")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    report = run()
    assert report["state"] == "succeeded" and report["offline"]["all"]


def test_cli_returns_machine_readable_json_in_checkout_external_directory(tmp_path):
    # Source execution here uses only an explicit import path; the installed
    # counterpart below proves the wheel needs no checkout import paths.
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ralf_agent.parent_completion_starter",
            "--kind",
            "team",
            "--model-verification",
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == {"status": "completed", "total": 1275}


def test_reference_rejects_unknown_kind_before_running():
    from ralf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        run(kind="workflow")


def test_persistent_reference_reuses_completed_parent_and_exact_credit_receipt(tmp_path):
    options = {"kind": "plan", "model_verification": True, "db_path": tmp_path / "reference.sqlite"}
    first = run(**options)
    assert run(**options) == first
    assert first["budget"]["spent"] == 7


@pytest.fixture(scope="module")
def reference_wheel(tmp_path_factory):
    import httpx

    work = tmp_path_factory.mktemp("parent-completion-wheel")
    project = work / "project"
    project.mkdir()
    root = Path(__file__).resolve().parents[1]
    # Build outputs belong to this private staging snapshot, never the shared
    # checkout's build/ or egg-info while another owner verifies its freeze.
    shutil.copytree(
        root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
    )
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(root / name, project / name)

    def command(arguments, *, cwd):
        completed = subprocess.run(
            [str(argument) for argument in arguments],
            cwd=cwd,
            env={},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout
        return completed.stdout

    wheels = work / "wheels"
    command(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels],
        cwd=project,
    )
    environment = work / "environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    purelib = Path(
        command(
            [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], cwd=work
        ).strip()
    )
    (purelib / "dependencies.pth").write_text(
        str(Path(httpx.__file__).resolve().parent.parent) + "\n", encoding="utf-8"
    )
    command(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-cache-dir",
            next(wheels.glob("ralf_agent-*.whl")),
        ],
        cwd=work,
    )
    imported = Path(
        command([python, "-c", "import ralf_agent; print(ralf_agent.__file__)"], cwd=work).strip()
    )
    assert imported.is_relative_to(purelib)
    return python


@pytest.mark.parametrize("kind", ["plan", "team"])
def test_wheel_cli_runs_outside_checkout_without_import_path_or_credentials(
    tmp_path, reference_wheel, kind
):
    completed = subprocess.run(
        [
            str(reference_wheel),
            "-m",
            "ralf_agent.parent_completion_starter",
            "--kind",
            kind,
            "--model-verification",
            "--db-path",
            str(tmp_path / "reference.sqlite"),
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["state"] == "succeeded" and report["gate_verdict"]["status"] == "accept"
    assert report["result"] == {"status": "completed", "total": 1275}
    assert report["children"][-1]["provider"] == "reviewer"
    assert report["model_quality"] is None and report["offline"]["all"]
