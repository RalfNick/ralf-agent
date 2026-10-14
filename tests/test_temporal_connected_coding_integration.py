"""Real History/PG, cold Workers, and a synthetic authenticated native stdio peer.

This proves structural ownership and recovery, not real native/model quality.
"""

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    ModelParentVerificationStage,
    ModelResponse,
    ParentCompletionPolicy,
    ParentCompletionVerdict,
    Scope,
    TeamSpec,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from ralf_agent.codex_model_connection import CodexModelConnection
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.connected_coding_fixture import connected_native_fixture
from tests.temporal_coding_worker_fixture import Provider
from tests.test_temporal_coding_owned_service import completed_updates
from tests.test_temporal_coding_service import wait_until

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires actual Temporal and PostgreSQL",
)


class StructuralProvider(Provider):
    """Fixed proposal for the hidden managed planner; no model quality claim."""

    identity = {"kind": "coding-orchestration-structural-peer", "version": "110"}

    async def complete(self, messages, tools):
        if not tools:
            if any("structural-verdict" in str(message.get("content", "")) for message in messages):
                return ModelResponse(
                    output={"status": "accept", "feedback": None, "evidence_ids": []}
                )
            return ModelResponse(
                output={
                    "steps": [
                        {"id": "proposal-node", "member": "actual-member", "input": "fixed task"},
                    ]
                }
            )
        return await super().complete(messages, tools)


class StructuralCompletionGate:
    identity = {"kind": "coding-structural-completion-gate", "version": "110"}

    def verify(self, request):
        return ParentCompletionVerdict(
            "accept", evidence_ids=[child["id"] for child in request.children]
        )


async def _application(directory):
    data = json.loads((directory / "application.json").read_text())
    registry = ComponentRegistry()
    registry.register(
        "provider", "connected-structural-peer", lambda config, context: StructuralProvider()
    )
    registry.register(
        "parent_completion_policies",
        "connected-structural-check",
        lambda config, context: {
            "checked": ParentCompletionPolicy(
                StructuralCompletionGate(),
                model_stage=ModelParentVerificationStage(
                    instructions="Return fixed structural-verdict."
                ),
                verifier_budget=2,
            ),
        },
    )
    scope = Scope(**data["scope"])
    assembly = await TemporalRuntimeBuilder(registry, base_dir=directory).abuild(
        TemporalProfile(**data["profile"]), scope=scope
    )
    return assembly, scope, data["queue"]


async def _worker():
    from temporalio.client import Client

    directory = Path(os.environ["RALF_CONNECTED_DIRECTORY"])
    assembly, _, queue = await _application(directory)
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        await assembly.start_worker(client, task_queue=queue)
        print("CONNECTED_WORKER_READY", flush=True)
        await asyncio.Event().wait()
    finally:
        await assembly.aclose(wait_timeout=30)


def test_current_worker_refuses_actual_previous_selected_metadata_before_resources(tmp_path):
    from copy import deepcopy

    from ralf_agent.temporal import TemporalEngine
    from ralf_agent.temporal_coding_protocol import check

    path = os.getenv("RALF_TEST_PREVIOUS_CODING_MANIFEST")
    if not path:
        pytest.skip("Requires a manifest captured from the immutable matching dev108 Worker")
    previous = json.loads(Path(path).read_text())
    assert previous["binding_protocol"] == 13
    assert previous["coding_execution_protocol"]["version"] == 1
    assert previous["coding_composition_protocol"]["version"] == 2

    class Client:
        namespace = "default"

        def __getattr__(self, name):
            raise AssertionError("Previous selected metadata reached SDK business I/O")

    class Runtime:
        coding_execution = True

        def __getattr__(self, name):
            raise AssertionError("Previous selected metadata reached resource registration")

    with pytest.raises(DefinitionMismatch):
        TemporalEngine(Client(), task_queue="refused-before-business", release=previous)
    for binding in (13, 14, 15):
        candidate = deepcopy(previous)
        candidate["binding_protocol"] = binding
        if binding == 14:
            candidate.pop("coding_composition_protocol")
        with pytest.raises(DefinitionMismatch):
            check(Runtime(), candidate)
    assert list(tmp_path.iterdir()) == []


def test_current_worker_refuses_actual_dev109_and_relabelled_selection_before_resources(tmp_path):
    from copy import deepcopy

    from ralf_agent.temporal import TemporalEngine
    from ralf_agent.temporal_coding_protocol import check

    path = os.getenv("RALF_TEST_PREVIOUS109_CODING_MANIFEST")
    if not path:
        pytest.skip("Requires actual selected15 captured from the immutable dev109 Worker")
    previous = json.loads(Path(path).read_text())
    assert previous["binding_protocol"] == 15
    assert previous["coding_execution_protocol"]["version"] == 2
    assert previous["coding_composition_protocol"]["version"] == 3

    class Client:
        namespace = "default"

        def __getattr__(self, name):
            raise AssertionError("Old selection reached business SDK I/O")

    class Runtime:
        coding_execution = True

        def __getattr__(self, name):
            raise AssertionError("Relabelled selection reached actual resources")

    with pytest.raises(DefinitionMismatch):
        TemporalEngine(Client(), task_queue="old-before-resources", release=previous)
    for binding in (15, 16, 17):
        candidate = deepcopy(previous)
        candidate["binding_protocol"] = binding
        if binding == 16:
            candidate.pop("coding_composition_protocol")
            candidate["coding_execution_protocol"]["version"] = 3
        elif binding == 17:
            candidate["coding_execution_protocol"]["version"] = 3
            candidate["coding_composition_protocol"].update(
                version=4, topology="bounded-agent-orchestration"
            )
        with pytest.raises(DefinitionMismatch):
            check(Runtime(), candidate)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "parent_kind,mode",
    [
        (kind, mode)
        for kind in (
            "native",
            "graph",
            "team",
            "router",
            "supervisor",
            "dynamic-flat",
            "dynamic-dag",
            "dynamic-model",
            "checked-team",
        )
        for mode in ("approval_cold_restart", "running_cancel")
    ]
    + [(kind, "owned_close") for kind in ("team", "dynamic-dag")],
)
def test_connected_original_action_approval_recovery_and_cancel(
    tmp_path, monkeypatch, parent_kind, mode
):
    composition = parent_kind != "native"

    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "connected_109_" + uuid.uuid4().hex
        admin = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = psycopg.conninfo.make_conninfo(
            os.environ["RALF_TEST_POSTGRES_DSN"], options="-c search_path=" + schema
        )
        canary = "synthetic-connected-" + secrets.token_hex(24)
        monkeypatch.setenv("RALF_CONNECTED_SCOPED_DSN", scoped_dsn)
        monkeypatch.setenv("RALF_CONNECTED_TEST_KEY", canary)
        root = tmp_path / "native"
        root.mkdir(mode=0o700)
        connection = CodexModelConnection(
            "https://api.deepseek.com",
            "deepseek-flash",
            "RALF_CONNECTED_TEST_KEY",
            "structural",
            "1",
        )
        cli = connected_native_fixture(
            tmp_path, connection, "completed" if mode == "approval_cold_restart" else "hang_turn"
        )
        sock = socket.socket(socket.AF_UNIX)
        sock_path = Path("/private/tmp") / ("ralf-connected-" + uuid.uuid4().hex[:12] + ".sock")
        sock.bind(str(sock_path))
        cli.write_text(
            cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(sock_path))
        )
        queue = "connected-109-" + uuid.uuid4().hex
        scope = Scope("connected-service", queue)
        profile = TemporalProfile(
            "connected-structural",
            "109",
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
                        "description": "Finite connected structural task",
                        "cost": 1,
                        "runner_root": str(root),
                        "fixed_dependencies": {"deployment": queue},
                        "docker_executable": str(cli),
                        "docker_host": "unix://" + str(sock_path),
                        "request_timeout": 30,
                        "connection": connection.to_dict(),
                    },
                },
            },
            execution={"coding_execution": True, "coding_composition": composition},
        )
        if parent_kind == "checked-team":
            data = profile.to_dict()
            data["components"]["parent_completion_policies"] = {
                "adapter": "connected-structural-check"
            }
            profile = TemporalProfile(**data)
        (tmp_path / "application.json").write_text(
            json.dumps(
                {
                    "profile": profile.to_dict(),
                    "scope": asdict(scope),
                    "queue": queue,
                    "schema": schema,
                }
            )
        )
        assembly = None
        processes = []

        async def start_worker():
            log = tmp_path / f"worker-{len(processes)}.log"
            test_root = Path(__file__).parents[1]
            paths = [str(test_root)]
            if (test_root / "src" / "ralf_agent" / "__init__.py").is_file():
                paths.append(str(test_root / "src"))
            env = {
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
                        "tests.test_temporal_connected_coding_integration",
                        "--worker",
                    ],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            await wait_until(
                lambda: asyncio.to_thread(log.read_text),
                lambda value: "CONNECTED_WORKER_READY" in value or process.poll() is not None,
            )
            assert process.poll() is None, log.read_text()
            return process

        try:
            assembly, _, _ = await _application(tmp_path)
            runtime = assembly._runtime
            published_release = assembly.release
            native = runtime.tools.get("coding").handler.runner
            journal = native._journal
            assert journal._effect is runtime.journal
            assert assembly.release["binding_protocol"] == (21 if composition else 20)
            assert assembly.release["coding_execution_protocol"]["version"] == 5
            if composition:
                assert assembly.release["coding_composition_protocol"]["version"] == 6
            first = await start_worker()
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            engine = assembly.create_engine(
                client, task_queue=queue, activity_timeout=40, drive_timeout=40
            )
            spec = AgentSpec("connected", "Perform approved connected Coding", tools=("coding",))
            task = "fixed task"
            if parent_kind == "graph":
                definition = GraphWorkflowSpec(
                    "connected-graph", [GraphNode("only", agent=spec)], max_concurrency=2
                )
            elif parent_kind in {"team", "router", "supervisor", "checked-team"}:
                config = {}
                if parent_kind == "router":
                    config = {"routes": {"code": "actual-member"}}
                    task = {"route": "code", "task": "fixed task"}
                elif parent_kind == "supervisor":
                    config = {"supervisor": "actual-member"}
                definition = TeamSpec(
                    "connected-team",
                    {"actual-member": spec},
                    strategy="sequential"
                    if parent_kind in {"team", "checked-team"}
                    else parent_kind,
                    strategy_config=config,
                    max_concurrency=2,
                    completion_policy="checked" if parent_kind == "checked-team" else None,
                )
            elif parent_kind.startswith("dynamic-"):
                definition = DynamicWorkflowSpec(
                    "connected-plan",
                    {"actual-member": spec},
                    planner="model" if parent_kind == "dynamic-model" else "rule",
                    plan_mode="dag" if parent_kind == "dynamic-dag" else "flat",
                    max_concurrency=2,
                )
            else:
                definition = spec
            handle = await engine.submit(definition, task, command_id="submit", budget=16)
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: value.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            child_id = pending.get("run_id", handle.run_id)
            child_sdk = client.get_workflow_handle(child_id)
            child_epoch = (await child_sdk.describe()).run_id
            assert list(root.iterdir()) == []
            assert not (tmp_path / "auth-methods.txt").exists()
            if mode == "approval_cold_restart":
                first.kill()
                await asyncio.to_thread(first.wait, timeout=5)
                await start_worker()
                assert (
                    await engine.submit(definition, task, command_id="submit", budget=16) == handle
                )
                recovered = await engine.status(handle.run_id)
                assert recovered.pending[0]["action_id"] == pending["action_id"]
                assert recovered.pending[0]["digest"] == pending["digest"]
                assert (await child_sdk.describe()).run_id == child_epoch
            await engine.approve(
                child_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            counter = tmp_path / "native-submissions.jsonl"
            if mode in {"running_cancel", "owned_close"}:
                await wait_until(
                    lambda: asyncio.to_thread(
                        lambda: counter.read_text() if counter.exists() else ""
                    ),
                    lambda value: len(value.splitlines()) == 2,
                )
                if mode == "owned_close":
                    await assembly.aclose(wait_timeout=40)
                    with pytest.raises(Exception, match="TemporalEngine is closed"):
                        await engine.status(handle.run_id)
                    # A closed owned facade cannot observe. The original
                    # borrowed SDK connection can reconnect to the same Run.
                    engine = TemporalEngine(
                        client,
                        task_queue=queue,
                        release=published_release,
                        scope=scope,
                    )
                else:
                    await engine.cancel(handle.run_id, command_id="cancel")
            final = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: (
                    value.state == ("succeeded" if mode == "approval_cold_restart" else "cancelled")
                ),
                wait_seconds=90,
            )
            raw = await child_sdk.query("view", {"scope": asdict(scope), "kind": "diagnostics"})
            actions = [action for action in raw["snapshot"]["actions"] if action["kind"] == "tool"]
            assert len(actions) == 1 and actions[0]["id"] == pending["action_id"]
            action = actions[0]
            assert len(action["attempts"]) == 1
            original = action["delegated_execution"]
            dispatch = original["request"]["dispatch"]
            assert dispatch["action_id"] == action["id"]
            assert dispatch["attempt_id"] == action["attempts"][0]["id"]
            assert dispatch["run_id"] == child_id and dispatch["execution_epoch"] == child_epoch
            assert original["fenced"] is True and original["pending_stop"] is False
            assert len(raw["workflow"]["tool_executions"]) == 1
            submissions = [json.loads(line) for line in counter.read_text().splitlines()]
            assert [message["method"] for message in submissions] == ["thread/start", "turn/start"]
            assert (tmp_path / "auth-methods.txt").read_text().splitlines() == [
                "account/read",
                "account/login/start",
                "account/read",
            ]
            docker = json.loads((tmp_path / "docker.json").read_text())
            assert docker["containers"] == {} and docker["removed"] == [
                original["prepared"]["container_id"]
            ]
            if mode != "owned_close":
                assert await journal.pending_resources(scope) == ()
            rows = await admin.execute(
                sql.SQL("SELECT record FROM {}.ralf_temporal_coding_resources").format(
                    sql.Identifier(schema)
                )
            )
            resources = [json.loads(row[0]) for row in await rows.fetchall()]
            assert len(resources) == 1
            assert resources[0]["request"]["dispatch"] == dispatch
            assert resources[0]["pending_stop"] is False
            effect = await admin.execute(
                sql.SQL("SELECT state FROM {}.ralf_temporal_effects").format(sql.Identifier(schema))
            )
            effect_rows = await effect.fetchall()
            assert len(effect_rows) == 1
            assert (effect_rows[0][0] == "adopted") is (mode == "approval_cold_restart")
            if composition:
                proof = await wait_until(
                    lambda: client.get_workflow_handle(handle.run_id).query(
                        "view", {"scope": asdict(scope), "kind": "coding_composition_proof"}
                    ),
                    lambda value: value["physical_stopped"] is True,
                )
                assert proof["execution_epoch"] == proof["original_execution_epoch"]
            histories = {handle.run_id, child_id}
            if composition:
                children = await client.get_workflow_handle(handle.run_id).query(
                    "view", {"scope": asdict(scope), "kind": "coding_composition_children"}
                )
                histories.update(call["run_id"] for call in children)
                assert all(call["planning_revision"] == 0 for call in children)
                if parent_kind == "dynamic-model":
                    planners = [call for call in children if call["member"] == "@planner"]
                    assert len(planners) == 1
                    assert planners[0]["physical_stop_proof"]["physical_stopped"] is True
                    assert planners[0]["request"]["definition"]["steps"][0]["tools"] == []
                if parent_kind == "checked-team" and mode == "approval_cold_restart":
                    verifiers = [call for call in children if call["member"] == "@verifier"]
                    assert len(verifiers) == 1
                    assert verifiers[0]["physical_stop_proof"]["physical_stopped"] is True
                    assert verifiers[0]["request"]["definition"]["steps"][0]["tools"] == []
            for run_id in histories:
                history = await client.get_workflow_handle(run_id).fetch_history()
                assert canary not in history.to_json()
                updates = await completed_updates(history)
                assert not any(
                    payload.get("method", "").startswith("account/") for _, payload, _ in updates
                )
                await replay_temporal_history(history, namespace=client.namespace)
                (tmp_path / (run_id + ".history.json")).write_text(history.to_json())
            for table in (
                "ralf_temporal_runner_effects",
                "ralf_temporal_coding_resources",
                "ralf_temporal_effects",
                "ralf_temporal_effect_evidence",
            ):
                rows = await admin.execute(
                    sql.SQL("SELECT row_to_json(t)::text FROM {}.{} t").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
                assert all(canary not in row[0] for row in await rows.fetchall())
            for file in tmp_path.rglob("*"):
                if file.is_file():
                    assert canary.encode() not in file.read_bytes(), file.name
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "binding": 19 if composition else 18,
                        "parent_kind": parent_kind,
                        "mode": mode,
                        "state": final.state,
                        "action_id": action["id"],
                        "attempt_id": dispatch["attempt_id"],
                        "effect_key": dispatch["effect_key"],
                        "execution_epoch": child_epoch,
                        "native_submissions": 2,
                        "auth_methods": 3,
                        "worker_count": len(processes),
                        "fenced": True,
                        "credential_absent": True,
                    },
                    indent=2,
                )
            )
        finally:
            try:
                # The original Worker must still receive registry/stop updates
                # while the owned facade retires its selected composition.
                if assembly is not None:
                    await assembly.aclose(wait_timeout=40)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
                sock.close()
                sock_path.unlink(missing_ok=True)
                try:
                    await admin.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
                finally:
                    await admin.close()

    asyncio.run(asyncio.wait_for(run(), 240))


if __name__ == "__main__":
    # Registry implementation identity includes the defining module. Use the
    # same canonical fixture module in both host and separate Worker process.
    from tests.test_temporal_connected_coding_integration import _worker as canonical_worker

    asyncio.run(canonical_worker())
