"""Verify the reviewed Docker 29.0.1 seccomp delta using local files only.

Usage: python tools/verify_codex_seccomp.py OFFICIAL_BASELINE INSTALLED_PROFILE
Success certifies byte integrity and the reviewed delta, not environment admission.
This utility never starts Docker, Codex, networking, or a task.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

BASELINE_SHA256 = "01536f1d1df938ae611eba20d6349e0de7a99b6ecdee1549427a0b01b8301e28"
PROFILE_SHA256 = "569e7aa0a4d8ed2b0bfada839187309d880c21350c36eaa2b55f15c0c85b41aa"


def _exact_rule(syscall: str, index: int, value: int) -> dict:
    return {
        "names": [syscall],
        "action": "SCMP_ACT_ALLOW",
        "args": [{"index": index, "value": value, "op": "SCMP_CMP_EQ"}],
    }


def verify_profiles(baseline_path: Path, profile_path: Path) -> dict:
    """Return a finite integrity result; caller-supplied digests are never accepted."""
    try:
        baseline_bytes = baseline_path.read_bytes()
        profile_bytes = profile_path.read_bytes()
    except OSError:
        return {"verified": False, "error": "input_unreadable"}
    if hashlib.sha256(baseline_bytes).hexdigest() != BASELINE_SHA256:
        return {"verified": False, "error": "baseline_sha256_mismatch"}
    # The pinned digest authenticates the baseline's JSON and structure.
    baseline = json.loads(baseline_bytes)
    try:
        profile = json.loads(profile_bytes)
    except (ValueError, UnicodeError):
        return {"verified": False, "error": "invalid_profile_json"}
    additions = [
        _exact_rule("clone", 0, 0x70020011),
        _exact_rule("unshare", 0, 0x10000000),
        *(
            _exact_rule("mount", 3, flags)
            for flags in (6, 10, 14, 0x8C000, 0xC0EDD000, 0xD000, 0x4C000, 0x209027)
        ),
        {"names": ["pivot_root"], "action": "SCMP_ACT_ALLOW"},
        _exact_rule("umount2", 1, 2),
    ]
    expected = copy.deepcopy(baseline)
    expected["syscalls"].extend(additions)
    if profile != expected:
        return {"verified": False, "error": "profile_delta_mismatch"}
    if hashlib.sha256(profile_bytes).hexdigest() != PROFILE_SHA256:
        return {"verified": False, "error": "profile_sha256_mismatch"}
    return {
        "verified": True,
        "baseline_sha256": BASELINE_SHA256,
        "profile_sha256": PROFILE_SHA256,
        "added_rules": len(additions),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    result = verify_profiles(args.baseline, args.profile)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
