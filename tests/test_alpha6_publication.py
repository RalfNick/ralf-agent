"""Publication accepts only a matching successful native gate and frozen bytes."""

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from tests import test_release_preflight

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
candidate = test_release_preflight.candidate


@pytest.fixture
def publication(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    path = ROOT / "tools/check_alpha6_publication.py"
    assert path.is_file(), "a4 must check qualification before publishing"
    spec = importlib.util.spec_from_file_location("check_alpha6_publication", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate_run():
    return {
        "id": 123,
        "run_attempt": 2,
        "repository": {"id": 1405169929, "full_name": "RalfNick/relf-agent"},
        "head_repository": {"id": 1405169929, "full_name": "RalfNick/relf-agent"},
        "head_sha": SHA,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/alpha6-release-gate.yml",
    }


def test_accepts_only_matching_completed_native_gate(publication):
    publication.verify_run(gate_run(), 123, 2, SHA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 124),
        ("run_attempt", 1),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_sha", "b" * 40),
        ("path", ".github/workflows/ci.yml"),
        ("path", ".github/workflows/alpha3-release-gate.yml"),
        ("path", ".github/workflows/alpha4-release-gate.yml"),
        ("path", ".github/workflows/alpha5-release-gate.yml"),
        ("repository", {"id": 9, "full_name": "RalfNick/relf-agent"}),
        ("head_repository", {"id": 9, "full_name": "someone/fork"}),
    ],
)
def test_rejects_unqualified_or_foreign_runs(publication, field, value):
    run = gate_run()
    run[field] = value
    with pytest.raises(RuntimeError, match="gate_run_mismatch"):
        publication.verify_run(run, 123, 2, SHA)


def test_rejects_mutable_checkout_identity(publication):
    with pytest.raises(RuntimeError, match="immutable_checkout_required"):
        publication.verify_run(gate_run(), 123, 2, "feat/m1-local-runtime")


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    spec = {
        "version": "0.1.0a6",
        "distribution_name": "relf-agent",
        "python_module": "relf_agent",
        "cli_name": "relf",
        "artifacts": {"a.whl": "wheel", "a.tar.gz": "sdist"},
        "tests": {"main": {"count": 311}, "related": {"count": 16}},
        "starter_cases": 2,
        "test_corrections": [],
    }
    tools = {
        "release_gate.py": "runner",
        "release_gate_manifest.json": "manifest",
        "release_gate_requirements.lock": "lock",
        "run_release_gate_linux.py": "wrapper",
    }
    (root / "matrix-input.json").write_text(
        json.dumps(
            {
                "tools": tools,
                "artifacts": spec["artifacts"],
                "native_required": True,
                "platform": "linux/amd64",
            }
        )
    )
    (root / "native-host.json").write_text(
        json.dumps(
            {
                "host": {"system": "Linux", "machine": "x86_64"},
                "docker": {"os": "linux", "architecture": "x86_64"},
            }
        )
    )
    rows = []
    for minor in ("3.11", "3.12", "3.13"):
        report = {
            "version": "0.1.0a6",
            "distribution_name": "relf-agent",
            "python_module": "relf_agent",
            "cli_name": "relf",
            "status": "passed_selected_scope",
            "phase": "complete",
            "artifacts": spec["artifacts"],
            "test_corrections": {},
            "runner_sha256": "runner",
            "manifest_sha256": "manifest",
            "requirements_sha256": "lock",
            "platform": {"system": "Linux", "machine": "x86_64", "python_minor": minor},
            "python": minor + ".1",
            "tests": {
                "main": {"tests": 311, "failures": 0, "errors": 0, "skipped": 0},
                "related": {"tests": 16, "failures": 0, "errors": 0, "skipped": 0},
            },
            "starter": {"cases": 2, "business_writes_per_case": 1},
            "linux_resources": {
                "memory_max": "2147483648",
                "memory_swap_max": "0",
                "cpu_max": "200000 100000",
                "memory_peak": 1000000,
                "memory_events": {"oom": 0, "oom_kill": 0},
            },
        }
        p = root / minor / "gate"
        p.mkdir(parents=True)
        (p / "report.json").write_text(json.dumps(report))
        rows.append({"python_minor": minor, "passed": True, "container_removed": True})
    (root / "matrix.json").write_text(json.dumps(rows))
    return root, spec, tools


def test_requires_all_three_native_reports_and_physical_cleanup(publication, evidence):
    root, spec, tools = evidence
    publication.verify_evidence(root, spec, tools)


@pytest.mark.parametrize(
    "drift",
    [
        "missing_python",
        "duplicate_python",
        "cleanup",
        "oom",
        "skipped",
        "manifest",
        "emulation",
        "foreign_tools",
    ],
)
def test_rejects_incomplete_or_mismatched_gate_evidence(publication, evidence, drift):
    root, spec, tools = evidence
    if drift in ("missing_python", "duplicate_python", "cleanup"):
        p = root / "matrix.json"
        data = json.loads(p.read_text())
        if drift == "missing_python":
            data.pop()
        elif drift == "duplicate_python":
            data[2] = copy.deepcopy(data[1])
        else:
            data[0]["container_removed"] = False
    elif drift == "emulation":
        p = root / "native-host.json"
        data = json.loads(p.read_text())
        data["host"]["machine"] = "arm64"
    elif drift == "foreign_tools":
        p = root / "matrix-input.json"
        data = json.loads(p.read_text())
        data["tools"]["release_gate.py"] = "other"
    else:
        p = root / "3.12/gate/report.json"
        data = json.loads(p.read_text())
        if drift == "oom":
            data["linux_resources"]["memory_events"]["oom"] = 1
        elif drift == "skipped":
            data["tests"]["main"]["skipped"] = 1
        else:
            data["manifest_sha256"] = "changed"
    p.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="gate_evidence_mismatch"):
        publication.verify_evidence(root, spec, tools)


def test_candidate_directory_has_only_the_two_exact_frozen_files(publication, tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    content = {"original.whl": b"wheel", "original.tar.gz": b"sdist"}
    for name, data in content.items():
        (root / name).write_bytes(data)
    expected = {n: hashlib.sha256(b).hexdigest() for n, b in content.items()}
    publication.verify_files(root, expected)
    (root / "unrelated.sqlite").write_bytes(b"private")
    with pytest.raises(RuntimeError, match="candidate_files_mismatch"):
        publication.verify_files(root, expected)
    (root / "unrelated.sqlite").unlink()
    (root / "original.whl").write_bytes(b"rebuilt")
    with pytest.raises(RuntimeError, match="candidate_files_mismatch"):
        publication.verify_files(root, expected)


@pytest.mark.parametrize("candidate", [("0.1.0a6", "relf-agent", "relf_agent")], indirect=True)
@pytest.mark.parametrize("drift", [None, "run", "cleanup", "bytes", "source_license"])
def test_publication_cli_composes_real_checks_before_handoff(
    publication, candidate, evidence, tmp_path, monkeypatch, drift
):
    source, wheel, sdist, spec = candidate
    root, gate_spec, _ = evidence
    spec.update({key: gate_spec[key] for key in ("tests", "starter_cases", "test_corrections")})
    spec["artifact_manifest_role"] = "external_delivery"
    tools_root = source / "tools"
    tools_root.mkdir()
    for name in ("release_gate.py", "run_release_gate_linux.py", "release_gate_requirements.lock"):
        shutil.copyfile(ROOT / "tools" / name, tools_root / name)
    manifest = tools_root / "release_gate_manifest.alpha6.json"
    manifest.write_text(json.dumps(spec))
    tools = {
        name: hashlib.sha256((tools_root / name).read_bytes()).hexdigest()
        for name in (
            "release_gate.py",
            "run_release_gate_linux.py",
            "release_gate_requirements.lock",
        )
    }
    tools["release_gate_manifest.json"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    inputs = root / "matrix-input.json"
    data = json.loads(inputs.read_text())
    data.update(tools=tools, artifacts=spec["artifacts"])
    inputs.write_text(json.dumps(data))
    for minor in ("3.11", "3.12", "3.13"):
        path = root / minor / "gate/report.json"
        data = json.loads(path.read_text())
        data.update(
            artifacts=spec["artifacts"],
            runner_sha256=tools["release_gate.py"],
            manifest_sha256=tools["release_gate_manifest.json"],
            requirements_sha256=tools["release_gate_requirements.lock"],
        )
        path.write_text(json.dumps(data))
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for path in (wheel, sdist):
        shutil.copyfile(path, incoming / path.name)
    run = gate_run()
    if drift == "run":
        run["conclusion"] = "failure"
    elif drift == "cleanup":
        path = root / "matrix.json"
        rows = json.loads(path.read_text())
        rows[0]["container_removed"] = False
        path.write_text(json.dumps(rows))
    elif drift == "bytes":
        (incoming / wheel.name).write_bytes(b"changed")
    elif drift == "source_license":
        (source / "LICENSE").write_text("changed")
    monkeypatch.setattr(publication, "HERE", tools_root)
    monkeypatch.setattr(publication, "fetch_run", lambda run_id: run)
    output = tmp_path / "handoff"
    code = publication.main(
        [
            "--candidate",
            str(incoming),
            "--evidence",
            str(root),
            "--output",
            str(output),
            "--run-id",
            "123",
            "--run-attempt",
            "2",
            "--checkout-sha",
            SHA,
        ]
    )
    if drift:
        assert code == 1
        assert not (output / "candidate").exists()
    else:
        assert code == 0
        receipt = json.loads((output / "qualification.json").read_text())
        assert receipt["status"] == "verified_alpha6_publication_input"
        assert "native AMD64 report" not in receipt["pending_external"]
        assert "remote CI" not in receipt["pending_external"]
        assert {p.name for p in (output / "candidate").iterdir()} == {wheel.name, sdist.name}
