"""Installed CLI configuration accepts the same composite declarations as the SDK."""

import json

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    TeamSpec,
)
from relf_agent.cli import main

from .test_binding_assembly import declarations
from .test_binding_execution import choice


@pytest.mark.parametrize("extension", ["json", "toml"])
@pytest.mark.parametrize("kind", ["graph", "team", "dynamic"])
def test_composite_cli_config_run_resume_and_inspection(tmp_path, capsys, extension, kind):
    profile = tmp_path / ("runtime." + extension)
    if extension == "json":
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [
                        {
                            "name": "app",
                            "version": "1",
                            "providers": {"default": {"adapter": "offline-echo"}},
                            "binding_components": declarations(),
                        }
                    ],
                }
            )
        )
    else:
        profile.write_text("""schema_version = 2
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[[profiles.binding_components]]
role = "provider"
component_id = "model"
version = "1"
[profiles.binding_components.component]
adapter = "offline-echo"
[profiles.binding_components.component.config]
label = "selected"
""")
    agent = AgentSpec("worker", "Answer")
    spec = {
        "graph": GraphWorkflowSpec("graph", [GraphNode("worker", agent=agent)]),
        "team": TeamSpec("team", {"worker": agent}),
        "dynamic": DynamicWorkflowSpec("dynamic", {"worker": agent}, plan_mode="dag"),
    }[kind]
    path = f"{kind}/{'nodes' if kind == 'graph' else 'members'}/worker"
    wrapped = BoundDefinition(spec, {path: AgentBindingDescriptor(provider=choice("model"))})
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(wrapped.to_dict()))
    common = ["--config", str(profile), "--db", str(tmp_path / "run.sqlite")]
    assert main([*common, "run", "--spec", str(source), "--input", "q", "--command-id", "s"]) == 0
    result = json.loads(capsys.readouterr().out)
    output = result["result"]["worker"] if kind == "graph" else result["result"]
    assert result["state"] == "succeeded" and output["label"] == "selected"
    run_id = result["run_id"]
    assert main([*common, "resume", run_id]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert main([*common, "inspect", run_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["release"]["kernel"] == "local-bindings-2"
    assert report["agent_bindings"][path]["providers"]["default"]["label"] == "selected"
