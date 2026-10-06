import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from ralf_agent import (
    ComponentRegistry,
    RuntimeBuilder,
    RuntimeProfile,
    StaticWorkflowScheduler,
    WorkflowBatch,
    load_spec,
)
from ralf_agent.starter import create_starter


def test_scheduler_factory_and_graph_declaration_need_no_engine_subclass(tmp_path):
    class Reverse(StaticWorkflowScheduler):
        identity = {"kind": "reverse", "version": "1"}

        def select(self, plan, input, states, limit):
            batch = super().select(plan, input, states, limit)
            return WorkflowBatch(
                tuple(reversed(batch.selections)), batch.skipped, batch.done, batch.result
            )

    path = tmp_path / "graph.toml"
    path.write_text(
        'kind="graph"\nname="parallel"\nmax_concurrency=2\n[[nodes]]\nid="a"\ntransform="identity"\n[[nodes]]\nid="b"\ntransform="identity"\n'
    )
    registry = ComponentRegistry()
    registry.register("workflow_scheduler", "reverse", lambda config, context: Reverse())
    profile = RuntimeProfile(
        "parallel",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"workflow_scheduler": {"adapter": "reverse"}},
    )
    with RuntimeBuilder(registry).build(profile, tmp_path / "run.db") as engine:
        handle = engine.submit(load_spec(path), "task", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).result == {"a": "task", "b": "task"}
        assert [
            e.data["node_id"]
            for e in engine.events(handle.run_id)
            if e.kind == "workflow_node_started"
        ] == ["b", "a"]


def test_parallel_starter_queue_resume_and_readonly_inspect(tmp_path):
    project = create_starter(tmp_path / "app", template="parallel")
    directory = Path(project.directory)
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    def command(*args):
        child = subprocess.run(
            [sys.executable, *args],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert child.returncode == 0, child.stderr
        return json.loads(child.stdout)

    queued = command("-m", "agent_app", "--input", "task", "--submit-only")
    done = command("-m", "ralf_agent", "--config", "runtime.toml", "resume", queued["run_id"])
    assert done["state"] == "succeeded" and set(done["result"]) == {"research", "verify"}
    report = command("-m", "ralf_agent", "inspect", queued["run_id"])
    assert report["workflow"]["plan"]["max_concurrency"] == 2
    assert all("execution" not in n for n in report["workflow"]["nodes"].values())
    assert command("-m", "agent_app", "--input", "task")["run_id"] == queued["run_id"]
