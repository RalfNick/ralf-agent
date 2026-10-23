"""Original graph/child Histories and physical Coding closure on actual services."""

import asyncio
import os
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, ValueRef
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests import temporal_coding_graph_worker_fixture as fixture
from tests.test_codex_runner import native_fixture
from tests.test_temporal_coding_service import wait_until

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires actual Temporal and PostgreSQL",
)


@pytest.mark.parametrize(
    "mode",
    [
        "serial",
        "bound_graph",
        "approval_restart",
        "running_cancel",
        "claim_crash",
        "prepare_crash",
        "turn_grant_crash",
        "candidate_loss",
    ],
)
def test_actual_serial_coding_graph_original_children_and_recovery(tmp_path, monkeypatch, mode):
    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "coding_graph_107_" + uuid.uuid4().hex
        conn = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        root = tmp_path / "native"
        root.mkdir(mode=0o700)
        cli = native_fixture(tmp_path, "hang_turn" if mode == "running_cancel" else "completed")
        sock = socket.socket(socket.AF_UNIX)
        sock_path = Path("/private/tmp") / ("ralf-coding-" + uuid.uuid4().hex[:12] + ".sock")
        sock.bind(str(sock_path))
        cli.write_text(
            cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(sock_path))
        )
        queue = "coding_graph_107_" + uuid.uuid4().hex
        for name, value in {
            "RALF_CODING_ROOT": str(root),
            "RALF_CODING_DOCKER": str(cli),
            "RALF_CODING_HOST": "unix://" + str(sock_path),
            "RALF_CODING_SCHEMA": schema,
            "RALF_CODING_QUEUE": queue,
        }.items():
            monkeypatch.setenv(name, value)
        if mode.endswith("crash") or mode == "candidate_loss":
            monkeypatch.setenv("RALF_CODING_FAULT", mode)
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
                    [sys.executable, "-u", "-m", "tests.temporal_coding_graph_worker_fixture"],
                    env=worker_env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            await wait_until(
                lambda: asyncio.to_thread(log.read_text),
                lambda value: "CODING_GRAPH_WORKER_READY" in value or process.poll() is not None,
            )
            assert process.poll() is None, log.read_text()
            return process

        try:
            first = await start()
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            scope = Scope("coding-service", queue)
            engine = TemporalEngine(
                client,
                task_queue=queue,
                release=built.orchestration_release,
                scope=scope,
                activity_timeout=40,
                drive_timeout=35,
            )
            graph = GraphWorkflowSpec(
                "serial-coding",
                (
                    GraphNode("first", agent=AgentSpec("a", "Perform Coding", tools=("coding",))),
                    GraphNode(
                        "second",
                        agent=AgentSpec("b", "Continue Coding", tools=("coding",)),
                        depends_on=("first",),
                        input=ValueRef("first"),
                    ),
                ),
                max_concurrency=1,
            )
            if mode == "bound_graph":
                from relf_agent import BindingSelection
                from relf_agent.binding_definitions import BoundDefinition
                from relf_agent.binding_types import AgentBindingDescriptor

                graph = BoundDefinition(
                    graph,
                    {
                        "graph/nodes/first": AgentBindingDescriptor(
                            runner=BindingSelection.ref("original", "1")
                        ),
                        "graph/nodes/second": AgentBindingDescriptor(
                            runner=BindingSelection.ref("original", "1")
                        ),
                    },
                )
            handle = await engine.submit(graph, "fixed task", command_id="submit", budget=32)
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: value.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            child_id = pending["run_id"]
            child_handle = client.get_workflow_handle(child_id)
            child_epoch = (await child_handle.describe()).run_id
            if mode == "approval_restart":
                first.kill()
                await asyncio.to_thread(first.wait, timeout=5)
                await start()
                repeated = await engine.submit(graph, "fixed task", command_id="submit", budget=32)
                assert repeated == handle
                assert (await child_handle.describe()).run_id == child_epoch
            await engine.approve(
                child_id,
                action_id=pending["action_id"],
                target_digest=pending["digest"],
                approved=True,
                command_id="approve-first",
            )
            counter = tmp_path / "native-submissions.jsonl"
            if mode.endswith("crash"):
                await wait_until(lambda: asyncio.to_thread(first.poll), lambda value: value == 71)
                await start()
            if mode == "running_cancel" or mode.endswith("crash"):
                if mode == "running_cancel":
                    await wait_until(
                        lambda: asyncio.to_thread(
                            lambda: counter.read_text() if counter.exists() else ""
                        ),
                        lambda value: len(value.splitlines()) == 2,
                    )
                await engine.cancel(handle.run_id, command_id="cancel")
                final = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: value.state == "cancelled",
                    wait_seconds=60,
                )
                diagnostics = await client.get_workflow_handle(handle.run_id).query(
                    "view", {"scope": asdict(scope), "kind": "diagnostics"}
                )
                assert diagnostics["budget"]["unknown"] > 0
                expected = (
                    2 if mode == "running_cancel" else (1 if mode == "turn_grant_crash" else 0)
                )
                assert (
                    len(counter.read_text().splitlines()) if counter.exists() else 0
                ) == expected
                assert len(diagnostics["workflow"]["children"]) == 1
            else:
                second = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: bool(value.pending) and value.pending[0]["run_id"] != child_id,
                    # The killed Worker may own an in-flight 40s control Activity;
                    # recovery must first observe that original timeout.
                    wait_seconds=60 if mode == "approval_restart" else 30,
                )
                item = second.pending[0]
                await engine.approve(
                    item["run_id"],
                    action_id=item["action_id"],
                    target_digest=item["digest"],
                    approved=True,
                    command_id="approve-second",
                )
                final = await wait_until(
                    lambda: engine.status(handle.run_id),
                    lambda value: value.state == "succeeded",
                )
                assert final.result == {"first": "finished", "second": "finished"}
                assert len(counter.read_text().splitlines()) == 4
            root_handle = client.get_workflow_handle(handle.run_id)
            proof = await wait_until(
                lambda: root_handle.query(
                    "view", {"scope": asdict(scope), "kind": "coding_composition_proof"}
                ),
                lambda value: value["physical_stopped"] is True,
            )
            children = await root_handle.query(
                "view", {"scope": asdict(scope), "kind": "coding_composition_children"}
            )
            assert proof["physical_stopped"] is True
            assert proof["execution_epoch"] == proof["original_execution_epoch"]
            assert children[0]["child_execution"]["execution_epoch"] == child_epoch
            for run_id in [handle.run_id, *(child["run_id"] for child in children)]:
                history = await client.get_workflow_handle(run_id).fetch_history()
                await replay_temporal_history(history, namespace=client.namespace)
                (tmp_path / (run_id + ".history.json")).write_text(history.to_json())
            assert await journal.pending_resources(scope) == ()
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            await native.aclose()
            await journal.aclose()
            await built.journal.aclose()
            sock.close()
            sock_path.unlink(missing_ok=True)
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await conn.close()

    asyncio.run(run())
