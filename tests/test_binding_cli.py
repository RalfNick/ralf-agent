"""Regression for review P2: diagnostics consumes fixed per-step manifests."""

import asyncio
import json

from relf_agent import AgentSpec, ModelResponse, ToolRegistry, ToolSpec, WorkflowSpec
from relf_agent.cli import main
from relf_agent.cli_views import diagnostics_inspection
from relf_agent.types import ToolCall

from .helpers import ScriptedProvider
from .test_binding_assembly import declarations
from .test_binding_execution import api, bound_catalog, choice, definition, engine


def test_cli_inspect_and_text_status_support_bound_run(tmp_path, capsys):
    path = tmp_path / "run.sqlite"
    with engine(path, bound_catalog()) as runtime:
        handle = runtime.submit(definition(), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
    assert main(["--db", str(path), "inspect", handle.run_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["release"]["kernel"] == "local-bindings-1"
    assert report["agent_bindings"]["agent"]["providers"]["default"]["label"] == "host"
    assert main(["--db", str(path), "--format", "text", "status", handle.run_id]) == 0
    output = capsys.readouterr().out
    assert "succeeded" in output and "Agent binding: agent" in output


def test_inspection_reads_approval_and_unknown_effect_from_action_step(tmp_path):
    t, d, _ = api()
    catalog = bound_catalog()
    catalog.register(
        "provider",
        "writer",
        "1",
        ScriptedProvider([ModelResponse(tool_calls=(ToolCall("write", {}),))]),
    )
    tools = ToolRegistry()

    def unknown(arguments, context):
        raise ConnectionError("fixture unknown effect")

    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, effect="queryable_write", requires_approval=True
        ),
        unknown,
    )
    sequence = d.BoundDefinition(
        WorkflowSpec("flow", [AgentSpec("a", "Act", tools=("write",)), AgentSpec("b", "Answer")]),
        {"sequence/steps/0": t.AgentBindingDescriptor(provider=choice("writer"))},
    )
    with engine(tmp_path / "approval.sqlite", catalog, tools=tools) as runtime:
        handle = runtime.submit(sequence, "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_approval"
        report = diagnostics_inspection(runtime.diagnostics(handle.run_id), "run.sqlite")
        assert report["pending"][0]["effect"] == "queryable_write"
        pending = report["pending"][0]
        runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
        )
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_reconciliation"
        report = diagnostics_inspection(runtime.diagnostics(handle.run_id), "run.sqlite")
        assert report["unresolved_effects"][0]["effect"] == "queryable_write"
        assert (
            report["agent_bindings"]["sequence/steps/1"]["providers"]["default"]["label"] == "host"
        )


def test_cli_text_run_and_resume_use_bound_profile(tmp_path, capsys):
    profile = tmp_path / "runtime.json"
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
    spec = tmp_path / "agent.json"
    spec.write_text(json.dumps(definition(provider=choice("model")).to_dict()))
    path = tmp_path / "run.sqlite"
    common = ["--config", str(profile), "--db", str(path), "--format", "text"]
    assert main([*common, "run", "--spec", str(spec), "--input", "q", "--command-id", "s"]) == 0
    output = capsys.readouterr().out
    assert "State: succeeded" in output
    run_id = next(
        line.removeprefix("Run: ") for line in output.splitlines() if line.startswith("Run: ")
    )
    assert main([*common, "resume", run_id]) == 0
    assert "State: succeeded" in capsys.readouterr().out
