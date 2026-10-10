import asyncio
import copy
import json

import pytest

import ralf_agent
from ralf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryArtifactStore,
    ModelResponse,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.errors import DefinitionMismatch
from tests.test_managed_data_context import context
from tests.test_managed_memory_stage import engine, schema


class Provider:
    identity = {"kind": "composite-data-context-test", "version": "1"}

    def __init__(self):
        self.summaries = 0
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        await asyncio.sleep(0)
        if messages[0]["content"].startswith("context-summary:"):
            self.summaries += 1
            return ModelResponse(
                output={"text": "Earlier evidence was observed; uncertainty remains."}
            )
        calls = [m for m in messages if m.get("tool_calls")]
        last = (
            json.loads(calls[-1]["tool_calls"][-1]["function"]["arguments"])["round"]
            if calls
            else 0
        )
        if last < 4:
            return ModelResponse(
                tool_calls=[ToolCall("lookup", {"round": last + 1}, call_id=f"c-{last + 1}")]
            )
        return ModelResponse(output="finished")


def registry(writes):
    result = ToolRegistry()

    def lookup(args, ctx):
        writes.append((ctx.run_id, args["round"]))
        return "BIG" * 4000 if args["round"] == 1 else "EVIDENCE" * 100

    result.register(
        ToolSpec("lookup", "Evidence", {"type": "object"}, effect="read_only", cost=0), lookup
    )
    return result


def agent(name="a"):
    return AgentSpec(name, "Answer", tools=["lookup"], max_context_chars=2500)


def definition(kind):
    if kind in {"graph", "parallel"}:
        return GraphWorkflowSpec(
            "g",
            [GraphNode("a", agent=agent()), GraphNode("b", agent=agent("b"))],
            max_concurrency=2 if kind == "parallel" else 1,
        )
    member = WorkflowSpec("nested", [agent()]) if kind == "nested" else agent()
    if kind in {"team", "nested"}:
        return TeamSpec("t", {"a": member, "b": agent("b")}, child_budget=12, max_depth=4)
    return DynamicWorkflowSpec(
        "d",
        {"a": member, "b": agent("b")},
        child_budget=12,
        plan_mode="dag" if kind == "dynamic-dag" else "flat",
    )


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic", "dynamic-dag", "nested"])
def test_composites_use_original_authority_and_actual_context(tmp_path, kind):
    artifacts = InMemoryArtifactStore(backend_id="artifacts")
    provider, writes = Provider(), []
    path = tmp_path / "run.sqlite"
    with engine(
        path,
        provider,
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        handle = local.submit(definition(kind), "task", command_id="s", budget=32)
        assert schema(local) == "11"
        result = asyncio.run(local.drive(handle.run_id))
        assert result.state == "succeeded", result
        assert provider.summaries >= 2
        assert len(writes) == 8
        info = local.diagnostics(handle.run_id)
        assert info.budget["held"] == 0
        assert info.budget["spent"] == 10 + provider.summaries
        if kind == "parallel":
            root = local.store.run(handle.run_id)
            frames = [n["execution"] for n in root["workflow"]["nodes"].values()]
            assert all(f["context_preparations"] and f["context_artifacts"] for f in frames)
            reservations = local.store.conn.execute(
                "SELECT id FROM reservations WHERE id LIKE 'node-context:%'"
            ).fetchall()
            assert len(reservations) == provider.summaries
    with engine(
        path,
        provider,
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        assert asyncio.run(local.drive(handle.run_id)).state == "succeeded"
        assert len(writes) == 8


def test_parallel_frame_tampering_is_rejected_before_resume(tmp_path):
    artifacts, writes = InMemoryArtifactStore(backend_id="artifacts"), []
    with engine(
        tmp_path / "run.sqlite",
        Provider(),
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        h = local.submit(definition("parallel"), "task", command_id="s", budget=32)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        with local.store.transaction():
            run = local.store.run(h.run_id)
            frame = run["workflow"]["nodes"]["a"]["execution"]
            frame["context_preparation_receipts"].clear()
            local.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            local._check_release(local.store.run(h.run_id))


def test_terminal_parallel_run_recovers_received_summary_accounting(tmp_path, monkeypatch):
    from ralf_agent import context_preparation
    from tests.test_context_preparation import PowerLoss

    artifacts, provider, writes = InMemoryArtifactStore(backend_id="artifacts"), Provider(), []
    path = tmp_path / "run.sqlite"
    with engine(
        path,
        provider,
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        h = local.submit(definition("parallel"), "task", command_id="s", budget=32)
        original = context_preparation._save
        triggered = False

        def interrupted(engine, run_id, key, record, event):
            nonlocal triggered
            original(engine, run_id, key, record, event)
            if event == "context_preparation_response_received" and not triggered:
                triggered = True
                raise PowerLoss()

        with monkeypatch.context() as patch:
            patch.setattr(context_preparation, "_save", interrupted)
            with pytest.raises(PowerLoss):
                asyncio.run(local.drive(h.run_id))
        assert local.status(h.run_id).state in {"cancelling", "cancelled"}
    with engine(
        path,
        provider,
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        assert asyncio.run(local.drive(h.run_id)).state == "cancelled"
        records = local.context_stages(h.run_id)
        assert not any(
            r["status"] in {"prepared", "executing", "response_received"} for r in records
        )
        assert local.diagnostics(h.run_id).budget["held"] == 0


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic-dag"])
@pytest.mark.parametrize(
    "window",
    ["artifact_commit", "context_preparation_response_received", "context_preparation_adopted"],
)
def test_actual_composite_process_death_restores_without_repeating_effects(tmp_path, kind, window):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    fixture = Path(__file__).with_name("composite_context_crash_fixture.py")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.pathsep.join(
            [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }
    first = subprocess.run(
        [sys.executable, str(fixture), str(tmp_path), kind, window, "crash"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert first.returncode == 77, first.stderr
    second = subprocess.run(
        [sys.executable, str(fixture), str(tmp_path), kind, window, "resume"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert second.returncode == 0, second.stderr
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        counts = dict(db.execute("SELECT kind,COUNT(*) FROM calls GROUP BY kind").fetchall())
    assert counts["tool"] == 8 and counts["summary"] == 4 and counts["artifact"] == 1


def test_missing_entire_parallel_frame_rejects_surviving_model_evidence(tmp_path):
    artifacts, writes = InMemoryArtifactStore(backend_id="artifacts"), []
    with engine(
        tmp_path / "run.sqlite",
        Provider(),
        tools=registry(writes),
        context_assembler=context(artifacts, mode="model", summary_max_chars=256),
    ) as local:
        h = local.submit(definition("parallel"), "task", command_id="s", budget=32)
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        with local.store.transaction():
            run = local.store.run(h.run_id)
            del run["workflow"]["nodes"]["a"]["execution"]
            local.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            local.context_stages(h.run_id)
        with pytest.raises(DefinitionMismatch):
            local.context_artifacts(h.run_id)
