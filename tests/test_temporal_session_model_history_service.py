"""Actual Temporal Session/Worker paths and History replay; deterministic signed fixture."""

import asyncio
import copy
import os
import uuid
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    Runtime,
    Scope,
    SQLiteMemory,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.managed_context import ManagedContextPipeline
from relf_agent.model_history import CompleteModelHistory
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_session_state import workflow_id
from relf_agent.temporal_session_topology import CompositeSessionTopology
from tests.test_temporal_session_model_history import SignedTools, one, two

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "kind", ["native", "sequence", "graph", "parallel", "team", "plan", "dag", "nested"]
)
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("external", [False, True, "redis", "postgres"])
def test_actual_session_two_turns_preserve_native_tool_signature_and_replay(
    tmp_path, kind, managed, external
):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-session-history-" + uuid.uuid4().hex
        provider, tools = SignedTools(), ToolRegistry()
        tools.register_function(one, effect="read_only")
        tools.register_function(two, effect="read_only")
        remote_client, remote_schema = None, None
        if external == "redis":
            url = os.getenv("RALF_TEST_NATIVE_REDIS_URL")
            if not url:
                pytest.skip("requires the task-owned actual Redis service")
            from redis.asyncio import Redis

            from relf_agent import RedisMemory

            remote_client = Redis.from_url(url, socket_timeout=3)
            backend = RedisMemory(remote_client, prefix=queue, backend_id="native:" + queue)
            await backend.initialize_session_identity()
        elif external == "postgres":
            dsn = os.getenv("RALF_TEST_POSTGRES_DSN")
            if not dsn:
                pytest.skip("requires the task-owned actual PostgreSQL service")
            import psycopg
            from psycopg import sql

            from relf_agent import PostgresMemory

            remote_client = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
            remote_schema = "native_" + uuid.uuid4().hex
            await remote_client.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(remote_schema))
            )
            await remote_client.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(remote_schema))
            )
            backend = PostgresMemory(remote_client, backend_id="native:" + queue)
            await backend.initialize()
            await backend.initialize_session_identity()
        else:
            backend = SQLiteMemory(tmp_path / "native.sqlite") if external else None
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=tools,
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
            context_builder=ManagedContextPipeline() if managed else None,
            session_store=backend,
            session_writes=bool(external),
            session_topology=CompositeSessionTopology()
            if external and kind not in {"native", "sequence"}
            else None,
        )
        agent = AgentSpec("answer", "Answer", tools=("one", "two"))
        if kind == "native":
            definition = agent
        elif kind == "sequence":
            definition = WorkflowSpec("sequence", [agent, agent])
        elif kind in {"graph", "parallel"}:
            nodes = [GraphNode("one", agent=agent)]
            if kind == "parallel":
                nodes.append(GraphNode("two", agent=agent))
            definition = GraphWorkflowSpec(
                "graph", nodes, max_concurrency=2 if kind == "parallel" else 1
            )
        elif kind == "team":
            definition = TeamSpec("team", {"one": agent})
        elif kind in {"plan", "dag"}:
            definition = DynamicWorkflowSpec(
                "dynamic",
                {"one": agent},
                planner="dag-rule" if kind == "dag" else "rule",
                plan_mode="dag" if kind == "dag" else "flat",
            )
        else:
            definition = TeamSpec(
                "nested", {"inner": GraphWorkflowSpec("graph", [GraphNode("one", agent=agent)])}
            )

        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("native-session-history", queue),
            activity_timeout=5,
        )
        host = Runtime.from_temporal(engine)
        before, runs = {}, []
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition, "chat", command_id="open")
                for seq in (1, 2):
                    turn = await entry.submit(
                        "turn-one" if seq == 1 else "turn-two", command_id=f"turn-{seq}", budget=48
                    )
                    done = await turn.wait(wait_timeout=30, terminal_only=True)
                    assert done.snapshot.state == "succeeded", await turn.diagnostics()
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- actual original Session adoption
                            await asyncio.sleep(0.05)
                    pending, episodes = [turn.ref.run_id], []
                    while pending:
                        run_id = pending.pop()
                        runs.append(run_id)
                        proof = await client.get_workflow_handle(run_id).query(
                            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                        )
                        pending.extend(c["run_id"] for c in proof["workflow"].get("children", []))
                        episodes.extend(proof.get("native_history_episodes", []))
                    assert len(episodes) == (2 if kind in {"sequence", "parallel"} else 1)
                    if seq == 1:
                        before = {e["stream"]: copy.deepcopy(e) for e in episodes}
                    else:
                        assert {e["stream"] for e in episodes} == set(before)
                        assert all(e["source"]["turn_seq"] == 2 for e in episodes)
                agents = 2 if kind in {"sequence", "parallel"} else 1
                assert len(provider.calls) == agents * 4
                for envelope in before.values():
                    expected = envelope["history"]
                    matching = [
                        actual
                        for actual in provider.calls[agents * 2 :]
                        if actual[: len(expected)] == expected
                    ]
                    assert len(matching) == 2
                    assert all(actual[len(expected)]["role"] == "user" for actual in matching)
                for run_id in runs + [workflow_id(entry.ref.key)]:
                    await replay_temporal_history(
                        await client.get_workflow_handle(run_id).fetch_history()
                    )
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            await host.aclose()
            await engine.aclose()
            if isinstance(backend, SQLiteMemory):
                backend.store.close()
            elif backend is not None:
                await backend.aclose()
                if external == "redis":
                    keys = [key async for key in remote_client.scan_iter(match=queue + ":*")]
                    if keys:
                        await remote_client.delete(*keys)
                    await remote_client.aclose()
                else:
                    await remote_client.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(remote_schema))
                    )
                    await remote_client.close()

    asyncio.run(asyncio.wait_for(run(), 100))


@pytest.mark.parametrize("kind", ["native", "graph"])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_worker_loss_after_native_final_receipt_restores_original_episode(
    tmp_path, kind, managed
):
    async def run():
        import json
        import subprocess
        import sys
        from pathlib import Path

        from temporalio.client import Client

        import relf_agent
        from tests.temporal_session_model_history_worker import runtime

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-session-crash-" + uuid.uuid4().hex
        execution, definition, backend = runtime(tmp_path, kind=kind, managed=managed)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("native-session-crash", queue),
            activity_timeout=3,
        )
        host, processes = Runtime.from_temporal(engine), []

        async def start(mode):
            log = tmp_path / f"native-worker-{mode}.log"
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_NATIVE_HISTORY_ROOT": str(tmp_path),
                "RALF_NATIVE_HISTORY_WORKER_MODE": mode,
                "RALF_NATIVE_HISTORY_KIND": kind,
                "RALF_NATIVE_HISTORY_MANAGED": str(int(managed)),
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_session_model_history_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            async with asyncio.timeout(25):
                while "TEMPORAL_NATIVE_HISTORY_READY" not in log.read_text():  # noqa: ASYNC110 -- process readiness
                    assert process.poll() is None, log.read_text()
                    await asyncio.sleep(0.05)
            return process

        def rows():
            return [
                json.loads(line)
                for line in (tmp_path / "native-audit.jsonl").read_text().splitlines()
            ]

        try:
            original = await start("original")
            entry = await host.open_session(definition, "chat", command_id="open")
            first = await entry.submit("turn-one", command_id="first", budget=40)
            marker = tmp_path / "native-window-ready"
            async with asyncio.timeout(30):
                while not marker.exists():  # noqa: ASYNC110 -- actual durable receipt window
                    assert original.poll() is None, (
                        tmp_path / "native-worker-original.log"
                    ).read_text()
                    await asyncio.sleep(0.05)
            leaf_id = marker.read_text()
            request = {"kind": "diagnostics", "scope": asdict(engine.scope)}
            before = await client.get_workflow_handle(leaf_id).query("view", request)
            assert before["manifest"]["binding_protocol"] == 8
            final_before = [a for a in before["snapshot"]["actions"] if a["kind"] == "model"][-1]
            assert (
                final_before["status"] == "received"
                and final_before["received_response"]["continuation"]
            )
            assert len([r for r in rows() if r["kind"] == "model"]) == 2
            assert len([r for r in rows() if r["kind"] == "tool"]) == 2
            original.kill()
            await asyncio.to_thread(original.wait, timeout=5)
            await host.aclose()
            host = Runtime.from_temporal(engine)
            recovered = await start("recover")
            entry = await host.aattach_session(entry.ref)
            attached = await host.aattach(first.ref)
            done = await attached.wait(wait_timeout=40, terminal_only=True)
            assert done.snapshot.state == "succeeded", await attached.diagnostics()
            async with asyncio.timeout(15):
                while (await entry.status()).busy:  # noqa: ASYNC110 -- actual Session release after receipt recovery
                    await asyncio.sleep(0.05)
            after = await client.get_workflow_handle(leaf_id).query("view", request)
            final_after = [a for a in after["snapshot"]["actions"] if a["kind"] == "model"][-1]
            assert final_after["received_response"] == final_before["received_response"]
            assert final_after["dispatch_request"] == final_before["dispatch_request"]
            assert final_after["model_receipt"] == final_before["model_receipt"]
            assert len([r for r in rows() if r["kind"] == "model"]) == 2
            assert len([r for r in rows() if r["kind"] == "tool"]) == 2
            second = await entry.submit("turn-two", command_id="second", budget=40)
            assert (
                await second.wait(wait_timeout=30, terminal_only=True)
            ).snapshot.state == "succeeded"
            native = after["native_history_episodes"][0]["history"]
            actual = [r for r in rows() if r["kind"] == "model"][2]["messages"]
            assert actual[: len(native)] == native and actual[len(native)]["content"] == "turn-two"
            assert len([r for r in rows() if r["kind"] == "model"]) == 4
            for run_id in {
                leaf_id,
                first.ref.run_id,
                second.ref.run_id,
                workflow_id(entry.ref.key),
            }:
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
            recovered.terminate()
            await asyncio.to_thread(recovered.wait, timeout=10)
            assert recovered.returncode == 0, (tmp_path / "native-worker-recover.log").read_text()
            assert (tmp_path / "native-worker-closed-recover").read_text() == "closed"
        finally:
            await host.aclose()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            backend.store.close()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), 150))


def test_actual_failed_parent_excludes_saved_leaf_candidates_over_two_turns(tmp_path):
    async def run():
        from temporalio.client import Client

        from relf_agent import ModelResponse
        from relf_agent.session_model_history import native_history_address

        class FailSecond(SignedTools):
            async def complete(self, messages, tools):
                if messages[0]["content"] == "Invalid integer":
                    self.calls.append(copy.deepcopy(messages))
                    return ModelResponse(output="invalid")
                return await super().complete(messages, tools)

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-root-fail-" + uuid.uuid4().hex
        provider, tools = FailSecond(), ToolRegistry()
        tools.register_function(one, effect="read_only")
        tools.register_function(two, effect="read_only")
        backend = SQLiteMemory(tmp_path / "failed-native.sqlite")
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=tools,
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
            session_store=backend,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        definition = GraphWorkflowSpec(
            "partial",
            [
                GraphNode("good", agent=AgentSpec("good", "Answer", tools=("one", "two"))),
                GraphNode(
                    "bad",
                    agent=AgentSpec("bad", "Invalid integer", output_schema={"type": "integer"}),
                    depends_on=("good",),
                ),
            ],
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("native-root-fail", queue),
            activity_timeout=5,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition, "chat", command_id="open")
                for seq in (1, 2):
                    turn = await entry.submit(f"turn-{seq}", command_id=f"turn-{seq}", budget=32)
                    assert (
                        await turn.wait(wait_timeout=30, terminal_only=True)
                    ).snapshot.state == "failed"
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- original failed-root Session qualification
                            await asyncio.sleep(0.05)
                    proof = await client.get_workflow_handle(turn.ref.run_id).query(
                        "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                    )
                    good = next(c for c in proof["workflow"]["children"] if c["member"] == "good")
                    leaf = await client.get_workflow_handle(good["run_id"]).query(
                        "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                    )
                    envelope = leaf["native_history_episodes"][0]
                    assert (
                        backend.read(engine.scope, native_history_address(envelope["stream"]))[0]
                        == seq
                    )
                    await replay_temporal_history(
                        await client.get_workflow_handle(turn.ref.run_id).fetch_history()
                    )
                assert provider.calls[3] == [
                    {"role": "system", "content": "Answer"},
                    {"role": "user", "content": "turn-2"},
                ]
                await replay_temporal_history(
                    await client.get_workflow_handle(workflow_id(entry.ref.key)).fetch_history()
                )
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(asyncio.wait_for(run(), 100))


def test_actual_nullable_output_keeps_null_native_final_over_two_turns():
    async def run():
        from temporalio.client import Client

        from relf_agent import ModelResponse

        class Nullable:
            identity = {"kind": "actual-native-null", "version": "1"}

            def __init__(self):
                self.calls = []

            async def complete(self, messages, tools):
                self.calls.append(copy.deepcopy(messages))
                return ModelResponse(output=None)

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-null-" + uuid.uuid4().hex
        provider = Nullable()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
        )
        engine = TemporalEngine(
            client, task_queue=queue, release=execution.manifest, scope=Scope("native-null", queue)
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(
                    AgentSpec("null", "Return null", output_schema={"type": "null"}),
                    "chat",
                    command_id="open",
                )
                for seq in (1, 2):
                    turn = await entry.submit(f"turn-{seq}", command_id=f"turn-{seq}")
                    done = await turn.wait(wait_timeout=25, terminal_only=True)
                    assert done.snapshot.state == "succeeded" and done.snapshot.result is None
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- actual null-output publication
                            await asyncio.sleep(0.05)
                    await replay_temporal_history(
                        await client.get_workflow_handle(turn.ref.run_id).fetch_history()
                    )
                assert provider.calls[1][2] == {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [],
                }
                assert provider.calls[1][-1] == {"role": "user", "content": "turn-2"}
                await replay_temporal_history(
                    await client.get_workflow_handle(workflow_id(entry.ref.key)).fetch_history()
                )
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), 90))


@pytest.mark.parametrize("managed", [False, True])
def test_actual_model_planner_has_separate_complete_native_history(tmp_path, managed):
    async def run():
        import json

        from temporalio.client import Client

        from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
        from relf_agent.planning import ModelPlanner
        from relf_agent.types import digest

        class PlannerProvider:
            identity = {"kind": "actual-native-model-planner", "version": "1"}

            def __init__(self):
                self.calls = []

            @property
            def continuation_identity(self):
                return {"protocol": "planner-signed-v1", "owner_digest": digest(self.identity)}

            async def complete(self, messages, tools):
                assert tools == []
                self.calls.append(copy.deepcopy(messages))
                task = json.loads(
                    next(m for m in reversed(messages) if m["role"] == "user")["content"]
                )
                output = {
                    "steps": [{"id": "business", "member": "one", "input": {"task": task["task"]}}]
                }
                return ContinuedModelResponse(
                    output=output,
                    continuation=ModelContinuation(
                        "planner-signed-v1",
                        digest(self.identity),
                        digest({"output": output, "tool_calls": []}),
                        {"signature": "opaque-planner-signature", "serial": len(self.calls)},
                    ),
                )

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-model-planner-" + uuid.uuid4().hex
        planner, business, tools = PlannerProvider(), SignedTools(), ToolRegistry()
        tools.register_function(one, effect="read_only")
        tools.register_function(two, effect="read_only")
        backend = SQLiteMemory(tmp_path / "model-planner.sqlite")
        execution = TemporalRuntime(
            providers={"default": business, "planner-fixture": planner},
            planners={"native-model": ModelPlanner(provider="planner-fixture")},
            tools=tools,
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
            context_builder=ManagedContextPipeline() if managed else None,
            session_store=backend,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        definition = DynamicWorkflowSpec(
            "model-planned",
            {"one": AgentSpec("business", "Answer", tools=("one", "two"))},
            planner="native-model",
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("native-model-planner", queue),
            activity_timeout=5,
        )
        host = Runtime.from_temporal(engine)
        first, run_ids = {}, []
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition, "chat", command_id="open")
                for seq in (1, 2):
                    turn = await entry.submit(f"turn-{seq}", command_id=f"turn-{seq}", budget=48)
                    done = await turn.wait(wait_timeout=30, terminal_only=True)
                    assert done.snapshot.state == "succeeded", await turn.diagnostics()
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- original managed planner publication
                            await asyncio.sleep(0.05)
                    proof = await client.get_workflow_handle(turn.ref.run_id).query(
                        "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                    )
                    children = proof["workflow"]["children"]
                    assert {c["member"] for c in children} == {"@planner", "one"}
                    run_ids.append(turn.ref.run_id)
                    episodes = {}
                    for child in children:
                        run_ids.append(child["run_id"])
                        leaf = await client.get_workflow_handle(child["run_id"]).query(
                            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                        )
                        assert len(leaf["native_history_episodes"]) == 1
                        episodes[child["member"]] = leaf["native_history_episodes"][0]
                    assert episodes["@planner"]["stream"] != episodes["one"]["stream"]
                    if seq == 1:
                        first = copy.deepcopy(episodes)
                    else:
                        assert {k: e["stream"] for k, e in episodes.items()} == {
                            k: e["stream"] for k, e in first.items()
                        }
                        assert all(e["source"]["turn_seq"] == 2 for e in episodes.values())
                assert len(planner.calls) == 2 and len(business.calls) == 4
                planner_past, business_past = first["@planner"]["history"], first["one"]["history"]
                assert planner.calls[1][: len(planner_past)] == planner_past
                assert business.calls[2][: len(business_past)] == business_past
                assert business.calls[3][: len(business_past)] == business_past
                assert (
                    planner_past[-1]["model_continuation"]["data"]["signature"]
                    == "opaque-planner-signature"
                )
                assert len([m for m in business_past if m["role"] == "tool"]) == 2
                assert json.loads(planner.calls[1][-1]["content"])["task"] == "turn-2"
                assert (
                    json.loads(business.calls[2][len(business_past)]["content"])["task"] == "turn-2"
                )
                for run_id in run_ids + [workflow_id(entry.ref.key)]:
                    await replay_temporal_history(
                        await client.get_workflow_handle(run_id).fetch_history()
                    )
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(asyncio.wait_for(run(), 100))


@pytest.mark.parametrize("external", [False, True])
def test_actual_full_native_stream_rejects_129th_model_and_releases_session(tmp_path, external):
    async def run():
        from temporalio.client import Client

        from relf_agent import ModelResponse

        class SmallFinal:
            identity = {"kind": "actual-native-capacity", "version": "1"}

            def __init__(self):
                self.calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                return ModelResponse(output="done")

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-full-stream-" + uuid.uuid4().hex
        provider = SmallFinal()
        backend = SQLiteMemory(tmp_path / "capacity.sqlite") if external else None
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
            session_store=backend,
            session_writes=external,
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("native-full-stream", queue),
            activity_timeout=10,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(
                    AgentSpec("a", "Answer", max_context_chars=1_000_000), "chat", command_id="open"
                )
                for seq in range(1, 130):
                    turn = await entry.submit(f"task-{seq}", command_id=f"turn-{seq}", budget=4)
                    done = await turn.wait(wait_timeout=30, terminal_only=True)
                    assert done.snapshot.state == ("succeeded" if seq <= 128 else "failed"), (
                        seq,
                        await turn.diagnostics(),
                    )
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- original capacity failure adoption
                            await asyncio.sleep(0.01)
                assert provider.calls == 128
                assert not (await entry.status()).busy
                await replay_temporal_history(
                    await client.get_workflow_handle(turn.ref.run_id).fetch_history()
                )
                await replay_temporal_history(
                    await client.get_workflow_handle(workflow_id(entry.ref.key)).fetch_history()
                )
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            await host.aclose()
            await engine.aclose()
            if backend is not None:
                backend.store.close()

    asyncio.run(asyncio.wait_for(run(), 420))


@pytest.mark.parametrize("kind", ["team", "plan"])
def test_actual_parent_capacity_failure_releases_without_partial_publication(monkeypatch, kind):
    """Lower only the limit for a small actual parent boundary fixture; no seeded History."""

    async def run():
        from temporalio.client import Client
        from temporalio.worker import Replayer
        from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

        from relf_agent import temporal_session_model_history as native
        from relf_agent.orchestration_types import ChildCall, TeamSelection
        from relf_agent.planning import PlanProposal
        from relf_agent.temporal import _workflow_runner
        from relf_agent.temporal_parent_workflow import TemporalParentWorkflow
        from relf_agent.temporal_session_workflow import TemporalSessionWorkflow
        from relf_agent.temporal_workflow import (
            TemporalCommandRegistryWorkflow,
            TemporalRunWorkflow,
        )

        class RepeatedTeam:
            identity = {"kind": "actual-repeated-capacity-team", "version": "1"}

            def select(self, request):
                return (
                    TeamSelection(done=True, result="done")
                    if request.results
                    else TeamSelection(
                        [
                            ChildCall("first", "one", "task-one"),
                            ChildCall("second", "one", "task-two"),
                        ]
                    )
                )

        class RepeatedPlanner:
            identity = {"kind": "actual-repeated-capacity-plan", "version": "1"}

            async def plan(self, request, caller):
                return PlanProposal(
                    [ChildCall("first", "one", "task-one"), ChildCall("second", "one", "task-two")]
                )

        monkeypatch.setattr(native, "MAX_TURNS", 1)
        runner = SandboxedWorkflowRunner(
            restrictions=_workflow_runner().restrictions.with_passthrough_modules(
                "relf_agent.temporal_session_model_history"
            )
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-parent-capacity-" + uuid.uuid4().hex
        tools = ToolRegistry()
        tools.register_function(one, effect="read_only")
        tools.register_function(two, effect="read_only")
        provider = SignedTools()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=tools,
            team_strategies={"repeat": RepeatedTeam()},
            planners={"repeat": RepeatedPlanner()},
            enable_sessions=True,
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
        )
        agent = AgentSpec("answer", "Answer", tools=("one", "two"))
        definition = (
            TeamSpec("repeat", {"one": agent}, strategy="repeat")
            if kind == "team"
            else DynamicWorkflowSpec("repeat", {"one": agent}, planner="repeat")
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("native-parent-capacity", queue),
            activity_timeout=5,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(
                client, task_queue=queue, runtime=execution, workflow_runner=runner
            ):
                entry = await host.open_session(definition, "chat", command_id="open")
                for seq in (1, 2):
                    turn = await entry.submit(f"task-{seq}", command_id=f"turn-{seq}", budget=32)
                    done = await turn.wait(wait_timeout=30, terminal_only=True)
                    assert (
                        done.snapshot.state == "failed"
                        and done.snapshot.error["code"] == "session_history_capacity"
                    )
                    async with asyncio.timeout(15):
                        while (await entry.status()).busy:  # noqa: ASYNC110 -- original failed parent adoption
                            await asyncio.sleep(0.05)
                    proof = await client.get_workflow_handle(turn.ref.run_id).query(
                        "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
                    )
                    assert len(proof["native_history_bundle"]) == 2
                    assert all(c["state"] == "succeeded" for c in proof["workflow"]["children"])
                    if seq == 2:
                        assert all(len(messages) == 2 for messages in provider.calls[4::2])
                    await Replayer(
                        workflows=[
                            TemporalRunWorkflow,
                            TemporalCommandRegistryWorkflow,
                            TemporalParentWorkflow,
                            TemporalSessionWorkflow,
                        ],
                        workflow_runner=runner,
                    ).replay_workflow(
                        await client.get_workflow_handle(turn.ref.run_id).fetch_history()
                    )
                assert len(provider.calls) == 8 and not (await entry.status()).busy
                await Replayer(
                    workflows=[
                        TemporalRunWorkflow,
                        TemporalCommandRegistryWorkflow,
                        TemporalParentWorkflow,
                        TemporalSessionWorkflow,
                    ],
                    workflow_runner=runner,
                ).replay_workflow(
                    await client.get_workflow_handle(workflow_id(entry.ref.key)).fetch_history()
                )
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await execution.close_session_execution(wait_timeout=5)
            await host.aclose()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), 100))
