"""The installed-style Session entry uses actual processes and durable records."""

import json
import shlex
import sqlite3
import sys
from pathlib import Path

import pytest

from relf_agent import load_catalog
from relf_agent.cli import main
from relf_agent.starter import create_starter

from .test_starter import subprocess_result


def call(project, *args, returncode=0):
    return json.loads(
        subprocess_result(
            [sys.executable, "-m", "session_app", *args], cwd=project, returncode=returncode
        )
    )


def test_session_starter_replays_and_keeps_namespaces_independent(tmp_path):
    project = tmp_path / "app"
    created = create_starter(project, template="sessions")
    assert created.module == "session_app"
    first = call(project, "run", "--input", "red question", "--command-id", "one")
    replay = call(project, "run", "--input", "red question", "--command-id", "one")
    blue = call(
        project, "run", "--input", "blue question", "--command-id", "two", "--namespace", "sales"
    )
    assert first == replay
    assert first["state"] == blue["state"] == "succeeded"
    assert first["result"] == {"echo": "red question", "label": "sessions-v1"}
    assert blue["result"] == {"echo": "blue question", "label": "sessions-v1"}
    reference = json.loads(Path(first["reference"]).read_text())
    assert reference["turn"]["session"]["key"]["namespace"] == "support"
    assert reference["turn"]["turn_seq"] == 1
    assert call(project, "resume", "--reference", first["reference"]) == first
    with sqlite3.connect(project / ".ralf/sessions.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        roots = connection.execute(
            "SELECT session FROM memory_session_items WHERE message_id LIKE '%:turn:result'"
        ).fetchall()
        assert sorted(row[0] for row in roots) == [
            'ralf-session-v1:["sales","customer"]',
            'ralf-session-v1:["support","customer"]',
        ]


def test_starter_resolves_original_profile_and_status_needs_no_config(tmp_path):
    project = tmp_path / "app"
    create_starter(project, template="sessions")
    first = call(project, "run", "--input", "original", "--command-id", "one")
    config = project / "runtime.toml"
    original = config.read_text()
    # Only move the catalog pointer; the previous Profile must remain available.
    config.write_text(original.replace('version = "1"', 'version = "2"', 1))
    assert call(project, "resume", "--reference", first["reference"]) == first
    run_id = json.loads(Path(first["reference"]).read_text())["turn"]["run"]["run_id"]
    config.write_text("invalid config")
    status = call(project, "status", "--run-id", run_id)
    assert status["state"] == "succeeded" and status["result"] == first["result"]
    with sqlite3.connect(project / ".ralf/sessions.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


@pytest.mark.parametrize("corruption", ["scope", "turn", "profile", "missing-profile"])
def test_corrupt_reference_cannot_resume_or_create_a_new_turn(tmp_path, corruption):
    project = tmp_path / "app"
    create_starter(project, template="sessions")
    first = call(project, "run", "--input", "original", "--command-id", "one")
    reference = Path(first["reference"])
    payload = json.loads(reference.read_text())
    if corruption == "scope":
        payload["turn"]["run"]["principal"] = "different-owner"
        payload["turn"]["session"]["key"]["principal"] = "different-owner"
    elif corruption == "turn":
        payload["turn"]["command_id"] = "another-command"
    elif corruption == "profile":
        payload["profile"]["digest"] = "0" * 64
    else:
        payload["profile"]["version"] = "unavailable"
    reference.write_text(json.dumps(payload))
    output = call(project, "resume", "--reference", reference, returncode=2)
    assert output["error"] in {"definition_mismatch", "authorization_denied"}
    with sqlite3.connect(project / ".ralf/sessions.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM agent_session_turns").fetchone()[0] == 1


def test_reference_replay_refuses_conflicting_file_without_overwrite(tmp_path):
    project = tmp_path / "app"
    create_starter(project, template="sessions")
    first = call(project, "run", "--input", "original", "--command-id", "one")
    reference = Path(first["reference"])
    reference.write_text('{"user":"keep this"}')
    output = call(project, "run", "--input", "original", "--command-id", "one", returncode=2)
    assert output["error"] == "definition_mismatch"
    assert reference.read_text() == '{"user":"keep this"}'


def test_cli_printed_first_command_executes_without_editing_it(tmp_path, capsys):
    project = tmp_path / "app"
    assert main(["--format", "text", "init", str(project), "--template", "sessions"]) == 0
    output = capsys.readouterr().out
    command = next(
        line.strip() for line in output.splitlines() if line.strip().startswith("python ")
    )
    arguments = shlex.split(command)
    arguments[0] = sys.executable
    done = json.loads(subprocess_result(arguments, cwd=project))
    assert done["state"] == "succeeded" and done["result"]["echo"] == "hello"


def test_valid_substituted_profile_cannot_replace_missing_original_on_terminal_resume(tmp_path):
    project = tmp_path / "app"
    create_starter(project, template="sessions")
    first = call(project, "run", "--input", "original", "--command-id", "one")
    config = project / "runtime.toml"
    catalog = load_catalog(config)
    catalog.set_default("sessions", "2")
    reference = Path(first["reference"])
    payload = json.loads(reference.read_text())
    payload["profile"] = catalog.default.identity
    reference.write_text(json.dumps(payload))
    text = config.read_text()
    config.write_text(
        text[: text.index("[[profiles]]")].replace('version = "1"', 'version = "2"')
        + text[text.rindex("[[profiles]]") :]
    )
    rejected = call(project, "resume", "--reference", reference, returncode=2)
    assert rejected["error"] == "definition_mismatch"
    with sqlite3.connect(project / ".ralf/sessions.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM agent_session_turns").fetchone()[0] == 1
