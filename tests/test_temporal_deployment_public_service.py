"""Actual public admission, first receipts and original-History quota retirement.

Requires an owned real Temporal Service. Deterministic Providers and trusted
Python handlers perform local business; no model network or Temporal test server.
The independent SQLite journal below stores only effect evidence, never quota,
Run state, closure, scheduler decisions, or SDK ownership.
"""

import asyncio
import copy
import json
import os
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ToolCall,
    ToolExecutionOwner,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.errors import CapacityExceeded, IdempotencyConflict
from ralf_agent.executors import EffectObservation
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.types import canonical, digest, submission_request

from .test_temporal_deployment_admission_service import _clients, _start, _worker
from .test_temporal_deployment_dispatch_service import BusinessProbe, _agent, _case, _eventually
from .test_temporal_policy_profiles_service import through_catalog

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)

CASES = [
    "agent",
    "sequence",
    "graph-sequential",
    "graph-parallel",
    "team-sequential",
    "team-router",
    "team-supervisor",
    "dynamic-dag",
    "nested-parent-sequence",
]


class SDKFaultClient:
    """Delegate all SDK identity/proof reads; lose selected real completed replies."""

    def __init__(self, original, *, lose=None, block_end=False, block_release=False):
        self.original, self.lose = original, lose
        self.dropped = []
        self.block_end = block_end
        self.end_attempted = asyncio.Event()
        self.block_release = block_release
        self.release_attempted = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.original, name)

    @staticmethod
    def unavailable(message):
        from temporalio.service import RPCError, RPCStatusCode

        return RPCError(message, RPCStatusCode.UNAVAILABLE, b"")

    async def start_workflow(self, name, *args, **kwargs):
        result = await self.original.start_workflow(name, *args, **kwargs)
        if self.lose == "start" and name in {"ralf.temporal.run.v1", "ralf.temporal.parent.v1"}:
            self.lose = None
            self.dropped.append({"kind": "start", "run_id": result.id})
            raise self.unavailable("injected loss after actual SDK start acceptance")
        return result

    def get_workflow_handle(self, *args, **kwargs):
        return SDKFaultHandle(self, self.original.get_workflow_handle(*args, **kwargs))


class SDKFaultHandle:
    def __init__(self, client, original):
        self.client, self.original = client, original

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def execute_update(self, name, *args, **kwargs):
        if name == "release_deployment_root" and self.client.block_release:
            self.client.release_attempted.set()
            raise self.client.unavailable(
                "injected unavailable original Registry release transport"
            )
        if name == "deployment_call_ended" and self.client.block_end:
            self.client.end_attempted.set()
            raise self.client.unavailable("injected unavailable original call-end ACK transport")
        result = await self.original.execute_update(name, *args, **kwargs)
        expected = {"reserve": "reserve", "release_deployment_root": "release"}.get(name)
        if expected is not None and self.client.lose == expected:
            self.client.lose = None
            self.client.dropped.append({"kind": expected, "workflow_id": self.original.id})
            raise self.client.unavailable("injected loss after actual original Registry Update")
        return result


class SQLiteEffectEvidence:
    """Test-only completed durable EffectJournal adapter, separate from business DB."""

    def __init__(self, path):
        self.path = str(path)
        self.block_ack = False
        self.ack_attempted = asyncio.Event()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE effects (scope TEXT, effect_key TEXT, identity TEXT, target TEXT, "
                "state TEXT, result TEXT, source TEXT, adopted_digest TEXT, "
                "run_id TEXT, action_id TEXT, "
                "PRIMARY KEY(scope,effect_key))"
            )

    @property
    def identity(self):
        return {"kind": "service-sqlite-effect-evidence", "version": "1", "path": self.path}

    @staticmethod
    def _key(envelope):
        context = envelope.context
        return (
            canonical(asdict(context.scope)),
            context.effect_key,
            digest([context.run_id, context.action_id, envelope.operation_digest]),
            digest([envelope.tool_name, envelope.arguments]),
        )

    def _record(self, db, envelope):
        scope, key, identity, _ = self._key(envelope)
        row = db.execute(
            "SELECT identity,state,result,source,adopted_digest FROM effects "
            "WHERE scope=? AND effect_key=?",
            (scope, key),
        ).fetchone()
        if row is not None and row[0] != identity:
            raise IdempotencyConflict("Original effect key identifies another operation")
        return row

    async def begin(self, envelope):
        scope, key, identity, target = self._key(envelope)
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._record(db, envelope)
            if row is not None:
                return {
                    "execute": False,
                    "observation": None
                    if row[2] is None
                    else EffectObservation(json.loads(row[2]), row[3]),
                }
            prior = db.execute(
                "SELECT run_id,action_id,effect_key FROM effects "
                "WHERE scope=? AND target=? AND state<>'adopted'",
                (scope, target),
            ).fetchone()
            if prior is not None:
                return {
                    "execute": False,
                    "blocked": True,
                    "prior": dict(zip(("run_id", "action_id", "effect_key"), prior, strict=True)),
                }
            db.execute(
                "INSERT INTO effects VALUES (?,?,?,?, 'dispatched',NULL,NULL,NULL,?,?)",
                (scope, key, identity, target, envelope.context.run_id, envelope.context.action_id),
            )
        return {"execute": True}

    async def received(self, envelope, observation):
        scope, key, _, _ = self._key(envelope)
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            assert self._record(db, envelope) is not None
            db.execute(
                "UPDATE effects SET result=COALESCE(result,?),source=COALESCE(source,?),"
                "state=CASE WHEN state='adopted' THEN state ELSE 'received' END "
                "WHERE scope=? AND effect_key=?",
                (canonical(observation.result), observation.source, scope, key),
            )

    async def observation(self, envelope):
        with sqlite3.connect(self.path) as db:
            row = self._record(db, envelope)
        return (
            None if row is None or row[2] is None else EffectObservation(json.loads(row[2]), row[3])
        )

    async def acknowledge(self, envelope, observation):
        self.ack_attempted.set()
        if self.block_ack:
            raise ConnectionError("injected unavailable effect evidence ACK")
        scope, key, _, _ = self._key(envelope)
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._record(db, envelope)
            assert row is not None
            if row[4] is not None and row[4] != digest(observation.result):
                raise IdempotencyConflict("Original adopted result cannot change")
            db.execute(
                "UPDATE effects SET state='adopted',adopted_digest=?,"
                "result=COALESCE(result,?),source=COALESCE(source,?) "
                "WHERE scope=? AND effect_key=?",
                (
                    digest(observation.result),
                    canonical(observation.result),
                    observation.source,
                    scope,
                    key,
                ),
            )

    async def aclose(self):
        pass  # Each completed operation owns and closes its SQLite connection.


class CommittedThreadWrite:
    """A real zero-cost write commits before its trusted sync thread blocks."""

    def __init__(self, path):
        self.path = str(path)
        self.started, self.release, self.ended = (threading.Event() for _ in range(3))
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE business (effect_key TEXT PRIMARY KEY, result TEXT, calls INTEGER)"
            )

    def write(self, arguments, context):
        result = {"label": arguments["label"], "effect_key": context.effect_key}
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO business VALUES (?,?,1) ON CONFLICT(effect_key) "
                "DO UPDATE SET calls=business.calls+1",
                (context.effect_key, canonical(result)),
            )
        self.started.set()
        try:
            assert self.release.wait(45), "owned sync write was not allowed to end"
            return result
        finally:
            self.ended.set()

    def reconcile(self, arguments, context):
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT result FROM business WHERE effect_key=?", (context.effect_key,)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def committed(self):
        with sqlite3.connect(self.path) as db:
            return [
                (json.loads(result), calls)
                for result, calls in db.execute("SELECT result,calls FROM business")
            ]

    def tools(self):
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "write",
                "Genuine committed local write",
                {"type": "object"},
                effect="queryable_write",
                cost=0,
            ),
            self.write,
            reconciler=self.reconcile,
        )
        return tools


class WriteProvider:
    identity = {"kind": "public-deployment-write-provider", "version": "1"}

    async def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return ModelResponse(output=json.loads(messages[-1]["content"]))
        return ModelResponse(tool_calls=(ToolCall("write", {"label": "genuine"}, "write-call"),))


class PublicSystem:
    def __init__(
        self, directory, client, namespace, queue, policy, runtime, probe, *, assembly=None
    ):
        self.directory, self.client, self.namespace = directory, client, namespace
        self.queue, self.policy, self.runtime, self.probe = queue, policy, runtime, probe
        self.scope = Scope("deployment-public-service", queue)
        self.assembly = assembly
        self.targets, self.workers, self.engines, self.finalizers = set(), [], [], []
        self.engine = self.facade()

    def facade(self, *, client=None, queue=None, release=None, scope=None, timeout=3):
        engine = TemporalEngine(
            client or self.client,
            task_queue=queue or self.queue,
            release=release or self.runtime.orchestration_release,
            scope=scope or self.scope,
            activity_timeout=timeout,
            drive_timeout=30,
        )
        self.engines.append(engine)
        return engine

    async def submit(self, spec, value, *, command_id="first", engine=None):
        engine = engine or self.engine
        self.targets.add(root_run_id(self.policy.deployment_id, asdict(engine.scope), command_id))
        return await engine.submit(spec, value, command_id=command_id, budget=64)

    @asynccontextmanager
    async def worker(self, *, client=None):
        worker = build_temporal_worker(
            client or self.client,
            task_queue=self.queue,
            runtime=self.runtime,
            release=self.runtime.orchestration_release,
            graceful_shutdown_timeout=timedelta(seconds=1),
            max_concurrent_activities=32,
        )
        self.workers.append(worker)
        async with worker:
            try:
                yield worker
            finally:
                self.unblock()
                from ralf_agent.temporal_deployment_release import check_owner

                assert await check_owner(self.runtime).wait(wait_timeout=15)

    def unblock(self):
        self.probe.release.set()
        for callback in self.finalizers:
            callback()

    async def count(self, expected):
        return await _eventually(
            self.engine.deployment_diagnostics,
            lambda value: value["counts"]["held_root_runs"] == expected,
        )

    async def status(self, run_id, states):
        return await _eventually(
            lambda: self.engine.status(run_id), lambda value: value.state in states
        )

    async def closure(self, run_id):
        return await self.client.get_workflow_handle(run_id).query(
            "view",
            {"scope": asdict(self.scope), "kind": "deployment_closure"},
            rpc_timeout=timedelta(seconds=10),
        )

    async def submission(self, spec, value, command_id="first"):
        from ralf_agent.temporal_bindings import normalize_request

        request = normalize_request(submission_request(spec, value, budget=64), None)
        return await self.client.get_workflow_handle(registry_id(self.policy.deployment_id)).query(
            "view",
            {
                "kind": "deployment_submission",
                "scope": asdict(self.scope),
                "command_id": command_id,
                "payload_digest": digest(request),
                "admission_policy": self.policy.identity,
                "namespace": self.namespace,
            },
        )

    async def evidence(self, run_id):
        view = await self.closure(run_id)
        assert view["ready"] and view["seal"] is not None
        certificate, deployment = view["seal"], view["deployment"]
        handle = self.client.get_workflow_handle(run_id, run_id=certificate["execution_epoch"])
        assert (await handle.describe()).run_id == certificate["original_execution_epoch"]
        assert certificate["request_digest"] == deployment["request_digest"]
        assert certificate["manifest_digest"] == deployment["manifest_digest"]
        history = await handle.fetch_history()
        await replay_temporal_history(history, namespace=self.namespace["name"])
        (self.directory / (run_id + ".json")).write_text(history.to_json())
        (self.directory / (run_id + "-closure.json")).write_text(json.dumps(view, sort_keys=True))
        count = 1
        for child in certificate["children"]:
            if child["execution_epoch"] is None:
                assert child["seal_digest"] is None
            else:
                child_view = await self.closure(child["run_id"])
                assert child["seal_digest"] == child_view["seal"]["proof_digest"]
                count += await self.evidence(child["run_id"])
        return count

    async def cleanup(self):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        self.unblock()
        pending, found, absent = list(self.targets), {}, []
        while pending:
            run_id = pending.pop()
            if run_id in found or run_id in absent:
                continue
            handle = self.client.get_workflow_handle(run_id)
            try:
                history = await handle.fetch_history()
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
                absent.append(run_id)
                continue
            found[run_id] = handle
            for event in history.events:
                if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                    pending.append(
                        event.start_child_workflow_execution_initiated_event_attributes.workflow_id
                    )
        for handle in reversed(list(found.values())):
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="owned public deployment test cleanup")
            assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
        registry = self.client.get_workflow_handle(registry_id(self.policy.deployment_id))
        history = await registry.fetch_history()
        await replay_temporal_history(history, namespace=self.namespace["name"])
        (self.directory / "registry-history.json").write_text(history.to_json())
        await registry.terminate(reason="owned public deployment Registry test cleanup")
        assert (await registry.describe()).status == WorkflowExecutionStatus.TERMINATED
        for engine in self.engines:
            await engine.aclose()
        if self.assembly is not None:
            await self.assembly.aclose(wait_timeout=15)
        from ralf_agent.temporal_deployment_release import close_owner

        await close_owner(self.runtime, wait_timeout=15)
        assert all(worker.is_shutdown and not worker.is_running for worker in self.workers)
        (self.directory / "cleanup.json").write_text(
            json.dumps(
                {
                    "closed_runs": sorted(found),
                    "never_started_ids": absent,
                    "registry_terminated": True,
                    "workers_shutdown": len(self.workers),
                }
            )
        )


@asynccontextmanager
async def public_system(directory, *, hold=False, approval=False, options=None, profile=None):
    clients, namespace = await _clients()
    queue = "deployment-public-" + uuid.uuid4().hex
    policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
    probe = BusinessProbe(hold=hold)
    assembly = None
    if profile is None:
        settings = {"providers": {"default": probe}, "tools": probe.tools(approval=approval)}
        if options is not None:
            settings.update(options)
        runtime = TemporalRuntime(**settings, admission_policy=policy)
    else:
        assembly = await profile(queue, policy, probe)
        runtime = assembly._runtime
    system = PublicSystem(
        directory, clients[0], namespace, queue, policy, runtime, probe, assembly=assembly
    )
    try:
        yield system
    finally:
        await system.cleanup()


@pytest.mark.parametrize("case", CASES)
def test_actual_public_definition_tree_retires_one_root_and_preserves_receipt(tmp_path, case):
    async def scenario():
        async with public_system(tmp_path) as system, system.worker():
            spec, reads, descendants, value = _case(case)
            original = await system.submit(spec, value)
            done = await system.status(original.run_id, {"succeeded", "failed"})
            assert done.state == "succeeded", done
            await system.count(0)
            assert len(system.probe.reads) == reads
            assert await system.evidence(original.run_id) == descendants + 1
            assert await system.submit(spec, value) == original
            assert len(system.probe.reads) == reads
            next_run = await system.submit(_agent("turnover"), {"next": case}, command_id="next")
            assert (
                await system.status(next_run.run_id, {"succeeded", "failed"})
            ).state == "succeeded"
            await system.count(0)
            assert len(system.probe.reads) == reads + 1
            recorded = await system.submission(spec, value)
            assert recorded["run_receipt"] == asdict(original.receipt)
            assert (
                recorded["execution_epoch"]
                == (await system.closure(original.run_id))["seal"]["execution_epoch"]
            )

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.parametrize(
    "syntax,factory",
    [
        ("sdk", "bounded"),
        ("json", "bounded"),
        ("toml", "bounded"),
        ("sdk", "sync"),
        ("sdk", "async"),
        ("sdk", "host"),
    ],
)
def test_actual_public_profile_policy_factories_and_catalog_forms(tmp_path, syntax, factory):
    async def scenario():
        built = []

        async def assemble(queue, policy, probe):
            registry = ComponentRegistry()
            registry.register("provider", "policy-service", lambda c, ctx: probe)
            registry.register("tools", "policy-service", lambda c, ctx: probe.tools())
            if factory in {"sync", "async"}:

                def select(config, context):
                    built.append((config, context.scope))
                    return policy

                async def select_async(config, context):
                    return select(config, context)

                if factory == "async":
                    registry.register_async("admission_policy", "custom", select_async)
                else:
                    registry.register("admission_policy", "custom", select)
            components = {"tools": {"adapter": "policy-service"}}
            if factory != "host":
                components["admission_policy"] = {
                    "adapter": "custom" if factory in {"sync", "async"} else "bounded",
                    "config": {
                        key: value
                        for key, value in policy.identity.items()
                        if key not in {"kind", "max_active_root_runs_per_scope"}
                    },
                }
            declared = TemporalProfile(
                queue, "1", {"default": {"adapter": "policy-service"}}, components
            )
            selected = through_catalog(tmp_path, declared, syntax)
            return await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                selected,
                scope=Scope("deployment-public-service", queue),
                **({"admission_policy": policy} if factory == "host" else {}),
            )

        async with public_system(tmp_path, profile=assemble) as system:
            assembly = system.assembly
            await assembly.start_worker(system.client, task_queue=system.queue)
            engine = assembly.create_engine(
                system.client, task_queue=system.queue, activity_timeout=3
            )
            try:
                original = await system.submit(_agent("profile"), {"form": syntax}, engine=engine)
                assert (
                    await system.status(original.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await system.count(0)
                assert (
                    system.runtime.orchestration_release["deployment_admission_protocol"]["version"]
                    == 2
                )
                assert len(system.probe.reads) == 1
                assert await system.evidence(original.run_id) == 1
                if factory in {"sync", "async"}:
                    assert len(built) == 1 and built[0][1] == system.scope
                assert (
                    assembly._runtime.orchestration_release["runtime_profile"]
                    == assembly.profile.identity
                )
            finally:
                await assembly.aclose(wait_timeout=15)

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.parametrize("boundary", ["reserve", "start"])
def test_actual_lost_first_acceptance_reply_recovers_original_queue_release_and_epoch(
    tmp_path, boundary
):
    async def scenario():
        from temporalio.service import RPCError

        async with public_system(tmp_path, hold=True) as system, system.worker():
            fault = SDKFaultClient(system.client, lose=boundary)
            first_engine = system.facade(client=fault, timeout=5)
            spec, value = _agent("first-release"), {"boundary": boundary}
            first = None
            try:
                first = await system.submit(spec, value, engine=first_engine)
            except RPCError:
                pass  # The injected loss is an actual accepted SDK operation.
            assert fault.dropped and fault.lose is None
            await system.count(1)
            recorded = await system.submission(spec, value)
            envelope = copy.deepcopy(recorded["submission"])
            assert envelope["task_queue"] == system.queue and envelope["activity_timeout"] == 5
            # The original SDK envelope is JSON. Registered planner AgentSpecs
            # contain Python tuples before their unchanged JSON serialization.
            assert envelope["manifest"] == json.loads(canonical(first_engine.release))
            other_probe = BusinessProbe()
            other_probe.identity = {**other_probe.identity, "version": "changed-alias"}
            changed = TemporalRuntime(
                providers={"default": other_probe},
                tools=other_probe.tools(),
                admission_policy=system.policy,
            )
            retry = system.facade(
                queue=system.queue + "-unserved", release=changed.orchestration_release, timeout=1
            )
            recovered = await system.submit(spec, value, engine=retry)
            if first is not None:
                assert recovered == first
            assert (await system.submission(spec, value))["submission"] == envelope
            await asyncio.wait_for(system.probe.started.wait(), 15)
            assert len(system.probe.models) == 1 and other_probe.models == []
            with pytest.raises(CapacityExceeded):
                await system.submit(spec, {"fresh": True}, command_id="full")
            system.probe.release.set()
            assert (
                await system.status(recovered.run_id, {"succeeded", "failed"})
            ).state == "succeeded"
            await system.count(0)
            assert len(system.probe.reads) == 1
            assert await system.submit(spec, value, engine=retry) == recovered
            await system.evidence(recovered.run_id)
            from ralf_agent.temporal_deployment_release import close_owner

            await close_owner(changed, wait_timeout=5)

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_lost_release_reply_and_retired_duplicate_need_no_business_poller(tmp_path):
    async def scenario():
        async with public_system(tmp_path) as system:
            fault = SDKFaultClient(system.client, lose="release")
            spec, value = _agent("lost-release"), {"release": True}
            async with system.worker(client=fault):
                original = await system.submit(spec, value)
                assert (
                    await system.status(original.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await _eventually(lambda: asyncio.sleep(0, result=fault.dropped), bool)
                await system.count(0)
                certificate = (await system.closure(original.run_id))["seal"]
                assert certificate is not None
                before = len(system.probe.models)
            registry_worker = _worker(system.client, system.queue)
            async with registry_worker:
                retry = system.facade(queue=system.queue + "-no-poller", timeout=1)
                assert (
                    await asyncio.wait_for(system.submit(spec, value, engine=retry), 10) == original
                )
                assert len(system.probe.models) == before
                assert (await system.submission(spec, value))["run_receipt"] == asdict(
                    original.receipt
                )
                assert (await system.engine.deployment_diagnostics())["counts"][
                    "held_root_runs"
                ] == 0
            assert registry_worker.is_shutdown
            async with system.worker():
                assert (await system.closure(original.run_id))["seal"] == certificate
                await system.evidence(original.run_id)
                next_run = await system.submit(_agent("next"), {}, command_id="next")
                assert (
                    await system.status(next_run.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await system.count(0)

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_public_approval_restart_preserves_claim_and_original_controls(tmp_path):
    async def scenario():
        async with public_system(tmp_path, approval=True) as system:
            spec, value = _agent("approval"), {"approval": True}
            async with system.worker():
                original = await system.submit(spec, value)
                pending = await system.status(original.run_id, {"waiting_approval"})
                assert system.probe.reads == []
                await system.count(1)
                with pytest.raises(CapacityExceeded):
                    await system.submit(spec, value, command_id="full")
            async with system.worker():
                assert await system.submit(spec, value) == original
                action = pending.pending[0]
                receipt = await system.engine.approve(
                    original.run_id, action["action_id"], action["digest"], command_id="approve"
                )
                assert (
                    await system.status(original.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await system.count(0)
                assert (
                    await system.engine.approve(
                        original.run_id, action["action_id"], action["digest"], command_id="approve"
                    )
                    == receipt
                )
                assert len(system.probe.reads) == 1
                await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_public_drive_recovers_sealed_root_after_registry_release_unavailable(tmp_path):
    async def scenario():
        async with public_system(tmp_path) as system:
            fault = SDKFaultClient(system.client, block_release=True)
            system.finalizers.append(lambda: setattr(fault, "block_release", False))
            async with system.worker(client=fault):
                spec, value = _agent("retirement-recovery"), {"recover": True}
                original = await system.submit(spec, value)
                assert (
                    await system.status(original.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await asyncio.wait_for(fault.release_attempted.wait(), 15)
                # First sealing wakes the original loop once. Keep transport
                # unavailable until that already-sealed automatic attempt also
                # records failure, so drive must recover a sleeping History.
                deferred = await _eventually(
                    lambda: system.engine.events(original.run_id),
                    lambda events: (
                        sum(event.kind == "deployment_retirement_deferred" for event in events) >= 2
                    ),
                )
                closure = await system.closure(original.run_id)
                certificate = copy.deepcopy(closure["seal"])
                assert closure["ready"] and certificate is not None
                await system.count(1)
                before = (len(system.probe.models), copy.deepcopy(system.probe.reads))
                assert before[0] == 2 and len(before[1]) == 1
                recorded = copy.deepcopy(await system.submission(spec, value))
                assert recorded["run_receipt"] == asdict(original.receipt)
                history = await system.client.get_workflow_handle(
                    original.run_id, run_id=certificate["execution_epoch"]
                ).fetch_history()
                (tmp_path / "sealed-held-history.json").write_text(history.to_json())
                (tmp_path / "sealed-held-proof.json").write_text(
                    json.dumps(
                        {
                            "closure": closure,
                            "events": [asdict(event) for event in deferred],
                            "models": before[0],
                            "reads": before[1],
                        },
                        sort_keys=True,
                    )
                )

                fault.block_release = False
                assert (
                    await system.engine.drive(original.run_id, wait_seconds=0)
                ).state == "succeeded"
                await system.count(0)
                assert (await system.closure(original.run_id))["seal"] == certificate
                assert (len(system.probe.models), system.probe.reads) == before
                assert await system.submit(spec, value) == original
                assert (await system.submission(spec, value))["submission"] == recorded[
                    "submission"
                ]
                assert (await system.submission(spec, value))["run_receipt"] == recorded[
                    "run_receipt"
                ]
                await system.evidence(original.run_id)

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.parametrize("kind", ["agent", "nested-parent-sequence"])
def test_actual_public_cancel_keeps_root_until_async_descendant_handler_ends(tmp_path, kind):
    async def scenario():
        async with public_system(tmp_path, hold=True) as system, system.worker():
            spec, _, _, value = _case(kind)
            engine = (
                system.facade(timeout=10) if kind == "nested-parent-sequence" else system.engine
            )
            original = await system.submit(spec, value, engine=engine)
            await asyncio.wait_for(system.probe.started.wait(), 20)
            receipt = await system.engine.cancel(original.run_id, command_id="cancel")
            assert receipt.outcome["remote_stop_confirmed"] is False
            assert (await system.status(original.run_id, {"cancelled"})).state == "cancelled"
            await system.count(1)
            held = await system.closure(original.run_id)
            assert held["seal"] is None and not held["ready"]
            if kind == "nested-parent-sequence":
                from temporalio.client import WorkflowUpdateFailedError

                # Parent acceptance records propagation intent, with no remote
                # stop confirmation. Establish cancellation in the original
                # descendant Histories before unblocking its actual Provider.
                parent_id = original.run_id
                for _ in range(2):
                    view = await _eventually(
                        lambda parent_id=parent_id: system.closure(parent_id),
                        lambda value: (
                            len(value["deployment"]["children"]) == 1
                            and value["deployment"]["children"][0].get("deployment_execution_epoch")
                        ),
                    )
                    child = view["deployment"]["children"][0]
                    pinned = system.client.get_workflow_handle(
                        child["run_id"], run_id=child["deployment_execution_epoch"]
                    )
                    assert (await pinned.describe()).run_id == child["deployment_execution_epoch"]
                    await system.status(child["run_id"], {"cancelled"})
                    parent_id = child["run_id"]

                # Caller certificate uses real original SDK identity but invents
                # closure and omits a genuine live subtree. Only SDK proof reads
                # of the original Histories may authorize Registry retirement.
                deployment = held["deployment"]
                certificate = {
                    "version": 1,
                    **{
                        name: deployment[name]
                        for name in (
                            "scope",
                            "run_id",
                            "command_id",
                            "namespace",
                            "execution_epoch",
                            "original_execution_epoch",
                            "request_digest",
                            "manifest_digest",
                        )
                    },
                    "admission_digest": digest(deployment["admission"]),
                    "receipt_digest": digest(deployment["admission_receipt"]),
                    "terminal_state": "cancelled",
                    "closure_digest": "a" * 64,
                    "children": [],
                }
                certificate["proof_digest"] = digest(certificate)
                root = deployment["admission_receipt"]["root"]
                with pytest.raises(WorkflowUpdateFailedError):
                    await system.client.get_workflow_handle(
                        registry_id(system.policy.deployment_id)
                    ).execute_update(
                        "release_deployment_root",
                        {
                            **{
                                name: root[name]
                                for name in (
                                    "scope",
                                    "command_id",
                                    "run_id",
                                    "request_digest",
                                    "manifest_digest",
                                    "proof_digest",
                                    "execution_epoch",
                                )
                            },
                            "namespace": system.namespace,
                            "admission_policy": system.policy.identity,
                            "certificate": certificate,
                        },
                        rpc_timeout=timedelta(seconds=15),
                    )
                await system.count(1)
            with pytest.raises(CapacityExceeded):
                await system.submit(_agent("contender"), {}, command_id="blocked")
            assert system.probe.reads == []
            system.probe.release.set()
            await system.count(0)
            assert await system.engine.cancel(original.run_id, command_id="cancel") == receipt
            assert system.probe.reads == []
            await system.evidence(original.run_id)
            next_run = await system.submit(_agent("next"), {}, command_id="next")
            assert (
                await system.status(next_run.run_id, {"succeeded", "failed"})
            ).state == "succeeded"
            await system.count(0)

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.parametrize("obligation", ["physical-thread", "effect-ack", "call-end-ack"])
def test_actual_zero_cost_commit_manual_evidence_and_ack_do_not_replace_real_end(
    tmp_path, obligation
):
    async def scenario():
        write = CommittedThreadWrite(tmp_path / "business.sqlite")
        journal = SQLiteEffectEvidence(tmp_path / "evidence.sqlite")
        journal.block_ack = obligation == "effect-ack"
        options = {
            "providers": {"default": WriteProvider()},
            "tools": write.tools(),
            "journal": journal,
            "tool_execution": ToolExecutionOwner(version="public-service-thread-1"),
        }
        async with public_system(tmp_path, options=options) as system:
            fault = SDKFaultClient(system.client)
            system.finalizers.extend(
                [
                    write.release.set,
                    lambda: setattr(journal, "block_ack", False),
                    lambda: setattr(fault, "block_end", False),
                ]
            )
            async with system.worker(client=fault):
                engine = system.facade(timeout=1)
                original = await system.submit(
                    AgentSpec("writer", "Write once", ("write",)), {}, engine=engine
                )
                assert await asyncio.to_thread(write.started.wait, 20)
                genuine, calls = write.committed()[0]
                assert calls == 1 and not write.ended.is_set()
                await system.engine.cancel(original.run_id, command_id="cancel")
                unknown = await _eventually(
                    lambda: system.engine.diagnostics(original.run_id),
                    lambda value: any(
                        action["kind"] == "tool" and action["status"] == "outcome_unknown"
                        for action in value.snapshot.actions
                    ),
                )
                action = next(
                    action for action in unknown.snapshot.actions if action["kind"] == "tool"
                )
                assert unknown.budget["reserved"] == unknown.budget["unknown"] == 0
                assert any(
                    reservation["amount"] == 0 and reservation["status"] == "unknown"
                    for reservation in unknown.budget["reservations"]
                )
                await system.engine.reconcile(
                    original.run_id, action["id"], genuine, command_id="manual-evidence"
                )
                assert not write.ended.is_set()
                await system.count(1)
                with pytest.raises(CapacityExceeded):
                    await system.submit(
                        AgentSpec("next", "Write", ("write",)), {}, command_id="blocked"
                    )
                if obligation == "call-end-ack":
                    fault.block_end = True
                write.release.set()
                assert await asyncio.to_thread(write.ended.wait, 10)
                if obligation == "effect-ack":
                    await asyncio.wait_for(journal.ack_attempted.wait(), 15)
                    await _eventually(
                        lambda: system.engine.events(original.run_id),
                        lambda events: any(
                            event.kind == "effect_journal_ack_deferred" for event in events
                        ),
                    )
                    deferred = await system.engine.diagnostics(original.run_id)
                    assert deferred.workflow["deferred_evidence_acks"] == 1
                    await system.count(1)
                    assert (await system.closure(original.run_id))["seal"] is None
                    journal.block_ack = False
                    await system.engine.drive(original.run_id, wait_seconds=0)
                if obligation == "call-end-ack":
                    await asyncio.wait_for(fault.end_attempted.wait(), 15)
                    await system.count(1)
                    assert (await system.closure(original.run_id))["seal"] is None
                    fault.block_end = False
                    from ralf_agent.temporal_deployment_release import check_owner

                    assert await check_owner(system.runtime).wait(wait_timeout=15)
                await system.count(0)
                assert write.committed() == [(genuine, 1)]
                await system.evidence(original.run_id)
                next_run = await system.submit(
                    AgentSpec("next", "Write once", ("write",)), {}, command_id="next"
                )
                assert (
                    await system.status(next_run.run_id, {"succeeded", "failed"})
                ).state == "succeeded"
                await system.count(0)
                assert len(write.committed()) == 2
                assert all(calls == 1 for _, calls in write.committed())
                (tmp_path / "genuine-effects.json").write_text(
                    json.dumps(
                        {
                            "committed": genuine,
                            "handler_ended": write.ended.is_set(),
                            "physical_calls": 1,
                        }
                    )
                )
        await journal.aclose()

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_clients_share_capacity_without_foreign_scope_locators(tmp_path):
    async def scenario():
        async with public_system(tmp_path, hold=True) as system, system.worker():
            original = await system.submit(_agent("owner"), {})
            await asyncio.wait_for(system.probe.started.wait(), 15)
            clients, _ = await _clients(3)
            foreign_scope = Scope(system.scope.workspace, system.scope.principal + "-foreign")
            foreign = [system.facade(client=client, scope=foreign_scope) for client in clients]
            attempts = await asyncio.gather(
                *(
                    system.submit(
                        _agent("contender"), {}, command_id="contender-" + str(i), engine=foreign[i]
                    )
                    for i in range(3)
                ),
                return_exceptions=True,
            )
            assert all(isinstance(value, CapacityExceeded) for value in attempts)
            view = await foreign[0].deployment_diagnostics()
            assert (
                view["counts"]["held_root_runs"] == 1
                and view["counts"]["held_root_runs_for_scope"] == 0
            )
            assert view["held_roots"] == [] and original.run_id not in canonical(view)
            system.probe.release.set()
            await system.count(0)
            system.probe.release.clear()
            candidates = await asyncio.gather(
                *(
                    system.submit(
                        _agent("contender"), {}, command_id="turnover-" + str(i), engine=foreign[i]
                    )
                    for i in range(3)
                ),
                return_exceptions=True,
            )
            winners = [value for value in candidates if not isinstance(value, Exception)]
            assert len(winners) == 1
            assert sum(isinstance(value, CapacityExceeded) for value in candidates) == 2
            await system.count(1)
            system.probe.release.set()
            done = await _eventually(
                lambda: foreign[0].status(winners[0].run_id),
                lambda value: value.state in {"succeeded", "failed"},
            )
            assert done.state == "succeeded"
            await system.count(0)

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_public_policy_refuses_existing_v1_registry_without_adopting_it(tmp_path):
    async def scenario():
        clients, namespace = await _clients()
        queue = "deployment-v1-refusal-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
        worker = _worker(clients[0], queue)
        async with worker:
            registry = await _start(clients[0], queue, policy.identity, namespace)
            probe = BusinessProbe()
            runtime = TemporalRuntime(
                providers={"default": probe}, tools=probe.tools(), admission_policy=policy
            )
            engine = TemporalEngine(
                clients[0],
                task_queue=queue,
                release=runtime.orchestration_release,
                scope=Scope("v1-public-refusal", queue),
            )
            try:
                from ralf_agent.errors import DefinitionMismatch, ValidationError

                with pytest.raises((DefinitionMismatch, ValidationError)):
                    await engine.submit(_agent("refused"), {}, command_id="first")
                assert probe.models == probe.reads == []
                configuration = await registry.query(
                    "view",
                    {
                        "kind": "deployment_configuration",
                        "scope": asdict(engine.scope),
                        "admission_policy": policy.identity,
                        "namespace": namespace,
                    },
                )
                assert configuration["version"] == 1
                assert (await registry.describe()).run_id == registry.first_execution_run_id
                await replay_temporal_history(
                    await registry.fetch_history(), namespace=namespace["name"]
                )
            finally:
                await engine.aclose()
                await registry.terminate(reason="owned v1 public refusal test cleanup")
                from ralf_agent.temporal_deployment_release import close_owner

                await close_owner(runtime, wait_timeout=5)
        assert worker.is_shutdown

    asyncio.run(asyncio.wait_for(scenario(), 90))
