import asyncio
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def a2a_http_service(tmp_path, request):
    pytest.importorskip("uvicorn")
    source = Path(__file__).resolve().parents[1] / "src"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}/rpc"
    with (tmp_path / "http.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("a2a_http_fixture.py")),
                str(tmp_path),
                str(port),
                str(listener.fileno()),
                str(getattr(request, "param", 10000)),
            ],
            pass_fds=(listener.fileno(),),
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(source)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if (
                        httpx.get(
                            f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=0.2
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    time.sleep(0.01)
            else:
                log.seek(0)
                pytest.fail("Loopback A2A service failed: " + log.read())
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            listener.close()


def test_true_http_native_tasks_dedup_cancel_and_unknown_lookup(a2a_http_service):
    from ralf_agent.a2a import A2AClient, A2ARemoteError

    async def check():
        client = A2AClient(a2a_http_service, headers={"Authorization": "Bearer test-owner"})
        try:
            assert (await client.discover())["preferredTransport"] == "JSONRPC"
            first = await client.send_message("real-http", {"question": "你好"})
            task = first
            async with asyncio.timeout(3):
                while task["status"]["state"] != "completed":
                    await asyncio.sleep(0.01)
                    task = await client.get_task(first["id"])
            assert task["artifacts"][0]["parts"][0]["data"]["result"] == {
                "echo": {"question": "你好"}
            }
            assert (await client.send_message("real-http", {"question": "你好"}))["id"] == first[
                "id"
            ]
            assert (await client.get_by_message("real-http"))["id"] == first["id"]
            with pytest.raises(A2ARemoteError) as late:
                await client.cancel_task(first["id"], command_id="late")
            assert late.value.rpc_code == -32002
            second = await client.send_message("waiting", {"wait": True})
            await client.cancel_task(second["id"], command_id="cancel")
            async with asyncio.timeout(3):
                while (await client.get_task(second["id"]))["status"]["state"] != "canceled":  # noqa: ASYNC110 -- remote polling has no local completion event
                    await asyncio.sleep(0.01)
        finally:
            await client.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("a2a_http_service", [1], indirect=True)
def test_full_inbox_preserves_http_lookup_replay_and_cancellation(a2a_http_service, tmp_path):
    """P3-3 preparation: existing controls remain reachable at receipt capacity."""
    from ralf_agent.a2a import A2AClient, A2ARemoteError

    async def check():
        client = A2AClient(a2a_http_service, headers={"Authorization": "Bearer test-owner"})
        try:
            original = await client.send_message("held", {"wait_for_cancel": True})
            assert original["status"]["state"] in {"submitted", "working"}
            async with asyncio.timeout(3):
                while not (tmp_path / "provider-started").exists():  # noqa: ASYNC110 -- signal from the independent service process
                    await asyncio.sleep(0.01)
            with pytest.raises(A2ARemoteError) as full:
                await client.send_message("overflow", {"wait_for_cancel": True})
            assert full.value.rpc_code == -32603
            assert (await client.send_message("held", {"wait_for_cancel": True}))["id"] == original[
                "id"
            ]
            assert (await client.get_by_message("held"))["id"] == original["id"]
            assert (await client.get_task(original["id"]))["status"]["state"] in {
                "submitted",
                "working",
            }
            canceled = await client.cancel_task(original["id"], command_id="cancel-at-capacity")
            assert canceled["metadata"]["ralf"]["state"] == "cancelling"
            assert not (tmp_path / "provider-ended").exists()
            (tmp_path / "provider-release").touch()
            async with asyncio.timeout(3):
                while canceled["status"]["state"] != "canceled":  # noqa: ASYNC110 -- external HTTP authority has no local completion event
                    await asyncio.sleep(0.01)
                    canceled = await client.get_task(original["id"])
            assert (await client.get_by_message("held"))["status"]["state"] == "canceled"
            assert (await client.send_message("held", {"wait_for_cancel": True}))["id"] == original[
                "id"
            ]
            assert (tmp_path / "provider-ended").exists()
        finally:
            (tmp_path / "provider-release").touch()
            await client.aclose()

    asyncio.run(check())
    with sqlite3.connect(tmp_path / "inbox.db") as database:
        assert database.execute("SELECT count(*) FROM ralf_inbox").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "runs.db") as database:
        assert database.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
