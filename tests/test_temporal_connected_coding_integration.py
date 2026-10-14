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
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
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
    WorkflowSpec,
)
from ralf_agent.codex_model_connection import CodexModelConnection
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from ralf_agent.types import digest, submission_request
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


RECURSIVE_KINDS = {"team-sequence", "nested-team-dynamic-sequence"}


def _recursive_definition(parent_kind, coding_agent):
    from ralf_agent.binding_paths import agent_paths

    sequence = WorkflowSpec(
        "connected-sequence",
        (AgentSpec("plain", "Complete the first step without tools."), coding_agent),
    )
    member = sequence
    if parent_kind == "nested-team-dynamic-sequence":
        member = DynamicWorkflowSpec(
            "connected-nested-plan",
            {"nested-team": TeamSpec("connected-inner-team", {"steps": sequence})},
            planner="rule",
            plan_mode="flat",
            max_concurrency=1,
        )
    source = TeamSpec("connected-recursive-root", {"nested": member}, max_concurrency=1)
    bindings = {
        path: AgentBindingDescriptor(
            runner=BindingSelection.ref("native", "1")
            if agent["tools"]
            else BindingSelection.disabled(),
            tool_set=BindingSelection.inherit() if agent["tools"] else BindingSelection.disabled(),
        )
        for path, agent in agent_paths(
            submission_request(source, "fixed task")["definition"]
        ).items()
    }
    assert len(bindings) == 2
    return BoundDefinition(source, bindings)


async def _recursive_evidence(client, scope, root_id, *, stopped):
    """Read and validate every original immediate edge, without issuing controls."""
    from ralf_agent.binding_paths import agent_paths
    from ralf_agent.temporal_bindings import request_release_digest

    proofs, edges = {}, []

    async def visit(run_id, depth):
        assert depth <= 3 and run_id not in proofs
        current = client.get_workflow_handle(run_id)
        epoch = (await current.describe()).run_id
        handle = client.get_workflow_handle(run_id, run_id=epoch)
        proof = await wait_until(
            lambda: handle.query(
                "view", {"scope": asdict(scope), "kind": "coding_composition_proof"}
            ),
            lambda value: not stopped or value["physical_stopped"] is True,
            wait_seconds=30,
        )
        assert proof["run_id"] == run_id
        assert proof["execution_epoch"] == proof["original_execution_epoch"] == epoch
        assert proof["request_digest"] == digest(proof["request"])
        assert proof["release_digest"] == request_release_digest(
            proof["request"], proof["manifest"]
        )
        assert proof["proof_digest"] == digest(
            {key: value for key, value in proof.items() if key != "proof_digest"}
        )
        assert proof["manifest"]["binding_protocol"] == 23
        assert proof["scope"] == asdict(scope)
        agents = agent_paths(proof["request"]["definition"])
        assert set(proof["request"]["agent_bindings"]) == set(agents)
        for path, agent in agents.items():
            descriptor = proof["request"]["agent_bindings"][path]
            expected = (
                BindingSelection.ref("native", "1")
                if agent["tools"]
                else BindingSelection.disabled()
            )
            assert descriptor["runner"] == expected.to_dict()
            if not agent["tools"]:
                assert descriptor["tool_set"] == BindingSelection.disabled().to_dict()
        proofs[run_id] = proof
        children = await handle.query(
            "view", {"scope": asdict(scope), "kind": "coding_composition_children"}
        )
        if proof["request"]["definition"]["kind"] == "sequence":
            assert children == []
            assert [step["name"] for step in proof["request"]["definition"]["steps"]] == [
                "plain",
                "connected",
            ]
            return
        assert len(children) == 1
        for call in children:
            link = call["request"]["coding_parent"]
            assert call["planning_revision"] == link["planning_revision"] == 0
            assert link["parent_run_id"] == run_id
            assert link["parent_execution_epoch"] == epoch
            assert link["parent_request_digest"] == proof["request_digest"]
            assert link["parent_release_digest"] == proof["release_digest"]
            assert link["member"] == call["member"]
            assert link["call_id"] == call["id"] and link["command_id"] == call["command_id"]
            assert link["cap"] == call["cap"] == call["request"]["budget"]
            assert link["depth"] == call["depth"] == depth + 1
            assert link["child_run_id"] == call["run_id"]
            child_base = {
                key: value for key, value in call["request"].items() if key != "coding_parent"
            }
            assert link["child_projection_digest"] == digest(child_base)
            assert call["child_request_digest"] == digest(call["request"])
            await visit(call["run_id"], depth + 1)
            child = proofs[call["run_id"]]
            assert child["request"] == call["request"]
            assert child["namespace"] == link["namespace"] == proof["namespace"]
            assert call["child_execution"]["execution_epoch"] == child["execution_epoch"]
            if stopped:
                adopted = call["physical_stop_proof"]
                assert adopted["physical_stopped"] is True
                assert adopted["execution_epoch"] == child["execution_epoch"]
                assert adopted["request_digest"] == child["request_digest"]
                assert adopted["proof_digest"] == digest(
                    {key: value for key, value in adopted.items() if key != "proof_digest"}
                )
            edges.append({"parent": run_id, "child": call["run_id"], "depth": depth + 1})

    await visit(root_id, 0)
    return proofs, edges


async def _cleanup_owned(assembly, processes, sock, sock_path, admin, schema, directory):
    """Retire actual Workers and retain recovery resources after a close failure."""
    failures = []
    workers = []

    async def attempt(label, operation, wait_seconds):
        try:
            await asyncio.wait_for(operation(), wait_seconds)
        except BaseException:
            failures.append(label)

    if assembly is not None:
        await attempt("assembly", lambda: assembly.aclose(wait_timeout=30), 40)
    preserve = "assembly" in failures
    for index, process in enumerate(processes):

        async def retire(process=process):
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
            assert process.poll() is not None

        await attempt(f"worker-{index}", retire, 7)
        workers.append({"index": index, "pid": process.pid, "returncode": process.poll()})
    preserve = preserve or any(label.startswith("worker-") for label in failures)
    if sock is not None and not preserve:

        async def close_socket():
            sock.close()

        await attempt("socket", close_socket, 2)
    if sock_path is not None and not preserve:

        async def unlink_socket():
            sock_path.unlink(missing_ok=True)

        await attempt("socket-path", unlink_socket, 2)
    if admin is not None:
        from psycopg import sql

        if not preserve:
            await attempt(
                "schema",
                lambda: admin.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                ),
                10,
            )
        await attempt("admin", admin.close, 10)
    socket_exists = sock_path is not None and sock_path.exists()
    (directory / "cleanup-responsibility.json").write_text(
        json.dumps(
            {
                "failures": failures,
                "assembly_close_failed": "assembly" in failures,
                "recovery_resources_retained": preserve,
                "workers": workers,
                "all_workers_exited": all(worker["returncode"] is not None for worker in workers),
                "schema": schema,
                "schema_retained_for_recovery": preserve and admin is not None,
                "socket_path": None if sock_path is None else str(sock_path),
                "socket_path_exists": socket_exists,
                "socket_inode": sock_path.stat().st_ino if socket_exists else None,
                "socket_close_deferred_to_driver_exit": preserve and sock is not None,
                "driver_pid": os.getpid(),
                "recovery_application": str(directory / "application.json"),
                "recovery_dsn": "derive from private service config using schema search_path",
                "original_histories": str(directory / "failure-before-cleanup"),
            },
            indent=2,
        )
    )
    if failures:
        raise AssertionError("Bounded owned fixture cleanup failed: " + ", ".join(failures))


async def _failure_evidence(directory, client, scope, root_id, admin, schema, canary, observed):
    """Capture original read-only evidence while receivers and PG still exist."""
    from psycopg import sql

    target = directory / "failure-before-cleanup"
    target.mkdir(mode=0o700, exist_ok=True)
    failures, histories = [], []
    secret = None if canary is None else canary.encode()

    def save(name, value):
        encoded = json.dumps(value, indent=2)
        if secret is not None and secret in encoded.encode():
            raise AssertionError("Failure evidence contains a synthetic credential")
        (target / name).write_text(encoded)

    async def read(label, operation):
        try:
            return await asyncio.wait_for(operation(), 10)
        except Exception as exc:
            failures.append({"operation": label, "error_type": type(exc).__name__})
            return None

    save("observed-status.json", observed)
    pending, seen, handles = ([] if root_id is None else [root_id]), set(), {}
    while client is not None and pending:
        run_id = pending.pop()
        if run_id in seen:
            continue
        seen.add(run_id)
        handle = client.get_workflow_handle(run_id)
        handles[run_id] = handle
        history = await read("history:" + run_id, handle.fetch_history)
        if history is not None:
            if secret is not None and any(
                secret in event.SerializeToString() for event in history.events
            ):
                raise AssertionError("Failure History contains a synthetic credential")
            save(run_id + ".history.json", json.loads(history.to_json()))
            histories.append(run_id)
            for event in history.events:
                if event.HasField("child_workflow_execution_started_event_attributes"):
                    pending.append(
                        event.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
                    )
    if admin is not None:
        for table in ("ralf_temporal_runner_effects", "ralf_temporal_coding_resources"):

            async def records(table=table):
                cursor = await admin.execute(
                    sql.SQL("SELECT record FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
                return [json.loads(row[0]) for row in await cursor.fetchall()]

            values = await read(table, records)
            if values is not None:
                selected = []
                for record in values:
                    if secret is not None and secret in json.dumps(record).encode():
                        raise AssertionError(
                            "Failure PostgreSQL evidence contains a synthetic credential"
                        )
                    request = record.get("request", record.get("binding", {}).get("request", {}))
                    dispatch = request.get(
                        "dispatch", record.get("binding", {}).get("dispatch", {})
                    )
                    selected.append(
                        {
                            "record_digest": digest(record),
                            "stage": record.get("stage"),
                            "thread_id": record.get("thread_id"),
                            "turn_id": record.get("turn_id"),
                            "process_epoch": record.get("process_epoch"),
                            "pending_stop": record.get("pending_stop"),
                            "cancel_requested": record.get("cancel_requested"),
                            "request_digest": request.get("request_digest"),
                            "dispatch": {
                                key: dispatch.get(key)
                                for key in (
                                    "run_id",
                                    "action_id",
                                    "attempt_id",
                                    "effect_key",
                                    "execution_epoch",
                                )
                            },
                            "prepared": {
                                key: (record.get("prepared") or {}).get(key)
                                for key in ("container_id", "generation", "stopped", "fenced")
                            },
                            "stop": {
                                key: (record.get("stop") or {}).get(key)
                                for key in ("container_id", "generation", "stopped", "fenced")
                            },
                            "observations": [
                                {
                                    key: item.get(key)
                                    for key in (
                                        "kind",
                                        "code",
                                        "native_status",
                                        "thread_id",
                                        "turn_id",
                                    )
                                }
                                for item in record.get("observations", [])
                            ],
                        }
                    )
                save(table + ".json", selected)

        async def effects():
            cursor = await admin.execute(
                sql.SQL(
                    "SELECT run_id,action_id,attempt_id,effect_key,state,adopted_result_digest FROM {}.ralf_temporal_effects"
                ).format(sql.Identifier(schema))
            )
            return [
                dict(
                    zip(
                        (
                            "run_id",
                            "action_id",
                            "attempt_id",
                            "effect_key",
                            "state",
                            "adopted_result_digest",
                        ),
                        row,
                        strict=True,
                    )
                )
                for row in await cursor.fetchall()
            ]

        value = await read("effect-states", effects)
        if value is not None:
            save("effect-states.json", value)
    for run_id, handle in handles.items():
        for kind in ("diagnostics", "coding_composition_proof", "coding_composition_children"):
            value = await read(
                kind + ":" + run_id,
                lambda kind=kind, handle=handle: handle.query(
                    "view", {"scope": asdict(scope), "kind": kind}
                ),
            )
            if value is not None:
                save(run_id + "." + kind + ".json", value)
    save(
        "capture.json", {"history_ids": histories, "read_failures": failures, "canary_absent": True}
    )


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
            "team-sequence",
            "nested-team-dynamic-sequence",
        )
        for mode in ("approval_cold_restart", "running_cancel")
    ]
    + [
        (kind, "owned_close")
        for kind in ("team", "dynamic-dag", "team-sequence", "nested-team-dynamic-sequence")
    ],
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
        admin, sock, sock_path, assembly = None, None, None, None
        client, handle, scope, canary = None, None, None, None
        observed = []
        processes = []
        try:
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
                tmp_path,
                connection,
                "completed" if mode == "approval_cold_restart" else "hang_turn",
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
                            "request_timeout": 60 if parent_kind in RECURSIVE_KINDS else 30,
                            "connection": connection.to_dict(),
                        },
                    },
                },
                execution={"coding_execution": True, "coding_composition": composition},
                binding_components=[
                    {
                        "role": "runner",
                        "component_id": "native",
                        "version": "1",
                        "component": {"adapter": "registered-tool", "config": {"name": "coding"}},
                    }
                ]
                if parent_kind in RECURSIVE_KINDS
                else None,
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

            assembly, _, _ = await _application(tmp_path)
            runtime = assembly._runtime
            published_release = assembly.release
            native = runtime.tools.get("coding").handler.runner
            journal = native._journal
            assert journal._effect is runtime.journal
            assert assembly.release["binding_protocol"] == (23 if composition else 22)
            assert assembly.release["coding_execution_protocol"]["version"] == 6
            if composition:
                assert assembly.release["coding_composition_protocol"]["version"] == 7
            first = await start_worker()
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            engine = assembly.create_engine(
                client,
                task_queue=queue,
                activity_timeout=80 if parent_kind in RECURSIVE_KINDS else 40,
                drive_timeout=80 if parent_kind in RECURSIVE_KINDS else 40,
            )
            spec = AgentSpec("connected", "Perform approved connected Coding", tools=("coding",))
            task = "fixed task"
            if parent_kind in RECURSIVE_KINDS:
                definition = _recursive_definition(parent_kind, spec)
            elif parent_kind == "graph":
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

            async def status():
                value = await engine.status(handle.run_id)
                observed[:] = [asdict(value)]
                return value

            waiting = await wait_until(
                status,
                lambda value: value.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            child_id = pending.get("run_id", handle.run_id)
            child_sdk = client.get_workflow_handle(child_id)
            child_epoch = (await child_sdk.describe()).run_id
            before_tree = None
            if parent_kind in RECURSIVE_KINDS:
                before_tree, _ = await _recursive_evidence(
                    client, scope, handle.run_id, stopped=False
                )
                leaves = [
                    run_id
                    for run_id, proof in before_tree.items()
                    if proof["request"]["definition"]["kind"] == "sequence"
                ]
                assert leaves == [child_id]
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
                if before_tree is not None:
                    recovered_tree, _ = await _recursive_evidence(
                        client, scope, handle.run_id, stopped=False
                    )
                    assert {
                        run_id: proof["execution_epoch"] for run_id, proof in recovered_tree.items()
                    } == {run_id: proof["execution_epoch"] for run_id, proof in before_tree.items()}
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
                    wait_seconds=80 if parent_kind in RECURSIVE_KINDS else 30,
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
                status,
                lambda value: (
                    value.state == ("succeeded" if mode == "approval_cold_restart" else "cancelled")
                ),
                wait_seconds=90,
            )
            raw = await child_sdk.query("view", {"scope": asdict(scope), "kind": "diagnostics"})
            actions = [action for action in raw["snapshot"]["actions"] if action["kind"] == "tool"]
            assert len(actions) == 1 and actions[0]["id"] == pending["action_id"]
            action = actions[0]
            if parent_kind in RECURSIVE_KINDS:
                assert raw["workflow"]["steps"] == 2 and action["node"] == 1
                assert any(
                    item["kind"] == "model" and item["node"] == 0 and item["status"] == "completed"
                    for item in raw["snapshot"]["actions"]
                )
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
            tree_edges = []
            if parent_kind in RECURSIVE_KINDS:
                tree, tree_edges = await _recursive_evidence(
                    client, scope, handle.run_id, stopped=True
                )
                expected = 2 if parent_kind == "team-sequence" else 4
                assert len(tree) == expected and len(tree_edges) == expected - 1
                assert {run_id: proof["execution_epoch"] for run_id, proof in tree.items()} == {
                    run_id: proof["execution_epoch"] for run_id, proof in before_tree.items()
                }
                histories.update(tree)
                (tmp_path / "recursive-tree.json").write_text(
                    json.dumps({"nodes": tree, "edges": tree_edges}, indent=2)
                )
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
                        "binding": published_release["binding_protocol"],
                        "native_version": published_release["coding_execution_protocol"]["version"],
                        "composition_version": published_release.get(
                            "coding_composition_protocol", {}
                        ).get("version"),
                        "request_timeout": 60 if parent_kind in RECURSIVE_KINDS else 30,
                        "activity_timeout": 80 if parent_kind in RECURSIVE_KINDS else 40,
                        "counter_wait_seconds": 80 if parent_kind in RECURSIVE_KINDS else 30,
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
                        "history_ids": sorted(histories),
                        "recursive_edges": tree_edges,
                    },
                    indent=2,
                )
            )
        except BaseException:
            try:
                await asyncio.wait_for(
                    _failure_evidence(
                        tmp_path,
                        client,
                        scope,
                        None if handle is None else handle.run_id,
                        admin,
                        schema,
                        canary,
                        observed,
                    ),
                    30,
                )
            except BaseException as capture_error:
                (tmp_path / "failure-capture-error.json").write_text(
                    json.dumps({"error_type": type(capture_error).__name__})
                )
            raise
        finally:
            await _cleanup_owned(assembly, processes, sock, sock_path, admin, schema, tmp_path)

    asyncio.run(asyncio.wait_for(run(), 240))


if __name__ == "__main__":
    # Registry implementation identity includes the defining module. Use the
    # same canonical fixture module in both host and separate Worker process.
    from tests.test_temporal_connected_coding_integration import _worker as canonical_worker

    asyncio.run(canonical_worker())
