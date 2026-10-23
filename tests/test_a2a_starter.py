import ast
import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import pytest

from relf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel

installed_wheel = _installed_wheel


def test_default_a2a_starter_is_installed_and_authentication_is_explicit(tmp_path):
    project = create_starter(tmp_path / "service", template="a2a")
    assert project.template == "a2a"
    source = (tmp_path / "service/agent_app/runtime.py").read_text()
    assert "RALF_A2A_TOKEN" in source
    assert "LocalA2AService" in source
    assert "OPENAI_API_KEY" not in source
    ast.parse(source)


@contextmanager
def serve(project, python, port):
    env = {"PATH": os.environ.get("PATH", ""), "RALF_A2A_TOKEN": "local-test-owner"}
    with (project / "service.log").open("w") as log:
        process = subprocess.Popen(
            [str(python), "-m", "agent_app", "serve", "--port", str(port)],
            cwd=project,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if (
                        client.get(
                            f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=0.2
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    time.sleep(0.01)
            else:
                pytest.fail("Starter startup failed: " + (project / "service.log").read_text())
        yield
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("installed", [False, True])
def test_real_source_and_installed_starter_run_replay_restart_and_explicit_auth(
    tmp_path, installed_wheel, installed
):
    pytest.importorskip("uvicorn")
    from relf_agent import A2AClient, SQLiteStore

    python = installed_wheel[0] if installed else sys.executable
    project = tmp_path / "service"
    create_starter(project, template="a2a")
    rejected = subprocess.run(
        [str(python), "-m", "agent_app", "serve"],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rejected.returncode == 2
    assert "RALF_A2A_TOKEN" in rejected.stderr
    assert not (project / ".ralf").exists()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    async def request():
        client = A2AClient(
            f"http://127.0.0.1:{port}/rpc", headers={"Authorization": "Bearer local-test-owner"}
        )
        try:
            task = await client.send_message("first", "hello")
            async with asyncio.timeout(5):
                while task["status"]["state"] != "completed":  # noqa: ASYNC110 -- remote polling
                    await asyncio.sleep(0.01)
                    task = await client.get_task(task["id"])
            assert task["artifacts"][0]["parts"][0]["data"]["result"] == {"echo": "hello"}
            assert (await client.send_message("first", "hello"))["id"] == task["id"]
            return task
        finally:
            await client.aclose()

    with serve(project, python, port):
        first = asyncio.run(request())
    with serve(project, python, port):
        second = asyncio.run(request())
        assert first == second
    with SQLiteStore(project / ".ralf/runs.sqlite", readonly=True) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert store.budget(first["id"])["spent"] == 1
