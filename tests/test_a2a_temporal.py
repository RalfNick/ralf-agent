"""Actual two HTTP processes, two execution workers and shared durable receipts."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from ralf_agent.a2a import A2AClient, A2AError
from ralf_agent.postgres_handoff import PostgresInbox
from ralf_agent.temporal import replay_temporal_history

from .test_temporal_service import system

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal Service and PostgreSQL",
)


@contextmanager
def http_process(tmp_path, engine, *, crash=False):
    pytest.importorskip("uvicorn")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    log_path = tmp_path / f"http-{port}.log"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        "RALF_TEST_POSTGRES_DSN": os.environ["RALF_TEST_POSTGRES_DSN"],
        "RALF_TEST_TEMPORAL_QUEUE": engine.task_queue,
        "RALF_TEST_SCOPE_WORKSPACE": engine.scope.workspace,
        "RALF_TEST_SCOPE_PRINCIPAL": engine.scope.principal,
    }
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(Path(__file__).with_name("a2a_temporal_fixture.py")),
                str(port),
                str(listener.fileno()),
                "crash" if crash else "normal",
            ],
            pass_fds=(listener.fileno(),),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 15
        with httpx.Client(trust_env=False) as client:
            while process.poll() is None and time.monotonic() < deadline:
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
                pytest.fail("Shared HTTP startup failed: " + log_path.read_text())
        yield (
            A2AClient(
                f"http://127.0.0.1:{port}/rpc", headers={"Authorization": "Bearer test-owner"}
            ),
            process,
            log_path,
        )
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        listener.close()


def test_real_shared_http_dedup_across_processes_and_history(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, runtime, workers):
            with (
                http_process(tmp_path, engine) as (left, _, _),
                http_process(tmp_path, engine) as (right, _, _),
            ):
                try:
                    tasks = await asyncio.gather(
                        left.send_message("same", {"task": "hello"}),
                        right.send_message("same", {"task": "hello"}),
                    )
                    assert tasks[0]["id"] == tasks[1]["id"]
                    snapshot = await engine.drive(tasks[0]["id"])
                    assert snapshot.state == "succeeded"
                    assert (await right.get_by_message("same"))["id"] == tasks[0]["id"]
                    assert (
                        sum(
                            log.read_text().count("TEMPORAL_PROVIDER_CALLED")
                            for _, log in workers.processes
                        )
                        == 1
                    )
                    history = await engine.client.get_workflow_handle(
                        tasks[0]["id"]
                    ).fetch_history()
                    await replay_temporal_history(history)
                finally:
                    await left.aclose()
                    await right.aclose()

    asyncio.run(run())


def test_http_process_death_before_inbox_completion_repairs_original_temporal_run(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, runtime, workers):
            inbox = await PostgresInbox.connect(
                os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="verify"
            )
            try:
                await inbox.initialize()
                with http_process(tmp_path, engine, crash=True) as (crashed, process, log):
                    try:
                        with pytest.raises(A2AError):
                            await crashed.send_message("original", {"task": "hello"})
                        await asyncio.to_thread(process.wait, timeout=5)
                        assert process.returncode == 78
                        original = json.loads(
                            next(
                                line[len("A2A_ACCEPTED_RUN ") :]
                                for line in log.read_text().splitlines()
                                if line.startswith("A2A_ACCEPTED_RUN ")
                            )
                        )["run_id"]
                        assert await inbox.result(engine.scope, "original") is None
                        assert len(await inbox.pending(engine.scope)) == 1
                    finally:
                        await crashed.aclose()
                with http_process(tmp_path, engine) as (replacement, _, _):
                    try:
                        task = await replacement.send_message("original", {"task": "hello"})
                        assert task["id"] == original
                        assert (await engine.drive(original)).state == "succeeded"
                        assert await inbox.result(engine.scope, "original") == {"run_id": original}
                        assert (
                            sum(
                                log.read_text().count("TEMPORAL_PROVIDER_CALLED")
                                for _, log in workers.processes
                            )
                            == 1
                        )
                    finally:
                        await replacement.aclose()
            finally:
                await inbox.aclose()

    asyncio.run(run())
