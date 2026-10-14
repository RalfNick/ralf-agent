"""Original SDK dispatch evidence; held claims do not establish safe release.

Uses actual Temporal Service with deterministic local business components. No
public Engine/Profile exemption, model network, PostgreSQL, or time skipping.
"""

import asyncio
import copy
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from ralf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    ModelResponse,
    TeamSpec,
    ToolCall,
    ValueRef,
    WorkflowSpec,
)
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal import build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME
from ralf_agent.temporal_state import WORKFLOW_NAME
from ralf_agent.tools import ToolRegistry, ToolSpec
from ralf_agent.types import canonical, digest, submission_request

from .test_temporal_deployment_admission_service import (
    _clients,
    _start,
    _update,
    _view,
    _worker,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class BusinessProbe:
    """Actual trusted Python read and deterministic Provider, with local counters."""

    identity = {"kind": "deployment-dispatch-service-provider", "version": "1"}

    def __init__(self, *, hold=False):
        self.models, self.reads = [], []
        self.started, self.release = asyncio.Event(), asyncio.Event()
        if not hold:
            self.release.set()

    async def complete(self, messages, tools):
        self.models.append(copy.deepcopy(messages))
        self.started.set()
        await self.release.wait()
        if messages[-1]["role"] == "tool":
            return ModelResponse(output=json.loads(messages[-1]["content"]))
        value = json.loads(messages[1]["content"])
        return ModelResponse(tool_calls=(ToolCall("probe", {"value": value}, "probe-call"),))

    async def read(self, arguments, context):
        self.reads.append({"run_id": context.run_id, "execution_epoch": context.execution_epoch})
        return {"observed": arguments["value"]}

    def tools(self, *, approval=False):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "probe",
                "Return supplied JSON through a trusted Python read",
                {
                    "type": "object",
                    "properties": {"value": {}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                effect="read_only",
                requires_approval=approval,
            ),
            self.read,
        )
        return registry


def _agent(name):
    return AgentSpec(name, "Call probe once, then return its result", tools=("probe",))


def _case(name):
    a, b = _agent("first"), _agent("second")
    sequence = WorkflowSpec("sequence", (a, b))
    if name == "agent":
        return a, 1, 0, {"case": name}
    if name == "sequence":
        return sequence, 2, 0, {"case": name}
    if name in {"graph-sequential", "graph-parallel"}:
        parallel = name == "graph-parallel"
        return (
            GraphWorkflowSpec(
                name,
                [
                    GraphNode("first", agent=a),
                    GraphNode(
                        "second",
                        agent=b,
                        depends_on=() if parallel else ("first",),
                        input=ValueRef() if parallel else ValueRef("first"),
                    ),
                ],
                max_concurrency=2 if parallel else 1,
                output=ValueRef("second"),
            ),
            2,
            2,
            {"case": name},
        )
    if name.startswith("team-"):
        strategy = name.removeprefix("team-")
        config = (
            {"routes": {"first": "a"}}
            if strategy == "router"
            else {"supervisor": "b"}
            if strategy == "supervisor"
            else {}
        )
        count = 1 if strategy == "router" else 2
        return (
            TeamSpec(name, {"a": a, "b": b}, strategy=strategy, strategy_config=config),
            count,
            count,
            {"case": name, "route": "first"},
        )
    if name == "dynamic-dag":
        return (
            DynamicWorkflowSpec(name, {"a": a, "b": b}, plan_mode="dag"),
            2,
            2,
            {"case": name},
        )
    assert name == "nested-parent-sequence"
    inner = TeamSpec("inner", {"sequence": sequence}, child_budget=8)
    return TeamSpec("outer", {"inner": inner}, child_budget=16), 2, 2, {"case": name}


async def _query(handle, scope, kind="status"):
    return await handle.query(
        "view", {"scope": scope, "kind": kind}, rpc_timeout=timedelta(seconds=5)
    )


async def _eventually(operation, predicate, *, seconds=30):
    async with asyncio.timeout(seconds):
        while not predicate(value := await operation()):  # noqa: ASYNC110
            await asyncio.sleep(0.05)
        return value


async def _command(handle, scope, kind, command_id, **values):
    return await handle.execute_update(
        "command",
        {"command_id": command_id, "payload": {"scope": scope, "kind": kind, **values}},
        rpc_timeout=timedelta(seconds=15),
    )


class DispatchSystem:
    def __init__(self, client, namespace, queue, policy, registry, runtime, probe, directory):
        self.client, self.namespace = client, namespace
        self.queue, self.policy, self.registry = queue, policy, registry
        self.runtime, self.probe, self.directory = runtime, probe, directory
        self.scope = {"workspace": "deployment-dispatch-service", "principal": queue}
        self.handles, self.workers = [], []

    def worker(self):
        worker = build_temporal_worker(
            self.client,
            task_queue=self.queue,
            runtime=self.runtime,
            release=self.runtime.orchestration_release,
            graceful_shutdown_timeout=timedelta(seconds=1),
            max_concurrent_activities=16,
        )
        self.workers.append(worker)
        return worker

    async def reserve(self, spec, value, *, command_id="first"):
        from ralf_agent.temporal_bindings import normalize_request

        # SDK JSON encodes AgentSpec's Python tuples as arrays. Freeze that same
        # business request representation before reservation and acceptance.
        manifest = self.runtime.orchestration_release
        request = json.loads(
            canonical(normalize_request(submission_request(spec, value, budget=64), manifest))
        )
        receipt = await _update(
            self.registry,
            {
                "scope": self.scope,
                "command_id": command_id,
                "kind": "submit",
                "target": root_run_id(self.policy.deployment_id, self.scope, command_id),
                "payload_digest": digest(request),
                "admission_policy": self.policy.identity,
                "namespace": self.namespace,
                "root_admission": {"version": 1, "manifest_digest": digest(manifest)},
            },
        )
        accepted = {
            "scope": self.scope,
            "command_id": command_id,
            "request": request,
            "manifest": manifest,
            "activity_timeout": 5,
            "deployment_admission": {
                "version": 1,
                "root": receipt["root_admission"],
                "lineage": [],
            },
        }
        return receipt, accepted

    async def start(self, accepted, *, run_id=None):
        root = accepted.get("deployment_admission", {}).get("root", {})
        handle = await self.client.start_workflow(
            PARENT_WORKFLOW_NAME
            if accepted["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}
            else WORKFLOW_NAME,
            accepted,
            id=run_id or root["run_id"],
            task_queue=self.queue,
            retry_policy=None,
        )
        self.handles.append(handle)
        return handle

    async def registry_view(self):
        return await _view(self.registry, self.policy.identity, self.namespace, self.scope)

    async def evidence_tree(self, handle):
        proof = await _query(handle, self.scope, "deployment_admission")
        assert proof["execution_epoch"] == proof["original_execution_epoch"]
        assert proof["execution_epoch"] == (await handle.describe()).run_id
        assert proof["admission_receipt"] is not None
        assert proof["admission_receipt"]["root"]["state"] == "held-bound"
        history = await handle.fetch_history()
        gate_ids = {
            event.event_id
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
            and event.activity_task_scheduled_event_attributes.activity_type.name
            == "ralf.temporal.deployment-admission.v1"
        }
        completed_gates = [
            event.event_id
            for event in history.events
            if event.HasField("activity_task_completed_event_attributes")
            and event.activity_task_completed_event_attributes.scheduled_event_id in gate_ids
        ]
        business = [
            event.event_id
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
            and event.event_id not in gate_ids
        ]
        assert completed_gates and business
        assert min(completed_gates) < min(business)
        await replay_temporal_history(history, namespace=self.namespace["name"])
        (self.directory / (handle.id + ".json")).write_text(history.to_json())
        result = [proof]
        for child in proof["children"]:
            child_handle = self.client.get_workflow_handle(
                child["run_id"], run_id=child["deployment_execution_epoch"]
            )
            child_proofs = await self.evidence_tree(child_handle)
            assert child_proofs[0]["admission"]["root"] == proof["admission"]["root"]
            assert (
                len(child_proofs[0]["admission"]["lineage"])
                == len(proof["admission"]["lineage"]) + 1
            )
            result.extend(child_proofs)
        return result

    async def cleanup(self):
        from temporalio.client import WorkflowExecutionStatus

        # Original SDK child-start History also finds children if a proof query failed.
        pending = list(self.handles)
        discovered = {}
        while pending:
            handle = pending.pop()
            if handle.id in discovered:
                continue
            discovered[handle.id] = handle
            history = await handle.fetch_history()
            for event in history.events:
                if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                    child_id = (
                        event.start_child_workflow_execution_initiated_event_attributes.workflow_id
                    )
                    pending.append(self.client.get_workflow_handle(child_id))
        for handle in reversed(list(discovered.values())):
            description = await handle.describe()
            if description.status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="owned deployment dispatch test cleanup")
            assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
        await self.registry.terminate(reason="owned deployment Registry test cleanup")
        assert (await self.registry.describe()).status == WorkflowExecutionStatus.TERMINATED
        (self.directory / "cleanup.json").write_text(
            json.dumps({"closed_owned_runs": sorted(discovered), "registry_terminated": True})
        )


@asynccontextmanager
async def _system(directory, *, approval=False, hold=False, runtime_options=None):
    clients, namespace = await _clients()
    client = clients[0]
    queue = "deployment-dispatch-" + uuid.uuid4().hex
    policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
    probe = BusinessProbe(hold=hold)
    options = {"providers": {"default": probe}, "tools": probe.tools(approval=approval)}
    if runtime_options is not None:
        options.update(
            runtime_options({"workspace": "deployment-dispatch-service", "principal": queue})
        )
    runtime = TemporalRuntime(**options, _deployment_admission_policy=policy)
    registry_worker = _worker(client, queue + "-registry")
    async with registry_worker:
        registry = await _start(client, queue + "-registry", policy.identity, namespace)
        system = DispatchSystem(
            client, namespace, queue, policy, registry, runtime, probe, directory
        )
        try:
            yield system
        finally:
            probe.release.set()
            await system.cleanup()
    assert registry_worker.is_shutdown and not registry_worker.is_running
    assert all(worker.is_shutdown and not worker.is_running for worker in system.workers)


@pytest.mark.parametrize(
    "case",
    [
        "agent",
        "sequence",
        "graph-sequential",
        "graph-parallel",
        "team-sequential",
        "team-router",
        "team-supervisor",
        "dynamic-dag",
        "nested-parent-sequence",
    ],
)
def test_actual_sdk_dispatch_inherits_one_root_for_selected_definition(tmp_path, case):
    """Missing gate or child ancestry binding permits business before original admission."""

    async def scenario():
        async with _system(tmp_path) as system:
            spec, reads, descendants, value = _case(case)
            receipt, accepted = await system.reserve(spec, value)
            original_request = copy.deepcopy(accepted["request"])
            handle = await system.start(accepted)
            await asyncio.sleep(0.15)
            assert system.probe.models == system.probe.reads == []
            assert (await system.registry_view())["held_roots"] == [receipt["root_admission"]]
            async with system.worker():
                done = await _eventually(
                    lambda: _query(handle, system.scope),
                    lambda snapshot: snapshot["state"] in {"succeeded", "failed", "cancelled"},
                )
                assert done["state"] == "succeeded", done
                assert done["result"] is not None
                assert len(system.probe.reads) == reads
                assert len(system.probe.models) == reads * 2
                proofs = await system.evidence_tree(handle)
                assert len(proofs) == descendants + 1
                assert proofs[0]["request"] == original_request == accepted["request"]
                assert proofs[0]["request_digest"] == digest(original_request)
                bound = (await system.registry_view())["held_roots"][0]
                assert bound["execution_epoch"] == handle.first_execution_run_id
                assert bound["state"] == "held-bound"
                assert (await system.registry_view())["counts"] == {
                    "held_root_runs": 1,
                    "held_root_runs_for_scope": 1,
                    "command_records": 1,
                }
                assert all(proof["admission_receipt"]["root"] == bound for proof in proofs)
                (tmp_path / "observations.json").write_text(
                    json.dumps(
                        {
                            "definition_case": case,
                            "original_root_sdk_epoch": handle.first_execution_run_id,
                            "proofs": proofs,
                            "held_registry": await system.registry_view(),
                            "business_reads": system.probe.reads,
                            "public_admission_tested": False,
                            "safe_release_tested": False,
                        },
                        sort_keys=True,
                    )
                )
                assert {
                    (read["run_id"], read["execution_epoch"]) for read in system.probe.reads
                } <= {(proof["run_id"], proof["execution_epoch"]) for proof in proofs}
                await replay_temporal_history(
                    await system.registry.fetch_history(), namespace=system.namespace["name"]
                )

    asyncio.run(asyncio.wait_for(scenario(), 90))


def test_actual_selected_per_agent_rag_and_managed_data_preserve_original_stage_digests(tmp_path):
    """Mechanical SDK headers must preserve context dispatch/adoption and scoped RAG."""

    async def scenario():
        import sqlite3

        from ralf_agent import (
            AgentBindingDescriptor,
            BindingCatalog,
            BindingSelection,
            BoundDefinition,
            Document,
            KnowledgeBindingResource,
            KnowledgeContext,
            LexicalRetriever,
            Scope,
            SQLiteArtifactStore,
            SQLiteStore,
        )

        from .temporal_knowledge_worker import AuditedKnowledge
        from .test_composite_data_context import Provider, agent, registry
        from .test_managed_data_context import context

        resources, configured, reads = [], {}, []

        def configure(scope):
            owner = Scope(**scope)
            store = SQLiteStore(tmp_path / "knowledge.sqlite")
            resources.append(store)
            store.conn.execute("CREATE TABLE audit (kind TEXT, value TEXT)")
            knowledge = AuditedKnowledge(store)
            for namespace in ("A", "B", "private"):
                knowledge.put(
                    owner,
                    namespace,
                    # The second sequence step receives the first's "finished"
                    # result, so both actual lexical queries must match this doc.
                    Document("guide", "pool " + namespace + " evidence for finished"),
                    expected_version=0,
                )
            artifacts = SQLiteArtifactStore(tmp_path / "artifacts.sqlite")
            resources.append(artifacts)
            catalog = BindingCatalog(scope=owner)
            catalog.register(
                "knowledge",
                "guides",
                "1",
                KnowledgeBindingResource(
                    KnowledgeContext(LexicalRetriever(knowledge)),
                    namespaces=("A", "B"),
                    default_namespace="A",
                ),
            )
            selections = {}
            for index, namespace in enumerate(("A", "B")):
                name = "context-" + namespace
                catalog.register(
                    "context",
                    name,
                    "1",
                    context(artifacts, scope=owner, mode="model", summary_max_chars=256),
                )
                selections[f"sequence/steps/{index}"] = AgentBindingDescriptor(
                    context=BindingSelection.ref(name, "1"),
                    knowledge=BindingSelection.ref(
                        "guides", "1", selector={"namespace": namespace}
                    ),
                )
            configured["definition"] = BoundDefinition(
                WorkflowSpec("selected-contexts", (agent("first"), agent("second"))), selections
            )
            configured["provider"] = Provider()
            return {
                "providers": {"default": configured["provider"]},
                "tools": registry(reads),
                "binding_catalog": catalog,
            }

        try:
            async with _system(tmp_path, runtime_options=configure) as system:
                _, accepted = await system.reserve(configured["definition"], "pool")
                original_request = copy.deepcopy(accepted["request"])
                handle = await system.start(accepted)
                await asyncio.sleep(0.15)
                assert configured["provider"].requests == reads == []
                with sqlite3.connect(tmp_path / "knowledge.sqlite") as db:
                    assert list(db.execute("SELECT kind, value FROM audit")) == []
                async with system.worker():
                    done = await _eventually(
                        lambda: _query(handle, system.scope),
                        lambda snapshot: snapshot["state"] in {"succeeded", "failed"},
                        seconds=60,
                    )
                    assert done["state"] == "succeeded", done
                    assert done["result"] == "finished"
                    assert len(reads) == 8
                    assert configured["provider"].summaries >= 2
                    seen = canonical(configured["provider"].requests)
                    assert "pool A evidence" in seen and "pool B evidence" in seen
                    assert "pool private evidence" not in seen
                    with sqlite3.connect(tmp_path / "knowledge.sqlite") as db:
                        rows = list(db.execute("SELECT kind, value FROM audit"))
                    assert {value for kind, value in rows if kind == "retrieve"} == {"A", "B"}
                    diagnostics = await _query(handle, system.scope, "diagnostics")
                    assert (
                        diagnostics["budget"]["reserved"] == diagnostics["budget"]["unknown"] == 0
                    )
                    assert diagnostics["context_stages"]
                    proofs = await system.evidence_tree(handle)
                    assert proofs[0]["request"] == original_request
                    assert (await system.registry_view())["counts"]["held_root_runs"] == 1
                    (tmp_path / "managed-observations.json").write_text(
                        json.dumps(
                            {
                                "knowledge_reads": rows,
                                "context_stages": diagnostics["context_stages"],
                            }
                        )
                    )
        finally:
            for resource in reversed(resources):
                resource.close()

    asyncio.run(asyncio.wait_for(scenario(), 120))


def test_actual_approval_restart_and_cancel_keep_original_bound_root(tmp_path):
    """A restart must recover original approval and cancellation must retain root occupancy."""

    async def scenario():
        async with _system(tmp_path, approval=True) as system:
            _, accepted = await system.reserve(_agent("approval"), {"case": "approval"})
            handle = await system.start(accepted)
            async with system.worker():
                pending = await _eventually(
                    lambda: _query(handle, system.scope),
                    lambda snapshot: snapshot["state"] == "waiting_approval",
                )
                assert len(system.probe.models) == 1 and system.probe.reads == []
                bound = await system.registry_view()
                proof = await _query(handle, system.scope, "deployment_admission")
            assert await system.registry_view() == bound
            async with system.worker():
                assert await _query(handle, system.scope, "deployment_admission") == proof
                assert await _query(handle, system.scope) == pending
                action = pending["pending"][0]
                approval = await _command(
                    handle,
                    system.scope,
                    "approve",
                    "approve",
                    action_id=action["action_id"],
                    approved=True,
                    **{"digest": action["digest"]},
                )
                assert approval["apply_state"] == "applied", approval
                done = await _eventually(
                    lambda: _query(handle, system.scope),
                    lambda snapshot: snapshot["state"] in {"succeeded", "failed"},
                )
                assert done["state"] == "succeeded", done
                assert len(system.probe.reads) == 1
                await _command(handle, system.scope, "cancel", "late-cancel")
                assert await system.registry_view() == bound
                await system.evidence_tree(handle)

    asyncio.run(asyncio.wait_for(scenario(), 90))


def test_actual_cancel_with_provider_in_flight_retains_held_root(tmp_path):
    async def scenario():
        async with _system(tmp_path, hold=True) as system:
            _, accepted = await system.reserve(_agent("held"), {"case": "held"})
            handle = await system.start(accepted)
            async with system.worker():
                try:
                    await asyncio.wait_for(system.probe.started.wait(), 30)
                    before = await system.registry_view()
                    cancel = await _command(handle, system.scope, "cancel", "cancel")
                    assert cancel["apply_state"] == "applied"
                    assert (await _query(handle, system.scope))["state"] == "cancelled"
                    assert system.probe.reads == []
                    assert await system.registry_view() == before
                finally:
                    system.probe.release.set()
                settled = await _eventually(
                    lambda: _query(handle, system.scope, "diagnostics"),
                    lambda diagnostics: diagnostics["workflow"]["quiescent"],
                )
                assert settled["snapshot"]["state"] == "cancelled"
                assert system.probe.reads == []
                assert await system.registry_view() == before
                await system.evidence_tree(handle)

    asyncio.run(asyncio.wait_for(scenario(), 90))


@pytest.mark.parametrize(
    "mutation",
    ["missing-metadata", "orphan", "forged-parent", "unreserved-root", "replaced-binding-epoch"],
)
def test_actual_sdk_unowned_or_forged_acceptance_never_dispatches_business(tmp_path, mutation):
    """SDK start bypass cannot turn absent or invented original authority into business."""

    async def scenario():
        async with _system(tmp_path) as system:
            receipt, accepted = await system.reserve(_agent("denied"), {"case": mutation})
            run_id = receipt["target"]
            if mutation == "missing-metadata":
                accepted.pop("deployment_admission")
            elif mutation == "orphan":
                run_id += "-orphan"
            elif mutation == "forged-parent":
                accepted["deployment_admission"]["lineage"] = [
                    {
                        "parent_run_id": receipt["target"],
                        "parent_execution_epoch": str(uuid.uuid4()),
                        "parent_request_digest": digest(accepted["request"]),
                        "parent_manifest_digest": digest(accepted["manifest"]),
                        "call_id": "invented",
                        "child_run_id": run_id + "-child",
                        "child_command_id": "invented-child",
                        "child_request_digest": digest(accepted["request"]),
                    }
                ]
                accepted["command_id"] = "invented-child"
                run_id += "-child"
            elif mutation == "unreserved-root":
                # This detached root has a valid schema and digest but no original
                # Registry reservation. Pure acceptance cannot authorize it.
                root = accepted["deployment_admission"]["root"]
                root["command_id"] = accepted["command_id"] = "unreserved"
                root["run_id"] = run_id = root_run_id(
                    system.policy.deployment_id, system.scope, "unreserved"
                )
                root["proof_digest"] = digest(
                    {
                        key: value
                        for key, value in root.items()
                        if key not in {"state", "execution_epoch", "proof_digest"}
                    }
                )
            else:
                root = receipt["root_admission"]
                await _update(
                    system.registry,
                    {
                        **{
                            key: root[key]
                            for key in (
                                "scope",
                                "command_id",
                                "run_id",
                                "request_digest",
                                "manifest_digest",
                                "proof_digest",
                            )
                        },
                        "admission_policy": system.policy.identity,
                        "namespace": system.namespace,
                        "execution_epoch": str(uuid.uuid4()),
                    },
                    "bind_deployment_root",
                )
            before = await system.registry_view()
            handle = await system.start(accepted, run_id=run_id)
            async with system.worker():
                # Malformed acceptance fails through the SDK-owned run coroutine;
                # constructor-valid invented authority reaches the guarded Activity.
                async def processed():
                    history = await handle.fetch_history()
                    if mutation in {"unreserved-root", "replaced-binding-epoch"}:
                        return any(
                            event.HasField("activity_task_completed_event_attributes")
                            or event.HasField("activity_task_failed_event_attributes")
                            for event in history.events
                        )
                    return any(
                        event.HasField("workflow_execution_failed_event_attributes")
                        for event in history.events
                    )

                await _eventually(processed, bool)
                await asyncio.sleep(0.2)
                assert system.probe.models == system.probe.reads == []
                assert await system.registry_view() == before
                if mutation in {"unreserved-root", "replaced-binding-epoch"}:
                    proof = await _query(handle, system.scope, "deployment_admission")
                    assert proof["admission_receipt"] is None
                else:
                    from temporalio.client import WorkflowExecutionStatus

                    assert (await handle.describe()).status == WorkflowExecutionStatus.FAILED
                    history = await handle.fetch_history()
                    assert not any(
                        event.HasField("activity_task_scheduled_event_attributes")
                        for event in history.events
                    )

    asyncio.run(asyncio.wait_for(scenario(), 90))
