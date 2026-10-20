"""A retained fixture may release its client socket only after its loop/Workers end."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.temporal_fixture_resources import RetainedConnections


@pytest.mark.parametrize("live", ["loop", "worker", None])
def test_retained_connection_teardown_requires_stopped_loop_and_workers(tmp_path, live):
    loop = asyncio.new_event_loop()
    if live != "loop":
        loop.close()
    running = live == "worker"
    worker = SimpleNamespace(poll=lambda: None if running else 0)
    calls = []

    class Connection:
        closed = False

        async def close(self):
            assert loop.is_closed() and worker.poll() is not None
            calls.append("client-closed")
            self.closed = True

    connection = Connection()
    pool = RetainedConnections()
    pool.retain(connection, loop, [worker], tmp_path)
    original = {"schema_retained": True, "assembly_close_succeeded": False}
    (tmp_path / "cleanup.json").write_text(json.dumps(original))
    try:
        if live:
            with pytest.raises(RuntimeError):
                pool.finish()
            assert calls == [] and not connection.closed
        else:
            pool.finish()
            assert connection.closed and calls == ["client-closed"]
        assert json.loads((tmp_path / "cleanup.json").read_text()) == original
    finally:
        if not loop.is_closed():
            loop.close()
        running = False
        pool.finish()
    assert connection.closed and calls == ["client-closed"]
    pool.finish()
    assert calls == ["client-closed"]
