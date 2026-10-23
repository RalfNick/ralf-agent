"""Offline installed-artifact gate for the frozen Local SDK Alpha scope.

Use --plan to inspect the scope. Execution requires explicit wheel, sdist,
wheelhouse and a NEW evidence directory. No SDK imports, builds or publication.
"""

import argparse
import email
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent


class GateError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_spec(path=None):
    return json.loads((path or HERE / "release_gate_manifest.json").read_text())


def check_platform(spec, system, machine, minor):
    if not any(
        p["system"] == system and p["machine"] == machine and minor in p["python"]
        for p in spec["platforms"]
    ):
        raise GateError("platform_not_declared")
    return {"system": system, "machine": machine, "python_minor": minor}


def check_linux_limits(resources):
    if (
        resources.get("memory_max") != "2147483648"
        or resources.get("memory_swap_max") != "0"
        or resources.get("cpu_max") != "200000 100000"
    ):
        raise GateError("linux_resource_limits_mismatch")


def linux_resources():
    root = Path("/sys/fs/cgroup")
    return {
        "memory_max": (root / "memory.max").read_text().strip(),
        "memory_swap_max": (root / "memory.swap.max").read_text().strip(),
        "cpu_max": (root / "cpu.max").read_text().strip(),
        "memory_peak": int((root / "memory.peak").read_text()),
        "memory_events": {
            k: int(v)
            for k, v in (line.split() for line in (root / "memory.events").read_text().splitlines())
        },
    }


def check_collection(text, phase):
    nodes = [
        line.strip() for line in text.splitlines() if line.startswith("tests/") and "::" in line
    ]
    if (
        len(nodes) != phase["count"]
        or len(nodes) != len(set(nodes))
        or any("fingerprint" in n.lower() or "s2_" in n.lower() for n in nodes)
        or digest(sorted(nodes)) != phase["node_ids_sha256"]
    ):
        raise GateError("collection_changed")
    return nodes


def check_junit(path, expected):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {
        k: sum(int(s.attrib[k]) for s in suites) for k in ("tests", "failures", "errors", "skipped")
    }
    if (
        counts != {"tests": expected, "failures": 0, "errors": 0, "skipped": 0}
        or len(list(root.iter("testcase"))) != expected
        or any(list(root.iter(tag)) for tag in ("failure", "error", "skipped"))
    ):
        raise GateError("test_report_failed")
    return counts


def distribution_name(spec):
    name = spec.get("distribution_name", "ralf-agent")
    if name not in ("ralf-agent", "relf-agent"):
        raise GateError("unsupported_distribution_name")
    return name


def extract_checks(sdist, target, version, distribution="ralf-agent"):
    prefix = f"{distribution.replace('-', '_')}-{version}/"
    contents, seen = {}, set()
    with tarfile.open(sdist, "r:gz") as stream:
        for member in stream:
            if member.isdir() and member.name == prefix.rstrip("/"):
                continue
            parts = PurePosixPath(member.name)
            if parts.is_absolute() or ".." in parts.parts or not member.name.startswith(prefix):
                raise GateError("unsafe_sdist_member")
            if member.isdir():
                continue
            if not member.isfile() or member.name in seen:
                raise GateError("unsafe_sdist_member")
            seen.add(member.name)
            name = member.name.removeprefix(prefix)
            if name.startswith("tests/") or name == "examples/support_journey.py":
                contents[name] = stream.extractfile(member).read()
    for name in (
        "tests/context_crash_assertions.py",
        "tests/test_starter.py",
        "examples/support_journey.py",
    ):
        if name not in contents:
            raise GateError("required_test_input_missing")
    for name, value in contents.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}


def apply_test_corrections(target, spec, original_tests):
    pending, applied = [], {}
    for rule in spec.get("test_corrections", []):
        name = rule["path"]
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] != "tests"
            or name in applied
            or original_tests.get(name) != rule["before_sha256"]
        ):
            raise GateError("test_correction_input_mismatch")
        path = target.joinpath(*relative.parts)
        if file_digest(path) != rule["before_sha256"]:
            raise GateError("test_correction_input_mismatch")
        text = path.read_text(encoding="utf-8")
        for edit in rule["replacements"]:
            if not edit["before"] or text.count(edit["before"]) != 1:
                raise GateError("test_correction_match_mismatch")
            text = text.replace(edit["before"], edit["after"], 1)
        data = text.encode("utf-8")
        if hashlib.sha256(data).hexdigest() != rule["after_sha256"]:
            raise GateError("test_correction_result_mismatch")
        pending.append((path, data))
        applied[name] = {key: rule[key] for key in ("before_sha256", "after_sha256")}
    for path, data in pending:
        path.write_bytes(data)
    return applied


def prepare_artifacts(wheel, sdist, target, spec):
    for artifact in (wheel, sdist):
        if spec["artifacts"].get(artifact.name) != file_digest(artifact):
            raise GateError("artifact_sha256_mismatch")
    distribution = distribution_name(spec)
    prefix = f"{distribution.replace('-', '_')}-{spec['version']}"
    with zipfile.ZipFile(wheel) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise GateError("duplicate_wheel_member")
        metadata = email.message_from_bytes(archive.read(prefix + ".dist-info/METADATA"))
        if metadata["Name"] != distribution or metadata["Version"] != spec["version"]:
            raise GateError("package_version_mismatch")
        products = {
            name.removeprefix("ralf_agent/"): hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("ralf_agent/") and Path(name).suffix in (".py", ".json")
        }
    if len(products) != spec["product_files"] or digest(products) != spec["product_tree_sha256"]:
        raise GateError("product_tree_mismatch")
    tests = extract_checks(sdist, target, spec["version"], distribution)
    if digest(tests) != spec["test_tree_sha256"]:
        raise GateError("test_tree_mismatch")
    corrections = apply_test_corrections(target, spec, tests)
    return {"products": products, "tests": tests, "test_corrections": corrections}


def command(args, log, cwd, env):
    with log.open("w") as output:
        process = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = process.wait(timeout=600)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
    if code:
        raise GateError(f"command_failed:{log.name}:{code}")


INSPECT_INSTALLED = """
import hashlib,importlib.metadata,importlib.util,json,pathlib,ralf_agent,sys,sysconfig
root=pathlib.Path(ralf_agent.__file__).resolve().parent
spec=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert root.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
assert ralf_agent.__version__==importlib.metadata.version(spec.get('distribution_name','ralf-agent'))==spec['version']
products={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json')}
actual=hashlib.sha256(json.dumps(products,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
assert len(products)==spec['product_files'] and actual==spec['product_tree_sha256']
assert all(importlib.util.find_spec(p) is None for p in ('temporalio','redis','psycopg','qdrant_client','torch','yaml','tiktoken'))
print(json.dumps({'version':ralf_agent.__version__,'path':str(root),'products':len(products),'minimal_install':True}))
"""

STARTER = """
import json,pathlib,sys
from tests.test_starter import test_wheel_starter_approves_and_recovers_once_without_repository_imports as check
root=pathlib.Path(sys.argv[1]);root.mkdir()
for crash in (False,True):
    case=root/('crash' if crash else 'normal');case.mkdir()
    check(case,(pathlib.Path(sys.executable),pathlib.Path(sys.executable).with_name('ralf')),crash)
print(json.dumps({'cases':2,'business_writes_per_case':1}))
"""


def execute(args, output, result, spec):
    result["platform"] = check_platform(
        spec,
        platform.system(),
        platform.machine(),
        f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    result["python"] = platform.python_version()
    if platform.system() == "Linux":
        check_linux_limits(linux_resources())
    result["os_release"] = (
        Path("/etc/os-release").read_text()
        if Path("/etc/os-release").exists()
        else platform.platform()
    )
    if not args.wheelhouse.is_dir():
        raise GateError("wheelhouse_missing")
    with tempfile.TemporaryDirectory(prefix="ralf-release-gate-") as directory:
        work = Path(directory).resolve()
        if work.is_relative_to(HERE.parent):
            raise GateError("work_directory_inside_checkout")
        checks = work / "checks"
        result["phase"] = "artifact_verification"
        inputs = prepare_artifacts(args.wheel, args.sdist, checks, spec)
        result["test_corrections"] = inputs["test_corrections"]
        (output / "input-files.json").write_text(json.dumps(inputs, indent=2) + "\n")
        lock = HERE / "release_gate_requirements.lock"
        result["requirements_sha256"] = file_digest(lock)
        requirements = work / "requirements.lock"
        requirements.write_text(
            lock.read_text()
            + f"\n{distribution_name(spec)} @ {args.wheel.as_uri()} --hash=sha256:{file_digest(args.wheel)}\n"
        )
        home = work / "home"
        home.mkdir()
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
        }
        venv = work / "venv"
        result["phase"] = "offline_install"
        command([sys.executable, "-m", "venv", str(venv)], output / "venv.log", work, env)
        python = str(venv / "bin/python")
        command(
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--only-binary=:all:",
                "--require-hashes",
                "--find-links",
                str(args.wheelhouse),
                "-r",
                str(requirements),
                "--report",
                str(output / "install-report.json"),
            ],
            output / "install.log",
            work,
            env,
        )
        command([python, "-m", "pip", "check"], output / "pip-check.log", work, env)
        command(
            [python, "-I", "-c", INSPECT_INSTALLED, str(output / "manifest.json")],
            output / "installed.json",
            work,
            env,
        )
        command([str(venv / "bin/ralf"), "--version"], output / "cli-version.log", work, env)
        command([python, "-m", "pip", "freeze"], output / "dependencies.txt", work, env)
        expected = {
            line.split("==")[0].lower().replace("_", "-"): line.split("==")[1].split()[0]
            for line in lock.read_text().splitlines()
            if "==" in line
        }
        actual = {
            line.split("==")[0].lower().replace("_", "-"): line.split("==")[1]
            for line in (output / "dependencies.txt").read_text().splitlines()
            if "==" in line
        }
        if actual != expected:
            raise GateError("dependency_versions_changed")
        result["tests"] = {}
        for name, phase in spec["tests"].items():
            result["phase"] = name
            base = [
                python,
                "-I",
                "-m",
                "pytest",
                "-q",
                "-W",
                "error",
                "-p",
                "no:cacheprovider",
                "-c",
                "/dev/null",
                "--rootdir=" + str(checks),
                *phase["selectors"],
                *("--deselect=" + p for p in phase["deselect"]),
            ]
            collection = output / f"{name}-collection.log"
            command([*base, "--collect-only"], collection, checks, env)
            nodes = check_collection(collection.read_text(), phase)
            (output / f"{name}-nodes.json").write_text(json.dumps(nodes, indent=2) + "\n")
            report = output / f"{name}.xml"
            command(
                [*base, "--junitxml=" + str(report), "--basetemp=" + str(work / name)],
                output / f"{name}.log",
                checks,
                env,
            )
            result["tests"][name] = check_junit(report, phase["count"])
        result["phase"] = "starter"
        command(
            [python, "-c", STARTER, str(work / "starter")],
            output / "starter.log",
            checks,
            dict(env, PYTHONPATH=str(checks)),
        )
        smoke = json.loads((output / "starter.log").read_text())
        if smoke != {"cases": spec["starter_cases"], "business_writes_per_case": 1}:
            raise GateError("starter_result_mismatch")
        result["starter"] = smoke
        result["warning_policy"] = {
            "main_related": "error",
            "starter_subprocesses": "original default",
        }
        if platform.system() == "Linux":
            result["linux_resources"] = linux_resources()
            if any(result["linux_resources"]["memory_events"][key] for key in ("oom", "oom_kill")):
                raise GateError("linux_oom_observed")
        result["phase"] = "complete"
        result["status"] = "passed_selected_scope"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--manifest", type=Path, default=HERE / "release_gate_manifest.json")
    for name in ("wheel", "sdist", "wheelhouse", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args(argv)
    spec = read_spec(args.manifest)
    if args.plan:
        print(json.dumps(spec, indent=2))
        return 0
    if any(getattr(args, name) is None for name in ("wheel", "sdist", "wheelhouse", "output")):
        parser.error("--wheel, --sdist, --wheelhouse and --output are required")
    for name in ("wheel", "sdist", "wheelhouse", "output"):
        setattr(args, name, getattr(args, name).resolve())
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(json.dumps({"status": "failed", "error": "output_already_exists"}))
        return 2
    start = time.monotonic()
    result = {
        "status": "failed",
        "phase": "setup",
        "version": spec["version"],
        "deferred": spec["deferred"],
        "artifacts": spec["artifacts"],
        "manifest_sha256": file_digest(args.manifest),
        "runner_sha256": file_digest(Path(__file__).resolve()),
        "public_upload": False,
    }
    (args.output / "manifest.json").write_text(json.dumps(spec, indent=2) + "\n")
    try:
        execute(args, args.output, result, spec)
    except Exception as error:
        result["status"] = "failed"
        result["error"] = str(error)
        result["error_type"] = type(error).__name__
    finally:
        result["wall_seconds"] = time.monotonic() - start
        (args.output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    return 0 if result["status"] == "passed_selected_scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
