import asyncio
import json
import shlex
import sqlite3
import subprocess
import sys

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.demo import create_demo_engine, demo_spec

from .test_cli import cli, subprocess_env


def execute_hint(command):
    arguments = shlex.split(command)
    assert arguments.pop(0) == "relf"
    completed = subprocess.run(
        [sys.executable, "-m", "relf_agent", *arguments],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_inspection_commands_can_be_copied_and_replayed_with_quoted_database_path(tmp_path):
    db = tmp_path / "team's $demo [1].sqlite"
    waiting = json.loads(cli(db, "demo").stdout)
    report = json.loads(cli(db, "inspect", waiting["run_id"]).stdout)
    assert report["state"] == "waiting_approval"
    assert report["budget"]["unit"] == "execution_credits"
    assert report["pending"][0]["tool"] == "apply_change"
    assert report["pending"][0]["arguments"] == {
        "ticket": "INC-001",
        "plan": "restart test cache",
    }
    assert "actions" not in report and "messages" not in report
    assert report["pending"][0]["digest"] == waiting["pending"][0]["digest"]
    approve = report["pending"][0]["approve_command"]
    assert execute_hint(approve) == execute_hint(approve)
    assert execute_hint(report["resume_command"])["state"] == "succeeded"
    with sqlite3.connect(str(db) + ".business.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1


def test_inspect_is_readonly_while_coordinator_is_owned_and_never_imports_factory(tmp_path):
    db = tmp_path / "run.sqlite"
    with create_demo_engine(db) as engine:
        handle = engine.submit(demo_spec(), {"ticket": "INC-001"}, command_id="start")
        waiting = asyncio.run(engine.drive(handle.run_id))
        before = engine.status(handle.run_id)
        before_events = engine.events(handle.run_id)
        report = json.loads(
            cli(db, "--factory", "missing_module:no_factory", "inspect", handle.run_id).stdout
        )
        assert report["pending"][0]["digest"] == waiting.pending[0]["digest"]
        assert "missing_module:no_factory" in shlex.split(report["resume_command"])
        assert engine.status(handle.run_id) == before
        assert engine.events(handle.run_id) == before_events


def test_text_output_exposes_reviewable_parameters_and_executable_approval_hint(tmp_path):
    db = tmp_path / "demo.sqlite"
    output = cli(db, "--format", "text", "demo", "--ticket", "INC-002").stdout
    assert "waiting_approval" in output and "apply_change" in output
    assert "INC-002" in output and "restart test cache" in output
    commands = [
        line.removeprefix("  ") for line in output.splitlines() if line.startswith("  relf ")
    ]
    approve = next(command for command in commands if "approve" in shlex.split(command))
    resume = next(command for command in commands if "resume" in shlex.split(command))
    assert execute_hint(approve)["apply_state"] == "applied"
    assert execute_hint(resume)["state"] == "succeeded"


class UnknownWriteProvider:
    identity = {"kind": "inspect-unknown-fixture", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(tool_calls=(ToolCall("write", {"value": 1}),))


def uncertain_write(arguments, context):
    raise RuntimeError("private-handler-failure")


def test_cancelled_unknown_effect_stays_visible_and_has_no_automatic_write_hint(tmp_path):
    db = tmp_path / "unknown.sqlite"
    tools = ToolRegistry()
    tools.register(
        ToolSpec("write", "An uncertain write", {"type": "object"}, effect="unqueryable_write"),
        uncertain_write,
    )
    with LocalEngine(
        SQLiteStore(db), providers={"default": UnknownWriteProvider()}, tools=tools
    ) as engine:
        handle = engine.submit(
            AgentSpec("unknown", "Run write", ("write",)), {}, command_id="start"
        )
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_reconciliation"
        engine.cancel(handle.run_id, command_id="stop")
    report = json.loads(cli(db, "inspect", handle.run_id).stdout)
    assert report["state"] == "cancelled"
    assert len(report["unresolved_effects"]) == 1
    assert report["unresolved_effects"][0]["tool"] == "write"
    assert report["unresolved_effects"][0]["effect_key"]
    assert report["resume_command"] is None and report["pending"] == []
    text = cli(db, "--format", "text", "inspect", handle.run_id).stdout
    assert "reconcile" in text and "private-handler-failure" not in text


def test_inspect_missing_database_never_creates_files(tmp_path):
    db = tmp_path / "missing" / "runs.sqlite"
    result = cli(db, "inspect", "missing", check=False)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "not_found"
    assert not db.parent.exists()


def test_init_creates_a_project_without_creating_an_execution_database(tmp_path):
    db = tmp_path / "unused.sqlite"
    project = tmp_path / "my-agent"
    result = json.loads(cli(db, "init", str(project)).stdout)
    assert result["factory"] == "agent_app.runtime:create_engine"
    assert (project / "agent_app" / "runtime.py").is_file()
    assert not db.exists()
    original = (project / "agent_app" / "runtime.py").read_bytes()
    denied = cli(db, "init", str(project), check=False)
    assert denied.returncode == 2
    assert json.loads(denied.stderr)["code"] == "validation_error"
    assert (project / "agent_app" / "runtime.py").read_bytes() == original


def test_text_init_outputs_a_usable_start_command(tmp_path):
    project = tmp_path / "new agent"
    result = cli(tmp_path / "unused.sqlite", "--format", "text", "init", str(project))
    commands = [line.strip() for line in result.stdout.splitlines() if line.startswith("  ")]
    assert ["cd", str(project)] in [shlex.split(command) for command in commands]
    assert ["python", "-m", "agent_app", "--ticket", "INC-001"] in [
        shlex.split(command) for command in commands
    ]
