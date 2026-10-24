"""Maintainer gate rejects false passes without running postponed SDK suites."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tomllib
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


def test_frozen_local_scope_keeps_separate_service_qualification(gate):
    spec = gate.read_spec()
    assert spec["tests"]["main"]["count"] == 311
    assert spec["tests"]["related"]["count"] == 16
    assert spec["starter_cases"] == 2
    assert spec["deferred"] == []
    assert spec["separate_qualification"]["S2"]["version"] == "0.1.0a2.dev19"
    assert spec["separate_qualification"]["S2"]["new_artifact_qualification"] is False
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


def test_plan_is_read_only_and_reports_current_candidate(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/release_gate.py"), "--plan"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["version"] == "0.1.0a2"
    assert "remote CI" in plan["not_qualified"]
    assert list(tmp_path.iterdir()) == []


def test_default_manifest_preserves_original_alpha2_after_new_source_versions(gate):
    current = gate.read_spec()
    original = json.loads((ROOT / "tools/release_gate_manifest.alpha1.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert current["version"] == "0.1.0a2"
    assert project["version"] == "0.1.0a7"
    assert set(current["artifacts"]) == {
        "ralf_agent-0.1.0a2-py3-none-any.whl",
        "ralf_agent-0.1.0a2.tar.gz",
    }
    assert original["version"] == "0.1.0a1"
    assert original["artifacts"] == {
        "ralf_agent-0.1.0a1-py3-none-any.whl": "a736993b941213945ed3309de1fc7ed69e7c5ad5033f69b24ce35b8c1c341aee",
        "ralf_agent-0.1.0a1.tar.gz": "bdf626bcee84678395b90a9c2b5bd5815a7c14188131b645b7f5ac337229fd63",
    }
    assert current["tests"] == original["tests"]
    assert current["product_tree_sha256"] != original["product_tree_sha256"]
    assert current["artifact_source_kind"] == "release_worktree"
    assert current["artifact_source_commit"] == "8e09ec79328e719074b14a656a5bf8f15e5a61ff"


def test_alpha2_idle_fixture_correction_is_exact_and_keeps_original_artifacts(gate, tmp_path):
    spec = gate.read_spec()
    rules = spec["test_corrections"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["path"] == "tests/test_agent_sessions.py"
    current = (ROOT / "tests/fixtures/release_gate_alpha2_agent_sessions.txt").read_bytes()
    assert hashlib.sha256(current).hexdigest() == rule["after_sha256"]
    original = current.decode()
    for edit in rule["replacements"]:
        assert original.count(edit["after"]) == 1
        original = original.replace(edit["after"], edit["before"], 1)
    original = original.encode()
    assert hashlib.sha256(original).hexdigest() == rule["before_sha256"]
    target = tmp_path / rule["path"]
    target.parent.mkdir()
    target.write_bytes(original)
    applied = gate.apply_test_corrections(tmp_path, spec, {rule["path"]: rule["before_sha256"]})
    assert target.read_bytes() == current
    assert applied[rule["path"]] == {
        "before_sha256": rule["before_sha256"],
        "after_sha256": rule["after_sha256"],
    }


def test_alpha2_initial_gate_manifest_remains_available_as_original_evidence(gate):
    path = ROOT / "tools/release_gate_manifest.alpha2-original.json"
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "f8396887f5d010e1052fc56bb9951aa518276269322361304004435af679bbd0"
    )
    original = json.loads(path.read_text())
    current = gate.read_spec()
    assert current["gate_revision"] == 2
    assert original["test_corrections"] == []
    assert current["artifacts"] == original["artifacts"]
    assert current["tests"] == original["tests"]
    assert current["test_tree_sha256"] == original["test_tree_sha256"]


@pytest.mark.parametrize("workflow", ["alpha1-release-gate.yml", "alpha1-stage-candidate.yml"])
def test_historical_alpha_workflows_keep_original_tools_and_products(workflow):
    text = (ROOT / ".github/workflows" / workflow).read_text()
    assert "ref: 0b9b6c9682c40285d91994cd831aa93d7e814bf1" in text
    assert "ref: ${{ github.sha }}" not in text


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
    stage_declared_gate(wrapper, tmp_path, (wheel, sdist), monkeypatch)
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


@pytest.fixture
def linux_wrapper():
    spec = importlib.util.spec_from_file_location(
        "linux_release_gate", ROOT / "tools/run_release_gate_linux.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    return wrapper


@pytest.fixture
def worker_inputs():
    return {
        name: hashlib.sha256((ROOT / "tools" / name).read_bytes()).hexdigest()
        for name in (
            "release_gate.py",
            "run_release_gate_linux.py",
            "release_gate_manifest.json",
            "release_gate_requirements.lock",
        )
    }


@pytest.fixture
def worker_report(gate, worker_inputs):
    spec = gate.read_spec()
    return {
        "status": "passed_selected_scope",
        "phase": "complete",
        "version": spec["version"],
        "artifacts": spec["artifacts"].copy(),
        "test_corrections": {
            entry["path"]: {key: entry[key] for key in ("before_sha256", "after_sha256")}
            for entry in spec.get("test_corrections", [])
        },
        "runner_sha256": worker_inputs["release_gate.py"],
        "manifest_sha256": worker_inputs["release_gate_manifest.json"],
        "requirements_sha256": worker_inputs["release_gate_requirements.lock"],
        "platform": {"system": "Linux", "machine": "aarch64", "python_minor": "3.11"},
        "python": "3.11.17",
        "tests": {
            name: {"tests": value["count"], "failures": 0, "errors": 0, "skipped": 0}
            for name, value in spec["tests"].items()
        },
        "starter": {"cases": 2, "business_writes_per_case": 1},
        "linux_resources": {
            "memory_max": "2147483648",
            "memory_swap_max": "0",
            "cpu_max": "200000 100000",
            "memory_peak": 1024,
            "memory_events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0},
        },
    }


def test_worker_report_must_match_current_gate_request(
    linux_wrapper, gate, worker_inputs, worker_report
):
    assert linux_wrapper.verify_report(
        worker_report, gate.read_spec(), "3.11", worker_inputs, gate.read_spec()["artifacts"]
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("artifacts",), {"different.whl": "wrong"}),
        (("runner_sha256",), "wrong"),
        (("manifest_sha256",), "wrong"),
        (("requirements_sha256",), "wrong"),
        (("status",), "failed"),
        (("phase",), "main"),
        (("version",), "0.1.0.dev120"),
        (("platform", "machine"), "x86_64"),
        (("platform", "system"), "Darwin"),
        (("platform", "python_minor"), "3.12"),
        (("python",), "3.12.15"),
        (("tests", "main", "skipped"), 1),
        (("tests", "related", "tests"), 0),
        (("starter", "cases"), 1),
        (("starter", "business_writes_per_case"), True),
        (("linux_resources", "memory_max"), "max"),
        (("linux_resources", "memory_swap_max"), "1"),
        (("linux_resources", "cpu_max"), "max 100000"),
        (("linux_resources", "memory_events", "oom_kill"), 1),
        (("linux_resources", "memory_events", "oom_group_kill"), 1),
        (("linux_resources", "memory_peak"), True),
        (("linux_resources",), None),
        (("linux_resources", "memory_peak"), 0),
        (("linux_resources", "memory_peak"), -1),
        (("linux_resources", "memory_peak"), 2147483649),
        (("linux_resources", "memory_peak"), float("nan")),
        (("linux_resources", "memory_events"), []),
        (("linux_resources", "memory_events", "oom"), False),
        (("linux_resources", "memory_events", "oom_group_kill"), False),
    ],
)
def test_passed_worker_report_with_mismatched_identity_or_results_is_rejected(
    linux_wrapper, gate, worker_inputs, worker_report, path, value
):
    target = worker_report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not linux_wrapper.verify_report(
        worker_report, gate.read_spec(), "3.11", worker_inputs, gate.read_spec()["artifacts"]
    )


@pytest.mark.parametrize("requested_platform", ["linux/arm64", "linux/amd64"])
@pytest.mark.parametrize("mismatch", ["architecture", "artifacts", "cached_image", None])
def test_matrix_binds_selected_platform_images_and_reports(
    linux_wrapper, worker_report, tmp_path, monkeypatch, mismatch, requested_platform
):
    containers = {}
    architecture = requested_platform.split("/")[1]
    machine = "x86_64" if architecture == "amd64" else "aarch64"
    other_machine = "aarch64" if architecture == "amd64" else "x86_64"
    removed = []

    def call(*args, **kwargs):
        if args[1:3] == ("image", "inspect"):
            assert args[3:5] == ("--platform", requested_platform)
            image_architecture = "wrong" if mismatch == "cached_image" else architecture
            return json.dumps([{"Architecture": image_architecture, "Os": "linux"}])
        if args[1] == "create":
            assert args[args.index("--platform") + 1] == requested_platform
            assert len(removed) == len(containers)  # Previous version finished and was removed.
            assert args[args.index("--cpus") + 1] == "2"
            assert args[args.index("--memory") + 1] == "2g"
            assert args[args.index("--memory-swap") + 1] == "2g"
            assert args[args.index("--network") + 1] == "none"
            name = args[args.index("--name") + 1]
            token = args[args.index("--label") + 1].split("=", 1)[1]
            output = next(
                a.split("src=", 1)[1].split(",dst=", 1)[0] for a in args if "dst=/output" in a
            )
            from copy import deepcopy

            report = deepcopy(worker_report)
            report["platform"] = {
                "system": "Linux",
                "machine": other_machine if mismatch == "architecture" else machine,
                "python_minor": Path(output).name,
            }
            report["python"] = Path(output).name + ".17"
            dest = Path(output) / "gate"
            dest.mkdir()
            (dest / "report.json").write_text(json.dumps(report))
            containers[name] = {
                "Id": name,
                "Config": {"Labels": {"ralf.release-gate": token}},
                "State": {"Running": False, "OOMKilled": False},
                "HostConfig": {"NetworkMode": "none"},
            }
            return name
        if args[1] == "inspect":
            return json.dumps([containers[args[2]]])
        if args[1] == "wait":
            return "0"
        if args[1] == "rm":
            removed.append(args[2])
            return ""
        if args[1] == "start":
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(linux_wrapper, "call", call)
    monkeypatch.setattr(linux_wrapper, "lookup_owned", lambda name, token: containers[name])
    monkeypatch.setattr(
        linux_wrapper.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "log", ""),
    )
    wheel, sdist = tmp_path / "one.whl", tmp_path / "one.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    if mismatch != "artifacts":
        declared = stage_declared_gate(linux_wrapper, tmp_path, (wheel, sdist), monkeypatch)
        worker_report["artifacts"] = declared["artifacts"]
        worker_report["manifest_sha256"] = hashlib.sha256(
            (linux_wrapper.HERE / "release_gate_manifest.json").read_bytes()
        ).hexdigest()
    output = tmp_path / "matrix"
    code = linux_wrapper.main(
        [
            "--wheel",
            str(wheel),
            "--sdist",
            str(sdist),
            "--wheelhouse",
            str(tmp_path),
            "--output",
            str(output),
            "--platform",
            requested_platform,
        ]
    )
    assert code == (0 if mismatch is None else 1)
    rows = json.loads((output / "matrix.json").read_text())
    if mismatch in ("architecture", None):
        assert len(rows) == 3 and all(
            row["passed"] == (mismatch is None) and row["container_removed"] for row in rows
        )
    elif mismatch == "cached_image":
        assert len(rows) == 3 and not containers
        assert all(row["error"] == "cached_image_platform_mismatch" for row in rows)
    else:
        assert rows == [] and not containers
        assert (
            json.loads((output / "matrix-error.json").read_text())["error"]
            == "artifact_sha256_mismatch"
        )
    provenance = json.loads((output / "matrix-input.json").read_text())
    assert provenance["platform"] == requested_platform
    assert (
        provenance["tools"]["run_release_gate_linux.py"]
        == hashlib.sha256((ROOT / "tools/run_release_gate_linux.py").read_bytes()).hexdigest()
    )


@pytest.fixture
def correction_case(tmp_path):
    original, corrected = b"one\n", b"two\n"
    path = tmp_path / "tests/test_case.py"
    path.parent.mkdir()
    path.write_bytes(original)
    rule = {
        "path": "tests/test_case.py",
        "before_sha256": hashlib.sha256(original).hexdigest(),
        "after_sha256": hashlib.sha256(corrected).hexdigest(),
        "replacements": [{"before": "one", "after": "two"}],
    }
    return path, rule, {rule["path"]: rule["before_sha256"]}


def test_frozen_test_correction_requires_exact_before_and_after(gate, tmp_path, correction_case):
    path, rule, original = correction_case
    applied = gate.apply_test_corrections(tmp_path, {"test_corrections": [rule]}, original)
    assert path.read_bytes() == b"two\n"
    assert applied == {rule["path"]: {key: rule[key] for key in ("before_sha256", "after_sha256")}}


@pytest.mark.parametrize("change", ["source", "before", "after", "matches", "escape", "unlisted"])
def test_test_correction_drift_fails_without_rewriting_inputs(
    gate, tmp_path, correction_case, change
):
    path, rule, original = correction_case
    if change == "source":
        path.write_bytes(b"source drift\n")
    elif change == "before":
        rule["before_sha256"] = "wrong"
    elif change == "after":
        rule["after_sha256"] = "wrong"
    elif change == "matches":
        rule["replacements"][0]["before"] = "absent"
    elif change == "escape":
        rule["path"] = "../escape.py"
    else:
        original.clear()
    before = path.read_bytes()
    with pytest.raises(gate.GateError):
        gate.apply_test_corrections(tmp_path, {"test_corrections": [rule]}, original)
    assert path.read_bytes() == before
    assert not (tmp_path.parent / "escape.py").exists()


def stage_declared_gate(wrapper, tmp_path, artifacts, monkeypatch):
    """Declare fake artifacts only in isolated lifecycle unit tests, never real QA."""
    import shutil

    target = tmp_path / "unit-gate"
    target.mkdir()
    for name in (
        "release_gate.py",
        "run_release_gate_linux.py",
        "release_gate_manifest.json",
        "release_gate_requirements.lock",
    ):
        shutil.copy2(ROOT / "tools" / name, target / name)
    spec = json.loads((target / "release_gate_manifest.json").read_text())
    spec["artifacts"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (target / "release_gate_manifest.json").write_text(json.dumps(spec, indent=2) + "\n")
    monkeypatch.setattr(wrapper, "HERE", target)
    return spec


def test_linux_wrapper_stages_selected_manifest_without_replacing_default(
    linux_wrapper, gate, tmp_path, monkeypatch
):
    wheel = tmp_path / "candidate.whl"
    sdist = tmp_path / "candidate.tar.gz"
    wheel.write_bytes(b"declared wheel")
    sdist.write_bytes(b"declared sdist")
    selected = gate.read_spec()
    selected["version"] = "0.1.0a3"
    selected["artifacts"] = {p.name: gate.file_digest(p) for p in (wheel, sdist)}
    manifest = tmp_path / "selected-manifest.json"
    manifest.write_text(json.dumps(selected))
    historical = (linux_wrapper.HERE / "release_gate_manifest.json").read_bytes()

    def no_docker(*args, **kwargs):
        raise RuntimeError("Docker intentionally unavailable in unit test")

    monkeypatch.setattr(linux_wrapper, "call", no_docker)
    out = tmp_path / "evidence"
    assert (
        linux_wrapper.main(
            [
                "--manifest",
                str(manifest),
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--wheelhouse",
                str(tmp_path),
                "--output",
                str(out),
            ]
        )
        == 1
    )
    assert (out / "input/gate/release_gate_manifest.json").read_bytes() == manifest.read_bytes()
    assert (linux_wrapper.HERE / "release_gate_manifest.json").read_bytes() == historical
    assert all(not row["passed"] for row in json.loads((out / "matrix.json").read_text()))


def test_worker_report_cannot_borrow_original_identity_for_other_actual_artifacts(
    linux_wrapper, gate, worker_inputs, worker_report
):
    assert not linux_wrapper.verify_report(
        worker_report, gate.read_spec(), "3.11", worker_inputs, {"other.whl": "different"}
    )


@pytest.mark.parametrize(
    ("system", "host_arch", "daemon_os", "daemon_arch", "allowed"),
    [
        ("Linux", "x86_64", "linux", "x86_64", True),
        ("Linux", "x86_64", "linux", "amd64", True),
        ("Darwin", "arm64", "linux", "amd64", False),
        ("Linux", "aarch64", "linux", "amd64", False),
        ("Linux", "x86_64", "linux", "aarch64", False),
        ("Linux", "x86_64", "windows", "amd64", False),
    ],
)
def test_native_gate_requires_matching_linux_host_and_daemon(
    linux_wrapper, monkeypatch, system, host_arch, daemon_os, daemon_arch, allowed
):
    monkeypatch.setattr(linux_wrapper.platform, "system", lambda: system)
    monkeypatch.setattr(linux_wrapper.platform, "machine", lambda: host_arch)
    monkeypatch.setattr(
        linux_wrapper,
        "call",
        lambda *a, **k: json.dumps({"OSType": daemon_os, "Architecture": daemon_arch}),
    )
    if allowed:
        result = linux_wrapper.verify_native_host("linux/amd64")
        assert result["host"] == {"system": "Linux", "machine": "x86_64"}
        assert result["docker"] == {"os": daemon_os, "architecture": daemon_arch}
    else:
        with pytest.raises(RuntimeError, match="native_.*_mismatch"):
            linux_wrapper.verify_native_host("linux/amd64")


def test_require_native_cli_records_rejection_before_any_docker_operation(
    linux_wrapper, tmp_path, monkeypatch
):
    monkeypatch.setattr(linux_wrapper.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(linux_wrapper.platform, "machine", lambda: "arm64")

    def forbidden(*args, **kwargs):
        pytest.fail("No Docker operation is allowed after a mismatched native host")

    monkeypatch.setattr(linux_wrapper, "call", forbidden)
    wheel, sdist = tmp_path / "one.whl", tmp_path / "one.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    stage_declared_gate(linux_wrapper, tmp_path, (wheel, sdist), monkeypatch)
    output = tmp_path / "native-rejected"
    assert (
        linux_wrapper.main(
            [
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--wheelhouse",
                str(tmp_path),
                "--output",
                str(output),
                "--platform",
                "linux/amd64",
                "--require-native",
            ]
        )
        == 1
    )
    assert json.loads((output / "matrix.json").read_text()) == []
    assert (
        json.loads((output / "matrix-error.json").read_text())["error"]
        == "native_host_platform_mismatch"
    )
