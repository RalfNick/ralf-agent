"""Serial cached ARM64 Docker execution of release_gate.py; never pulls images."""

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent


def call(*args, timeout=45):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-1500:]}")
    return result.stdout.strip()


def verify_owned(info, token):
    if (info["Config"].get("Labels") or {}).get("ralf.release-gate") != token:
        raise RuntimeError("container_owner_mismatch")


def lookup_owned(identifier, token):
    result = subprocess.run(
        ["docker", "inspect", identifier], capture_output=True, text=True, timeout=45
    )
    if result.returncode:
        if result.stdout.strip() == "[]" and any(
            message in result.stderr.lower() for message in ("no such object", "no such container")
        ):
            return None
        raise RuntimeError("container_state_unknown")
    values = json.loads(result.stdout)
    if len(values) != 1:
        raise RuntimeError("container_state_unknown")
    verify_owned(values[0], token)
    return values[0]


def verify_report(report, spec, minor, inputs, artifacts):
    try:
        if artifacts != spec["artifacts"]:
            return False
        expected = {
            "status": "passed_selected_scope",
            "phase": "complete",
            "version": spec["version"],
            "artifacts": artifacts,
            "test_corrections": {
                rule["path"]: {key: rule[key] for key in ("before_sha256", "after_sha256")}
                for rule in spec.get("test_corrections", [])
            },
            "runner_sha256": inputs["release_gate.py"],
            "manifest_sha256": inputs["release_gate_manifest.json"],
            "requirements_sha256": inputs["release_gate_requirements.lock"],
            "platform": {"system": "Linux", "machine": "aarch64", "python_minor": minor},
            "tests": {
                name: {"tests": phase["count"], "failures": 0, "errors": 0, "skipped": 0}
                for name, phase in spec["tests"].items()
            },
            "starter": {"cases": spec["starter_cases"], "business_writes_per_case": 1},
        }
        actual = {name: report[name] for name in expected}
        if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(
            expected, sort_keys=True, allow_nan=False
        ):
            return False
        if not re.fullmatch(re.escape(minor) + r"\.\d+", report["python"]):
            return False
        resources = report["linux_resources"]
        if any(
            resources[name] != value
            for name, value in {
                "memory_max": "2147483648",
                "memory_swap_max": "0",
                "cpu_max": "200000 100000",
            }.items()
        ):
            return False
        peak = resources["memory_peak"]
        events = resources["memory_events"]
        if type(events) is not dict:
            return False
        return (
            type(peak) is int
            and 0 < peak <= 2147483648
            and all(
                type(events.get(name)) is int and events[name] == 0 for name in ("oom", "oom_kill")
            )
            and type(events.get("oom_group_kill", 0)) is int
            and events.get("oom_group_kill", 0) == 0
        )
    except (KeyError, TypeError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "sdist", "wheelhouse", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.output.resolve()
    if root.exists():
        parser.error("output_already_exists")
    root.mkdir(parents=True)
    spec = json.loads((HERE / "release_gate_manifest.json").read_text())
    inputs = root / "input"
    inputs.mkdir()
    gate = inputs / "gate"
    gate.mkdir()
    for name in (
        "release_gate.py",
        "run_release_gate_linux.py",
        "release_gate_manifest.json",
        "release_gate_requirements.lock",
    ):
        shutil.copy2(HERE / name, gate / name)
    for source in (args.wheel, args.sdist):
        shutil.copy2(source.resolve(), inputs / source.name)
    tool_inputs = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in gate.iterdir()
    }
    actual_artifacts = {
        source.name: hashlib.sha256((inputs / source.name).read_bytes()).hexdigest()
        for source in (args.wheel, args.sdist)
    }
    (root / "matrix-input.json").write_text(
        json.dumps(
            {
                "tools": tool_inputs,
                "artifacts": actual_artifacts,
                "host": {"system": platform.system(), "machine": platform.machine()},
                "platform": "linux/arm64",
                "artifact_source_commit": spec["artifact_source_commit"],
                "limits": spec["linux_container_limits"],
            },
            indent=2,
        )
        + "\n"
    )
    if actual_artifacts != spec["artifacts"]:
        error = {"phase": "artifact_verification", "error": "artifact_sha256_mismatch"}
        (root / "matrix-error.json").write_text(json.dumps(error, indent=2) + "\n")
        (root / "matrix.json").write_text("[]\n")
        print(json.dumps(error), flush=True)
        return 1
    results = []
    for minor, image in spec["linux_arm64_images"].items():
        output = root / minor
        output.mkdir()
        token = uuid.uuid4().hex
        name = "ralf-release-gate-" + minor.replace(".", "") + "-" + token[:8]
        attempted_create = False
        container, final, clean = None, None, False
        row = {"python_minor": minor, "passed": False, "container_name": name}
        try:
            info = json.loads(call("docker", "image", "inspect", image))[0]
            if info["Architecture"] != "arm64" or info["Os"] != "linux":
                raise RuntimeError("cached_image_platform_mismatch")
            (output / "image.json").write_text(json.dumps(info, indent=2) + "\n")
            (output / "create-attempt.json").write_text(
                json.dumps({"name": name, "owner_token": token, "image": image}, indent=2) + "\n"
            )
            attempted_create = True
            container = call(
                "docker",
                "create",
                "--pull=never",
                "--platform",
                "linux/arm64",
                "--name",
                name,
                "--label",
                "ralf.release-gate=" + token,
                "--cpus",
                "2",
                "--memory",
                "2g",
                "--memory-swap",
                "2g",
                "--pids-limit",
                "256",
                "--init",
                "--network",
                "none",
                "--workdir",
                "/work",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--mount",
                f"type=bind,src={inputs},dst=/input,readonly",
                "--mount",
                f"type=bind,src={args.wheelhouse.resolve()},dst=/wheels,readonly",
                "--mount",
                f"type=bind,src={output},dst=/output",
                image,
                "python",
                "-u",
                "/input/gate/release_gate.py",
                "--wheel",
                "/input/" + args.wheel.name,
                "--sdist",
                "/input/" + args.sdist.name,
                "--wheelhouse",
                "/wheels",
                "--output",
                "/output/gate",
            )
            created = json.loads(call("docker", "inspect", container))[0]
            verify_owned(created, token)
            (output / "created.json").write_text(json.dumps(created, indent=2) + "\n")
            call("docker", "start", container)
            print(json.dumps({"python": minor, "phase": "offline-gate-started"}), flush=True)
            code = int(call("docker", "wait", container, timeout=900))
            report = json.loads((output / "gate/report.json").read_text())
            row["passed"] = code == 0 and verify_report(
                report, spec, minor, tool_inputs, actual_artifacts
            )
            if not row["passed"]:
                raise RuntimeError("gate_report_identity_or_result_mismatch")
        except Exception as error:
            row["error"] = str(error)
        finally:
            if attempted_create:
                try:
                    final = lookup_owned(container or name, token)
                    if final is None:
                        if container is None:
                            raise RuntimeError("create_result_unknown_recheck_saved_name")
                        row["passed"] = False
                        clean = True
                    else:
                        container = final["Id"]
                        if final["State"]["Running"]:
                            call("docker", "stop", "--time", "15", container)
                            final = lookup_owned(container, token)
                        if final is None or final["State"]["Running"]:
                            raise RuntimeError("owned_container_not_stopped")
                        logs = subprocess.run(
                            ["docker", "logs", container],
                            capture_output=True,
                            text=True,
                            timeout=45,
                        )
                        (output / "container.log").write_text(logs.stdout + logs.stderr)
                        if logs.returncode:
                            raise RuntimeError("container_logs_unavailable")
                        (output / "exited.json").write_text(json.dumps(final, indent=2) + "\n")
                        row["passed"] = (
                            row["passed"]
                            and not final["State"]["OOMKilled"]
                            and final["HostConfig"]["NetworkMode"] == "none"
                        )
                        call("docker", "rm", container)
                        clean = True
                except Exception as error:
                    row["cleanup_error"] = str(error)
                    row["passed"] = False
            else:
                clean = True
            row["container_removed"] = container is not None and clean
            results.append(row)
            (root / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps(row), flush=True)
        if not clean:
            break  # Never start another version while ownership/stop is unconfirmed.
    return 0 if len(results) == 3 and all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
