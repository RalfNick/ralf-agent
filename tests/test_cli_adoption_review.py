import json
import sqlite3
import subprocess
import sys

import pytest

from ralf_agent import AgentSpec, LocalEngine, Scope, SQLiteStore, ToolRegistry

from .helpers import ScriptedProvider
from .test_cli import cli, subprocess_env
from .test_cli_inspect import execute_hint


@pytest.mark.parametrize("destination", [".", "../existing-empty", "absolute"])
def test_init_cannot_replace_the_current_shell_directory(tmp_path, destination):
    project = tmp_path / "existing-empty"
    project.mkdir()
    original = project.stat()
    requested = str(project) if destination == "absolute" else destination
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'cd "$1"\n'
            '"$2" -m ralf_agent init "$3"\n'
            "init_status=$?\n"
            'if [ "$init_status" -eq 0 ]; then\n'
            '    "$2" -m agent_app --ticket INIT-CWD\n'
            "else\n"
            '    exit "$init_status"\n'
            "fi\n",
            "starter-review",
            str(project),
            sys.executable,
            requested,
        ],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stderr)["code"] == "validation_error"
    assert result.stdout == ""
    current = project.stat()
    assert (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)
    assert list(project.iterdir()) == []


def test_inspect_refuses_another_scope_without_acquiring_or_changing_execution(tmp_path):
    db = tmp_path / "scoped.sqlite"
    with LocalEngine(
        SQLiteStore(db),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
        scope=Scope("private-workspace", "private-owner"),
    ) as engine:
        handle = engine.submit(AgentSpec("a", "x"), "x", command_id="private")
        snapshot, events = engine.status(handle.run_id), engine.events(handle.run_id)
        rejected = cli(db, "inspect", handle.run_id, check=False)
        assert rejected.returncode == 2
        assert json.loads(rejected.stderr)["code"] == "authorization_denied"
        assert rejected.stdout == ""
        assert engine.status(handle.run_id) == snapshot
        assert engine.events(handle.run_id) == events


def test_copied_reject_hint_is_idempotent_and_cannot_be_reversed_by_old_approval(tmp_path):
    db = tmp_path / "reject.sqlite"
    waiting = json.loads(cli(db, "demo", "--ticket", "INC-REJECT").stdout)
    report = json.loads(cli(db, "inspect", waiting["run_id"]).stdout)
    pending = report["pending"][0]
    rejected = execute_hint(pending["reject_command"])
    assert rejected["apply_state"] == "applied"
    assert execute_hint(pending["reject_command"]) == rejected
    closed = json.loads(cli(db, "status", waiting["run_id"]).stdout)
    assert closed["state"] == "failed"
    assert closed["error"] == {"code": "approval_rejected"}
    assert closed["pending"] == []
    assert closed["result"] is None
    stale_approval = execute_hint(pending["approve_command"])
    assert stale_approval["apply_state"] == "rejected"
    assert stale_approval["outcome"]["reason"] == "target_closed"
    assert json.loads(cli(db, "status", waiting["run_id"]).stdout) == closed
    with sqlite3.connect(str(db) + ".business.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 0
