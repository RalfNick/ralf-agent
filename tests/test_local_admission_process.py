"""Original SQLite root quota survives actual process death and unknown effects."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ralf_agent as r

WORKER = Path(__file__).with_name("local_admission_worker.py")


def environment():
    return {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(r.__file__).resolve().parent.parent),
        "PYTHONIOENCODING": "utf-8",
    }


def configure(directory, kind):
    if kind == "sdk":
        return
    profile = {
        "name": "business",
        "version": "1",
        "providers": {"default": {"adapter": "process-provider"}},
        "components": {
            "tools": {"adapter": "process-tools"},
            "admission_policy": {
                "adapter": "bounded",
                "config": {"deployment_id": "business", "max_active_root_runs": 1},
            },
        },
    }
    if kind == "json":
        (directory / "profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "default": {"name": "business", "version": "1"},
                    "profiles": [profile],
                }
            )
        )
    else:
        (directory / "profile.toml").write_text("""schema_version = 1
[default]
name = "business"
version = "1"
[[profiles]]
name = "business"
version = "1"
[profiles.providers.default]
adapter = "process-provider"
[profiles.components.tools]
adapter = "process-tools"
[profiles.components.admission_policy]
adapter = "bounded"
[profiles.components.admission_policy.config]
deployment_id = "business"
max_active_root_runs = 1
""")


def kill_ready(directory, mode, kind, locator):
    process = subprocess.Popen(
        [sys.executable, str(WORKER), str(directory), mode, kind],
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        path = directory / locator
        while not path.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"Original Worker exited before durable readiness: {stdout}\n{stderr}")
            if time.monotonic() >= deadline:
                pytest.fail("Original Worker did not persist approval readiness")
            time.sleep(0.01)
        proof = json.loads(path.read_text())
        assert proof["pid"] == process.pid and process.poll() is None
        process.kill()
        process.communicate(timeout=5)
        assert process.returncode == -signal.SIGKILL
        return proof
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def invoke(directory, mode, kind, expected_exit=0):
    process = subprocess.run(
        [sys.executable, str(WORKER), str(directory), mode, kind],
        env=environment(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == expected_exit, process.stdout + process.stderr
    return process


def proof(directory, name):
    return json.loads((directory / name).read_text())


def assert_origin(original, restored):
    assert restored["run_id"] == original["run_id"]
    assert restored["manifest"] == original["manifest"]
    assert restored["local_admission"] == original["local_admission"]
    assert restored["product_file"] == original["product_file"] == str(Path(r.__file__).resolve())


@pytest.mark.skipif(os.name == "nt", reason="Selected deployment requires POSIX SIGKILL")
@pytest.mark.parametrize("kind", ["sdk", "json", "toml"])
def test_approval_claim_survives_two_sigkills_then_original_recovery_releases_once(tmp_path, kind):
    configure(tmp_path, kind)
    original = kill_ready(tmp_path, "start", kind, "ready.json")
    assert original["holders"] == [original["run_id"]]
    invoke(tmp_path, "blocked", kind)
    blocked = proof(tmp_path, "blocked-proof.json")
    assert_origin(original, blocked)
    assert blocked["state"] == "waiting_approval" and blocked["holders"] == original["holders"]
    invoke(tmp_path, "foreign-refusal", kind)
    assert proof(tmp_path, "foreign-proof.json")["holders"] == []
    approved = kill_ready(tmp_path, "approve-hold", kind, "approved.json")
    assert approved["holders"] == original["holders"]
    assert not (tmp_path / "business-effects.jsonl").exists()
    invoke(tmp_path, "resume", kind)
    restored = proof(tmp_path, "success-proof.json")
    assert_origin(original, restored)
    assert restored["receipt"] == approved["receipt"]
    assert restored["tool_attempts"] == restored["dispatch_events"] == 1
    assert restored["holders"] == []
    assert restored["budget"] == {"limit": 4, "held": 0, "spent": 3}
    effects = [
        json.loads(line) for line in (tmp_path / "business-effects.jsonl").read_text().splitlines()
    ]
    assert effects == [{"effect_key": original["effect_key"], "value": "accepted"}]
    assert restored["effect_key"] == original["effect_key"]
    assert (tmp_path / "model-calls.txt").read_text().splitlines() == ["proposal", "final", "plain"]
    invoke(tmp_path, "resume", kind)
    assert proof(tmp_path, "success-proof.json") | {"pid": restored["pid"]} == restored
    assert len((tmp_path / "business-effects.jsonl").read_text().splitlines()) == 1


@pytest.mark.skipif(os.name == "nt", reason="Selected deployment requires POSIX process death")
@pytest.mark.parametrize("kind", ["sdk", "json", "toml"])
def test_effect_commit_process_death_and_terminal_unknown_retain_original_quota(tmp_path, kind):
    configure(tmp_path, kind)
    crashed = invoke(tmp_path, "unknown-start", kind, expected_exit=77)
    original = proof(tmp_path, "ready.json")
    crash = proof(tmp_path, "crash-ready.json")
    assert crashed.returncode == 77 and crash["run_id"] == original["run_id"]
    assert crash["effect_key"] == original["effect_key"]
    invoke(tmp_path, "unknown-recover", kind)
    restored = proof(tmp_path, "unknown-recover-proof.json")
    assert_origin(original, restored)
    assert restored["state"] == "cancelled" and restored["tool_status"] == "outcome_unknown"
    assert restored["holders"] == [original["run_id"]]
    assert restored["budget"]["held"] > 0
    invoke(tmp_path, "foreign-refusal", kind)
    assert proof(tmp_path, "foreign-proof.json")["holders"] == []
    effects = [
        json.loads(line) for line in (tmp_path / "business-effects.jsonl").read_text().splitlines()
    ]
    assert effects == [{"effect_key": original["effect_key"], "value": "accepted"}]
    assert (tmp_path / "model-calls.txt").read_text().splitlines() == ["proposal"]
