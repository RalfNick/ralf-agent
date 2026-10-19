"""Maintainer gate rejects false passes without running postponed SDK suites."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location("release_gate", ROOT / "tools/release_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_frozen_scope_never_selects_postponed_suites(gate):
    spec = gate.read_spec()
    assert spec["tests"]["main"]["count"] == 311
    assert spec["tests"]["related"]["count"] == 16
    assert spec["starter_cases"] == 2
    assert spec["deferred"] == ["function-fingerprint qualification", "S2"]
    assert len(spec["tests"]["main"]["deselect"]) == 1
    for phase in spec["tests"].values():
        assert all("fingerprint" not in p and "s2" not in p.lower() for p in phase["selectors"])


@pytest.mark.parametrize(
    ("system", "machine", "minor"),
    [("Linux", "aarch64", "3.11"), ("Linux", "x86_64", "3.13"), ("Darwin", "arm64", "3.12")],
)
def test_declared_platform_allows_execution_without_claiming_qualification(
    gate, system, machine, minor
):
    value = gate.check_platform(gate.read_spec(), system, machine, minor)
    assert value == {"system": system, "machine": machine, "python_minor": minor}


@pytest.mark.parametrize(
    ("system", "machine", "minor"),
    [("Windows", "AMD64", "3.12"), ("Darwin", "arm64", "3.11"), ("Linux", "x86_64", "3.14")],
)
def test_undeclared_platform_fails_before_install(gate, system, machine, minor):
    with pytest.raises(gate.GateError, match="platform_not_declared"):
        gate.check_platform(gate.read_spec(), system, machine, minor)


def test_collection_requires_exact_identities_even_when_count_matches(gate):
    phase = {"count": 2, "node_ids_sha256": identity(["tests/a.py::one", "tests/a.py::two"])}
    assert gate.check_collection("tests/a.py::one\ntests/a.py::two\n2 tests collected", phase)
    with pytest.raises(gate.GateError, match="collection_changed"):
        gate.check_collection("tests/a.py::one\ntests/a.py::replacement", phase)


@pytest.mark.parametrize(
    "text", ["", "tests/a.py::one\ntests/a.py::one", "tests/test_fingerprint.py::one"]
)
def test_empty_duplicate_or_postponed_collection_never_passes(gate, text):
    with pytest.raises(gate.GateError):
        gate.check_collection(text, {"count": 2, "node_ids_sha256": "invalid"})


def test_junit_needs_real_cases_and_zero_failure_error_or_skip(gate, tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="one"/></testsuite></testsuites>'
    )
    assert gate.check_junit(report, 1)["tests"] == 1


@pytest.mark.parametrize(
    "suite",
    [
        '<testsuite tests="1" failures="0" errors="0" skipped="1"><testcase><skipped/></testcase></testsuite>',
        '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase><failure/></testcase></testsuite>',
        '<testsuite tests="1" failures="0" errors="1" skipped="0"><testcase><error/></testcase></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
    ],
)
def test_failed_skipped_or_incomplete_junit_is_not_a_pass(gate, tmp_path, suite):
    report = tmp_path / "junit.xml"
    report.write_text(suite)
    with pytest.raises(gate.GateError, match="test_report_failed"):
        gate.check_junit(report, 1)


def test_wrong_artifact_rejected_without_extracting_or_installing(gate, tmp_path):
    wheel = tmp_path / "ralf_agent-0.1.0a1-py3-none-any.whl"
    sdist = tmp_path / "ralf_agent-0.1.0a1.tar.gz"
    wheel.write_bytes(b"different-wheel")
    sdist.write_bytes(b"different-sdist")
    target = tmp_path / "checks"
    with pytest.raises(gate.GateError, match="artifact_sha256_mismatch"):
        gate.prepare_artifacts(wheel, sdist, target, gate.read_spec())
    assert not target.exists()


def test_safe_extraction_rejects_escaping_path_before_writing(gate, tmp_path):
    import io
    import tarfile

    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo("ralf_agent-0.1.0a1/../../escaped.py")
        member.size = 1
        stream.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(gate.GateError, match="unsafe_sdist_member"):
        gate.extract_checks(archive, tmp_path / "checks", "0.1.0a1")
    assert not (tmp_path / "escaped.py").exists()


def test_standard_sdist_root_directory_and_required_inputs_are_accepted(gate, tmp_path):
    import io
    import tarfile

    archive = tmp_path / "valid.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        root = tarfile.TarInfo("ralf_agent-0.1.0a1")
        root.type = tarfile.DIRTYPE
        stream.addfile(root)
        for name in (
            "tests/context_crash_assertions.py",
            "tests/test_starter.py",
            "examples/support_journey.py",
        ):
            member = tarfile.TarInfo("ralf_agent-0.1.0a1/" + name)
            member.size = 1
            stream.addfile(member, io.BytesIO(b"x"))
    files = gate.extract_checks(archive, tmp_path / "checks", "0.1.0a1")
    assert len(files) == 3
    assert (tmp_path / "checks/tests/test_starter.py").read_bytes() == b"x"


def test_plan_is_read_only_and_preserves_postponed_status(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/release_gate.py"), "--plan"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["version"] == "0.1.0a1"
    assert "S2" in plan["deferred"]
    assert list(tmp_path.iterdir()) == []


def test_existing_evidence_is_never_overwritten(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    sentinel = output / "report.json"
    sentinel.write_text("original failure")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/release_gate.py"),
            "--wheel",
            "missing.whl",
            "--sdist",
            "missing.tar.gz",
            "--wheelhouse",
            str(tmp_path),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "output_already_exists"
    assert sentinel.read_text() == "original failure"


@pytest.mark.parametrize(
    "change", [{"memory_max": "max"}, {"cpu_max": "max 100000"}, {"memory_swap_max": "1"}]
)
def test_linux_gate_rejects_unbounded_or_different_resource_profile(gate, change):
    resources = {"memory_max": "2147483648", "memory_swap_max": "0", "cpu_max": "200000 100000"}
    resources.update(change)
    with pytest.raises(gate.GateError, match="linux_resource_limits_mismatch"):
        gate.check_linux_limits(resources)


@pytest.mark.parametrize("late", [False, True])
def test_failed_execution_is_persisted_and_never_reported_passed(gate, tmp_path, monkeypatch, late):
    def fail(*args):
        if late:
            args[2]["status"] = "passed_selected_scope"
        raise gate.GateError("intentional_failure")

    monkeypatch.setattr(gate, "execute", fail)
    output = tmp_path / "evidence"
    assert (
        gate.main(
            [
                "--wheel",
                "missing.whl",
                "--sdist",
                "missing.tar.gz",
                "--wheelhouse",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    result = json.loads((output / "report.json").read_text())
    assert result["status"] == "failed" and result["error"] == "intentional_failure"


@pytest.mark.parametrize("labels", [{}, {"ralf.release-gate": "someone-else"}])
def test_linux_wrapper_never_controls_another_owners_container(labels):
    spec = importlib.util.spec_from_file_location(
        "linux_release_gate", ROOT / "tools/run_release_gate_linux.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    with pytest.raises(RuntimeError, match="container_owner_mismatch"):
        wrapper.verify_owned({"Config": {"Labels": labels}}, "this-run")


@pytest.mark.parametrize("known", [True, False, None])
def test_uncertain_create_is_reconciled_or_stops_before_next_version(tmp_path, monkeypatch, known):
    spec = importlib.util.spec_from_file_location(
        "linux_release_gate", ROOT / "tools/run_release_gate_linux.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    states, removed, attempted = {}, [], []

    def fake_call(*args, **kwargs):
        if args[1:3] == ("image", "inspect"):
            return json.dumps([{"Architecture": "arm64", "Os": "linux"}])
        if args[1] == "create":
            name = args[args.index("--name") + 1]
            token = args[args.index("--label") + 1].split("=", 1)[1]
            attempted.append(name)
            states[name] = {
                "Id": name + "-id",
                "Config": {"Labels": {"ralf.release-gate": token}},
                "State": {"Running": False, "OOMKilled": False},
                "HostConfig": {"NetworkMode": "none"},
            }
            raise subprocess.TimeoutExpired(args, 45)
        if args[1] == "rm":
            removed.append(args[2])
            return args[2]
        raise AssertionError(args)

    def lookup(identifier, token):
        if known is None:
            return None
        if not known:
            raise RuntimeError("container_state_unknown")
        return states[identifier]

    monkeypatch.setattr(wrapper, "call", fake_call)
    monkeypatch.setattr(wrapper, "lookup_owned", lookup, raising=False)
    monkeypatch.setattr(
        wrapper.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "log", "stderr"),
    )
    wheel, sdist = tmp_path / "one.whl", tmp_path / "one.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    output = tmp_path / "matrix"
    assert (
        wrapper.main(
            [
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--wheelhouse",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    rows = json.loads((output / "matrix.json").read_text())
    if known:
        assert len(removed) == len(rows) == 3
        assert all(row["container_removed"] for row in rows)
    else:
        assert len(attempted) == len(rows) == 1 and not removed
        assert "cleanup_error" in rows[0]
    assert (output / "3.11/create-attempt.json").is_file()


@pytest.mark.parametrize("absent", [True, False])
def test_container_absence_requires_explicit_daemon_evidence(monkeypatch, absent):
    spec = importlib.util.spec_from_file_location(
        "linux_release_gate", ROOT / "tools/run_release_gate_linux.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    result = subprocess.CompletedProcess(
        [],
        1,
        "[]" if absent else "",
        "Error: No such object: owned" if absent else "daemon unavailable",
    )
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *a, **k: result)
    if absent:
        assert wrapper.lookup_owned("owned", "token") is None
    else:
        with pytest.raises(RuntimeError, match="container_state_unknown"):
            wrapper.lookup_owned("owned", "token")
