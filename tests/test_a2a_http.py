import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def a2a_http_service(tmp_path):
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
