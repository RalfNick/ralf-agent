import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent import AgentSpec, __version__

from .cli_runtime import create_engine

ROOT = Path(__file__).resolve().parents[1]


def cli(db, *args, check=True):
    env = subprocess_env()
    result = subprocess.run(
        [sys.executable, "-m", "relf_agent", "--db", str(db), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def subprocess_env():
    # Do not copy credentials into subprocesses or pytest's failure-local diagnostics.
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
    }


def test_cli_demo_requires_explicit_approval_and_resumes_across_processes(tmp_path):
    db = tmp_path / "demo.db"
    waiting = json.loads(cli(db, "demo", "--ticket", "INC-1").stdout)
    assert waiting["state"] == "waiting_approval"
    pending = waiting["pending"][0]
    receipt = json.loads(
        cli(
            db,
            "approve",
            waiting["run_id"],
            pending["action_id"],
            "--digest",
            pending["digest"],
            "--command-id",
            "approve-1",
        ).stdout
    )
    assert receipt["apply_state"] == "applied"
    done = json.loads(cli(db, "resume", waiting["run_id"]).stdout)
    assert done["state"] == "succeeded"
    assert done["result"]["verified"] is True
    events = json.loads(cli(db, "events", waiting["run_id"], "--after", "0").stdout)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    replay = json.loads(cli(db, "demo", "--ticket", "INC-1").stdout)
    assert replay["run_id"] == waiting["run_id"]
    assert replay["state"] == "succeeded"


def test_cli_reports_typed_errors_without_a_traceback(tmp_path):
    result = cli(tmp_path / "demo.db", "status", "missing", check=False)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "not_found"
    assert "Traceback" not in result.stderr


def test_cli_custom_factory_approves_resumes_and_cancels_sdk_runs(tmp_path):
    db = tmp_path / "custom.db"
    with create_engine(db) as engine:
        run = engine.submit(
            AgentSpec("custom", "Run the custom test tool", ("custom_change",)),
            "update",
            command_id="custom-submit",
        )
        waiting = asyncio.run(engine.drive(run.run_id))
        pending = waiting.pending[0]
        cancel_run = engine.submit(
            AgentSpec("cancel", "Answer directly"), "stop", command_id="stop"
        )
    factory = ("--factory", "tests.cli_runtime:create_engine")
    receipt = json.loads(
        cli(
            db,
            *factory,
            "approve",
            run.run_id,
            pending["action_id"],
            "--digest",
            pending["digest"],
            "--command-id",
            "approve-custom",
        ).stdout
    )
    assert receipt["apply_state"] == "applied"
    done = json.loads(cli(db, *factory, "resume", run.run_id).stdout)
    assert done["state"] == "succeeded"
    assert done["result"] == {"custom": True}
    cancelled = json.loads(
        cli(db, *factory, "cancel", cancel_run.run_id, "--command-id", "cancel-custom").stdout
    )
    assert cancelled["apply_state"] == "applied"
    assert json.loads(cli(db, "status", cancel_run.run_id).stdout)["state"] == "cancelled"


@pytest.mark.parametrize(
    "factory",
    [
        "no-colon",
        "not_a_ralf_test_module:create_engine",
        "tests.cli_runtime:missing",
        "tests.cli_runtime:not_callable",
        "tests.cli_runtime:broken_factory",
        "tests.cli_runtime:wrong_factory",
    ],
)
def test_cli_factory_load_errors_are_typed_and_redacted(tmp_path, factory):
    result = cli(tmp_path / "run.db", "--factory", factory, "resume", "unused", check=False)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "validation_error"
    assert "Traceback" not in result.stderr
    assert "fixture-private-configuration" not in result.stderr


def test_default_cli_resume_custom_run_explains_factory_requirement(tmp_path):
    db = tmp_path / "custom.db"
    with create_engine(db) as engine:
        run = engine.submit(AgentSpec("custom", "Answer directly"), "hello", command_id="custom")
    result = cli(db, "resume", run.run_id, check=False)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "definition_mismatch"
    assert "--factory" in json.loads(result.stderr)["message"]


def test_cli_event_page_size_and_version(tmp_path):
    db = tmp_path / "demo.db"
    run = json.loads(cli(db, "demo").stdout)
    page = json.loads(cli(db, "events", run["run_id"], "--limit", "2").stdout)
    assert [event["seq"] for event in page] == [1, 2]
    next_page = json.loads(cli(db, "events", run["run_id"], "--after", "2", "--limit", "2").stdout)
    assert [event["seq"] for event in next_page] == [3, 4]
    assert __version__ in cli(db, "--version").stdout
