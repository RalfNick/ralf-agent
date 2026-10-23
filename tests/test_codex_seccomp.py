"""Offline integrity checks; these do not admit or execute an environment."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "src/relf_agent/_codex_coding_seccomp.json"
VERIFIER = ROOT / "tools/verify_codex_seccomp.py"
BASELINE_SHA256 = "01536f1d1df938ae611eba20d6349e0de7a99b6ecdee1549427a0b01b8301e28"
PROFILE_SHA256 = "569e7aa0a4d8ed2b0bfada839187309d880c21350c36eaa2b55f15c0c85b41aa"


@pytest.fixture
def baseline(tmp_path):
    # Restore the independently pinned vendor serialization (tabs, no final newline).
    # The literal source digest makes this fixture independent of a changed asset.
    original = json.loads(PROFILE.read_bytes())
    original["syscalls"] = original["syscalls"][:-12]
    raw = json.dumps(original, indent="\t").encode()
    assert hashlib.sha256(raw).hexdigest() == BASELINE_SHA256
    path = tmp_path / "official-default.json"
    path.write_bytes(raw)
    return path


def invoke(baseline, profile):
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(baseline), str(profile)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def assert_rejected(result, error):
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout) == {"verified": False, "error": error}


def test_offline_verifier_accepts_exact_pinned_original_and_modified_profile(baseline):
    assert hashlib.sha256(PROFILE.read_bytes()).hexdigest() == PROFILE_SHA256
    result = invoke(baseline, PROFILE)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "verified": True,
        "baseline_sha256": BASELINE_SHA256,
        "profile_sha256": PROFILE_SHA256,
        "added_rules": 12,
    }


def test_offline_verifier_rejects_changed_official_baseline(baseline):
    baseline.write_bytes(baseline.read_bytes() + b"\n")
    assert_rejected(invoke(baseline, PROFILE), "baseline_sha256_mismatch")


@pytest.mark.parametrize(
    "mutation",
    ["injected_rule", "removed_baseline_rule", "changed_clone_flags", "changed_default_action"],
)
def test_offline_verifier_rejects_unreviewed_policy_changes(baseline, tmp_path, mutation):
    policy = copy.deepcopy(json.loads(PROFILE.read_bytes()))
    if mutation == "injected_rule":
        policy["syscalls"].append({"names": ["setns"], "action": "SCMP_ACT_ALLOW"})
    elif mutation == "removed_baseline_rule":
        del policy["syscalls"][0]
    elif mutation == "changed_clone_flags":
        policy["syscalls"][-12]["args"][0]["value"] = 17
    else:
        policy["defaultAction"] = "SCMP_ACT_ALLOW"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(policy, indent=2) + "\n")
    assert_rejected(invoke(baseline, path), "profile_delta_mismatch")


def test_offline_verifier_rejects_profile_byte_tamper_even_when_json_is_equal(baseline, tmp_path):
    path = tmp_path / "reserialized.json"
    path.write_bytes(PROFILE.read_bytes() + b"\n")
    assert_rejected(invoke(baseline, path), "profile_sha256_mismatch")


def test_offline_verifier_rejects_malformed_profile(baseline, tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text("{invalid")
    assert_rejected(invoke(baseline, path), "invalid_profile_json")


def test_offline_verifier_reports_missing_input_without_traceback(baseline, tmp_path):
    result = invoke(baseline, tmp_path / "missing.json")
    assert_rejected(result, "input_unreadable")
    assert not result.stderr
