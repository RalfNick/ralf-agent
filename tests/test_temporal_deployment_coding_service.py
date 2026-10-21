"""Public Coding3 on actual Temporal/PG; physical peers are not model quality.

Services are externally owned. Every case has a unique Scope, queue, PG schema
and Runner roots. Peer Docker inventory is structural; separately gated Docker
cases delegate actual CREATE/inspect/control to the explicitly selected daemon.
"""

import asyncio
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pytest

from ralf_agent import (
    AgentSpec,
    BindingSelection,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    Scope,
    TeamSpec,
    TemporalProfile,
    WorkflowSpec,
)
from ralf_agent.binding_definitions import AgentDefinition, BoundDefinition
from ralf_agent.binding_paths import agent_paths
from ralf_agent.binding_types import AgentBindingDescriptor
from ralf_agent.errors import CapacityExceeded, CloseIncomplete, DefinitionMismatch
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.types import canonical, digest, submission_request
from tests import temporal_deployment_coding_worker_fixture as fixture
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_deployment_public_service import SDKFaultClient

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires externally owned actual Temporal and PostgreSQL",
)

TOPOLOGIES = [
    ("agent", "sdk"),
    ("sequence", "json"),
    ("graph-sequential", "sdk"),
    ("graph-parallel", "toml"),
    ("team-sequential", "sdk"),
    ("team-router", "json"),
    ("team-supervisor", "sdk"),
    ("dynamic-flat", "toml"),
    ("dynamic-dag", "sdk"),
    ("dynamic-model", "json"),
    ("checked-team", "sdk"),
    ("team-sequence", "toml"),
    ("recursive", "json"),
]


def definition(kind):
    a = AgentSpec("a", "Perform approved Coding", tools=("coding",))
    b = AgentSpec("b", "Perform approved Coding", tools=("coding_second",))
    plain = AgentSpec("plain", "Complete plain work without tools.")
    value, calls = {"task": "fixed"}, 1
    if kind == "agent":
        source = a
    elif kind == "sequence":
        source, calls = WorkflowSpec("sequence", (plain, a, a)), 2
    elif kind in {"graph-sequential", "graph-parallel"}:
        source, calls = (
            GraphWorkflowSpec(
                kind,
                (
                    GraphNode("a", agent=a),
                    GraphNode(
                        "b", agent=b, depends_on=("a",) if kind.endswith("sequential") else ()
                    ),
                    GraphNode("join", agent=plain, depends_on=("a", "b")),
                ),
                max_concurrency=2,
            ),
            2,
        )
    elif kind in {"team-sequential", "team-router", "team-supervisor", "checked-team"}:
        strategy = kind.removeprefix("team-") if kind != "checked-team" else "sequential"
        config = (
            {"routes": {"code": "actual-member"}}
            if strategy == "router"
            else ({"supervisor": "actual-member"} if strategy == "supervisor" else {})
        )
        value = {"route": "code", "task": "fixed"}
        source = TeamSpec(
            kind,
            {"actual-member": a},
            strategy=strategy,
            strategy_config=config,
            completion_policy="checked" if kind == "checked-team" else None,
        )
    elif kind.startswith("dynamic-"):
        source = DynamicWorkflowSpec(
            kind,
            {"actual-member": a},
            planner="model" if kind == "dynamic-model" else "rule",
            plan_mode="dag" if kind == "dynamic-dag" else "flat",
        )
    else:
        sequence = WorkflowSpec("nested-sequence", (plain, a))
        member = sequence
        if kind == "recursive":
            member = DynamicWorkflowSpec(
                "nested-dynamic",
                {"inner": TeamSpec("inner", {"steps": sequence})},
                plan_mode="flat",
                max_concurrency=1,
            )
        else:
            assert kind == "team-sequence"
        source = TeamSpec(kind, {"nested": member}, max_concurrency=1)
    bindings = {
        path: AgentBindingDescriptor(
            runner=BindingSelection.ref(
                "second" if agent["tools"] == ["coding_second"] else "native", "1"
            )
            if agent["tools"]
            else BindingSelection.disabled(),
            tool_set=BindingSelection.inherit() if agent["tools"] else BindingSelection.disabled(),
        )
        for path, agent in agent_paths(submission_request(source, value)["definition"]).items()
    }
    selected = (
        AgentDefinition(source, next(iter(bindings.values())))
        if kind == "agent"
        else BoundDefinition(source, bindings)
    )
    return selected, value, calls


async def _close_while_serving(assembly, directory, *, wait_timeout):
    """Caller retries incomplete close while retaining its borrowed receiver."""
    from ralf_agent.errors import CloseIncomplete

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_timeout
    attempts = 0
    while True:
        remaining = max(0, deadline - loop.time())
        try:
            await asyncio.wait_for(assembly.aclose(wait_timeout=remaining), remaining)
            return
        except CloseIncomplete as error:
            attempts += 1
            if attempts <= 64:
                with (directory / "close-retries.jsonl").open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "attempt": attempts,
                                "code": error.code,
                                "report": error.report,
                                "remaining_seconds": max(0, deadline - loop.time()),
                            }
                        )
                        + "\n"
                    )
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise
            await asyncio.sleep(min(0.05, remaining))


class CodingSystem:
    def __init__(self, directory, admin, schema, socket_owner, socket_path, data, assembly, client):
        self.directory, self.admin, self.schema = directory, admin, schema
        self.socket_owner, self.socket_path = socket_owner, socket_path
        self.data, self.assembly, self.client = data, assembly, client
        self.runtime, self.scope = assembly._runtime, Scope(**data["scope"])
        self.policy = DeploymentAdmissionPolicy(**data["policy"])
        self.queue, self.release = data["queue"], copy.deepcopy(assembly.release)
        self.workers, self.processes, self.engines, self.targets = [], [], [], set()
        self.approvals = set()
        self.expected_retention = []
        self.recovery = None
        self.engine = assembly.create_engine(
            client, task_queue=self.queue, activity_timeout=90, drive_timeout=80
        )
        self.engines.append(self.engine)

    async def candidates(self, *, scope=None, manifest=None):
        return await self.client.get_workflow_handle(registry_id(self.policy.deployment_id)).query(
            "view",
            {
                "kind": "coding_composition_candidates",
                "scope": asdict(scope or self.scope),
                "admission_policy": self.policy.identity,
                "namespace": self.data["namespace"],
                "manifest_digest": digest(manifest or self.release),
            },
        )

    async def rows(self, table):
        from psycopg import sql

        result = await self.admin.execute(
            sql.SQL("SELECT record FROM {}.{} ").format(
                sql.Identifier(self.schema), sql.Identifier(table)
            )
        )
        return [json.loads(row[0]) for row in await result.fetchall()]

    async def effect_ack_gate(self, blocked):
        from psycopg import sql

        if blocked:
            await self.admin.execute(
                sql.SQL("CREATE TABLE {}.ralf_test_ack_gate (blocked boolean)").format(
                    sql.Identifier(self.schema)
                )
            )
            await self.admin.execute(
                sql.SQL("INSERT INTO {}.ralf_test_ack_gate VALUES (true)").format(
                    sql.Identifier(self.schema)
                )
            )
            await self.admin.execute(
                sql.SQL("""CREATE FUNCTION {}.ralf_test_ack_fault() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.state='adopted' AND (SELECT blocked FROM {}.ralf_test_ack_gate) THEN
                    RAISE EXCEPTION 'Controlled effect ACK unavailable'; END IF; RETURN NEW; END $$""").format(
                    sql.Identifier(self.schema), sql.Identifier(self.schema)
                )
            )
            await self.admin.execute(
                sql.SQL(
                    "CREATE TRIGGER ralf_test_ack_fault BEFORE UPDATE ON {}.ralf_temporal_effects FOR EACH ROW EXECUTE FUNCTION {}.ralf_test_ack_fault()"
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
        else:
            await self.admin.execute(
                sql.SQL("UPDATE {}.ralf_test_ack_gate SET blocked=false").format(
                    sql.Identifier(self.schema)
                )
            )

    def facade(self, *, client=None, queue=None, release=None, scope=None, timeout=90):
        engine = TemporalEngine(
            client or self.client,
            task_queue=queue or self.queue,
            release=release or self.release,
            scope=scope or self.scope,
            activity_timeout=timeout,
            drive_timeout=80,
        )
        self.engines.append(engine)
        return engine

    async def submit(self, spec, value, *, command_id="first", engine=None):
        engine = engine or self.engine
        self.targets.add(root_run_id(self.policy.deployment_id, asdict(engine.scope), command_id))
        return await engine.submit(spec, value, command_id=command_id, budget=64)

    @asynccontextmanager
    async def worker(self):
        client = fixture.FaultClient(self.client, self.directory)
        worker = build_temporal_worker(
            client,
            task_queue=self.queue,
            runtime=self.runtime,
            release=self.release,
            max_concurrent_activities=32,
            graceful_shutdown_timeout=timedelta(seconds=1),
        )
        self.workers.append(worker)
        with fixture.definition_mismatch_trace(self.directory):
            async with worker:
                primary_error = None
                try:
                    yield worker
                except BaseException as error:
                    primary_error = error
                    try:
                        from tests.temporal_coding_primary_failure import save_primary_failure

                        save_primary_failure(self.directory, error)
                        (self.directory / "primary-failure.json").replace(
                            self.directory / "initial-body-error.json"
                        )
                    except BaseException:
                        pass  # Diagnostics must not replace the original body failure.
                    raise
                finally:
                    (self.directory / "release-turns").touch()
                    for path in self.directory.glob("block-*"):
                        path.unlink(missing_ok=True)
                    for name in ("fail-kill", "fail-kill-cid"):
                        (self.directory / name).unlink(missing_ok=True)
                    gate = await self.admin.execute(
                        "SELECT to_regclass(%s)", (self.schema + ".ralf_test_ack_gate",)
                    )
                    if (await gate.fetchone())[0] is not None:
                        await self.effect_ack_gate(False)
                    # Keep this receiver alive through native and deployment ACKs.
                    try:
                        await _close_while_serving(self.assembly, self.directory, wait_timeout=60)
                    except BaseException as error:
                        try:
                            from tests.temporal_coding_primary_failure import save_primary_failure

                            save_primary_failure(
                                self.directory,
                                error,
                                owned_tasks=(
                                    getattr(self.assembly, "_coding_stop_task", None),
                                    getattr(self.assembly, "_session_stop_task", None),
                                ),
                            )
                            (self.directory / "primary-failure.json").replace(
                                self.directory / "initial-close-wait.json"
                            )
                        except BaseException:
                            pass  # Preserve the original close failure and live owned tasks.
                        path = self.directory / "initial-close-error.json"
                        path.write_text(
                            json.dumps(
                                {
                                    "type": type(error).__name__,
                                    "code": getattr(error, "code", None),
                                    "report": getattr(error, "report", None),
                                    "obligations": getattr(error, "obligations", None),
                                },
                                sort_keys=True,
                            )
                        )
                        path.chmod(0o600)
                        if primary_error is not None:
                            raise BaseExceptionGroup(
                                "Coding Worker body and owned cleanup failed",
                                [primary_error, error],
                            ) from None
                        raise

    async def start_process(self):
        log = self.directory / f"worker-{len(self.processes)}.log"
        root = Path(__file__).parents[1]
        paths = [str(root)]
        if (root / "src" / "ralf_agent").is_dir():
            paths.append(str(root / "src"))
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": os.pathsep.join(paths),
            "RALF_DEPLOYMENT_CODING_DIRECTORY": str(self.directory),
            "RALF_DEPLOYMENT_CODING_DSN": os.environ["RALF_DEPLOYMENT_CODING_DSN"],
            "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        }
        if os.getenv("RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE") == "1":
            env["RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE"] = "1"
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-u", "-m", "tests.temporal_deployment_coding_worker_fixture"],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        self.processes.append(process)
        await _eventually(
            lambda: asyncio.to_thread(log.read_text),
            lambda value: "DEPLOYMENT_CODING_WORKER_READY" in value or process.poll() is not None,
        )
        assert process.poll() is None, log.read_text()
        return process

    async def kill(self, process):
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, timeout=5)
        assert process.poll() is not None

    async def view(self, run_id, kind="diagnostics", *, epoch=None):
        return await self.client.get_workflow_handle(
            run_id, **({"run_id": epoch} if epoch else {})
        ).query(
            "view", {"scope": asdict(self.scope), "kind": kind}, rpc_timeout=timedelta(seconds=15)
        )

    async def count(self, expected):
        observer = self.facade() if self.assembly._closed or self.assembly._closing else self.engine
        return await _eventually(
            observer.deployment_diagnostics,
            lambda value: value["counts"]["held_root_runs"] == expected,
            seconds=60,
        )

    async def approve(self, root_id, *, all_steps=False):
        seen = self.approvals
        async with asyncio.timeout(180):
            while True:
                state = await self.engine.status(root_id)
                if state.state in {"succeeded", "failed", "cancelled", "waiting_reconciliation"}:
                    return state
                for pending in state.pending:
                    key = (pending.get("run_id", root_id), pending.get("action_id"))
                    if key in seen or pending.get("kind") not in {None, "approval"}:
                        continue
                    await self.engine.approve(
                        key[0], key[1], pending["digest"], command_id="approve:" + key[1]
                    )
                    seen.add(key)
                    if not all_steps:
                        return key
                await asyncio.sleep(0.05)

    def lines(self, name):
        path = self.directory / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def committed(self, count=1):
        records = await _eventually(
            lambda: asyncio.sleep(0, result=self.lines("native-commits.jsonl")),
            lambda rows: len(rows) >= count,
            seconds=80,
        )
        evidence = []
        for record in records:
            path = Path(record["path"])
            contents = await asyncio.to_thread(path.read_bytes)
            assert contents == b"fixture artifact\n"
            os.kill(record["pid"], 0)
            evidence.append({**record, "sha256": hashlib.sha256(contents).hexdigest()})
        return evidence

    async def evidence(self, run_id, *, sealed=True):
        view = await self.view(run_id, "deployment_closure")
        proof, certificate = view["deployment"], view["seal"]
        if sealed:
            assert view["ready"] and certificate is not None
        epoch = proof["execution_epoch"]
        handle = self.client.get_workflow_handle(run_id, run_id=epoch)
        assert (await handle.describe()).run_id == proof["original_execution_epoch"] == epoch
        history = await handle.fetch_history()
        await replay_temporal_history(history, namespace=self.client.namespace)
        (self.directory / (run_id + ".history.json")).write_text(history.to_json())
        (self.directory / (run_id + ".closure.json")).write_text(json.dumps(view, sort_keys=True))
        if self.data["composition"]:
            native = await self.view(run_id, "coding_composition_proof", epoch=epoch)
            assert native["execution_epoch"] == native["original_execution_epoch"] == epoch
            if sealed:
                assert native["physical_stopped"] is True
        for call in proof["children"]:
            if call.get("deployment_execution_epoch"):
                assert (
                    call["child_execution"]["execution_epoch"] == call["deployment_execution_epoch"]
                )
                await self.evidence(call["run_id"], sealed=sealed)
        return view

    async def expect_retention(self, run_id):
        view = await self.view(run_id, "deployment_closure")
        proof = view["deployment"]
        assert view["seal"] is None and proof["admission"]["lineage"] == []
        assert proof["execution_epoch"] == proof["original_execution_epoch"]
        self.expected_retention.append(
            {
                "run_id": run_id,
                "scope": copy.deepcopy(proof["scope"]),
                "execution_epoch": proof["execution_epoch"],
            }
        )

    def assert_retained(self):
        assert self.expected_retention
        report = json.loads((self.directory / "cleanup.json").read_text())
        assert (
            report["schema_retained"] is True
            and not report["deletion_evidence"]["deletion_allowed"]
        )
        for root in self.expected_retention:
            assert root in report["deletion_evidence"]["retained_roots"]
        assert self.socket_path.exists() and (self.directory / "application.json").exists()
        assert self.recovery["socket"] is self.socket_owner

    async def capture(self):
        from psycopg import sql

        captured = {}

        for table in (
            "ralf_temporal_effects",
            "ralf_temporal_effect_evidence",
            "ralf_temporal_runner_effects",
            "ralf_temporal_coding_resources",
        ):
            exists = await self.admin.execute(
                "SELECT to_regclass(%s)", (self.schema + "." + table,)
            )
            if (await exists.fetchone())[0] is not None:
                rows = await self.admin.execute(
                    sql.SQL("SELECT row_to_json(t)::text FROM {}.{} t").format(
                        sql.Identifier(self.schema), sql.Identifier(table)
                    )
                )
                captured[table] = [json.loads(row[0]) for row in await rows.fetchall()]
                path = self.directory / (table + ".json")
                path.write_text(json.dumps(captured[table]))
                path.chmod(0o600)
        return captured

    async def cleanup(self):
        from psycopg import sql
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        (self.directory / "release-turns").touch()
        for path in self.directory.glob("block-*"):
            path.unlink(missing_ok=True)
        for name in ("fail-kill", "fail-kill-cid", "crash-after-turn", "crash-after-candidate"):
            (self.directory / name).unlink(missing_ok=True)
        gate = await self.admin.execute(
            "SELECT to_regclass(%s)", (self.schema + ".ralf_test_ack_gate",)
        )
        if (await gate.fetchone())[0] is not None:
            await self.effect_ack_gate(False)
        from tests.temporal_deployment_coding_retention import deletion_evidence

        evidence_errors = []
        close_error = None
        try:
            await self.assembly.aclose(wait_timeout=40)
        except BaseException as error:
            close_error = error
        # A successful component close is independent of accepted Root retirement.
        # Capture the post-close journals even when business uncertainty remains.
        captured = {}
        try:
            captured = await self.capture()
        except Exception as error:
            evidence_errors.append({"phase": "post_close_pg", "type": type(error).__name__})
        pending, found = list(self.targets), {}
        while pending:
            identity = pending.pop()
            if identity in found:
                continue
            try:
                handle = self.client.get_workflow_handle(identity)
                description = await handle.describe(rpc_timeout=timedelta(seconds=15))
                handle = self.client.get_workflow_handle(identity, run_id=description.run_id)
                history = await handle.fetch_history(rpc_timeout=timedelta(seconds=15))
                started = history.events[0].workflow_execution_started_event_attributes
                assert (
                    started.first_execution_run_id
                    == started.original_execution_run_id
                    == description.run_id
                    == description.raw_description.workflow_execution_info.first_run_id
                )
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    evidence_errors.append({"phase": "root_history", "type": type(error).__name__})
                continue
            except Exception as error:
                evidence_errors.append({"phase": "root_history", "type": type(error).__name__})
                continue
            found[identity] = handle
            path = self.directory / (identity + ".cleanup-history.json")
            path.write_text(history.to_json())
            path.chmod(0o600)
            for event in history.events:
                if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                    pending.append(
                        event.start_child_workflow_execution_initiated_event_attributes.workflow_id
                    )

        def archive(identity, history):
            path = self.directory / (identity + ".retention-history.json")
            path.write_text(history.to_json())
            path.chmod(0o600)

        gate = {
            "deletion_allowed": False,
            "accepted_roots": [],
            "retired_roots": [],
            "retained_roots": [],
            "reasons": ["registry_evidence_unavailable"],
        }
        registry = None
        try:
            registry = self.client.get_workflow_handle(registry_id(self.policy.deployment_id))
            description = await registry.describe(rpc_timeout=timedelta(seconds=15))
            registry = self.client.get_workflow_handle(registry.id, run_id=description.run_id)
            history = await registry.fetch_history(rpc_timeout=timedelta(seconds=15))
            path = self.directory / "registry-history.json"
            path.write_text(history.to_json())
            path.chmod(0o600)
            await replay_temporal_history(history, namespace=self.client.namespace)
            gate = await deletion_evidence(
                self.client,
                description,
                history,
                policy=self.policy.identity,
                namespace=self.data["namespace"],
                scope=asdict(self.scope),
                manifest_digest=digest(self.release),
                targets=self.targets,
                effects=captured.get("ralf_temporal_effects", []),
                archive=archive,
            )
        except Exception as error:
            evidence_errors.append({"phase": "registry_history", "type": type(error).__name__})
        deletion_allowed = close_error is None and gate["deletion_allowed"] and not evidence_errors
        # Stop only owned fixture processes. This is never an original call fence,
        # effect adoption or permission to retire a Root/delete its recovery data.
        for process in self.processes:
            await self.kill(process)
        if deletion_allowed:
            for handle in reversed(list(found.values())):
                if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                    await handle.terminate(reason="owned Coding deployment service test cleanup")
            await registry.terminate(reason="owned Coding deployment Registry test cleanup")
            self.socket_owner.close()
            self.socket_path.unlink(missing_ok=True)
            await self.admin.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )
        else:
            self.recovery = {
                "socket": self.socket_owner,
                "socket_path": self.socket_path,
                "assembly": self.assembly,
                "schema": self.schema,
                "application": self.directory / "application.json",
                "client": self.client,
            }
        for engine in self.engines:
            await engine.aclose()
        await self.admin.close()
        report = {
            "workers_exited": all(p.poll() is not None for p in self.processes),
            "scope": asdict(self.scope),
            "schema": self.schema,
            "schema_retained": not deletion_allowed,
            "original_application": str(self.directory / "application.json"),
            "assembly_close_succeeded": close_error is None,
            "close_error": None if close_error is None else type(close_error).__name__,
            "deletion_evidence": gate,
            "evidence_errors": evidence_errors,
            "expected_retention": self.expected_retention,
            "unexpected_retention": not deletion_allowed and not self.expected_retention,
        }
        path = self.directory / "cleanup.json"
        path.write_text(json.dumps(report, sort_keys=True))
        path.chmod(0o600)
        if not deletion_allowed:
            path = self.directory / "cleanup-retention.json"
            path.write_text(json.dumps(report, sort_keys=True))
            path.chmod(0o600)
        if close_error is not None:
            close_error.deployment_coding_fixture_recovery = self.recovery
            raise close_error


@asynccontextmanager
async def coding_system(
    directory,
    monkeypatch,
    *,
    kind="agent",
    syntax="sdk",
    factory="bounded",
    hold=False,
    cost=1,
    execution_policy=None,
    roots=1,
    actual_docker=None,
    never_go=False,
    deployment_sessions=False,
):
    import psycopg
    from psycopg import sql

    from ralf_agent.codex_create_supervisor import CreateSupervisor

    original_create_start = CreateSupervisor.start_once

    directory = Path(directory)
    schema = "deployment_coding_" + uuid.uuid4().hex
    admin = await psycopg.AsyncConnection.connect(
        os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
    )
    await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = psycopg.conninfo.make_conninfo(
        os.environ["RALF_TEST_POSTGRES_DSN"], options="-c search_path=" + schema
    )
    monkeypatch.setenv("RALF_DEPLOYMENT_CODING_DSN", dsn)
    if never_go:
        monkeypatch.setenv("RALF_CONNECTED_DIRECTORY", str(directory))
    queue = "deployment-coding-" + uuid.uuid4().hex
    policy = {"deployment_id": queue, "max_active_root_runs": roots}
    sock, socket_path = (
        socket.socket(socket.AF_UNIX),
        Path("/private/tmp") / ("ralf-dcoding-" + uuid.uuid4().hex[:12] + ".sock"),
    )
    sock.bind(str(socket_path))
    cli = fixture.peer(directory, hold=hold)
    cli.write_text(
        cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(socket_path))
    )
    host = "unix://" + str(socket_path)
    if actual_docker is not None:
        executable, host, mode = actual_docker
        cli = fixture.actual_create_cli(directory, executable, mode)
    entries = []
    for name, root_name in (("coding", "native"), ("coding_second", "native-second")):
        root = directory / root_name
        root.mkdir(mode=0o700)
        entries.append(
            {
                "name": name,
                "description": "Finite original Coding task",
                "cost": cost,
                "runner_root": str(root),
                "fixed_dependencies": {"deployment": queue},
                "docker_executable": str(cli),
                "docker_host": host,
                "request_timeout": 60,
            }
        )
    components = {
        "effect_journal": {
            "adapter": "postgres",
            "config": {
                "dsn_env": "RALF_DEPLOYMENT_CODING_DSN",
                "backend_id": queue,
                "initialize": True,
            },
        },
        "tools": {"adapter": "codex-coding-postgres", "config": {"tools": entries}},
    }
    if factory != "host":
        components["admission_policy"] = {
            "adapter": "bounded"
            if factory == "bounded"
            else "deployment-coding-custom-async"
            if factory == "async"
            else "deployment-coding-custom",
            "config": policy
            if factory == "bounded"
            else {"directory": str(directory), "policy": policy},
        }
    if execution_policy is not None:
        components["execution_policy"] = {"adapter": "bounded", "config": execution_policy}
    if kind == "checked-team":
        components["parent_completion_policies"] = {"adapter": "deployment-coding-check"}
    composition = kind not in {"agent", "sequence"}
    profile = TemporalProfile(
        queue,
        "120",
        {"default": {"adapter": "deployment-coding-peer", "config": {"directory": str(directory)}}},
        components,
        execution={
            "coding_execution": True,
            "coding_composition": composition,
            **(
                {"enable_sessions": True, "deployment_sessions": True}
                if deployment_sessions
                else {}
            ),
        },
        binding_components=[
            {
                "role": "runner",
                "component_id": name,
                "version": "1",
                "component": {"adapter": "registered-tool", "config": {"name": tool}},
            }
            for name, tool in (("native", "coding"), ("second", "coding_second"))
        ],
    )
    data = {
        "profile": profile.to_dict(),
        "scope": asdict(Scope("deployment-coding-service", queue)),
        "policy": policy,
        "queue": queue,
        "syntax": syntax,
        "composition": composition,
    }
    data["never_go"] = never_go
    if factory == "host":
        data["host_policy"] = policy
    (directory / "application.json").write_text(json.dumps(data))
    system, assembly, primary_error = None, None, None
    try:
        assembly = await fixture.application(directory)
        clients, namespace = await _clients()
        client = clients[0]
        data["namespace"] = namespace
        system = CodingSystem(directory, admin, schema, sock, socket_path, data, assembly, client)
        assert system.release["deployment_admission_protocol"]["version"] == (
            4 if deployment_sessions else 3
        )
        assert system.release["coding_execution_protocol"]["version"] == 6
        assert system.release["binding_protocol"] == (23 if composition else 22)
        if composition:
            assert system.release["coding_composition_protocol"]["version"] == 7
        with fixture.definition_mismatch_trace(directory):
            yield system
    except BaseException as error:
        primary_error = error
        try:
            from tests.temporal_coding_primary_failure import save_primary_failure

            save_primary_failure(directory, error)
        except BaseException:
            pass  # Diagnostics must not replace the original fixture failure.
        raise
    finally:
        try:
            if system is not None:
                await system.cleanup()
                if primary_error is not None and system.recovery is not None:
                    primary_error.deployment_coding_fixture_recovery = system.recovery
            elif assembly is not None:
                try:
                    await assembly.aclose(wait_timeout=40)
                except BaseException as close_error:
                    recovery = {
                        "assembly": assembly,
                        "socket": sock,
                        "socket_path": socket_path,
                        "schema": schema,
                        "application": directory / "application.json",
                    }
                    path = directory / "construction-close-error.json"
                    path.write_text(
                        json.dumps(
                            {
                                "type": type(close_error).__name__,
                                "code": getattr(close_error, "code", None),
                                "report": getattr(close_error, "report", None),
                                "schema": schema,
                                "schema_retained": True,
                                "original_application": str(recovery["application"]),
                            },
                            sort_keys=True,
                        )
                    )
                    path.chmod(0o600)
                    await admin.close()
                    close_error.deployment_coding_fixture_recovery = recovery
                    raise
                else:
                    sock.close()
                    socket_path.unlink(missing_ok=True)
                    await admin.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
                    await admin.close()
            else:
                # A failed build may retain partial owned resources. Keep its
                # original schema rather than guessing that absent receipts mean
                # no obligations. The builder's error remains the primary failure.
                sock.close()
                await admin.close()
                path = directory / "construction-resources-retained.json"
                path.write_text(
                    json.dumps(
                        {
                            "schema": schema,
                            "schema_retained": True,
                            "original_application": str(directory / "application.json"),
                        }
                    )
                )
                path.chmod(0o600)
        except BaseException as cleanup_error:
            if primary_error is not None:
                grouped = BaseExceptionGroup(
                    "Coding fixture operation and cleanup failed", [primary_error, cleanup_error]
                )
                if hasattr(cleanup_error, "deployment_coding_fixture_recovery"):
                    grouped.deployment_coding_fixture_recovery = (
                        cleanup_error.deployment_coding_fixture_recovery
                    )
                raise grouped from None
            raise
        finally:
            # This FD belongs only to the test's bind-only identity marker, not
            # to a listener, native helper or actual Docker connection. Closing
            # it retains the original path/inode and all durable recovery data.
            sock.close()
            CreateSupervisor.start_once = original_create_start
            from tests.temporal_fixture_resources import retain_assembly_clients

            retain_assembly_clients(assembly, [] if system is None else system.processes, directory)


@pytest.mark.parametrize("kind,syntax", TOPOLOGIES)
def test_actual_coding3_topologies_original_tree_and_quota_turnover(
    tmp_path, monkeypatch, kind, syntax
):
    async def scenario():
        async with (
            coding_system(tmp_path, monkeypatch, kind=kind, syntax=syntax) as system,
            system.worker(),
        ):
            spec, value, calls = definition(kind)
            original = await system.submit(spec, value)
            await _eventually(
                lambda: system.engine.status(original.run_id),
                lambda s: s.state == "waiting_approval",
                seconds=80,
            )
            await system.count(1)
            assert system.lines("native-submissions.jsonl") == []
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, value, command_id="full")
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == calls * 2
            assert len(system.lines("native-commits.jsonl")) == calls
            view = await system.evidence(original.run_id)
            assert view["deployment"]["admission"]["lineage"] == []
            assert await system.submit(spec, value) == original
            assert len(system.lines("native-submissions.jsonl")) == calls * 2
            next_run = await system.submit(spec, value, command_id="next")
            assert next_run.run_id != original.run_id
            assert (await system.approve(next_run.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == calls * 4

    asyncio.run(asyncio.wait_for(scenario(), 360))


def test_actual_graph_approval_idle_preserves_original_history_and_call_ledger(
    tmp_path, monkeypatch
):
    """Ten clean approval-idle seconds add no original-tree History or call debt."""

    async def scenario():
        async with (
            coding_system(tmp_path, monkeypatch, kind="graph-parallel", syntax="toml") as system,
            system.worker(),
        ):
            original = await system.submit(*definition("graph-parallel")[:2])
            root_epoch = (
                await system.client.get_workflow_handle(original.run_id).describe()
            ).run_id

            async def measure():
                nodes, diagnostics = {}, {}
                clean = True

                async def visit(run_id, epoch, parent=None):
                    nonlocal clean
                    handle = system.client.get_workflow_handle(run_id, run_id=epoch)
                    description = await handle.describe()
                    assert description.id == run_id and description.run_id == epoch
                    closure = await system.view(run_id, "deployment_closure", epoch=epoch)
                    proof = closure["deployment"]
                    assert proof["execution_epoch"] == proof["original_execution_epoch"] == epoch
                    details = await system.view(run_id, epoch=epoch)
                    diagnostics[run_id] = details
                    clean &= closure["seal"] is None
                    clean &= all(
                        c["stopped"] and c["end_proof"] == c["identity"]
                        for c in closure["calls"].values()
                    )
                    flow = details["workflow"]
                    clean &= not flow.get("reconciliation_pending", False)
                    clean &= not flow.get("evidence_ack_pending", False)
                    clean &= not flow.get("deferred_evidence_acks", 0)
                    history = await handle.fetch_history()
                    started = history.events[0].workflow_execution_started_event_attributes
                    assert started.workflow_id == run_id
                    assert (
                        started.first_execution_run_id
                        == started.original_execution_run_id
                        == epoch
                        == description.raw_description.workflow_execution_info.first_run_id
                    )
                    assert started.task_queue.name == system.queue
                    if parent is None:
                        assert not started.HasField("parent_workflow_execution")
                    else:
                        assert (
                            started.parent_workflow_execution.workflow_id,
                            started.parent_workflow_execution.run_id,
                        ) == parent
                    pending = {
                        "activity": set(),
                        "workflow_task": set(),
                        "signal": set(),
                        "timer": set(),
                    }
                    signaled = 0
                    for event in history.events:
                        for category in ("activity", "workflow"):
                            prefix = "activity_task" if category == "activity" else "workflow_task"
                            target = "activity" if category == "activity" else "workflow_task"
                            if event.HasField(prefix + "_scheduled_event_attributes"):
                                pending[target].add(event.event_id)
                            for ending in ("completed", "failed", "timed_out", "canceled"):
                                field = prefix + "_" + ending + "_event_attributes"
                                if field in event.DESCRIPTOR.fields_by_name and event.HasField(
                                    field
                                ):
                                    pending[target].discard(
                                        getattr(event, field).scheduled_event_id
                                    )
                        field = "signal_external_workflow_execution_initiated_event_attributes"
                        if event.HasField(field):
                            pending["signal"].add(event.event_id)
                        field = "external_workflow_execution_signaled_event_attributes"
                        if event.HasField(field):
                            pending["signal"].discard(getattr(event, field).initiated_event_id)
                            signaled += 1
                        assert not event.HasField(
                            "signal_external_workflow_execution_failed_event_attributes"
                        )
                        if event.HasField("timer_started_event_attributes"):
                            pending["timer"].add(event.timer_started_event_attributes.timer_id)
                        for ending in ("fired", "canceled"):
                            field = "timer_" + ending + "_event_attributes"
                            if event.HasField(field):
                                pending["timer"].discard(getattr(event, field).timer_id)
                    clean &= not any(pending.values())
                    if parent is not None:
                        clean &= signaled > 0
                    nodes[run_id] = {
                        "execution_epoch": epoch,
                        "events": len(history.events),
                        "history_json_bytes": len(history.to_json().encode()),
                        "history_proto_bytes": sum(e.ByteSize() for e in history.events),
                        "calls": len(closure["calls"]),
                        "ended_calls": sum(c["stopped"] for c in closure["calls"].values()),
                        "ledger_digest": digest(closure["calls"]),
                    }
                    children = [c for c in proof["children"] if c.get("dispatch_started")]
                    for call in children:
                        child_epoch = call.get("deployment_execution_epoch")
                        if child_epoch is None:
                            clean = False
                            continue
                        assert call["child_execution"]["execution_epoch"] == child_epoch
                        assert call["child_execution"]["original_execution_epoch"] == child_epoch
                        await visit(call["run_id"], child_epoch, (run_id, epoch))
                        child = diagnostics[call["run_id"]]["snapshot"]
                        clean &= call.get("observed_revision") == child["state_revision"]
                        clean &= call.get("snapshot") == child

                await visit(original.run_id, root_epoch)
                root = diagnostics[original.run_id]
                clean &= len(nodes) == 3 and len(root["workflow"]["children"]) == 2
                clean &= root["snapshot"]["state"] == "waiting_approval"
                clean &= len(root["snapshot"]["pending"]) == 2
                for run_id, details in diagnostics.items():
                    if run_id != original.run_id:
                        clean &= details["snapshot"]["state"] == "waiting_approval"
                        clean &= len(details["snapshot"]["pending"]) == 1
                return {
                    "clean": bool(clean),
                    "nodes": nodes,
                    "total_events": sum(n["events"] for n in nodes.values()),
                    "total_json_bytes": sum(n["history_json_bytes"] for n in nodes.values()),
                    "total_proto_bytes": sum(n["history_proto_bytes"] for n in nodes.values()),
                    "total_calls": sum(n["calls"] for n in nodes.values()),
                }

            previous = None

            async def settled():
                nonlocal previous
                current = await measure()
                stable = current["clean"] and current == previous
                previous = current
                return {"stable": stable, "measurement": current}

            baseline = (await _eventually(settled, lambda s: s["stable"], seconds=80))[
                "measurement"
            ]
            await system.count(1)
            assert system.lines("native-submissions.jsonl") == []
            # This is the finite idle interval under test, not a settling delay.
            await asyncio.sleep(10)
            after = await measure()
            summary = tmp_path / "approval-idle-history-summary.json"
            summary.write_text(
                json.dumps({"idle_seconds": 10, "before": baseline, "after": after}, sort_keys=True)
            )
            summary.chmod(0o600)
            assert after == baseline
            await system.count(1)
            assert system.lines("native-submissions.jsonl") == []
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == 4
            assert len(system.lines("native-commits.jsonl")) == 2
            closure = await system.evidence(original.run_id)
            assert closure["ready"] and closure["seal"] is not None
            physical = await system.view(
                original.run_id, "coding_composition_proof", epoch=root_epoch
            )
            assert physical["physical_stopped"] is True
            effects = await system.capture()
            assert len(effects["ralf_temporal_effects"]) == 2
            assert all(
                row["state"] == "adopted" and row["adopted_result_digest"]
                for row in effects["ralf_temporal_effects"]
            )
            assert len(effects["ralf_temporal_effect_evidence"]) == 2

    asyncio.run(asyncio.wait_for(scenario(), 360))


def test_actual_never_used_owned_assembly_records_only_original_scoped_close(tmp_path, monkeypatch):
    async def scenario():
        from temporalio.api.enums.v1 import EventType
        from temporalio.service import RPCError, RPCStatusCode

        from ralf_agent.errors import NotFound, ValidationError

        async with coding_system(tmp_path, monkeypatch) as system:
            await system.assembly.start_worker(system.client, task_queue=system.queue)
            engine = system.assembly.create_engine(system.client, task_queue=system.queue)
            registry = system.client.get_workflow_handle(registry_id(system.policy.deployment_id))

            async def original_registry_missing():
                with pytest.raises(RPCError) as missing:
                    await registry.describe()
                assert missing.value.status == RPCStatusCode.NOT_FOUND

            # This test performs no submission at all. Missing observations are
            # never substituted for a no-start proof of an accepted root.
            assert system.targets == set()
            await original_registry_missing()
            try:
                diagnostic = await engine.deployment_diagnostics()
            except RPCError as missing:
                assert missing.status == RPCStatusCode.NOT_FOUND
            except NotFound:
                pass
            else:
                assert diagnostic["state"] == "missing"
            await original_registry_missing()
            runner = system.runtime.tools.get("coding").handler.runner
            assert runner.active_operations == 0
            assert (
                system.lines("model-calls.jsonl") == system.lines("native-submissions.jsonl") == []
            )
            await system.assembly.aclose(wait_timeout=40)
            assert system.assembly._closed and system.assembly._context._resources == []
            assert system.assembly._worker_start.done() and system.assembly._worker_stop.done()
            assert system.runtime.journal.connection.closed and runner.active_operations == 0
            with pytest.raises(ValidationError, match="TemporalEngine is closed"):
                await engine.deployment_diagnostics()
            # Owned close starts the same Registry3 and durably seals this Scope.
            # The borrowed SDK client reads History without a remaining poller.
            description = await registry.describe()
            history = await registry.fetch_history()
            started = history.events[0].workflow_execution_started_event_attributes
            assert (
                description.id == registry.id
                and description.workflow_type == "ralf.temporal.commands.v1"
            )
            assert started.workflow_id == registry.id and started.task_queue.name == system.queue
            assert (
                started.original_execution_run_id
                == started.first_execution_run_id
                == description.run_id
                == description.raw_description.workflow_execution_info.first_run_id
            )
            assert await system.client.data_converter.decode(started.input.payloads) == [
                {
                    "deployment_admission": {
                        "version": 3,
                        "policy": system.policy.identity,
                        "namespace": system.data["namespace"],
                    }
                }
            ]
            accepted = [
                event
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED
            ]
            completed = [
                event
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_COMPLETED
            ]
            assert len(accepted) == len(completed) == 1
            request = accepted[
                0
            ].workflow_execution_update_accepted_event_attributes.accepted_request
            assert request.input.name == "close_deployment_coding_submissions"
            assert await system.client.data_converter.decode(request.input.args.payloads) == [
                {
                    "scope": asdict(system.scope),
                    "admission_policy": system.policy.identity,
                    "namespace": system.data["namespace"],
                    "manifest_digest": digest(system.release),
                }
            ]
            result = completed[0].workflow_execution_update_completed_event_attributes
            assert result.accepted_event_id == accepted[0].event_id
            assert result.meta.update_id == request.meta.update_id
            assert result.outcome.WhichOneof("value") == "success"
            assert await system.client.data_converter.decode(result.outcome.success.payloads) == [
                {
                    "manifest_digest": digest(system.release),
                    "close_requested": True,
                    "candidates": [],
                }
            ]
            assert not any(
                event.event_type
                in {
                    EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED,
                    EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED,
                }
                for event in history.events
            )
            assert system.targets == set()
            (tmp_path / "unused-registry-history.json").write_text(history.to_json())

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.parametrize("factory", ["sync", "async", "host"])
def test_actual_coding3_public_policy_factory_replacement(tmp_path, monkeypatch, factory):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch, factory=factory) as system, system.worker():
            original = await system.submit(*definition("agent")[:2])
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            if factory != "host":
                assert system.lines("factory-calls.jsonl") == [{"scope": asdict(system.scope)}]
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 180))


@pytest.mark.parametrize("boundary", ["reserve", "start"])
def test_actual_coding3_lost_first_acceptance_recovers_original_alias_queue_and_epoch(
    tmp_path, monkeypatch, boundary
):
    async def scenario():
        from temporalio.service import RPCError

        async with coding_system(tmp_path, monkeypatch) as system, system.worker():
            spec, value, _ = definition("agent")
            fault = SDKFaultClient(system.client, lose=boundary)
            first = system.facade(client=fault)
            try:
                await system.submit(spec, value, engine=first)
            except RPCError:
                pass
            assert fault.dropped
            await system.count(1)
            moved = copy.deepcopy(system.release)
            moved["providers"]["default"]["version"] = "moved-alias"
            retry = system.facade(queue=system.queue + "-unserved", release=moved, timeout=1)
            recovered = await system.submit(spec, value, engine=retry)
            proof = (await system.view(recovered.run_id, "deployment_closure"))["deployment"]
            assert proof["manifest"] == json.loads(canonical(first.release))
            assert system.lines("native-submissions.jsonl") == []
            assert (await system.approve(recovered.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert await system.submit(spec, value, engine=retry) == recovered
            assert len(system.lines("native-submissions.jsonl")) == 2
            history = await system.client.get_workflow_handle(recovered.run_id).fetch_history()
            accepted = await system.client.data_converter.decode(
                history.events[0].workflow_execution_started_event_attributes.input.payloads
            )
            assert accepted[0]["activity_timeout"] == 90
            assert (
                history.events[0].workflow_execution_started_event_attributes.task_queue.name
                == system.queue
            )
            await system.evidence(recovered.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 180))


def test_actual_coding3_recursive_approval_cold_worker_replays_original_epochs(
    tmp_path, monkeypatch
):
    """Cold replay after a drained handoff, not arbitrary active-CONTROL death."""

    async def scenario():
        async with coding_system(tmp_path, monkeypatch, kind="recursive") as system:
            first = await system.start_process()
            spec, value, _ = definition("recursive")
            original = await system.submit(spec, value)
            before = await _eventually(
                lambda: system.engine.status(original.run_id),
                lambda s: s.state == "waiting_approval",
                seconds=80,
            )
            pending = copy.deepcopy(before.pending[0])
            leaf = pending["run_id"]
            epoch = (await system.client.get_workflow_handle(leaf).describe()).run_id
            root_epoch = (
                await system.client.get_workflow_handle(original.run_id).describe()
            ).run_id
            await system.count(1)
            assert system.lines("native-submissions.jsonl") == []
            # Stop original pollers/handlers and finish their independent end
            # ACKs. No Assembly.close/cancel is used to obtain this handoff.
            first.terminate()
            assert await asyncio.to_thread(first.wait, timeout=80) == 0
            assert (
                "DEPLOYMENT_CODING_WORKER_HANDOFF_COMPLETE"
                in (tmp_path / "worker-0.log").read_text()
            )
            await system.start_process()
            assert await system.submit(spec, value) == original
            after = await system.engine.status(original.run_id)
            assert after.pending[0] == pending
            assert (await system.client.get_workflow_handle(leaf).describe()).run_id == epoch
            assert (
                await system.client.get_workflow_handle(original.run_id).describe()
            ).run_id == root_epoch
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == 2
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_coding3_control_hard_kill_retains_original_unknown_call(tmp_path, monkeypatch):
    """A real active CONTROL death has no Tool-owner fence or quota release."""

    async def scenario():
        async with coding_system(tmp_path, monkeypatch, kind="recursive") as system:
            # The gate is inside the real observe body, after its deployment
            # begin grant. It carries no permission or caller stop attestation.
            gate = tmp_path / "block-control-observe"
            gate.touch()
            first = await system.start_process()
            spec, value, _ = definition("recursive")
            original = await system.submit(spec, value)
            marker = tmp_path / "held-control-observe.json"
            await _eventually(lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=80)
            held = json.loads(marker.read_text())
            assert held["pid"] == first.pid
            before = await system.view(
                held["workflow_id"], "deployment_closure", epoch=held["execution_epoch"]
            )
            matching = [
                record
                for record in before["calls"].values()
                if record["identity"]["activity_id"] == held["activity_id"]
            ]
            assert len(matching) == 1
            call = matching[0]
            assert call["identity"]["activity_name"] == "ralf.temporal.control.v1"
            assert call["allowed"] and not call["stopped"] and call["end_proof"] is None
            assert call["fence_proof"] is None
            assert system.lines("native-submissions.jsonl") == []
            await system.kill(first)
            gate.unlink()
            await system.start_process()
            assert await system.submit(spec, value) == original
            after = await system.view(
                held["workflow_id"], "deployment_closure", epoch=held["execution_epoch"]
            )
            assert [
                record
                for record in after["calls"].values()
                if record["identity"]["activity_id"] == held["activity_id"]
            ] == [call]
            assert "actual_call_not_stopped" in after["reasons"] and after["seal"] is None
            await system.count(1)
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, value, command_id="active-control-still-held")
            assert system.lines("native-submissions.jsonl") == []
            assert system.lines("native-commits.jsonl") == []
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_parallel_same_runner_pressure_does_not_create_busy_second_child(
    tmp_path, monkeypatch
):
    async def scenario():
        async with (
            coding_system(tmp_path, monkeypatch, kind="graph-parallel", hold=True) as system,
            system.worker(),
        ):
            graph = GraphWorkflowSpec(
                "shared-original-runner",
                (
                    GraphNode("first", agent=AgentSpec("first", "Perform Coding", ("coding",))),
                    GraphNode("second", agent=AgentSpec("second", "Perform Coding", ("coding",))),
                    GraphNode(
                        "join",
                        agent=AgentSpec("join", "Complete plain join without tools."),
                        depends_on=("first", "second"),
                    ),
                ),
                max_concurrency=2,
            )
            choices = {
                path: AgentBindingDescriptor(
                    runner=BindingSelection.ref("native", "1")
                    if agent["tools"]
                    else BindingSelection.disabled(),
                    tool_set=BindingSelection.inherit()
                    if agent["tools"]
                    else BindingSelection.disabled(),
                )
                for path, agent in agent_paths(submission_request(graph, {})["definition"]).items()
            }
            original = await system.submit(BoundDefinition(graph, choices), {})
            await system.approve(original.run_id)
            await system.committed()
            held = await system.view(original.run_id, "deployment_closure")
            assert len(held["deployment"]["children"]) == 1
            assert len(system.lines("native-submissions.jsonl")) == 2
            await system.count(1)
            assert held["seal"] is None
            (tmp_path / "release-turns").touch()
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == 4
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 300))


@pytest.mark.parametrize("kind,actual", [("agent", False), ("recursive", False), ("agent", True)])
def test_actual_never_go_original_helper_proof_retires_physical_only_not_unknown_effect(
    tmp_path, monkeypatch, kind, actual
):
    if actual and os.getenv("RALF_TEST_DEPLOYMENT_CODING_REAL_DOCKER") != "1":
        pytest.skip("explicit actual Docker never-GO probe is not selected")

    async def scenario():
        docker = None
        if actual:
            docker = (
                os.environ["RALF_TEST_DEPLOYMENT_CODING_DOCKER"],
                os.environ["RALF_TEST_DEPLOYMENT_CODING_HOST"],
                "hold",
            )
        async with (
            coding_system(
                tmp_path, monkeypatch, kind=kind, cost=0, never_go=True, actual_docker=docker
            ) as system,
            system.worker(),
        ):
            original = await system.submit(*definition(kind)[:2])
            leaf, action_id = await system.approve(original.run_id)
            raw = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id
                    and a.get("delegated_execution", {}).get("create_not_dispatched")
                    for a in d["snapshot"]["actions"]
                ),
                seconds=100,
            )
            native = next(a for a in raw["snapshot"]["actions"] if a["id"] == action_id)[
                "delegated_execution"
            ]
            proof = native["create_not_dispatched"]
            assert proof["cli_gate_accepted"] is False and proof["cli_exec_started"] is False
            assert proof["gate_sealed"] is True and proof["helpers_ended"] is True
            assert proof["control_drained"] is True
            assert (
                proof["namespace_query_succeeded"] is True and proof["namespace_confirmed"] is True
            )
            assert proof["container_present"] is False
            physical = system.lines("no-submit-physical.jsonl")
            assert physical and physical[0]["broker_returncode"] is not None
            assert system.lines("native-submissions.jsonl") == []
            assert system.lines("actual-docker-calls.jsonl") == [] or all(
                c["operation"] != "create" for c in system.lines("actual-docker-calls.jsonl")
            )
            await system.engine.cancel(original.run_id, command_id="cancel-never-go")
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: all(t["execution_stopped"] for t in d["workflow"]["tool_executions"]),
                seconds=80,
            )
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in stopped["budget"]["reservations"]
            )
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            with pytest.raises(CapacityExceeded):
                await system.submit(*definition(kind)[:2], command_id="never-go-unknown-still-held")
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_ordinary2_and_coding3_share_registry3_capacity_without_coding_index_rewrite(
    tmp_path, monkeypatch
):
    async def scenario():
        from ralf_agent import ToolRegistry
        from ralf_agent.temporal_activities import TemporalRuntime
        from ralf_agent.temporal_deployment_release import close_owner
        from ralf_agent.types import ModelResponse

        class HeldProvider:
            identity = {"kind": "deployment-coding-ordinary-peer", "version": "1"}

            def __init__(self):
                self.started, self.release = asyncio.Event(), asyncio.Event()

            async def complete(self, messages, tools):
                self.started.set()
                await self.release.wait()
                return ModelResponse(output="ordinary-finished")

        async with coding_system(tmp_path, monkeypatch, roots=2) as system, system.worker():
            coding = await system.submit(*definition("agent")[:2])
            await _eventually(
                lambda: system.engine.status(coding.run_id), lambda s: s.state == "waiting_approval"
            )
            provider = HeldProvider()
            runtime = TemporalRuntime(
                providers={"default": provider},
                tools=ToolRegistry(),
                admission_policy=system.policy,
            )
            assert runtime.orchestration_release["deployment_admission_protocol"]["version"] == 2
            queue = system.queue + "-ordinary"
            ordinary = system.facade(queue=queue, release=runtime.orchestration_release)
            worker = build_temporal_worker(system.client, task_queue=queue, runtime=runtime)
            try:
                async with worker:
                    handle = await system.submit(
                        AgentSpec("ordinary", "Return plain output"),
                        {},
                        command_id="ordinary",
                        engine=ordinary,
                    )
                    await asyncio.wait_for(provider.started.wait(), 30)
                    await system.count(2)
                    with pytest.raises(CapacityExceeded):
                        await system.submit(*definition("agent")[:2], command_id="mixed-full")
                    candidates = await system.candidates()
                    assert [c["run_id"] for c in candidates] == [coding.run_id]
                    registry = system.client.get_workflow_handle(
                        registry_id(system.policy.deployment_id)
                    )
                    configuration = await registry.query(
                        "view",
                        {
                            "scope": asdict(system.scope),
                            "kind": "deployment_configuration",
                            "admission_policy": system.policy.identity,
                            "namespace": system.data["namespace"],
                        },
                    )
                    assert configuration["version"] == 3
                    provider.release.set()
                    assert (
                        await _eventually(
                            lambda: ordinary.status(handle.run_id), lambda s: s.state == "succeeded"
                        )
                    ).state == "succeeded"
                    await system.count(1)
                    assert (
                        await system.approve(coding.run_id, all_steps=True)
                    ).state == "succeeded"
                    await system.count(0)
                    assert len(system.lines("native-submissions.jsonl")) == 2
                    await system.evidence(coding.run_id)
            finally:
                provider.release.set()
                await close_owner(runtime, wait_timeout=30)

    asyncio.run(asyncio.wait_for(scenario(), 240))


@pytest.mark.skipif(
    os.getenv("RALF_TEST_DEPLOYMENT_CODING_REAL_DOCKER") != "1",
    reason="requires explicitly selected actual Docker CREATE probe",
)
@pytest.mark.parametrize("window", ["hold", "reply-loss", "unreachable"])
def test_actual_docker_create_completed_reply_window_keeps_original_deployment_and_cid(
    tmp_path, monkeypatch, window
):
    async def scenario():
        executable, host = (
            os.environ["RALF_TEST_DEPLOYMENT_CODING_DOCKER"],
            os.environ["RALF_TEST_DEPLOYMENT_CODING_HOST"],
        )
        assert Path(executable).is_absolute() and host.startswith("unix:///")
        client_config = tmp_path / "read-only-docker-client"
        client_config.mkdir(mode=0o700)
        (client_config / "config.json").write_text("{}")

        async def docker(*args):
            return await asyncio.to_thread(
                subprocess.run,
                [executable, "--config", str(client_config), "--host", host, *args],
                env={"PATH": str(Path(executable).parent) + ":/usr/bin:/bin"},
                capture_output=True,
                timeout=30,
            )

        async with coding_system(
            tmp_path, monkeypatch, actual_docker=(executable, host, window), cost=0
        ) as system:
            first = await system.start_process()
            original = await system.submit(*definition("agent")[:2])
            leaf, action_id = await system.approve(original.run_id)
            marker = tmp_path / "actual-create.json"
            await _eventually(lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=50)
            created = json.loads(marker.read_text())
            if window == "hold":
                os.kill(created["pid"], 0)
                inspect = await docker("inspect", created["cid"])
                assert inspect.returncode == 0
                before = json.loads(inspect.stdout)[0]
                assert before["Id"] == created["cid"]
                assert before["State"]["Running"] is False and before["State"]["Pid"] == 0
                assert before["State"]["StartedAt"] == "0001-01-01T00:00:00Z"
                (tmp_path / "actual-created-cli-alive.json").write_text(
                    json.dumps({"cli": created, "container": before})
                )
            await system.count(1)
            initial_closure = await system.view(leaf, "deployment_closure")
            assert initial_closure["seal"] is None
            original_epoch = initial_closure["deployment"]["execution_epoch"]
            if window == "unreachable":
                # Real daemon query transport failed; no fabricated absent inventory.
                unknown = await _eventually(
                    lambda: system.view(leaf),
                    lambda d: any(
                        a["id"] == action_id and a["status"] == "outcome_unknown"
                        for a in d["snapshot"]["actions"]
                    ),
                    seconds=80,
                )
                assert any(r["status"] == "unknown" for r in unknown["budget"]["reservations"])
                inspect = await docker("inspect", created["cid"])
                assert inspect.returncode == 0
                assert json.loads(inspect.stdout)[0]["Id"] == created["cid"]
                with pytest.raises(CapacityExceeded):
                    await system.submit(*definition("agent")[:2], command_id="unknown-create-held")
            # All three windows must still own the original physical container
            # when the old Worker dies. Natural cleanup is not cold recovery.
            before_kill = await docker("inspect", created["cid"])
            (tmp_path / "actual-cid-before-worker-kill.json").write_text(
                json.dumps(
                    {
                        "cid": created["cid"],
                        "worker_pid": first.pid,
                        "returncode": before_kill.returncode,
                        "stdout": before_kill.stdout.decode(errors="replace"),
                        "stderr": before_kill.stderr.decode(errors="replace"),
                    }
                )
            )
            assert before_kill.returncode == 0, (
                "Original CID already absent/unreachable; not a cold CID recovery"
            )
            assert json.loads(before_kill.stdout)[0]["Id"] == created["cid"]
            calls_before_kill = copy.deepcopy(system.lines("actual-docker-calls.jsonl"))
            await system.kill(first)
            (tmp_path / "hold-actual-create").unlink(missing_ok=True)
            (tmp_path / "block-actual-inventory").unlink(missing_ok=True)
            await system.start_process()
            assert await system.submit(*definition("agent")[:2]) == original
            await system.engine.cancel(original.run_id, command_id="stop-original-create")
            if window == "unreachable":
                # The old Worker may own the first stop Activity, or the new
                # Worker may finish it. Observe either original fact; a read
                # query cannot retry a failed stop itself.
                recovery_state = await _eventually(
                    lambda: system.view(leaf),
                    lambda d: any(
                        a["id"] == action_id
                        and (
                            (
                                a.get("delegated_execution", {}).get("fenced") is True
                                and a["delegated_execution"]["pending_stop"] is False
                            )
                            or (
                                a.get("delegated_execution", {}).get("stop_retry") is True
                                and a["delegated_execution"]["stop_active"] is False
                            )
                        )
                        for a in d["snapshot"]["actions"]
                    ),
                    seconds=80,
                )
                assert leaf == original.run_id
                assert any(
                    r["amount"] == 0 and r["status"] == "unknown"
                    for r in recovery_state["budget"]["reservations"]
                )
                await system.count(1)
                before_retry = system.lines("actual-docker-calls.jsonl")
                assert sum(c["operation"] == "create" for c in before_retry) == 1
                assert sum(c["operation"] == "start" for c in before_retry) == 0
                native = next(
                    a["delegated_execution"]
                    for a in recovery_state["snapshot"]["actions"]
                    if a["id"] == action_id
                )
                if not (native["fenced"] is True and native["pending_stop"] is False):
                    assert native["stop_retry"] is True and native["stop_active"] is False
                    await system.engine.drive(original.run_id, wait_seconds=0)
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id
                    and a.get("delegated_execution", {}).get("fenced") is True
                    and a["delegated_execution"]["pending_stop"] is False
                    for a in d["snapshot"]["actions"]
                ),
                seconds=100,
            )
            action = next(a for a in stopped["snapshot"]["actions"] if a["id"] == action_id)
            proof = action["delegated_execution"]["stop"]
            assert proof["container_id"] == created["cid"]
            assert all(proof[key] is True for key in ("fenced", "stopped", "retired"))
            assert proof["container_present"] is False and proof["running"] is False
            assert (await system.view(leaf, "deployment_closure"))["deployment"][
                "execution_epoch"
            ] == original_epoch
            assert await system.submit(*definition("agent")[:2]) == original
            assert system.lines("native-submissions.jsonl") == []
            inventory = await docker(
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                "id=" + created["cid"],
                "--format",
                "{{.ID}}",
            )
            auxiliary_inspect = await docker("inspect", created["cid"])
            (tmp_path / "actual-cid-after-original-stop.json").write_text(
                json.dumps(
                    {
                        "cid": created["cid"],
                        "original_stop_proof": proof,
                        "ps_returncode": inventory.returncode,
                        "ps_stdout": inventory.stdout.decode(errors="replace"),
                        "ps_stderr": inventory.stderr.decode(errors="replace"),
                        "inspect_returncode": auxiliary_inspect.returncode,
                        "inspect_stdout": auxiliary_inspect.stdout.decode(errors="replace"),
                        "inspect_stderr": auxiliary_inspect.stderr.decode(errors="replace"),
                    }
                )
            )
            assert inventory.returncode == 0 and inventory.stdout.split() == []
            calls = system.lines("actual-docker-calls.jsonl")
            assert sum(c["operation"] == "create" for c in calls) == 1
            assert sum(c["operation"] == "start" for c in calls) == 0
            assert sum(c["operation"] == "rm" for c in calls) == 1
            retirement = next(c for c in calls if c["operation"] == "rm")
            assert created["cid"] in retirement["args"]
            assert retirement in calls[len(calls_before_kill) :]
            await system.count(1)
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in stopped["budget"]["reservations"]
            )
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_scoped_coding_close_preserves_other_scope_under_same_manifest(
    tmp_path, monkeypatch
):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch, roots=2) as system, system.worker():
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            await _eventually(
                lambda: system.engine.status(original.run_id),
                lambda s: s.state == "waiting_approval",
            )
            other_scope = Scope(system.scope.workspace, system.scope.principal + "-other")
            other = system.facade(scope=other_scope)
            # Inherit the declared original tool, with no foreign explicit reference.
            foreign = await system.submit(
                AgentSpec("other", "Perform approved Coding", ("coding",)), value, engine=other
            )
            assert foreign.run_id != original.run_id
            await _eventually(
                lambda: other.status(foreign.run_id), lambda s: s.state == "waiting_approval"
            )
            await system.count(2)
            registry = system.client.get_workflow_handle(registry_id(system.policy.deployment_id))
            closed = await registry.execute_update(
                "close_deployment_coding_submissions",
                {
                    "scope": asdict(system.scope),
                    "admission_policy": system.policy.identity,
                    "namespace": system.data["namespace"],
                    "manifest_digest": digest(system.release),
                },
            )
            assert closed["close_requested"] is True
            assert [c["run_id"] for c in closed["candidates"]] == [original.run_id]
            other_candidates = await system.candidates(scope=other_scope)
            assert [c["run_id"] for c in other_candidates] == [foreign.run_id]
            assert other_candidates[0]["close_requested"] is False
            assert await system.submit(spec, value) == original
            with pytest.raises(DefinitionMismatch):
                await system.submit(spec, value, command_id="closed-new")
            await system.count(2)
            assert await system.submit(spec, value) == original
            assert system.lines("native-submissions.jsonl") == []
            await system.engine.cancel(original.run_id, command_id="close-original")
            waiting = await other.status(foreign.run_id)
            pending = waiting.pending[0]
            await other.approve(
                foreign.run_id, pending["action_id"], pending["digest"], command_id="approve-other"
            )
            assert (
                await _eventually(
                    lambda: other.status(foreign.run_id),
                    lambda s: s.state in {"succeeded", "failed"},
                    seconds=80,
                )
            ).state == "succeeded"
            await system.count(0)
            assert len(system.lines("native-submissions.jsonl")) == 2

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_closed_atomic_acceptance_index_late_original_start_is_stop_only(
    tmp_path, monkeypatch
):
    async def scenario():
        from temporalio.service import RPCError

        async with coding_system(tmp_path, monkeypatch) as system, system.worker():
            spec, value, _ = definition("agent")
            first = system.facade(client=SDKFaultClient(system.client, lose="reserve"))
            with pytest.raises(RPCError):
                await system.submit(spec, value, engine=first)
            await system.count(1)
            candidates = await system.candidates()
            assert len(candidates) == 1 and candidates[0]["execution_epoch"] is None
            assert await system.rows("ralf_temporal_coding_resources") == []
            closed = await system.client.get_workflow_handle(
                registry_id(system.policy.deployment_id)
            ).execute_update(
                "close_deployment_coding_submissions",
                {
                    "scope": asdict(system.scope),
                    "admission_policy": system.policy.identity,
                    "namespace": system.data["namespace"],
                    "manifest_digest": digest(system.release),
                },
            )
            assert closed["candidates"][0]["run_id"] == candidates[0]["run_id"]
            recovered = await system.submit(spec, value)
            assert recovered.run_id == candidates[0]["run_id"]
            final = await _eventually(
                lambda: system.engine.status(recovered.run_id),
                lambda s: s.state == "cancelled",
                seconds=80,
            )
            assert final.state == "cancelled"
            assert system.lines("model-calls.jsonl") == []
            assert system.lines("native-submissions.jsonl") == []
            await system.count(0)
            assert await system.submit(spec, value) == recovered
            await system.evidence(recovered.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_sealed_coding_root_drive_retries_registry_without_new_native_permission(
    tmp_path, monkeypatch
):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch) as system, system.worker():
            (tmp_path / "block-release").touch()
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await _eventually(
                lambda: system.engine.events(original.run_id),
                lambda events: sum(e.kind == "deployment_retirement_deferred" for e in events) >= 2,
                seconds=80,
            )
            closure = await system.view(original.run_id, "deployment_closure")
            certificate = copy.deepcopy(closure["seal"])
            assert closure["ready"] and certificate is not None
            await system.count(1)
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            (tmp_path / "block-release").unlink()
            await system.engine.drive(original.run_id, wait_seconds=0)
            await system.count(0)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] == certificate
            assert system.lines("native-submissions.jsonl") == before
            assert await system.submit(spec, value) == original
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_coding3_lost_release_reply_recovers_original_retirement_and_receipt(
    tmp_path, monkeypatch
):
    async def scenario():
        from temporalio.api.enums.v1 import EventType

        async with coding_system(tmp_path, monkeypatch) as system, system.worker():
            (tmp_path / "lose-release-reply").touch()
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            marker = tmp_path / "lost-release-reply.json"
            await _eventually(lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=80)
            await _eventually(
                lambda: system.engine.events(original.run_id),
                lambda events: any(e.kind == "deployment_retirement_deferred" for e in events),
                seconds=80,
            )
            lost = json.loads(marker.read_text())
            certificate = copy.deepcopy(
                (await system.view(original.run_id, "deployment_closure"))["seal"]
            )
            assert certificate is not None and lost["payload"]["certificate"] == certificate
            assert lost["workflow_id"] == registry_id(system.policy.deployment_id)
            assert lost["result"]["released"] is True
            assert lost["result"]["certificate"] == certificate
            assert lost["result"]["root"]["run_id"] == original.run_id
            # The real Update retired quota before its reply was lost.
            await system.count(0)
            business = copy.deepcopy(system.lines("native-submissions.jsonl"))
            commits = copy.deepcopy(system.lines("native-commits.jsonl"))
            assert len(business) == 2 and len(commits) == 1
            await system.engine.drive(original.run_id, wait_seconds=0)
            await _eventually(
                lambda: system.engine.events(original.run_id),
                lambda events: any(e.kind == "deployment_retired" for e in events),
                seconds=80,
            )
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] == certificate
            assert await system.submit(spec, value) == original
            await system.count(0)
            assert system.lines("native-submissions.jsonl") == business
            assert system.lines("native-commits.jsonl") == commits
            history = await system.client.get_workflow_handle(lost["workflow_id"]).fetch_history()
            releases = {
                event.event_id
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED
                and event.workflow_execution_update_accepted_event_attributes.accepted_request.input.name
                == "release_deployment_root"
            }
            completed = [
                event.workflow_execution_update_completed_event_attributes
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_COMPLETED
                and event.workflow_execution_update_completed_event_attributes.accepted_event_id
                in releases
            ]
            # Retry uses the first Update ID and its already completed response.
            assert len(releases) == len(completed) == 1
            assert completed[0].outcome.WhichOneof("value") == "success"
            assert await system.client.data_converter.decode(
                completed[0].outcome.success.payloads
            ) == [lost["result"]]
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_hidden_planner_without_pg_rows_keeps_root_until_actual_handler_ends(
    tmp_path, monkeypatch
):
    async def scenario():
        async with (
            coding_system(tmp_path, monkeypatch, kind="dynamic-model") as system,
            system.worker(),
        ):
            (tmp_path / "block-aux-model").touch()
            original = await system.submit(*definition("dynamic-model")[:2])
            await _eventually(
                lambda: asyncio.sleep(0, result=(tmp_path / "block-aux-model.attempted").exists()),
                bool,
            )
            held = await system.view(original.run_id, "deployment_closure")
            planner = next(c for c in held["deployment"]["children"] if c["member"] == "@planner")
            assert await system.rows("ralf_temporal_coding_resources") == []
            await system.engine.cancel(original.run_id, command_id="cancel-planner")
            await _eventually(
                lambda: system.engine.status(planner["run_id"]), lambda s: s.state == "cancelled"
            )
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            assert system.lines("native-submissions.jsonl") == []
            (tmp_path / "block-aux-model").unlink()
            await system.count(0)
            assert system.lines("native-submissions.jsonl") == []
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_dynamic_patch_retains_live_original_revision_and_child_seals(tmp_path, monkeypatch):
    async def scenario():
        from ralf_agent import DAGNode, DAGProposal

        async with (
            coding_system(tmp_path, monkeypatch, kind="dynamic-dag", hold=True) as system,
            system.worker(),
        ):
            original = await system.submit(*definition("dynamic-dag")[:2])
            await system.approve(original.run_id)
            await system.committed()
            details = await system.engine.diagnostics(original.run_id)
            prior = DAGProposal.from_dict(details.workflow["dag"]["proposal"])
            original_calls = copy.deepcopy(
                (await system.view(original.run_id, "deployment_closure"))["deployment"]["children"]
            )
            proposal = DAGProposal(
                [
                    *(DAGNode.from_dict(node) for node in prior.nodes),
                    DAGNode("later", "actual-member", depends_on=(prior.nodes[-1]["id"],)),
                ]
            )
            receipt = await system.engine.patch_plan(
                original.run_id, proposal, expected_plan_revision=0, command_id="patch"
            )
            assert (
                await system.engine.patch_plan(
                    original.run_id, proposal, expected_plan_revision=0, command_id="patch"
                )
                == receipt
            )
            current = (await system.view(original.run_id, "deployment_closure"))["deployment"][
                "children"
            ]
            assert current == original_calls and current[0]["planning_revision"] == 0
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            (tmp_path / "release-turns").touch()
            assert (await system.approve(original.run_id, all_steps=True)).state == "succeeded"
            await system.count(0)
            closure = await system.evidence(original.run_id)
            assert len(closure["deployment"]["children"]) == 2
            assert len(system.lines("native-submissions.jsonl")) == 4

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_zero_credit_native_commit_alive_and_unknown_keeps_deployment_quota(
    tmp_path, monkeypatch
):
    async def scenario():
        async with (
            coding_system(
                tmp_path,
                monkeypatch,
                hold=True,
                cost=0,
            ) as system,
            system.worker(),
        ):
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            leaf, action_id = await system.approve(original.run_id)
            committed = await system.committed()
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            (tmp_path / "fail-kill").touch()
            await system.engine.cancel(original.run_id, command_id="cancel")
            unknown = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id and a["status"] == "outcome_unknown"
                    for a in d["snapshot"]["actions"]
                ),
                seconds=40,
            )
            assert unknown["budget"]["reserved"] == unknown["budget"]["unknown"] == 0
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in unknown["budget"]["reservations"]
            )
            native = next(a for a in unknown["snapshot"]["actions"] if a["id"] == action_id)[
                "delegated_execution"
            ]
            assert native["pending_stop"] is True and native["fenced"] is False
            # Genuine file evidence is not a forged Coding result_candidate.
            await system.engine.reconcile(
                leaf, action_id, {"artifact": committed[0]}, command_id="actual-file-evidence"
            )
            await system.count(1)
            assert (await system.view(leaf, "deployment_closure"))["seal"] is None
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, value, command_id="still-held")
            (tmp_path / "fail-kill").unlink()
            await system.engine.drive(leaf, wait_seconds=0)
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: (
                    all(t["execution_stopped"] for t in d["workflow"]["tool_executions"])
                    and any(
                        a.get("delegated_execution", {}).get("fenced") is True
                        and a["delegated_execution"]["pending_stop"] is False
                        for a in d["snapshot"]["actions"]
                    )
                ),
                seconds=80,
            )
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in stopped["budget"]["reservations"]
            )
            await system.count(1)
            assert system.lines("native-submissions.jsonl") == before
            actual = await asyncio.to_thread(Path(committed[0]["path"]).read_bytes)
            assert committed[0]["sha256"] == hashlib.sha256(actual).hexdigest()
            (tmp_path / "genuine-commit-and-unknown.json").write_text(
                json.dumps({"committed": committed, "original_native": native, "stopped": stopped})
            )
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_zero_credit_dispatched_deadline_unknown_keeps_deployment_quota(
    tmp_path, monkeypatch
):
    """The fixed deadline may precede commit; dispatch and uncertainty stay distinct."""

    async def scenario():
        async with (
            coding_system(
                tmp_path,
                monkeypatch,
                hold=True,
                cost=0,
                execution_policy={"run_timeout_seconds": 15},
            ) as system,
            system.worker(),
        ):
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            leaf, action_id = await system.approve(original.run_id)
            unknown = await _eventually(
                lambda: system.view(leaf),
                lambda d: (
                    (d["snapshot"].get("error") or {}).get("code") == "deadline_exceeded"
                    and any(
                        a["id"] == action_id and a["status"] == "outcome_unknown"
                        for a in d["snapshot"]["actions"]
                    )
                ),
                seconds=40,
            )
            owner = next(
                t for t in unknown["workflow"]["tool_executions"] if t["action_id"] == action_id
            )
            # Original History positively admitted this dispatched Tool. Missing
            # native commit logs are never a no-dispatch or no-start certificate.
            assert owner["grant_allowed"] is True and owner["invocation_id"]
            assert unknown["budget"]["reserved"] == unknown["budget"]["unknown"] == 0
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in unknown["budget"]["reservations"]
            )
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: (
                    all(t["execution_stopped"] for t in d["workflow"]["tool_executions"])
                    and any(
                        a["id"] == action_id
                        and a.get("delegated_execution", {}).get("fenced") is True
                        and a["delegated_execution"]["pending_stop"] is False
                        for a in d["snapshot"]["actions"]
                    )
                ),
                seconds=80,
            )
            action = next(a for a in stopped["snapshot"]["actions"] if a["id"] == action_id)
            assert action["status"] == "outcome_unknown"
            grants = copy.deepcopy(action["delegated_execution"]["grants"])
            business = copy.deepcopy(system.lines("native-submissions.jsonl"))
            commit_evidence = []
            for record in system.lines("native-commits.jsonl"):
                contents = await asyncio.to_thread(Path(record["path"]).read_bytes)
                assert contents == b"fixture artifact\n"
                commit_evidence.append({**record, "sha256": hashlib.sha256(contents).hexdigest()})
            await system.engine.drive(leaf, wait_seconds=0)
            assert await system.submit(spec, value) == original
            await system.count(1)
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, value, command_id="deadline-unknown-still-held")
            after = await system.view(leaf)
            action_after = next(a for a in after["snapshot"]["actions"] if a["id"] == action_id)
            assert action_after["status"] == "outcome_unknown"
            assert action_after["delegated_execution"]["grants"] == grants
            assert system.lines("native-submissions.jsonl") == business
            assert any(
                r["amount"] == 0 and r["status"] == "unknown"
                for r in after["budget"]["reservations"]
            )
            events = await system.engine.events(leaf)
            deadline = next(
                i for i, event in enumerate(events) if event.kind == "deadline_exceeded"
            )
            assert not any(event.kind == "coding_phase_granted" for event in events[deadline + 1 :])
            record_path = tmp_path / "deadline-dispatched-and-unknown.json"
            record_path.write_text(
                json.dumps(
                    {
                        "commit_observed": bool(commit_evidence),
                        "committed": commit_evidence,
                        "missing_commit_is_no_dispatch_proof": False,
                        "deadline_after_commit_gate": "not_claimed",
                        "original_receipt": asdict(original),
                        "stopped": stopped,
                        "after_drive": after,
                    }
                )
            )
            record_path.chmod(0o600)
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 240))


@pytest.mark.parametrize("boundary", ["native-stop", "tool-end", "deployment-end", "effect"])
def test_actual_original_native_tool_deployment_and_effect_ack_gates_are_independent(
    tmp_path, monkeypatch, boundary
):
    _native_ack_case(tmp_path, monkeypatch, boundary, pressure=False)


def test_actual_original_coding_stop_receipt_after_2000_updates(tmp_path, monkeypatch):
    _native_ack_case(tmp_path, monkeypatch, "native-stop", pressure=True)


def _native_ack_case(tmp_path, monkeypatch, boundary, *, pressure):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch) as system, system.worker() as first_worker:
            if pressure:
                await system.effect_ack_gate(True)
            if boundary == "effect":
                await system.effect_ack_gate(True)
            else:
                prefix = "hold-" if boundary == "native-stop" else "block-"
                (tmp_path / (prefix + boundary)).touch()
            original = await system.submit(*definition("agent")[:2])
            leaf, action_id = await system.approve(original.run_id)
            await _eventually(
                lambda: asyncio.sleep(0, result=system.lines("native-commits.jsonl")),
                bool,
                seconds=80,
            )
            if boundary == "effect":
                await _eventually(
                    lambda: system.engine.events(leaf),
                    lambda events: any(e.kind == "effect_journal_ack_deferred" for e in events),
                    seconds=80,
                )
            else:
                marker = tmp_path / (prefix + boundary + ".attempted")
                await _eventually(
                    lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=80
                )
            if pressure:
                from temporalio.converter import DataConverter

                assert boundary == "native-stop"
                start = asyncio.get_running_loop().time()
                handle = system.client.get_workflow_handle(leaf)
                epoch = (await handle.describe()).run_id
                history = await handle.fetch_history()
                approvals = []
                for event in history.events:
                    if event.HasField("workflow_execution_signaled_event_attributes"):
                        attrs = event.workflow_execution_signaled_event_attributes
                        if attrs.signal_name == "control_command":
                            (envelope,) = await DataConverter.default.decode(attrs.input.payloads)
                            if envelope["request"]["payload"]["kind"] == "approve":
                                approvals.append(envelope["request"])
                    elif event.HasField("workflow_execution_update_accepted_event_attributes"):
                        attrs = event.workflow_execution_update_accepted_event_attributes
                        if attrs.accepted_request.input.name == "command":
                            (request,) = await DataConverter.default.decode(
                                attrs.accepted_request.input.args.payloads
                            )
                            if request["payload"]["kind"] == "approve":
                                approvals.append(request)
                assert len(approvals) == 1
                accepted = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in history.events
                )
                assert 1 <= accepted < 2000
                for fill_start in range(accepted, 2000, 8):
                    receipts = await asyncio.gather(
                        *[
                            handle.execute_update("command", approvals[0])
                            for _ in range(fill_start, min(fill_start + 8, 2000))
                        ]
                    )
                    assert all(r == receipts[0] for r in receipts)
                    (tmp_path / "pressure-progress.json").write_text(
                        json.dumps({"accepted_updates": min(fill_start + 8, 2000)})
                    )
                history = await handle.fetch_history()
                accepted = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in history.events
                )
                completed = sum(
                    e.HasField("workflow_execution_update_completed_event_attributes")
                    for e in history.events
                )
                elapsed = asyncio.get_running_loop().time() - start
                assert accepted == completed == 2000
                assert (await handle.describe()).run_id == epoch
                assert (tmp_path / "hold-native-stop").exists() and elapsed < 30
                (tmp_path / "pressure-history.json").write_text(history.to_json())
                (tmp_path / "pressure.json").write_text(
                    json.dumps(
                        {
                            "accepted_updates": accepted,
                            "completed_updates": completed,
                            "original_execution_epoch": epoch,
                            "original_approval_repeated": True,
                            "hold_gate_seconds_unchanged": 30,
                            "pressure_seconds": elapsed,
                        }
                    )
                )
            view = await system.view(leaf, "deployment_closure")
            assert view["seal"] is None and not view["ready"]
            await system.count(1)
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            assert [v["method"] for v in before] == ["thread/start", "turn/start"]
            if pressure:
                cancel = await system.engine.cancel(original.run_id, command_id="pressure-stop")
                assert (
                    await system.engine.cancel(original.run_id, command_id="pressure-stop")
                    == cancel
                )
            if boundary == "effect":
                await system.effect_ack_gate(False)
            else:
                (tmp_path / (prefix + boundary)).unlink()
            if pressure:
                await _eventually(
                    lambda: system.engine.events(leaf),
                    lambda events: any(e.kind == "effect_journal_ack_deferred" for e in events),
                    seconds=80,
                )
                await system.count(1)
                assert (await system.view(leaf, "deployment_closure"))["seal"] is None
                await system.effect_ack_gate(False)
            if boundary == "tool-end":
                assert await system.runtime.wait_context_executions(wait_timeout=60) is True
            elif boundary == "deployment-end":
                from ralf_agent.temporal_deployment_release import check_owner

                owner = check_owner(system.runtime)
                assert owner is not None
                assert await owner.wait(wait_timeout=60) is True
            await system.engine.drive(leaf, wait_seconds=0)
            details = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id
                    and a["status"]
                    in ({"completed"} if pressure else {"completed", "outcome_unknown"})
                    for a in d["snapshot"]["actions"]
                ),
                seconds=80,
            )
            action = next(a for a in details["snapshot"]["actions"] if a["id"] == action_id)
            if action["status"] == "outcome_unknown":
                candidate = action["delegated_execution"].get("result_candidate")
                assert type(candidate) is dict
                recorded = await system.capture()
                assert any(
                    receipt.get("kind") == "result_candidate" and receipt["result"] == candidate
                    for row in recorded["ralf_temporal_runner_effects"]
                    for receipt in json.loads(row["record"])["observations"]
                )
                await system.engine.reconcile(
                    leaf, action_id, query=True, command_id="recover-durable-original-candidate"
                )
            await system.count(0)
            assert system.lines("native-submissions.jsonl") == before
            closure = await system.evidence(original.run_id)
            assert closure["calls"] and all(
                call["stopped"] and call["end_proof"] == call["identity"]
                for call in closure["calls"].values()
            )
            final = await system.view(leaf)
            action = next(a for a in final["snapshot"]["actions"] if a["id"] == action_id)
            assert final["snapshot"]["state"] == ("cancelled" if pressure else "succeeded")
            assert action["status"] == "completed"
            recorded = await system.capture()
            effects = recorded["ralf_temporal_effects"]
            assert len(effects) == 1 and effects[0]["state"] == "adopted"
            assert effects[0]["adopted_result_digest"] == digest(action["result"])
            evidence = recorded["ralf_temporal_effect_evidence"]
            assert len(evidence) == 1 and evidence[0]["effect_key"] == effects[0]["effect_key"]
            if pressure:
                history = await system.client.get_workflow_handle(leaf).fetch_history()
                assert (
                    sum(
                        e.HasField("workflow_execution_update_accepted_event_attributes")
                        for e in history.events
                    )
                    == 2000
                )
                assert [v["method"] for v in before] == ["thread/start", "turn/start"]
                (tmp_path / "pressure-result.json").write_text(
                    json.dumps(
                        {
                            "held_roots": 0,
                            "effect_adopted": True,
                            "physical_stopped": True,
                            "original_submissions_unchanged": True,
                            "run_history_replayed": True,
                            "model_calls": 0,
                            "structural_native_peer": True,
                        }
                    )
                )
                await first_worker.shutdown()
                assert first_worker.is_shutdown and not first_worker.is_running
                restarted = build_temporal_worker(
                    first_worker.config()["client"],
                    task_queue=system.queue,
                    runtime=system.runtime,
                    release=system.release,
                    graceful_shutdown_timeout=timedelta(seconds=1),
                )
                system.workers.append(restarted)
                async with restarted:
                    from ralf_agent.temporal_coding_recovery_transport import execute

                    stops = []
                    for event in history.events:
                        if event.HasField("workflow_execution_signaled_event_attributes"):
                            attrs = event.workflow_execution_signaled_event_attributes
                            if attrs.signal_name == "coding_recovery":
                                (envelope,) = await DataConverter.default.decode(
                                    attrs.input.payloads
                                )
                                if (
                                    envelope["operation"] == "coding_receipt"
                                    and envelope["proof"].get("kind") == "stop"
                                ):
                                    stops.append(envelope)
                    assert stops
                    original_stop = stops[0]
                    observed = await system.client.get_workflow_handle(leaf).query(
                        "view",
                        {
                            "kind": "status",
                            "scope": asdict(system.scope),
                            "coding_recovery_observation": original_stop,
                        },
                    )
                    receipt = observed["coding_recovery_observation"]["result"]
                    assert receipt["ok"] is True
                    repeated = await execute(
                        system.client,
                        leaf,
                        "coding_receipt",
                        original_stop["proof"],
                        execution_epoch=epoch,
                    )
                    assert repeated == receipt["receipt"]
                    await system.count(0)
                    assert system.lines("native-submissions.jsonl") == before
                    await system.evidence(original.run_id)
                    await system.assembly.aclose(wait_timeout=60)
                (tmp_path / "pressure-restart.json").write_text(
                    json.dumps(
                        {
                            "original_stop_receipt_equal": True,
                            "held_roots": 0,
                            "submissions_unchanged": True,
                            "history_replayed": True,
                            "owned_assembly_closed": True,
                        }
                    )
                )

    asyncio.run(asyncio.wait_for(scenario(), 240))


def test_actual_native_stop_prewrite_failure_without_candidate_retains_unknown(
    tmp_path, monkeypatch
):
    """A failed stop ACK cannot manufacture the candidate lost with its stack."""

    async def scenario():
        async with coding_system(tmp_path, monkeypatch) as system, system.worker():
            gate = tmp_path / "block-native-stop"
            gate.touch()
            spec, value, _ = definition("agent")
            original = await system.submit(spec, value)
            leaf, action_id = await system.approve(original.run_id)
            await _eventually(
                lambda: asyncio.sleep(
                    0, result=(tmp_path / "block-native-stop.attempted").exists()
                ),
                bool,
                seconds=80,
            )
            unknown = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id
                    and a["status"] == "outcome_unknown"
                    and a["delegated_execution"]["stop_retry"] is True
                    and a["delegated_execution"]["stop_active"] is False
                    for a in d["snapshot"]["actions"]
                ),
                seconds=80,
            )
            native = next(
                a["delegated_execution"]
                for a in unknown["snapshot"]["actions"]
                if a["id"] == action_id
            )
            assert "result_candidate" not in native and native["pending_stop"] is True
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            assert [record["method"] for record in before] == ["thread/start", "turn/start"]
            assert len(system.lines("native-commits.jsonl")) == 1
            await system.count(1)
            gate.unlink()
            await system.engine.drive(leaf, wait_seconds=0)
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: (
                    all(t["execution_stopped"] for t in d["workflow"]["tool_executions"])
                    and any(
                        a["id"] == action_id
                        and a["delegated_execution"]["pending_stop"] is False
                        and a["delegated_execution"]["fenced"] is True
                        for a in d["snapshot"]["actions"]
                    )
                ),
                seconds=80,
            )
            action = next(a for a in stopped["snapshot"]["actions"] if a["id"] == action_id)
            assert action["status"] == "outcome_unknown"
            assert "result_candidate" not in action["delegated_execution"]
            assert any(r["status"] == "unknown" for r in stopped["budget"]["reservations"])
            captured = await system.capture()
            effects = captured["ralf_temporal_effects"]
            assert len(effects) == 1 and effects[0]["state"] == "dispatched"
            assert effects[0]["adopted_result_digest"] is None
            assert captured["ralf_temporal_effect_evidence"] == []
            records = captured["ralf_temporal_runner_effects"]
            assert len(records) == 1
            assert all(
                r.get("kind") != "result_candidate"
                for r in json.loads(records[0]["record"])["observations"]
            )
            closure = await _eventually(
                lambda: system.view(leaf, "deployment_closure"),
                lambda d: bool(d["calls"]) and all(c["stopped"] for c in d["calls"].values()),
                seconds=80,
            )
            assert all(
                c["end_proof"] is not None and c["fence_proof"] is None
                for c in closure["calls"].values()
            )
            assert closure["seal"] is None and not closure["ready"]
            await system.count(1)
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, value, command_id="no-candidate-still-held")
            assert system.lines("native-submissions.jsonl") == before
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 240))


@pytest.mark.parametrize("window", ["turn", "candidate"])
def test_actual_worker_death_uses_exact_original_cold_call_fence(tmp_path, monkeypatch, window):
    async def scenario():
        from temporalio.client import WorkflowUpdateFailedError

        async with coding_system(tmp_path, monkeypatch, hold=window == "turn", cost=0) as system:
            (tmp_path / ("crash-after-" + window)).touch()
            (tmp_path / "block-cold-verification").touch()
            first = await system.start_process()
            original = await system.submit(*definition("agent")[:2])
            leaf, action_id = await system.approve(original.run_id)
            await _eventually(
                lambda: asyncio.sleep(0, result=first.poll()), lambda code: code == 71, seconds=80
            )
            await asyncio.to_thread(first.wait, timeout=5)
            crash = json.loads((tmp_path / "actual-worker-crash.json").read_text())
            assert crash["pid"] == first.pid and crash["workflow_id"] == leaf
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            assert [r["method"] for r in before] == ["thread/start", "turn/start"]
            await system.start_process()
            assert await system.submit(*definition("agent")[:2]) == original
            await system.engine.cancel(original.run_id, command_id="stop-original")
            stopped = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    t.get("coding_owner_stop_proof") is not None and t["execution_stopped"] is True
                    for t in d["workflow"]["tool_executions"]
                ),
                seconds=100,
            )
            tool = next(
                t
                for t in stopped["workflow"]["tool_executions"]
                if t.get("coding_owner_stop_proof")
            )
            assert tool["coding_owner_stop_proof"]["evidence"]["owner"]["pid"] == first.pid
            closure = await system.view(leaf, "deployment_closure")
            call = next(
                c
                for c in closure["calls"].values()
                if c["identity"]["activity_name"] == "ralf.temporal.tool.v1"
            )
            assert call["stopped"] is False and call["fence_proof"] is None
            await system.count(1)
            with pytest.raises(WorkflowUpdateFailedError):
                await system.client.get_workflow_handle(
                    leaf, run_id=call["identity"]["execution_epoch"]
                ).execute_update(
                    "deployment_coding_call_stopped",
                    {
                        "scope": asdict(system.scope),
                        "identity": call["identity"],
                        "process_present": False,
                        "native_fenced": True,
                    },
                )
            (tmp_path / "cold-before-fence.json").write_text(
                json.dumps({"closure": closure, "tool": tool})
            )
            if window == "candidate":
                # Genuine candidate was durably accepted before process death.
                # Query its original PG receipt; do not manufacture an outcome.
                await system.engine.reconcile(
                    leaf, action_id, query=True, command_id="recover-durable-candidate"
                )
                await _eventually(
                    lambda: system.view(leaf),
                    lambda d: all(r["status"] == "settled" for r in d["budget"]["reservations"]),
                    seconds=80,
                )
                await system.count(1)
            (tmp_path / "block-cold-verification").unlink()
            await system.engine.drive(leaf, wait_seconds=0)
            await system.client.get_workflow_handle(
                leaf, run_id=call["identity"]["execution_epoch"]
            ).execute_update(
                "deployment_coding_call_stopped",
                {"scope": asdict(system.scope), "identity": call["identity"]},
            )
            fenced = await _eventually(
                lambda: system.view(leaf, "deployment_closure"),
                lambda d: any(c.get("fence_proof") is not None for c in d["calls"].values()),
                seconds=80,
            )
            exact = next(c for c in fenced["calls"].values() if c.get("fence_proof"))
            assert exact["identity"] == call["identity"] and exact["end_proof"] == call["identity"]
            assert exact["fence_proof"]["owner"]["pid"] == first.pid
            assert exact["fence_proof"]["action_id"] == action_id
            assert exact["fence_proof"]["process_present"] is False
            assert exact["fence_proof"]["native_fenced"] is True
            assert exact["fence_proof"]["execution_epoch"] == call["identity"]["execution_epoch"]
            assert system.lines("native-submissions.jsonl") == before
            await system.count(0 if window == "candidate" else 1)
            if window == "turn":
                assert fenced["seal"] is None
            await system.evidence(original.run_id, sealed=window == "candidate")
            if window == "turn":
                await system.expect_retention(original.run_id)
        if window == "turn":
            system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 300))


@pytest.mark.parametrize("kind", ["agent", "recursive"])
def test_actual_owned_close_includes_approval_children_without_pg_resource_rows(
    tmp_path, monkeypatch, kind
):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch, kind=kind) as system:
            await system.start_process()
            await system.assembly.start_worker(system.client, task_queue=system.queue)
            engine = system.assembly.create_engine(
                system.client, task_queue=system.queue, activity_timeout=80
            )
            original = await system.submit(*definition(kind)[:2], engine=engine)
            await _eventually(
                lambda: engine.status(original.run_id),
                lambda s: s.state == "waiting_approval",
                seconds=80,
            )
            assert await system.rows("ralf_temporal_coding_resources") == []
            candidates = await system.candidates()
            assert any(c["run_id"] == original.run_id for c in candidates)
            await system.count(1)
            await system.assembly.aclose(wait_timeout=80)
            assert system.assembly._closed
            assert system.lines("native-submissions.jsonl") == []
            observer = system.facade()
            assert (await observer.status(original.run_id)).state == "cancelled"
            assert (await system.client.get_workflow_handle(original.run_id).describe()).run_id == (
                await system.view(original.run_id, "deployment_closure")
            )["deployment"]["execution_epoch"]
            await system.count(0)
            await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 300))


def test_actual_parallel_owned_close_retains_failed_leaf_and_original_receivers(
    tmp_path, monkeypatch
):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch, kind="graph-parallel", hold=True) as system:
            await system.start_process()
            # Native kill failure is injected by the original peer CLI below;
            # the assembly must retain the same SDK client as its first engine.
            await system.assembly.start_worker(system.client, task_queue=system.queue)
            engine = system.assembly.create_engine(
                system.client, task_queue=system.queue, activity_timeout=80
            )
            original = await system.submit(*definition("graph-parallel")[:2], engine=engine)
            await system.approve(original.run_id)
            await system.approve(original.run_id)
            committed = await system.committed(2)
            failure = tmp_path / "fail-kill-cid"
            failure.write_text(committed[0]["cid"])
            ledger = system.assembly._context._resources
            originals = tuple(entry.resource for entry in ledger)
            with pytest.raises(CloseIncomplete):
                await system.assembly.aclose(wait_timeout=10)
            original_stop_task = system.assembly._coding_stop_task
            if original_stop_task is not None:
                # Consume this retained original failure before releasing its
                # fault, so the recovery call cannot inherit its late failure.
                with pytest.raises(CloseIncomplete):
                    await system.assembly.aclose(wait_timeout=80)
                assert original_stop_task.done()
                assert system.assembly._coding_stop_task is None
            assert {"cid": committed[0]["cid"], "kind": "native_kill_failure"} in system.lines(
                "native-stop-failures.jsonl"
            )
            assert system.assembly._closing and not system.assembly._closed
            assert system.assembly._context._resources is ledger
            assert tuple(entry.resource for entry in ledger) == originals
            assert system.assembly._client is system.client
            assert not system.runtime.journal.connection.closed
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            assert len(before) == 4
            failure.unlink()
            try:
                await system.assembly.aclose(wait_timeout=80)
            except CloseIncomplete:
                # An independent SDK STOP may still own the preceding failed
                # cleanup wave. Consume that failure without dropping its
                # resources, then make one explicit close retry. The scenario's
                # original 300-second limit still bounds both calls.
                assert system.assembly._coding_stop_task is None
                assert system.assembly._closing and not system.assembly._closed
                assert system.assembly._context._resources is ledger
                assert tuple(entry.resource for entry in ledger) == originals
                assert system.assembly._client is system.client
                assert not system.runtime.journal.connection.closed
                assert system.lines("native-submissions.jsonl") == before
                await system.count(1)
                assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
                await system.assembly.aclose(wait_timeout=80)
            assert system.assembly._closed and system.runtime.journal.connection.closed
            assert system.lines("native-submissions.jsonl") == before
            await system.count(1)
            await system.evidence(original.run_id, sealed=False)
            await system.expect_retention(original.run_id)
        system.assert_retained()

    asyncio.run(asyncio.wait_for(scenario(), 300))
