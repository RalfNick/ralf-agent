"""Actual version queues and original Histories survive a complete Worker gap."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from relf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    RunRef,
    Runtime,
    Scope,
    TemporalProfile,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch
from relf_agent.temporal import TemporalEngine, replay_temporal_history

from .temporal_profile_host_worker import build, context_metadata_root

pytestmark = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("RALF_TEST_TEMPORAL_ADDRESS", "RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal and PostgreSQL services",
)


def configuration(default):
    return {
        "kind": "temporal-profiles",
        "schema_version": 1,
        "default": {"name": "service", "version": default},
        "profiles": [
            TemporalProfile(
                "service",
                version,
                {"default": {"adapter": "host-offline", "config": {"label": version}}},
                {
                    "tools": {"adapter": "host-tools"},
                    "session_store": {"adapter": "sqlite", "config": {"path": "session.sqlite"}},
                    "effect_journal": {
                        "adapter": "postgres",
                        "config": {
                            "dsn_env": "RALF_TEST_POSTGRES_DSN",
                            "backend_id": "host-effects",
                            "initialize": True,
                        },
                    },
                },
                execution={
                    "enable_sessions": True,
                    "session_writes": True,
                    "composite_sessions": True,
                    "context_reads": True,
                },
            ).to_dict()
            for version in ("1", "2")
        ],
    }


@pytest.mark.parametrize("kind", ["agent", "native-session", "graph-session"])
def test_all_versions_restart_default_switch_original_receipt_and_session_rebind(tmp_path, kind):
    async def run():
        from temporalio.client import Client

        scope_id = uuid.uuid4().hex
        prefix = "host-" + scope_id
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(configuration("1")))
        processes = []
        local = None
        remote = None

        async def start():
            identity = str(len(processes))
            log_path = tmp_path / ("worker-" + identity + ".log")
            env = {
                k: os.environ[k]
                for k in ("PATH", "RALF_TEST_TEMPORAL_ADDRESS", "RALF_TEST_POSTGRES_DSN")
                if k in os.environ
            }
            env.update(
                PYTHONPATH=str(Path(__file__).parents[1] / "src"),
                RALF_HOST_ROOT=str(tmp_path),
                RALF_HOST_SCOPE_ID=scope_id,
                RALF_HOST_QUEUE_PREFIX=prefix,
                RALF_HOST_WORKER_ID=identity,
            )
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "import asyncio; from tests.temporal_profile_host_worker import run; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append((identity, process, log_path))
            async with asyncio.timeout(20):
                while "HOST_WORKER_READY" not in log_path.read_text():  # noqa: ASYNC110 -- exact process readiness
                    assert process.poll() is None, log_path.read_text()
                    await asyncio.sleep(0.05)
            return json.loads((tmp_path / ("routes-" + identity + ".json")).read_text())

        async def stop():
            for identity, process, log_path in processes:
                if process.poll() is None:
                    (tmp_path / ("stop-" + identity)).touch()
                    assert await asyncio.to_thread(process.wait, 25) == 0, log_path.read_text()
                if "HOST_WORKER_READY" in log_path.read_text():
                    assert "HOST_WORKER_CLOSED" in log_path.read_text()

        async def finish(run, expected):
            result = await run.wait(wait_timeout=20)
            assert result.snapshot.state == "waiting_approval", result
            pending = (await run.pending())[0]
            target = await run._runtime.aattach(RunRef.from_dict(pending["ref"]))
            receipt = await target.approve(
                pending["action_id"], pending["digest"], command_id="approve:" + run.ref.run_id
            )
            assert (
                await target.approve(
                    pending["action_id"], pending["digest"], command_id="approve:" + run.ref.run_id
                )
                == receipt
            )
            done = await run.wait(wait_timeout=20, terminal_only=True)
            assert done.snapshot.state == "succeeded", done
            answer = done.snapshot.result
            if kind == "graph-session":
                answer = answer["answer"]
            assert answer == "answer-" + expected
            return receipt

        token = context_metadata_root.set(str(tmp_path))
        try:
            first_routes = await start()
            first = first_routes[0]
            remote = Runtime.from_temporal(
                TemporalEngine(
                    client,
                    task_queue=first["queue"],
                    release=first["release"],
                    scope=Scope("host-service", scope_id),
                    activity_timeout=3,
                    drive_timeout=30,
                )
            )
            agent = AgentSpec("a", "Apply", ["change"])
            definition = (
                GraphWorkflowSpec("flow", [GraphNode("answer", agent=agent)])
                if kind == "graph-session"
                else agent
            )
            entry = None
            if kind == "agent":
                original = await remote.submit(definition, "task", command_id="original", budget=32)
            else:
                entry = await remote.open_session(definition, "chat", command_id="open")
                original = await entry.submit("task", command_id="original", budget=32)
            assert (await original.wait(wait_timeout=20)).snapshot.state == "waiting_approval"
            original_ref, original_receipt = original.ref, original.receipt
            session_ref = None if entry is None else entry.ref
            await stop()  # All actual hosted Workers absent; the client owns none.
            if kind == "agent":
                missing = configuration("2")
                missing["profiles"] = missing["profiles"][1:]
                path.write_text(json.dumps(missing))
                unavailable = await build(tmp_path, scope_id)
                try:
                    with pytest.raises(DefinitionMismatch, match="Registry"):
                        await unavailable.start_workers(client, queue_prefix=prefix)
                    assert all(a._worker_start is None for a in unavailable._assemblies)
                finally:
                    await unavailable.aclose(wait_timeout=20)
            path.write_text(json.dumps(configuration("2")))
            second_routes = await start()
            assert first_routes == second_routes
            local = await build(tmp_path, scope_id)
            await local.start_workers(
                client,
                queue_prefix=prefix,
                engine_options={"activity_timeout": 3, "drive_timeout": 30},
            )
            assert local.default_profile.version == "2"
            if kind == "agent":
                from temporalio.service import RPCError, RPCStatusCode

                with pytest.raises(AuthorizationDenied):
                    await local.aattach(replace(original_ref, principal="another"))
                with pytest.raises(RPCError) as absent:
                    await local.aattach(replace(original_ref, run_id="missing-" + scope_id))
                assert absent.value.status == RPCStatusCode.NOT_FOUND
                with sqlite3.connect(tmp_path / "audit.sqlite") as connection:
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM calls WHERE kind='model'"
                        ).fetchone()[0]
                        == 1
                    )
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM calls WHERE kind='tool'"
                        ).fetchone()[0]
                        == 0
                    )
            attached = await local.aattach(original_ref)
            approval = await finish(attached, "1")
            assert attached.ref == original_ref
            if kind == "agent":
                duplicate = await local.runtime().submit(
                    definition, "task", command_id="original", budget=32
                )
                assert duplicate.ref == original_ref and duplicate.receipt == original_receipt
                new = await local.runtime().submit(
                    definition, "new task", command_id="new", budget=32
                )
                await finish(new, "2")
            else:
                attached_session = await local.aattach_session(session_ref)
                async with asyncio.timeout(15):
                    while (await attached_session.status()).busy:  # noqa: ASYNC110 -- original Session end gate
                        await asyncio.sleep(0.05)
                duplicate = await attached_session.submit("task", command_id="original", budget=32)
                assert duplicate.ref == original_ref and duplicate.receipt == original_receipt
                replacement = await local.runtime().open_session(
                    definition, "chat", command_id="open"
                )
                assert replacement.ref == session_ref  # Defaults do not rebind.
                changed = await replacement.rebind(
                    definition, expected_binding_revision=1, command_id="rebind"
                )
                assert changed.ref.binding_revision == 2
                resumed = await local.aattach_session(changed.ref)
                new = await resumed.submit("new task", command_id="new", budget=32)
                await finish(new, "2")
                async with asyncio.timeout(15):
                    while (await resumed.status()).busy:  # noqa: ASYNC110
                        await asyncio.sleep(0.05)
            await replay_temporal_history(
                await client.get_workflow_handle(original_ref.run_id).fetch_history()
            )
            with sqlite3.connect(tmp_path / "audit.sqlite") as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM calls WHERE kind='model' AND label='1'"
                    ).fetchone()[0]
                    == 2
                )
                assert (
                    connection.execute(
                        "SELECT count(*) FROM calls WHERE kind='model' AND label='2'"
                    ).fetchone()[0]
                    == 2
                )
                assert (
                    connection.execute("SELECT count(*) FROM calls WHERE kind='tool'").fetchone()[0]
                    == 2
                )
                assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 2
            assert approval.record_state == "durably_recorded"
        finally:
            if remote is not None:
                await remote.aclose()
            if local is not None:
                await local.aclose(wait_timeout=20)
            await stop()
            context_metadata_root.reset(token)

    asyncio.run(run())
