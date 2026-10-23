"""SIGKILL recovery uses the original approval time and original command receipts."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import relf_agent as r

WORKER = Path(__file__).with_name("local_deadline_worker.py")


def worker_environment():
    # Use this interpreter's actual product origin for both source and wheel
    # verification. No repository path assumption or credentials are inherited.
    return {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(r.__file__).resolve().parent.parent),
        "PYTHONIOENCODING": "utf-8",
    }


def configure(directory, kind, approval_seconds):
    if kind == "sdk":
        return
    profile = {
        "name": "business",
        "version": "1",
        "providers": {"default": {"adapter": "process-provider"}},
        "components": {
            "tools": {"adapter": "process-tools"},
            "execution_policy": {
                "adapter": "local-bounded",
                "config": {"approval_timeout_seconds": approval_seconds},
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
        (directory / "profile.toml").write_text(f"""schema_version = 1
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
[profiles.components.execution_policy]
adapter = "local-bounded"
[profiles.components.execution_policy.config]
approval_timeout_seconds = {approval_seconds}
""")


def kill_ready_worker(directory, mode, kind, seconds, ready_name):
    process = subprocess.Popen(
        [sys.executable, str(WORKER), str(directory), mode, kind, str(seconds)],
        env=worker_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        expires = time.monotonic() + 10
        ready = directory / ready_name
        while not ready.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"Original worker exited before readiness: {stdout}\n{stderr}")
            if time.monotonic() >= expires:
                pytest.fail("Original worker failed to reach durable approval readiness")
            time.sleep(0.01)
        proof = json.loads(ready.read_text())
        assert proof["pid"] == process.pid and process.poll() is None
        process.kill()
        process.communicate(timeout=5)
        assert process.returncode == -signal.SIGKILL
        return proof
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def resume(directory, kind, seconds):
    process = subprocess.run(
        [sys.executable, str(WORKER), str(directory), "resume", kind, str(seconds)],
        env=worker_environment(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads((directory / "proof.json").read_text())


def assert_original_facts(original, restored):
    assert restored["run_id"] == original["run_id"]
    assert restored["before_manifest"] == original["manifest"]
    assert restored["manifest"] == original["manifest"]
    assert restored["local_deadlines"] == original["local_deadlines"]
    assert restored["approval_requested_at"] == original["approval_requested_at"]
    assert restored["approval_expires_at"] == original["approval_expires_at"]
    assert restored["effect_key"] == original["effect_key"]
    assert restored["product_file"] == original["product_file"] == str(Path(r.__file__).resolve())


@pytest.mark.skipif(os.name == "nt", reason="Selected local host uses POSIX SIGKILL")
@pytest.mark.parametrize("kind", ["sdk", "json", "toml"])
def test_sigkill_cold_approval_expiry_cannot_gain_new_time_or_execute_business(tmp_path, kind):
    seconds = 2.0
    configure(tmp_path, kind, seconds)
    original = kill_ready_worker(tmp_path, "start", kind, seconds, "ready.json")
    assert original["scope"] == {"workspace": "deadline-process", "principal": "original-owner"}
    assert original["approval_expires_at"] == pytest.approx(
        original["approval_requested_at"] + seconds
    )
    remaining = original["approval_expires_at"] - time.time()
    if remaining > 0:
        time.sleep(remaining + 0.02)
    restored = resume(tmp_path, kind, seconds)
    assert_original_facts(original, restored)
    assert restored["state"] == "failed" and restored["error"]["code"] == "approval_expired"
    assert restored["receipt"]["apply_state"] == "rejected"
    assert restored["tool_attempts"] == restored["dispatch_events"] == 0
    assert restored["budget"] == {"limit": 4, "held": 0, "spent": 1}
    assert not (tmp_path / "business-effects.jsonl").exists()
    assert (tmp_path / "model-calls.txt").read_text().splitlines() == ["proposal"]
    repeated = resume(tmp_path, kind, seconds)
    assert repeated == restored


@pytest.mark.skipif(os.name == "nt", reason="Selected local host uses POSIX SIGKILL")
@pytest.mark.parametrize("kind", ["sdk", "json", "toml"])
def test_approval_commit_then_sigkill_resumes_once_with_original_effect_key(tmp_path, kind):
    seconds = 20.0
    configure(tmp_path, kind, seconds)
    original = kill_ready_worker(tmp_path, "start", kind, seconds, "ready.json")
    approved = kill_ready_worker(tmp_path, "approve-hold", kind, seconds, "approved.json")
    assert approved["run_id"] == original["run_id"]
    assert approved["receipt"]["apply_state"] == "applied"
    assert not (tmp_path / "business-effects.jsonl").exists()
    restored = resume(tmp_path, kind, seconds)
    assert_original_facts(original, restored)
    assert restored["state"] == "succeeded" and restored["error"] is None
    assert restored["receipt"] == approved["receipt"]
    assert restored["tool_attempts"] == restored["dispatch_events"] == 1
    assert restored["budget"] == {"limit": 4, "held": 0, "spent": 3}
    effects = [
        json.loads(line) for line in (tmp_path / "business-effects.jsonl").read_text().splitlines()
    ]
    assert len(effects) == 1 and effects[0]["value"] == "accepted"
    assert isinstance(effects[0]["effect_key"], str) and effects[0]["effect_key"]
    assert effects[0]["effect_key"] == original["effect_key"]
    assert (tmp_path / "model-calls.txt").read_text().splitlines() == ["proposal", "final"]
    assert resume(tmp_path, kind, seconds) == restored
    assert (tmp_path / "business-effects.jsonl").read_text().splitlines() == [
        json.dumps(effects[0])
    ]
