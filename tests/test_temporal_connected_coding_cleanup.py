"""Failure capture must survive an unconfirmed original owner shutdown."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.test_temporal_connected_coding_integration import _cleanup_owned


@pytest.mark.parametrize("failure", [None, "assembly", "worker"])
def test_cleanup_preserves_recovery_resources_until_all_owned_workers_end(tmp_path, failure):
    events = []
    socket_path = tmp_path / "original.sock"
    socket_path.touch()

    async def close_assembly(**kwargs):
        events.append("assembly")
        if failure == "assembly":
            raise RuntimeError("original closure remains pending")

    class Process:
        pid = 12345
        returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            events.append("kill")

        def wait(self, timeout):
            events.append("wait")
            if failure == "worker":
                raise TimeoutError("actual process has not ended")
            self.returncode = -9
            return self.returncode

    async def execute(statement):
        events.append("drop")

    async def close_admin():
        events.append("admin")

    operation = _cleanup_owned(
        SimpleNamespace(aclose=close_assembly),
        [Process()],
        SimpleNamespace(close=lambda: events.append("socket")),
        socket_path,
        SimpleNamespace(execute=execute, close=close_admin),
        "original_schema",
        tmp_path,
    )
    if failure:
        with pytest.raises(AssertionError, match="Bounded owned fixture cleanup failed"):
            asyncio.run(operation)
        assert "drop" not in events and "socket" not in events
        assert socket_path.exists()
    else:
        asyncio.run(operation)
        assert "drop" in events and "socket" in events
        assert not socket_path.exists()
    assert "kill" in events and "wait" in events and "admin" in events
    receipt = json.loads((tmp_path / "cleanup-responsibility.json").read_text())
    assert receipt["all_workers_exited"] is (failure != "worker")
    assert receipt["schema_retained_for_recovery"] is (failure is not None)
