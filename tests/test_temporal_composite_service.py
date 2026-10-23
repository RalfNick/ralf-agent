import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InputMap,
    Literal,
    Scope,
    TeamSpec,
    ValueRef,
)
from relf_agent.errors import NotFound
from relf_agent.temporal import TemporalEngine, replay_temporal_history

from .test_temporal_service import wait_effect, wait_status

fixture_spec = importlib.util.spec_from_file_location(
    "temporal_composite_worker", Path(__file__).with_name("temporal_composite_worker.py")
)
fixture = importlib.util.module_from_spec(fixture_spec)
sys.modules["temporal_composite_worker"] = fixture
fixture_spec.loader.exec_module(fixture)

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires real Temporal/PostgreSQL",
)


@asynccontextmanager
async def system(tmp_path, policy=None, *, rag=False):
    import importlib.util

    assert importlib.util.find_spec("relf_agent.temporal_parent_workflow"), (
        "Missing registered distributed parent Workflow"
    )
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    collection = "temporal_rag_" + uuid.uuid4().hex if rag else None
    execution = await fixture.runtime(rag_collection=collection)
    queue = "composite-" + uuid.uuid4().hex
    if policy is not None:
        from relf_agent.temporal_activities import TemporalRuntime

        execution = TemporalRuntime(
            providers=execution.providers,
            tools=execution.tools,
            journal=execution.journal,
            execution_policy=policy,
        )
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("composite", queue),
        activity_timeout=3,
        drive_timeout=30,
    )
    processes = []
    env = {
        name: os.environ[name]
        for name in ["PATH", "RALF_TEST_TEMPORAL_ADDRESS", "RALF_TEST_POSTGRES_DSN"]
        if name in os.environ
    }
    env.update(PYTHONPATH=str(Path(__file__).parents[1] / "src"), RALF_TEST_TEMPORAL_QUEUE=queue)
    if rag:
        env["RALF_TEST_RAG_COLLECTION"] = collection
        env["RALF_TEST_QDRANT_URL"] = os.environ["RALF_TEST_QDRANT_URL"]
    if policy is not None:
        value = policy.identity
        value.pop("kind")
        env["RALF_TEST_EXECUTION_POLICY"] = json.dumps(value)

    async def start():
        for _ in range(2):
            log_path = tmp_path / f"worker-{uuid.uuid4().hex}.log"
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        str(Path(__file__).with_name("temporal_composite_worker.py")),
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append((process, log_path))
            deadline = asyncio.get_running_loop().time() + 15
            while "TEMPORAL_WORKER_READY" not in log_path.read_text():
                if process.poll() is not None or asyncio.get_running_loop().time() > deadline:
                    raise AssertionError(log_path.read_text())
                await asyncio.sleep(0.05)

    async def kill():
        for process, _ in processes:
            if process.poll() is None:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)

    try:
        await start()
        yield engine, execution, processes, kill, start
    finally:
        await kill()
        for resource in getattr(execution, "rag_resources", []):
            await resource.aclose()
        await execution.journal.aclose()


async def approve_all(engine, run_id):
    snapshot = await engine.drive(run_id)
    assert snapshot.state == "waiting_approval"
    for item in snapshot.pending:
        child = item["run_id"]
        receipt = await engine.approve(
            child, item["action_id"], item["digest"], command_id="approve:" + child
        )
        assert (
            await engine.approve(
                child, item["action_id"], item["digest"], command_id="approve:" + child
            )
            == receipt
        )
    deadline = asyncio.get_running_loop().time() + 15
    while True:
        result = await engine.drive(run_id, wait_seconds=1)
        if result.state in {"succeeded", "failed", "cancelled"}:
            return result
        assert asyncio.get_running_loop().time() < deadline, "Parent observation did not converge"
        await asyncio.sleep(0.1)


def test_real_distributed_graph_bindings_parallel_and_history_replay(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, _, processes, _, _):
            graph = GraphWorkflowSpec(
                "parallel",
                [
                    GraphNode("left", agent=AgentSpec("left", "Answer"), input=Literal("left")),
                    GraphNode("right", agent=AgentSpec("right", "Answer"), input=Literal("right")),
                    GraphNode(
                        "join",
                        agent=AgentSpec("join", "Answer"),
                        depends_on=("left", "right"),
                        input=InputMap({"left": ValueRef("left"), "right": ValueRef("right")}),
                    ),
                ],
                max_concurrency=2,
                output=ValueRef("join"),
            )
            handle = await engine.submit(graph, "task", command_id="first", budget=24)
            assert await engine.submit(graph, "task", command_id="first", budget=24) == handle
            snapshot = await engine.drive(handle.run_id)
            if snapshot.state != "succeeded":
                events = await engine.events(handle.run_id)
                print("PARENT_DIAGNOSTICS", await engine.diagnostics(handle.run_id), events[-5:])
            assert snapshot.state == "succeeded" and snapshot.result == {
                "left": "left",
                "right": "right",
            }
            details = await engine.diagnostics(handle.run_id)
            assert (
                len(details.workflow["children"]) == 3
                and details.budget["spent"] == 3
                and details.budget["reserved"] == 0
            )
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )
            assert (
                sum(log.read_text().count("TEMPORAL_PROVIDER_CALLED") for _, log in processes) == 3
            )

    asyncio.run(run())


def test_real_nested_team_model_dag_child_approval_and_worker_restart(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, _, processes, kill, start):
            spec = TeamSpec(
                "outer",
                {
                    "nested": DynamicWorkflowSpec(
                        "dag",
                        {"operator": AgentSpec("op", "Change", ("write",))},
                        plan_mode="dag",
                        planner="dag-model",
                        child_budget=8,
                    )
                },
                child_budget=16,
            )
            task = {"tool": True, "arguments": {"label": uuid.uuid4().hex}}
            handle = await engine.submit(spec, task, command_id="first", budget=24)
            snapshot = await engine.drive(handle.run_id)
            if snapshot.state != "waiting_approval":
                print(
                    "PARENT_DIAGNOSTICS",
                    await engine.diagnostics(handle.run_id),
                    await engine.events(handle.run_id),
                )
            assert snapshot.state == "waiting_approval" and len(snapshot.pending) == 1
            await kill()
            await start()
            result = await approve_all(engine, handle.run_id)
            assert result.state == "succeeded"
            details = await engine.diagnostics(handle.run_id)
            assert details.budget["reserved"] == 0 and details.budget["spent"] == 4
            assert (
                sum(log.read_text().count("TEMPORAL_PLANNER_CALLED") for _, log in processes) == 1
            )
            child = details.workflow["children"][0]["run_id"]
            await replay_temporal_history(
                await engine.client.get_workflow_handle(child).fetch_history()
            )

    asyncio.run(run())


def test_real_deadline_retains_active_model_cap_and_late_evidence(tmp_path):
    from relf_agent.governance import TemporalExecutionPolicy

    async def run():
        async with system(tmp_path, TemporalExecutionPolicy(run_timeout_seconds=1)) as (
            engine,
            _,
            _,
            _,
            _,
        ):
            handle = await engine.submit(
                AgentSpec("slow", "Answer"), {"model_delay": 2.5}, command_id="slow", budget=8
            )
            deadline = asyncio.get_running_loop().time() + 8
            while (snapshot := await engine.status(handle.run_id)).state != "cancelled":
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
            details = await engine.diagnostics(handle.run_id)
            assert details.budget["reserved"] == 1 and not details.workflow["quiescent"]
            while not (details := await engine.diagnostics(handle.run_id)).workflow["quiescent"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            assert (
                details.snapshot.state == "cancelled"
                and details.budget["reserved"] == 0
                and details.budget["spent"] == 1
            )
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


def test_real_approval_expiry_is_fixed_across_repeated_drive_controls(tmp_path):
    from relf_agent.governance import TemporalExecutionPolicy

    async def run():
        async with system(tmp_path, TemporalExecutionPolicy(approval_timeout_seconds=0.5)) as (
            engine,
            _,
            _,
            _,
            _,
        ):
            handle = await engine.submit(
                AgentSpec("change", "Change", ("write",)),
                {"tool": True, "arguments": {"label": uuid.uuid4().hex}},
                command_id="first",
            )
            snapshot = await engine.drive(handle.run_id)
            assert snapshot.state == "waiting_approval"
            action = snapshot.pending[0]
            for _ in range(3):
                await asyncio.sleep(0.15)
                await engine.drive(handle.run_id, wait_seconds=0.1)
            await asyncio.sleep(0.2)
            snapshot = await engine.status(handle.run_id)
            assert snapshot.state == "failed" and snapshot.error["code"] == "approval_expired"
            assert not any(a["kind"] == "tool" and a["attempts"] for a in snapshot.actions)
            receipt = await engine.approve(
                handle.run_id, action["action_id"], "wrong", command_id="late-wrong"
            )
            assert receipt.outcome["rejected"]

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("RALF_TEST_QDRANT_URL"), reason="Requires actual Qdrant")
def test_real_distributed_rag_uses_shared_postgres_qdrant_and_replays_snapshot(tmp_path):
    from relf_agent import Document

    async def run():
        async with system(tmp_path, rag=True) as (engine, execution, processes, kill, start):
            retriever = execution.knowledge.retriever
            for scope, document in [
                (
                    engine.scope,
                    Document(
                        "guide", "Database timeout: inspect pool first", source_uri="probe://guide"
                    ),
                ),
                (
                    Scope("other", engine.task_queue),
                    Document("private", "private database timeout", source_uri="probe://private"),
                ),
            ]:
                await retriever.store.put(scope, "runbooks", document, expected_version=0)
                await retriever.index_document(scope, "runbooks", document.document_id)
            graph = GraphWorkflowSpec(
                "rag",
                [GraphNode("answer", agent=AgentSpec("answer", "Use evidence"))],
                output=ValueRef("answer"),
            )
            handle = await engine.submit(graph, "database timeout", command_id="first", budget=16)
            result = await engine.drive(handle.run_id)
            assert result.state == "succeeded" and result.result["citations"] == [
                {
                    "document_id": "guide",
                    "version": 1,
                    "text": "Database timeout: inspect pool first",
                }
            ]
            child = (await engine.diagnostics(handle.run_id)).workflow["children"][0]["run_id"]
            child_snapshot = await engine.status(child)
            context = next(
                action for action in child_snapshot.actions if action["kind"] == "context"
            )
            assert context["response"]["references"][0]["_knowledge"]["scope"] == {
                "workspace": engine.scope.workspace,
                "principal": engine.scope.principal,
            }
            await kill()
            await start()
            assert (
                await engine.submit(graph, "database timeout", command_id="first", budget=16)
                == handle
            )
            assert (await engine.drive(handle.run_id)).result == result.result
            assert (
                sum(log.read_text().count("TEMPORAL_PROVIDER_CALLED") for _, log in processes) == 1
            )
            await replay_temporal_history(
                await engine.client.get_workflow_handle(child).fetch_history()
            )
            # A received snapshot pins source versions across real remote reads.
            await retriever.store.put(
                engine.scope, "runbooks", Document("guide", "changed"), expected_version=1
            )
            context_request = {
                "runtime_manifest": execution.orchestration_release,
                "step": graph.nodes[0].to_dict()["agent"],
                "scope": {"workspace": engine.scope.workspace, "principal": engine.scope.principal},
                "context": context["response"],
            }
            refused = await execution.complete_model(context_request)
            assert not refused["ok"] and not refused["dispatched"]

    asyncio.run(run())


def test_real_parent_cancel_keeps_cap_after_effect_query_without_remote_stop_proof(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, execution, _, kill, start):
            label = engine.task_queue + "-lost"
            spec = TeamSpec(
                "outer", {"operator": AgentSpec("op", "Change", ("write",))}, child_budget=8
            )
            handle = await engine.submit(
                spec,
                {"tool": True, "arguments": {"label": label, "delay": 20}},
                command_id="first",
                budget=16,
            )
            pending = await engine.drive(handle.run_id)
            target = pending.pending[0]
            leaf = target["run_id"]
            await engine.approve(leaf, target["action_id"], target["digest"], command_id="approve")
            key, writes = await wait_effect(execution, label)
            assert writes == 1
            await kill()
            await start()
            unknown = await wait_status(engine, leaf, {"waiting_reconciliation"})
            receipt = await engine.cancel(handle.run_id, command_id="stop")
            assert not receipt.outcome["remote_stop_confirmed"]
            # Parent acceptance records propagation intent. The child has its
            # own History and may still process a concurrent reconcile before
            # that cancellation arrives. Establish this scenario's child
            # cancellation precondition before asking it to adopt evidence.
            assert (await wait_status(engine, leaf, {"cancelled"})).state == "cancelled"
            deadline = asyncio.get_running_loop().time() + 15
            while not (details := await engine.diagnostics(handle.run_id)).budget["unknown"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.1)
            assert details.budget["unknown"] == 8 and not details.workflow["quiescent"]
            action = next(a for a in unknown.actions if a["kind"] == "tool")
            assert action["effect_key"] == key
            await engine.reconcile(leaf, action["id"], query=True, command_id="query")
            while (leaf_details := await engine.diagnostics(leaf)).budget[
                "unknown"
            ] or leaf_details.workflow["evidence_ack_pending"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.1)
            assert leaf_details.budget["spent"] == 2 and not leaf_details.workflow["quiescent"]
            details = await engine.diagnostics(handle.run_id)
            assert (
                details.snapshot.state == "cancelled"
                and details.budget["unknown"] == 8
                and not details.workflow["quiescent"]
            )
            assert (await wait_effect(execution, label))[1] == 1
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


def test_real_parent_cancel_releases_cap_after_actual_child_model_completion(tmp_path):
    async def run():
        async with system(tmp_path) as (engine, _, _, _, _):
            spec = TeamSpec("outer", {"slow": AgentSpec("slow", "Answer")}, child_budget=8)
            handle = await engine.submit(spec, {"model_delay": 2.5}, command_id="first", budget=16)
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                details = await engine.diagnostics(handle.run_id)
                children = details.workflow["children"]
                if children:
                    # A durable child intent precedes the service accepting StartChild.
                    try:
                        child = await engine.diagnostics(children[0]["run_id"])
                    except NotFound:
                        pass
                    else:
                        if child.budget["reserved"] == 1:
                            break
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            await engine.cancel(handle.run_id, command_id="stop")
            assert not (await engine.diagnostics(handle.run_id)).workflow["quiescent"]
            while not (details := await engine.diagnostics(handle.run_id)).workflow["quiescent"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.1)
            assert (
                details.snapshot.state == "cancelled"
                and details.budget["spent"] == 1
                and details.budget["reserved"] == 0
                and details.budget["unknown"] == 0
            )
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


def test_real_dynamic_dag_patch_adds_pending_node_with_durable_cas(tmp_path):
    from relf_agent import DAGNode, DAGProposal

    async def run():
        async with system(tmp_path) as (engine, _, _, _, _):
            spec = DynamicWorkflowSpec(
                "dag",
                {
                    "operator": AgentSpec("op", "Change", ("write",)),
                    "summary": AgentSpec("summary", "Answer"),
                },
                plan_mode="dag",
                child_budget=8,
            )
            handle = await engine.submit(
                spec,
                {"tool": True, "arguments": {"label": uuid.uuid4().hex}},
                command_id="first",
                budget=24,
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_approval"
            details = await engine.diagnostics(handle.run_id)
            prior = DAGProposal.from_dict(details.workflow["dag"]["proposal"])
            nodes = [DAGNode.from_dict(n) for n in prior.nodes]
            proposal = DAGProposal(
                [
                    *nodes,
                    DAGNode(
                        "audit",
                        "summary",
                        depends_on=(nodes[-1].to_dict()["id"],),
                        input=ValueRef(nodes[-1].to_dict()["id"]),
                    ),
                ]
            )
            receipt = await engine.patch_plan(
                handle.run_id, proposal, expected_plan_revision=0, command_id="patch"
            )
            assert receipt.apply_state == "applied"
            assert (
                await engine.patch_plan(
                    handle.run_id, proposal, expected_plan_revision=0, command_id="patch"
                )
                == receipt
            )
            from relf_agent.errors import ValidationError

            with pytest.raises(ValidationError):
                await engine.patch_plan(
                    handle.run_id, proposal, expected_plan_revision=0, command_id="stale"
                )
            assert any(
                event.kind == "command_applied"
                and event.data.get("command_id") == "stale"
                and event.data.get("apply_state") == "rejected"
                for event in await engine.events(handle.run_id)
            )
            result = await approve_all(engine, handle.run_id)
            assert result.state == "succeeded"
            assert len((await engine.diagnostics(handle.run_id)).workflow["children"]) == 3
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())
