import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent import (
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    InputMap,
    Literal,
    RuntimeBuilder,
    RuntimeProfile,
    ValueRef,
    load_spec,
)
from relf_agent.cli_views import inspection, render_inspection
from relf_agent.errors import ValidationError
from relf_agent.starter import create_starter


def test_json_graph_loader_uses_same_public_definition(tmp_path):
    expected = GraphWorkflowSpec(
        "flow",
        [
            GraphNode(
                "a",
                transform="identity",
                input=InputMap({"task": ValueRef(), "constant": Literal(3)}),
            )
        ],
        output=ValueRef("a"),
    )
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(expected.to_dict()))
    assert load_spec(path).to_dict() == expected.to_dict()


def test_toml_graph_loader_and_configured_runtime(tmp_path):
    path = tmp_path / "graph.toml"
    path.write_text("""kind = "graph"
name = "flow"
[output]
kind = "ref"
source = "answer"
[[nodes]]
id = "answer"
depends_on = ["prepare"]
[nodes.agent]
name = "answer"
instructions = "Answer"
[nodes.input]
kind = "ref"
source = "prepare"
[[nodes]]
id = "prepare"
transform = "identity"
""")
    profile = RuntimeProfile(
        "graph",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "workflow_compiler": {"adapter": "static"},
            "workflow_interpreter": {"adapter": "static"},
            "workflow_transforms": {"adapter": "identity"},
        },
    )
    with RuntimeBuilder().build(profile, tmp_path / "runs.db") as engine:
        handle = engine.submit(load_spec(path), "question", command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {
            "echo": "question",
            "label": "offline",
        }


def test_explicit_transform_factory_needs_no_engine_subclass(tmp_path):
    class Add:
        identity = {"kind": "add", "version": "1"}

        def transform(self, input, config):
            return input + config["amount"]

    registry = ComponentRegistry()
    registry.register("workflow_transforms", "numbers", lambda config, context: {"add": Add()})
    profile = RuntimeProfile(
        "custom",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"workflow_transforms": {"adapter": "numbers"}},
    )
    spec = GraphWorkflowSpec(
        "flow", [GraphNode("a", transform="add", config={"amount": 2})], output=ValueRef("a")
    )
    with RuntimeBuilder(registry).build(profile, tmp_path / "runs.db") as engine:
        handle = engine.submit(spec, 10, command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).result == 12


@pytest.mark.parametrize(
    "field,value",
    [
        ("unexpected", True),
        ("nodes", None),
        ("nodes", []),
        ("output", {"kind": "code", "value": "print(1)"}),
    ],
)
def test_invalid_graph_declarations_are_typed(tmp_path, field, value):
    payload = GraphWorkflowSpec("flow", [GraphNode("a", transform="identity")]).to_dict()
    payload[field] = value
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValidationError):
        load_spec(path)


def test_read_only_inspect_shows_node_states_and_plan(tmp_path):
    from .test_engine_workflow import runtime

    path = tmp_path / "runs.db"
    with runtime(path) as engine:
        handle = engine.submit(
            GraphWorkflowSpec("flow", [GraphNode("a", transform="identity")]),
            "task",
            command_id="s",
        )
        report = inspection(
            engine.store.run(handle.run_id), engine.store.budget(handle.run_id), path
        )
        assert report["workflow"]["nodes"]["a"]["state"] == "pending"
        assert report["workflow"]["plan"]["schema_version"] == 1
        assert report["needs_factory"] is True  # No models does not imply the demo runtime.
        assert "Node: a (pending)" in render_inspection(report)


@pytest.mark.parametrize(
    "input,selected,skipped", [("urgent", "urgent", "routine"), ("hello", "routine", "urgent")]
)
def test_graph_starter_and_cli_resume_across_processes(tmp_path, input, selected, skipped):
    project = create_starter(tmp_path / "app", template="graph")
    directory = Path(project.directory)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }

    def command(*args):
        result = subprocess.run(
            [sys.executable, *args],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    queued = command("-m", "agent_app", "--input", input, "--submit-only")
    run_id = queued["run_id"]
    done = command("-m", "relf_agent", "--config", "runtime.toml", "resume", run_id)
    assert done["state"] == "succeeded"
    assert (
        done["result"][selected] == {"echo": input, "label": "graph-demo"}
        and done["result"][skipped] is None
    )
    report = command("-m", "relf_agent", "inspect", run_id)
    assert report["workflow"]["nodes"][skipped]["state"] == "skipped"
    assert report["workflow"]["nodes"][selected]["state"] == "completed"
    replay = command("-m", "agent_app", "--input", input)
    assert replay["run_id"] == run_id and replay["state"] == "succeeded"
