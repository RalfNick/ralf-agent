"""Verify frozen Alpha 7 bytes and native qualification; never upload or rebuild."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

import release_gate as gate
import release_preflight
import run_release_gate_linux as linux

REPOSITORY = "RalfNick/relf-agent"
REPOSITORY_ID = 1405169929
HERE = Path(__file__).resolve().parent


def verify_run(run, run_id, attempt, checkout_sha):
    if not re.fullmatch(r"[0-9a-f]{40}", checkout_sha):
        raise RuntimeError("immutable_checkout_required")
    expected = {
        "id": run_id,
        "run_attempt": attempt,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_sha": checkout_sha,
        "path": ".github/workflows/alpha7-release-gate.yml",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise RuntimeError("gate_run_mismatch")
    for key in ("repository", "head_repository"):
        repo = run.get(key) or {}
        if repo.get("id") != REPOSITORY_ID or repo.get("full_name") != REPOSITORY:
            raise RuntimeError("gate_run_mismatch")


def verify_files(directory, expected):
    paths = list(directory.iterdir())
    if (
        {path.name for path in paths} != set(expected)
        or any(path.is_symlink() or not path.is_file() for path in paths)
        or any(gate.file_digest(path) != expected[path.name] for path in paths)
    ):
        raise RuntimeError("candidate_files_mismatch")


def verify_evidence(root, spec, tools):
    def read(name):
        return json.loads((root / name).read_text())

    rows = read("matrix.json")
    inputs = read("matrix-input.json")
    native = read("native-host.json")
    if (
        len(rows) != 3
        or {row["python_minor"] for row in rows} != {"3.11", "3.12", "3.13"}
        or any(
            row.get("passed") is not True or row.get("container_removed") is not True
            for row in rows
        )
        or inputs.get("tools") != tools
        or inputs.get("artifacts") != spec["artifacts"]
        or inputs.get("platform") != "linux/amd64"
        or inputs.get("native_required") is not True
        or native["host"]["system"] != "Linux"
        or native["host"]["machine"] not in ("amd64", "x86_64")
        or native["docker"]["os"] != "linux"
        or native["docker"]["architecture"] not in ("amd64", "x86_64")
    ):
        raise RuntimeError("gate_evidence_mismatch")
    for row in rows:
        minor = row["python_minor"]
        if not linux.verify_report(
            read(minor + "/gate/report.json"),
            spec,
            minor,
            tools,
            spec["artifacts"],
            "linux/amd64",
        ):
            raise RuntimeError("gate_evidence_mismatch")


def fetch_run(run_id):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("github_read_token_required")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise RuntimeError("gate_run_response_too_large")
    return json.loads(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "evidence", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--checkout-sha", required=True)
    args = parser.parse_args(argv)
    if args.run_id <= 0 or args.run_attempt <= 0:
        parser.error("positive run id and attempt required")
    try:
        manifest = HERE / "release_gate_manifest.alpha7.json"
        spec = gate.read_spec(manifest)
        if (
            spec["version"] != "0.1.0a7"
            or spec.get("distribution_name") != "relf-agent"
            or spec.get("python_module") != "relf_agent"
            or spec.get("cli_name") != "relf"
            or spec.get("artifact_manifest_role") != "external_delivery"
        ):
            raise RuntimeError("frozen_alpha7_manifest_required")
        verify_run(fetch_run(args.run_id), args.run_id, args.run_attempt, args.checkout_sha)
        tools = {
            name: gate.file_digest(HERE / name)
            for name in (
                "release_gate.py",
                "run_release_gate_linux.py",
                "release_gate_requirements.lock",
            )
        }
        tools["release_gate_manifest.json"] = gate.file_digest(manifest)
        verify_evidence(args.evidence, spec, tools)
        verify_files(args.candidate, spec["artifacts"])
        result = release_preflight.prepare(
            args.candidate / "relf_agent-0.1.0a7-py3-none-any.whl",
            args.candidate / "relf_agent-0.1.0a7.tar.gz",
            HERE.parent,
            spec,
            args.output,
        )
        result.update(
            status="verified_alpha7_publication_input",
            gate_run_id=args.run_id,
            gate_run_attempt=args.run_attempt,
            checkout_sha=args.checkout_sha,
            verified_external=["native AMD64 report", "remote CI"],
            pending_external=[
                item
                for item in result["pending_external"]
                if item not in ("native AMD64 report", "remote CI")
            ],
        )
        (args.output / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0
    except Exception as error:
        # Never print a request, environment or response body containing credentials.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error)
                    if isinstance(error, RuntimeError)
                    else "publication_check_failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
