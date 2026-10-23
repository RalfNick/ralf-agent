import asyncio
import json
import stat

import pytest

from relf_agent.errors import CloseIncomplete
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
        "module": "relf_agent.errors",
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
    assert all(
        set(entry) == {"cancelling", "frames", "await_frames"} for entry in value["pending_tasks"]
    )
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


def test_failure_diagnostic_identifies_nested_wait_without_resuming_owned_task(tmp_path):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()
        resumed = []

        async def original_sdk_read():
            entered.set()
            await finish.wait()
            resumed.append(True)

        async def original_fence_leaf():
            await original_sdk_read()

        async def original_coding_close():
            await original_fence_leaf()

        task = asyncio.create_task(original_coding_close())
        await entered.wait()
        try:
            save_primary_failure(tmp_path, CloseIncomplete("private payload"))
            value = json.loads((tmp_path / "primary-failure.json").read_text())
            entry = next(
                entry
                for entry in value["pending_tasks"]
                if any(frame["function"] == "original_coding_close" for frame in entry["frames"])
            )
            assert [frame["function"] for frame in entry["await_frames"]][:3] == [
                "original_coding_close",
                "original_fence_leaf",
                "original_sdk_read",
            ]
            assert all(
                set(frame) == {"file", "function", "line"} for frame in entry["await_frames"]
            )
            assert not resumed and not task.done() and task.cancelling() == 0
        finally:
            finish.set()
            await task
        assert resumed == [True]

    asyncio.run(scenario())


def test_failure_diagnostic_prioritizes_exact_owned_task_in_bounded_snapshot(tmp_path):
    async def scenario():
        finish = asyncio.Event()
        tasks = [asyncio.create_task(finish.wait()) for _ in range(40)]

        async def owned_stop():
            await finish.wait()

        original = asyncio.create_task(owned_stop())
        await asyncio.sleep(0)
        try:
            save_primary_failure(tmp_path, TimeoutError(), owned_tasks=(original, None))
            pending = json.loads((tmp_path / "primary-failure.json").read_text())["pending_tasks"]
            assert len(pending) == 32
            assert pending[0]["await_frames"][0]["function"] == "owned_stop"
            assert (
                sum(
                    frame["function"] == "owned_stop"
                    for item in pending
                    for frame in item["await_frames"]
                )
                == 1
            )
            assert all(not task.done() and task.cancelling() == 0 for task in [original, *tasks])
        finally:
            finish.set()
            await asyncio.gather(original, *tasks)

    asyncio.run(scenario())


def test_failure_diagnostic_bounds_deep_wait_chain(tmp_path):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def nested(depth):
            if depth:
                await nested(depth - 1)
            else:
                entered.set()
                await finish.wait()

        task = asyncio.create_task(nested(40))
        await entered.wait()
        try:
            save_primary_failure(tmp_path, TimeoutError(), owned_tasks=(task,))
            pending = json.loads((tmp_path / "primary-failure.json").read_text())["pending_tasks"]
            assert len(pending[0]["await_frames"]) == 16
            assert all(frame["function"] == "nested" for frame in pending[0]["await_frames"])
            assert not task.done() and task.cancelling() == 0
        finally:
            finish.set()
            await task

    asyncio.run(scenario())
