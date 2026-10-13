"""Actual History/PG/new Worker; native peer counters are mechanical evidence."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests import temporal_coding_worker_fixture as fixture
from tests.test_codex_runner import native_fixture

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires actual Temporal and PostgreSQL",
)


async def wait_until(operation, predicate, *, wait_seconds=30):
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        value = await operation()
        if predicate(value):
            return value
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Original operation did not reach expected state: {value}")
        await asyncio.sleep(0.05)


@pytest.mark.parametrize(
    "mode",
    [
        "agent",
        "crash",
        "bound_sequence",
        "claim_crash",
        "prepare_crash",
        "turn_grant_crash",
        "candidate_loss",
        "native_control",
    ],
)
def test_actual_history_pg_native_attempt_survives_worker_replacement(tmp_path, monkeypatch, mode):
    if mode == "native_control" and os.getenv("RALF_TEST_CODING_NATIVE") != "1":
        pytest.skip("Requires explicitly selected actual unauthenticated Codex containment probe")
    crash = mode.endswith("crash")

    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "coding_106_" + uuid.uuid4().hex
        conn = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        root = tmp_path / "native"
        root.mkdir(mode=0o700)
        actual = mode == "native_control"
        cli = (
            await asyncio.to_thread(Path(os.environ["RALF_TEST_CODING_DOCKER"]).resolve)
            if actual
            else native_fixture(tmp_path, "hang_turn" if mode == "crash" else "completed")
        )
        sock = socket.socket(socket.AF_UNIX)
        sock_path = Path("/private/tmp") / ("ralf-coding-" + uuid.uuid4().hex[:12] + ".sock")
        if actual:
            sock_path = Path(os.environ["RALF_TEST_CODING_HOST"].removeprefix("unix://"))
        else:
            sock.bind(str(sock_path))
            cli.write_text(
                cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(sock_path))
            )
        queue = "coding_106_" + uuid.uuid4().hex
        env = {
            "RALF_CODING_ROOT": str(root),
            "RALF_CODING_DOCKER": str(cli),
            "RALF_CODING_HOST": "unix://" + str(sock_path),
            "RALF_CODING_SCHEMA": schema,
            "RALF_CODING_QUEUE": queue,
        }
        if mode != "crash" and (crash or mode == "candidate_loss"):
            env["RALF_CODING_FAULT"] = mode
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        built, native, journal = await fixture.runtime()
        processes = []

        async def start():
            log = tmp_path / f"worker-{len(processes)}.log"
            worker_env = {
                key: value
                for key, value in os.environ.items()
                if key.startswith("RALF_") or key == "PATH"
            }
            if processes:
                worker_env.pop("RALF_CODING_FAULT", None)
            worker_env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [sys.executable, "-u", "-m", "tests.temporal_coding_worker_fixture"],
                    env=worker_env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            await wait_until(
                lambda: asyncio.to_thread(log.read_text),
                lambda value: "CODING_WORKER_READY" in value,
            )
            return process

        try:
            first = await start()
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            engine = TemporalEngine(
                client,
                task_queue=queue,
                release=built.manifest,
                scope=Scope("coding-service", queue),
                activity_timeout=3 if crash else 15,
                drive_timeout=35,
            )
            spec = AgentSpec("code", "Perform approved Coding", tools=("coding",))
            definition = spec
            if mode == "bound_sequence":
                from ralf_agent import BindingSelection, WorkflowSpec
                from ralf_agent.binding_definitions import BoundDefinition
                from ralf_agent.binding_types import AgentBindingDescriptor

                definition = BoundDefinition(
                    WorkflowSpec(
                        "two", (spec, AgentSpec("second", "Another task", tools=("coding",)))
                    ),
                    {
                        f"sequence/steps/{i}": AgentBindingDescriptor(
                            runner=BindingSelection.ref("original", "1")
                        )
                        for i in range(2)
                    },
                )
            handle = await engine.submit(
                definition,
                "fixed task",
                command_id="submit",
            )
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: value.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            await engine.approve(
                handle.run_id,
                action_id=pending["action_id"],
                target_digest=pending["digest"],
                approved=True,
                command_id="approve",
            )
            if crash:
                counter = tmp_path / "native-submissions.jsonl"
                expected = 2 if mode == "crash" else (1 if mode == "turn_grant_crash" else 0)
                if mode == "crash":
                    await wait_until(
                        lambda: asyncio.to_thread(
                            lambda: counter.read_text() if counter.exists() else ""
                        ),
                        lambda value: len(value.splitlines()) == expected,
                    )
                else:
                    await wait_until(
                        lambda: asyncio.to_thread(lambda: first.poll()), lambda value: value == 71
                    )
                action = {"id": pending["action_id"]}
                if first.poll() is None:
                    first.kill()
                await asyncio.to_thread(first.wait, timeout=5)
                await start()
                await engine.cancel(handle.run_id, command_id="cancel")
                final = await wait_until(
                    lambda: engine.status(handle.run_id), lambda value: value.state == "cancelled"
                )
                recovered = next(a for a in final.actions if a["kind"] == "tool")
                assert recovered["id"] == action["id"] and len(recovered["attempts"]) == 1
                assert (
                    len(counter.read_text().splitlines()) if counter.exists() else 0
                ) == expected
                diagnostics = await client.get_workflow_handle(handle.run_id).query(
                    "view", {"scope": asdict(engine.scope), "kind": "diagnostics"}
                )
                assert diagnostics["budget"]["unknown"] == 1
            elif actual:
                final = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: (
                        value.state == "waiting_reconciliation"
                        and any(
                            a.get("delegated_execution", {}).get("fenced") is True
                            for a in value.actions
                        )
                    ),
                )
                action = next(a for a in final.actions if a["kind"] == "tool")
                native_state = action["delegated_execution"]
                assert len(action["attempts"]) == 1 and native_state["fenced"] is True
                assert (
                    native_state["pending_stop"] is False and "result_candidate" not in native_state
                )
                from ralf_agent.codex_coding_profile import CodexCodingProfile
                from ralf_agent.codex_environment import _pin

                metadata = next(root.glob("*/environment.json"))
                saved = json.loads(metadata.read_text())
                config_path = metadata.parent / "state/config.toml"
                assert config_path.read_text() == CodexCodingProfile().config_text
                assert _pin(config_path) == saved["files"]["state/config.toml"]
                assert saved["identity"]["configuration_readonly"] is True
                stopped = native_state["stop"]
                removed = await asyncio.to_thread(
                    subprocess.run,
                    [
                        str(cli),
                        "--host",
                        "unix://" + str(sock_path),
                        "inspect",
                        stopped["container_id"],
                    ],
                    capture_output=True,
                )
                assert removed.returncode != 0
                await engine.cancel(handle.run_id, command_id="cancel-native")
                await wait_until(
                    lambda: engine.status(handle.run_id), lambda value: value.state == "cancelled"
                )
            else:
                if mode == "bound_sequence":
                    second = await wait_until(
                        lambda: engine.status(handle.run_id),
                        lambda value: (
                            bool(value.pending)
                            and value.pending[0]["action_id"] != pending["action_id"]
                        ),
                    )
                    await engine.approve(
                        handle.run_id,
                        second.pending[0]["action_id"],
                        second.pending[0]["digest"],
                        command_id="approve-second",
                    )
                final = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: value.state in {"succeeded", "waiting_reconciliation"},
                )
                assert final.state == "succeeded" and final.result == "finished"
                assert len((tmp_path / "native-submissions.jsonl").read_text().splitlines()) == (
                    4 if mode == "bound_sequence" else 2
                )
            history = await client.get_workflow_handle(handle.run_id).fetch_history()
            await replay_temporal_history(history)
            assert await journal.pending_resources(engine.scope) == ()
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            await native.aclose()
            await journal.aclose()
            await built.journal.aclose()
            sock.close()
            if not actual:
                sock_path.unlink(missing_ok=True)
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await conn.close()

    asyncio.run(run())
