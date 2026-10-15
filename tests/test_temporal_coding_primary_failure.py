import asyncio
import json
import stat

import pytest

from ralf_agent.errors import CloseIncomplete
from tests.temporal_coding_primary_failure import save_primary_failure


def test_primary_failure_saves_only_static_exception_and_task_frames(tmp_path):
    secret = "postgres://private-password-and-model-key"

    async def scenario():
        ready = asyncio.Event()

        async def waiting():
            await ready.wait()

        task = asyncio.create_task(waiting(), name=secret)
        await asyncio.sleep(0)
        error = CloseIncomplete(secret)
        error.args = (secret,)
        try:
            try:
                raise error
            except CloseIncomplete as original:
                assert save_primary_failure(tmp_path, original) is None
        finally:
            ready.set()
            await task
        assert task.done() and not task.cancelled()

    asyncio.run(scenario())
    path = tmp_path / "primary-failure.json"
    text = path.read_text()
    assert secret not in text
    value = json.loads(text)
    assert set(value) == {"error", "frames", "pending_tasks"}
    assert value["error"] == {
        "module": "ralf_agent.errors",
        "type": "CloseIncomplete",
        "code": "close_incomplete",
    }
    assert value["frames"][-1]["function"] == "scenario"
    assert all(set(frame) == {"file", "function", "line"} for frame in value["frames"])
    assert any(
        frame["function"] == "waiting"
        for entry in value["pending_tasks"]
        for frame in entry["frames"]
    )
    assert all(set(entry) == {"cancelling", "frames"} for entry in value["pending_tasks"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_diagnostic_save_failure_preserves_the_same_primary_exception(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("existing file")
    original = ValueError("secret exception message")
    with pytest.raises(ValueError) as caught:
        try:
            raise original
        except BaseException as error:
            save_primary_failure(blocked, error)
            raise
    assert caught.value is original
    assert blocked.read_text() == "existing file"
