"""Real History/PG no-submit adoption after an actual registered broker ends."""

import asyncio
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TemporalProfile
from ralf_agent.codex_create_journal import process_ended
from ralf_agent.codex_create_supervisor import CreateSupervisor
from ralf_agent.codex_model_connection import CodexModelConnection
from ralf_agent.errors import ExecutionHostFailed
from ralf_agent.temporal import replay_temporal_history
from ralf_agent.types import canonical
from tests.connected_coding_fixture import connected_native_fixture
from tests.test_temporal_coding_owned_service import completed_updates
from tests.test_temporal_coding_service import wait_until
from tests.test_temporal_connected_coding_integration import _application

pytestmark = pytest.mark.skipif(
    os.getenv("RALF_TEST_CREATE_SUPERVISION_SERVICE") != "1"
    or not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires explicitly selected actual Temporal/PostgreSQL no-submit service probe",
)


def abort_before_go(supervisor):
    """Only fixture fault: drain the original physical broker before its live GO."""
    # Explicit conditions keep its pinned bytecode identical in pytest and in
    # the normal canonical module imported by the separate Worker process.
    if (
        supervisor._process is None
        or supervisor._journal.read("worker-go.json", missing=True) is not None
    ):
        raise ExecutionHostFailed("Fixture requires the original registered never-granted broker")
    result = supervisor.abort(timeout=8)
    receipt = result["receipt"]
    if (
        receipt["outer_gate_accepted"] is not False
        or receipt["cli_gate_accepted"] is not False
        or receipt["cli_exec_started"] is not False
        or receipt["gate_sealed"] is not True
        or receipt["child"] is not None
        or result["helpers_ended"] is not True
        or result["control_drained"] is not True
        or supervisor._process.returncode is None
    ):
        raise ExecutionHostFailed("Fixture original broker end/no-GO proof is incomplete")
    observation = {
        "broker_pid": supervisor._process.pid,
        "broker_returncode": supervisor._process.returncode,
        "declaration_digest": result["declaration_digest"],
        "receipt_digest": result["receipt_digest"],
        "helpers_ended": True,
        "control_drained": True,
        "outer_gate_accepted": False,
        "cli_gate_accepted": False,
        "cli_exec_started": False,
        "child": None,
    }
    directory = Path(os.environ["RALF_CONNECTED_DIRECTORY"])
    with (directory / "no-submit-physical.jsonl").open("a") as output:
        output.write(json.dumps(observation) + "\n")
    raise ExecutionHostFailed("Fixture original CREATE broker ended before GO")


async def _worker():
    from temporalio.client import Client

    from tests.test_temporal_coding_create_supervision_integration import (
        abort_before_go as canonical_fault,
    )

    # Use the same defining module/function in both parent and actual Worker.
    CreateSupervisor.start_once = canonical_fault
    assembly = None
    try:
        directory = Path(os.environ["RALF_CONNECTED_DIRECTORY"])
        assembly, _, queue = await _application(directory)
        (directory / ("no-submit-worker-" + str(os.getpid()) + ".release.json")).write_text(
            json.dumps(assembly.release)
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        await assembly.start_worker(client, task_queue=queue)
        print("CREATE_NO_SUBMIT_WORKER_READY", flush=True)
        await asyncio.Event().wait()
    except Exception as error:
        # The service configuration remains in RAM; do not print exception bodies.
        print("CREATE_NO_SUBMIT_WORKER_FAILED " + type(error).__name__, flush=True)
        raise SystemExit(72) from None
    finally:
        if assembly is not None:
            await assembly.aclose(wait_timeout=15)


@pytest.mark.parametrize("composition", [False, True], ids=["native20", "graph21"])
def test_actual_no_submit_original_receipt_survives_cold_worker(tmp_path, monkeypatch, composition):
    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "create_nosubmit_112_" + uuid.uuid4().hex
        queue = "create-nosubmit-112-" + uuid.uuid4().hex
        admin = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = psycopg.conninfo.make_conninfo(
            os.environ["RALF_TEST_POSTGRES_DSN"], options="-c search_path=" + schema
        )
        canary = "synthetic-no-submit-" + secrets.token_hex(24)
        monkeypatch.setenv("RALF_CONNECTED_DIRECTORY", str(tmp_path))
        monkeypatch.setenv("RALF_CONNECTED_SCOPED_DSN", scoped_dsn)
        monkeypatch.setenv("RALF_CONNECTED_TEST_KEY", canary)
        monkeypatch.setattr(CreateSupervisor, "start_once", abort_before_go)
        root = tmp_path / "native"
        root.mkdir(mode=0o700)
        connection = CodexModelConnection(
            "https://api.deepseek.com",
            "deepseek-flash",
            "RALF_CONNECTED_TEST_KEY",
            "structural",
            "1",
        )
        cli = connected_native_fixture(tmp_path, connection)
        sock = socket.socket(socket.AF_UNIX)
        socket_path = Path("/private/tmp") / ("ralf-nosubmit-" + uuid.uuid4().hex[:12] + ".sock")
        sock.bind(str(socket_path))
        source = cli.read_text().replace(
            "unix:///fixture/docker.sock", "unix://" + str(socket_path)
        )
        # Observe actual CLI invocations without changing their response semantics.
        anchor = "root=pathlib.Path(__file__).parent; db=root/'docker.json'"
        assert source.count(anchor) == 1
        source = source.replace(
            anchor,
            anchor
            + "\nwith (root/'docker-methods.jsonl').open('a') as out:out.write(json.dumps(a)+'\\n')",
        )
        cli.write_text(source)
        scope = Scope("create-no-submit-service", queue)
        profile = TemporalProfile(
            "create-no-submit-structural",
            "112",
            {"default": {"adapter": "connected-structural-peer"}},
            {
                "effect_journal": {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_CONNECTED_SCOPED_DSN",
                        "backend_id": queue,
                        "initialize": True,
                    },
                },
                "tools": {
                    "adapter": "codex-coding-connected-postgres",
                    "config": {
                        "name": "coding",
                        "description": "Original no-submit structural probe",
                        "cost": 1,
                        "runner_root": str(root),
                        "fixed_dependencies": {"deployment": queue},
                        "docker_executable": str(cli),
                        "docker_host": "unix://" + str(socket_path),
                        "request_timeout": 15,
                        "connection": connection.to_dict(),
                    },
                },
            },
            execution={"coding_execution": True, "coding_composition": composition},
        )
        (tmp_path / "application.json").write_text(
            json.dumps({"profile": profile.to_dict(), "scope": asdict(scope), "queue": queue})
        )
        assembly = None
        processes = []
        controls = set()
        cleanup = {
            "workers_ended": False,
            "helpers_ended": False,
            "control_directories_removed": False,
            "schema_dropped": False,
        }

        async def start_worker():
            log = tmp_path / ("no-submit-worker-" + str(len(processes)) + ".log")
            test_root = Path(__file__).parents[1]
            paths = [str(test_root)]
            if (test_root / "src" / "ralf_agent" / "__init__.py").is_file():
                paths.append(str(test_root / "src"))
            environment = {
                "PATH": os.environ["PATH"],
                "PYTHONPATH": os.pathsep.join(paths),
                "RALF_CONNECTED_DIRECTORY": str(tmp_path),
                "RALF_CONNECTED_SCOPED_DSN": scoped_dsn,
                "RALF_CONNECTED_TEST_KEY": canary,
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-m",
                        "tests.test_temporal_coding_create_supervision_integration",
                    ],
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    cwd=test_root,
                )
            processes.append(process)
            await wait_until(
                lambda: asyncio.to_thread(log.read_text),
                lambda value: (
                    "CREATE_NO_SUBMIT_WORKER_READY" in value or process.poll() is not None
                ),
            )
            assert process.poll() is None, "Dedicated no-submit Worker failed before readiness"
            return process

        async def diagnostics(handle):
            return await handle.query("view", {"scope": asdict(scope), "kind": "diagnostics"})

        try:
            assembly, _, _ = await _application(tmp_path)
            assert assembly.release["binding_protocol"] == (21 if composition else 20)
            assert assembly.release["coding_execution_protocol"]["version"] == 5
            first = await start_worker()
            worker_release = json.loads(
                (tmp_path / ("no-submit-worker-" + str(first.pid) + ".release.json")).read_text()
            )
            (tmp_path / "parent.release.json").write_text(json.dumps(assembly.release))
            assert canonical(worker_release) == canonical(assembly.release), (
                "Parent/actual Worker full implementation metadata differs"
            )
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            engine = assembly.create_engine(
                client, task_queue=queue, activity_timeout=30, drive_timeout=30
            )
            spec = AgentSpec("no-submit", "Perform approved structural Coding", tools=("coding",))
            definition = (
                GraphWorkflowSpec("no-submit-graph", [GraphNode("only", agent=spec)])
                if composition
                else spec
            )
            handle = await engine.submit(definition, "fixed task", command_id="submit", budget=8)
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda status: status.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            child_id = pending.get("run_id", handle.run_id)
            child = client.get_workflow_handle(child_id)
            epoch = (await child.describe()).run_id
            await engine.approve(
                child_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            raw = await wait_until(
                lambda: diagnostics(child),
                lambda view: any(
                    action.get("delegated_execution", {}).get("create_not_dispatched") is not None
                    and action["status"] == "outcome_unknown"
                    for action in view["snapshot"]["actions"]
                ),
                wait_seconds=60,
            )
            action = next(
                action for action in raw["snapshot"]["actions"] if action["kind"] == "tool"
            )
            original = action["delegated_execution"]
            proof = original["create_not_dispatched"]
            dispatch = original["request"]["dispatch"]
            assert action["id"] == pending["action_id"] and len(action["attempts"]) == 1
            assert set(original["grants"]) == {"prepare"}
            assert original["pending_stop"] is False and original["fenced"] is True
            assert all(
                name not in original for name in ("prepared", "binding", "thread", "turn", "stop")
            )
            assert raw["budget"]["unknown"] == 1
            physical = [
                json.loads(line)
                for line in (tmp_path / "no-submit-physical.jsonl").read_text().splitlines()
            ]
            assert len(physical) == 1 and physical[0]["helpers_ended"] is True
            assert proof["supervision_receipt_digest"] == physical[0]["receipt_digest"]
            capacity = root / ".coding-capacity.json"
            await wait_until(
                lambda: asyncio.to_thread(lambda: json.loads(capacity.read_text())),
                lambda record: record["obligation"] is None,
            )
            rows = await admin.execute(
                sql.SQL("SELECT record FROM {}.ralf_temporal_coding_resources").format(
                    sql.Identifier(schema)
                )
            )
            resources = [json.loads(row[0]) for row in await rows.fetchall()]
            assert len(resources) == 1 and resources[0]["version"] == "2"
            assert (
                resources[0]["create_not_dispatched"] == proof
                and resources[0]["pending_stop"] is False
            )
            assert resources[0]["prepared"] is None and resources[0]["stop"] is None
            namespaces = list(root.glob("*/environment.json"))
            assert len(namespaces) == 1
            metadata = json.loads(namespaces[0].read_text())
            declaration = metadata["create_operation"]["declaration"]
            controls.add(Path(declaration["control_directory"]["path"]))
            assert (
                metadata["container_id"] is None
                and metadata["create_operation"]["no_submit"] == proof
            )
            assert metadata["create_operation"]["phase"] == "not_dispatched"
            broker = json.loads(
                (namespaces[0].parent / ".create-operation" / "broker-register.json").read_text()
            )
            assert process_ended(broker) is True
            before = (
                action["id"],
                action["attempts"][0]["id"],
                dispatch["effect_key"],
                original["request"],
                proof,
            )
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            await start_worker()
            assert (await child.describe()).run_id == epoch
            assert (
                await engine.submit(definition, "fixed task", command_id="submit", budget=8)
                == handle
            )
            await engine.cancel(handle.run_id, command_id="cancel")
            await wait_until(
                lambda: engine.status(handle.run_id),
                lambda status: status.state == "cancelled",
                wait_seconds=60,
            )
            recovered = await diagnostics(child)
            again = next(
                action for action in recovered["snapshot"]["actions"] if action["kind"] == "tool"
            )
            adopted = again["delegated_execution"]
            assert (
                again["id"],
                again["attempts"][0]["id"],
                adopted["request"]["dispatch"]["effect_key"],
                adopted["request"],
                adopted["create_not_dispatched"],
            ) == before
            assert len(again["attempts"]) == 1 and set(adopted["grants"]) == {"prepare"}
            assert again["status"] == "outcome_unknown" and adopted["effect_case"] == "unknown"
            assert recovered["budget"]["unknown"] == 1
            methods = [
                json.loads(line)
                for line in (tmp_path / "docker-methods.jsonl").read_text().splitlines()
            ]
            assert not any("create" in argv or "start" in argv for argv in methods)
            assert not (tmp_path / "native-submissions.jsonl").exists()
            assert not (tmp_path / "auth-methods.txt").exists()
            assert len((tmp_path / "no-submit-physical.jsonl").read_text().splitlines()) == 1
            histories = {handle.run_id, child_id}
            if composition:
                parent = client.get_workflow_handle(handle.run_id)
                evidence = await wait_until(
                    lambda: parent.query(
                        "view", {"scope": asdict(scope), "kind": "coding_composition_proof"}
                    ),
                    lambda value: value["physical_stopped"] is True,
                )
                assert evidence["execution_epoch"] == evidence["original_execution_epoch"]
            for run_id in histories:
                history = await client.get_workflow_handle(run_id).fetch_history()
                assert canary not in history.to_json()
                updates = await completed_updates(history)
                prepares = [
                    payload
                    for name, payload, result in updates
                    if name == "admit_coding_phase"
                    and payload.get("method") == "prepare"
                    and result.get("execute") is True
                ]
                if run_id == child_id:
                    assert len(prepares) == 1
                    receipts = [
                        payload["evidence"]
                        for name, payload, _ in updates
                        if name == "coding_receipt"
                        and payload.get("kind") == "create_not_dispatched"
                    ]
                    assert receipts and all(value == proof for value in receipts)
                await replay_temporal_history(history, namespace=client.namespace)
                (tmp_path / (run_id + ".history.json")).write_text(history.to_json())
            effects = await admin.execute(
                sql.SQL("SELECT state FROM {}.ralf_temporal_effects").format(sql.Identifier(schema))
            )
            assert [row[0] for row in await effects.fetchall()] != ["adopted"]
            assert (
                await assembly._runtime.tools.get(
                    "coding"
                ).handler.runner._journal.pending_resources(scope)
                == ()
            )
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "binding": 21 if composition else 20,
                        "mode": "original_no_submit_cold_recovery",
                        "run_id": child_id,
                        "execution_epoch": epoch,
                        "action_id": again["id"],
                        "attempt_id": again["attempts"][0]["id"],
                        "prepare_grants": 1,
                        "create_count": 0,
                        "start_count": 0,
                        "native_submissions": 0,
                        "proof_digest": proof["proof_digest"],
                        "broker_pid": physical[0]["broker_pid"],
                        "helpers_ended": True,
                        "capacity_released": True,
                        "unknown_cost": 1,
                        "worker_count": len(processes),
                        "histories_replayed": len(histories),
                    },
                    indent=2,
                )
            )
            cleanup["helpers_ended"] = True
        finally:
            try:
                if assembly is not None:
                    await assembly.aclose(wait_timeout=20)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
                cleanup["workers_ended"] = all(
                    process.returncode is not None for process in processes
                )
                # Discover only this probe's original declared directories.
                for path in root.glob("*/environment.json"):
                    declaration = (
                        json.loads(path.read_text()).get("create_operation", {}).get("declaration")
                    )
                    if declaration is not None:
                        controls.add(Path(declaration["control_directory"]["path"]))
                for control in controls:
                    assert control.parent == Path("/private/tmp") and control.name.startswith(
                        "ralf-c-"
                    )
                    assert not (control / "control.sock").exists(), (
                        "Original broker endpoint remains live"
                    )
                    control.rmdir()
                cleanup["control_directories_removed"] = all(not path.exists() for path in controls)
                sock.close()
                socket_path.unlink(missing_ok=True)
                try:
                    await admin.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
                    cleanup["schema_dropped"] = True
                finally:
                    await admin.close()
                    (tmp_path / "cleanup.json").write_text(json.dumps(cleanup, indent=2))

    asyncio.run(asyncio.wait_for(run(), 200))


if __name__ == "__main__":
    logging.getLogger("temporalio").setLevel(logging.WARNING)
    from tests.test_temporal_coding_create_supervision_integration import (
        _worker as canonical_worker,
    )

    asyncio.run(canonical_worker())
