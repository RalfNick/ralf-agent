"""Real loopback evidence for serial trusted-Scope routing and redacted audit."""

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

from relf_agent.a2a import A2AClient
from relf_agent.types import canonical
from tests.test_a2a_scope_isolation import persisted


@contextmanager
def http_process(directory):
    pytest.importorskip("uvicorn")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/rpc"
    root = Path(__file__).resolve().parents[1]
    with (directory / "http.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("a2a_scope_audit_http_fixture.py")),
                str(directory),
                str(listener.fileno()),
            ],
            pass_fds=(listener.fileno(),),
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": str(root / "src") + os.pathsep + str(root),
            },
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if (
                        httpx.get(
                            url.removesuffix("rpc") + ".well-known/agent-card.json",
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
                pytest.fail("Owned scope/audit HTTP startup failed: " + log.read())
            yield url, process
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            listener.close()


def test_actual_http_two_valid_scopes_recover_once_and_emit_redacted_audit(tmp_path):
    async def run():
        with http_process(tmp_path) as (url, process):
            async with httpx.AsyncClient(trust_env=False) as http:
                alice = A2AClient(url, client=http, headers={"Authorization": "Bearer alice"})
                bob = A2AClient(url, client=http, headers={"Authorization": "Bearer bob"})
                original = await alice.send_message("shared-message-secret", "request-body-secret")
                other = await bob.send_message("shared-message-secret", "request-body-secret")
                assert other["id"] != original["id"]
                assert (await bob.get_task(other["id"]))["id"] == other["id"]
                assert (await bob.get_by_message("shared-message-secret"))["id"] == other["id"]
                assert (await alice.get_task(original["id"]))["id"] == original["id"]
                waiting = await alice.resume_task(original["id"])
                assert waiting["metadata"]["ralf"]["state"] == "waiting_approval"
                target = waiting["metadata"]["ralf"]["pending"][0]
                page = await alice.get_events(original["id"], limit=1)
                assert page["events"]
                before = persisted(tmp_path)
                for method, params in (
                    ("tasks/events", {"id": original["id"], "afterCursor": page["cursor_token"]}),
                    (
                        "tasks/cancel",
                        {"id": original["id"], "metadata": {"ralfCommandId": "cancel-secret"}},
                    ),
                ):
                    denied = await http.post(
                        url,
                        headers={"Authorization": "Bearer bob"},
                        json={
                            "jsonrpc": "2.0",
                            "id": "foreign-request-secret",
                            "method": method,
                            "params": params,
                        },
                    )
                    assert denied.status_code == 401 and denied.json() == {"error": "unauthorized"}
                    assert persisted(tmp_path) == before
                unauthenticated = await http.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": "auth-secret",
                        "method": "tasks/get",
                        "params": {"id": original["id"]},
                    },
                )
                assert unauthenticated.status_code == 401
                assert persisted(tmp_path) == before and len(before[1]) == 0
                approval = await alice.approve_task(
                    original["id"],
                    target["action_id"],
                    target["digest"],
                    command_id="approve-command-secret",
                )
                assert (
                    await alice.approve_task(
                        original["id"],
                        target["action_id"],
                        target["digest"],
                        command_id="approve-command-secret",
                    )
                    == approval
                )
                completed = await alice.resume_task(original["id"])
                assert completed["metadata"]["ralf"]["state"] == "succeeded"
                assert len(persisted(tmp_path)[1]) == 1
                assert (await alice.send_message("shared-message-secret", "request-body-secret"))[
                    "id"
                ] == original["id"]
                assert (await alice.get_by_message("shared-message-secret"))["id"] == original["id"]
                assert (await alice.get_task(original["id"]))["status"]["state"] == "completed"
                await alice.aclose()
                await bob.aclose()
        assert process.returncode in {0, -signal.SIGTERM}
        evidence = json.loads((tmp_path / f"shutdown-{process.pid}.json").read_text())
        assert {
            key: evidence[key]
            for key in (
                "hosted_closed",
                "engine_closed",
                "active_drives",
                "active_threads",
                "failures",
                "dropped",
            )
        } == {
            "hosted_closed": True,
            "engine_closed": True,
            "active_drives": 0,
            "active_threads": 0,
            "failures": 0,
            "dropped": 0,
        }
        records = evidence["records"]
        assert any(r["outcome"] == "unauthorized" and r["scope_ref"] is None for r in records)
        denied = [r for r in records if r["outcome"] == "unauthorized" and r["scope_ref"]]
        assert {r["operation"] for r in denied} == {"tasks/events", "tasks/cancel"}
        owners = [
            r for r in records if r["operation"] == "tasks/resume" and r["outcome"] == "rpc_ok"
        ]
        assert len(owners) == 2
        assert all(r["task_ref"] == owners[0]["task_ref"] for r in denied + owners)
        assert all(r["scope_ref"] != owners[0]["scope_ref"] for r in denied)
        approvals = [r for r in records if r["operation"] == "tasks/approve"]
        assert len(approvals) == 2 and all(r["outcome"] == "rpc_ok" for r in approvals)
        assert (
            approvals[0]["command_ref"]
            and approvals[0]["command_ref"] == approvals[1]["command_ref"]
        )
        serialized = canonical(records)
        for private in (
            "secret",
            "Bearer alice",
            "Bearer bob",
            "shared-workspace",
            original["id"],
            other["id"],
            target["action_id"],
            target["digest"],
        ):
            assert private not in serialized

    asyncio.run(run())
