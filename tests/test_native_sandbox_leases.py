"""Local native-resource FD leases; never a RALF state machine."""

import os
import subprocess
import sys

import pytest

from ralf_agent.docker_sandbox_transport import NativeSandboxLease, lease_root
from ralf_agent.errors import RalfError


def test_second_real_process_refuses_held_native_invocation_and_can_acquire_after_exit(tmp_path):
    root = lease_root(str(tmp_path / "leases"))
    lease = NativeSandboxLease(root, "invocation")
    script = """import json,sys
from ralf_agent.docker_sandbox_transport import NativeSandboxLease
from ralf_agent.sandbox import SandboxUnavailable
try:
 value=NativeSandboxLease(json.loads(sys.argv[1]),'invocation')
except SandboxUnavailable:
 print('busy')
else:
 value.close();print('owned')
"""
    import json

    def call():
        return subprocess.run(
            [sys.executable, "-c", script, json.dumps(root)],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    try:
        assert call() == "busy"
    finally:
        lease.close()
    assert call() == "owned"
    assert (tmp_path / "leases/invocation.lock").is_file()


@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_native_invocation_lease_refuses_unsafe_file_aliases(tmp_path, alias):
    root = lease_root(str(tmp_path / "leases"))
    target = tmp_path / "target"
    target.write_text("")
    target.chmod(0o600)
    alias_path = tmp_path / "leases/invocation.lock"
    if alias == "hardlink":
        os.link(target, alias_path)
    else:
        alias_path.symlink_to(target)
    with pytest.raises((RalfError, OSError)):
        NativeSandboxLease(root, "invocation")


def test_native_lease_root_replacement_is_refused(tmp_path):
    root = lease_root(str(tmp_path / "leases"))
    (tmp_path / "leases").rename(tmp_path / "old")
    (tmp_path / "leases").mkdir(mode=0o700)
    with pytest.raises(RalfError):
        NativeSandboxLease(root, "invocation")
