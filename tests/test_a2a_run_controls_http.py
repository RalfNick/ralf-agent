"""Installed/source HTTP process restart preserves original controls and effects."""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from ralf_agent.a2a import A2AClient
from tests.test_a2a_run_controls import wait_state, writes


@contextmanager
def http_process(tmp_path, uncertain):
    pytest.importorskip("uvicorn")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}/rpc"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
        + os.pathsep
        + str(Path(__file__).resolve().parents[1]),
    }
    log_path = tmp_path / f"service-{port}.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("a2a_controls_http_fixture.py")),
                str(tmp_path),
                str(listener.fileno()),
                "uncertain" if uncertain else "approval",
            ],
            pass_fds=(listener.fileno(),),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if (
                        httpx.get(
                            f"http://127.0.0.1:{port}/.well-known/agent-card.json",
                            timeout=0.2,
                            trust_env=False,
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    time.sleep(0.01)
            else:
                log.seek(0)
                pytest.fail("Owned HTTP control service startup failed: " + log.read())
            yield A2AClient(url, headers={"Authorization": "Bearer owner"}), process
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            listener.close()


@pytest.mark.parametrize("uncertain", [False, True])
def test_actual_http_controls_restart_replay_and_single_business_write(tmp_path, uncertain):
    async def run():
        state = "waiting_reconciliation" if uncertain else "waiting_approval"
        with http_process(tmp_path, uncertain) as (client, first):
            try:
                task = await client.send_message("original", "change")
                waiting = await wait_state(client, task["id"], state)
                if uncertain:
                    assert writes(tmp_path) == 1
                else:
                    target = waiting["metadata"]["ralf"]["pending"][0]
                    assert writes(tmp_path) == 0
                assert (await client.get_by_message("original"))["id"] == task["id"]
            finally:
                await client.aclose()
        assert_closed(tmp_path, first)
        with http_process(tmp_path, uncertain) as (client, replacement):
            try:
                assert (await client.send_message("original", "change"))["id"] == task["id"]
                assert (await client.get_task(task["id"]))["metadata"]["ralf"]["state"] == state
                if uncertain:
                    page = await client.get_events(task["id"], limit=1000)
                    action_id = next(
                        record["event"]["data"]["action_id"]
                        for record in page["events"]
                        if record["event"]["kind"] == "effect_unknown"
                    )
                    resumed = await client.resume_task(task["id"])
                    assert resumed["id"] == task["id"]
                    receipt = await client.reconcile_task(
                        task["id"], action_id, {"changed": True}, command_id="control"
                    )
                else:
                    receipt = await client.approve_task(
                        task["id"], target["action_id"], target["digest"], command_id="control"
                    )
                await wait_state(client, task["id"], "succeeded")
                if uncertain:
                    repeated = await client.reconcile_task(
                        task["id"], action_id, {"changed": True}, command_id="control"
                    )
                else:
                    repeated = await client.approve_task(
                        task["id"], target["action_id"], target["digest"], command_id="control"
                    )
                assert repeated == receipt
                assert writes(tmp_path) == 1
            finally:
                await client.aclose()
        assert_closed(tmp_path, replacement)

    asyncio.run(run())


def assert_closed(directory, process):
    # Uvicorn re-raises captured SIGTERM after graceful shutdown. Neither that
    # exit status nor process death substitutes for the actual close evidence.
    assert process.returncode in {0, -signal.SIGTERM}
    assert json.loads((directory / f"shutdown-{process.pid}.json").read_text()) == {
        "service_closed": True,
        "engine_closed": True,
        "active_drives": 0,
        "active_threads": 0,
    }
