"""Copied editable Session adapter and SDK/JSON/TOML application assembly."""

import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def application(tmp_path):
    try:
        module = importlib.import_module("ralf_agent.session_adapter_contract_starter")
    except ModuleNotFoundError:
        pytest.fail("The editable Session adapter starter is missing")
    files = module.session_contract_files()
    project = tmp_path / "application"
    project.mkdir()
    for name, content in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return project


def invoke(project, *arguments):
    completed = subprocess.run(
        [sys.executable, "-m", "agent_app", *arguments],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_starter_copies_full_independent_implementation_without_importing_reference(tmp_path):
    project = application(tmp_path)
    copied = (project / "agent_app/adapter.py").read_text()
    assert "class ReferenceSessionSource:" in copied
    assert "class ReferenceSQLiteSessionStore:" in copied
    assert "class ReferenceSQLiteReceiptSessionStore" in copied
    assert "sqlite3.connect(" in copied
    assert "SQLiteMemory" not in copied
    assert "ralf_agent.session_adapter_contract_reference" not in copied
    assert "from ralf_agent.session_adapter_contract import" in copied


@pytest.mark.parametrize("format", ["json", "toml"])
@pytest.mark.parametrize("mode", ["core", "receipts"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_starter_uses_original_local_consumer_with_declared_ownership(
    tmp_path, format, mode, asynchronous, owned
):
    project = application(tmp_path)
    assert invoke(project, "seed") == {"seeded": 2}
    assert invoke(project, "seed") == {"seeded": 0}
    flags = ["--async"] if asynchronous else []
    if not owned:
        flags.append("--borrowed")
    actual = invoke(project, "run", "--mode", mode, "--format", format, *flags)
    assert actual["state"] == "succeeded", actual
    assert actual["result"]["history"] == [{"role": "user", "content": "original seeded history"}]
    assert actual["audit"]["model_calls"] == actual["audit"]["save_count"] == 1
    assert actual["audit"]["close_calls"] == int(owned)
    assert actual["adapter_module"] == "agent_app.adapter"
    assert actual["model_quality"] is None
    assert (actual["session_ref"] is not None) == (mode == "receipts")


def test_starter_profiled_observation_factory_leaves_source_unopened(tmp_path):
    project = application(tmp_path)
    program = """
import json
from agent_app.runtime import create_engine, source_path
engine = create_engine('.ralf/runs.sqlite')
before = source_path().exists()
engine.close()
print(json.dumps({'before': before, 'after': source_path().exists()}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"before": False, "after": False}


def test_starter_never_implicitly_seeds_during_run(tmp_path):
    actual = invoke(application(tmp_path), "run")
    assert actual["state"] == "succeeded"
    assert actual["result"]["history"] == []


@pytest.mark.parametrize("first_mode", ["core", "receipts"])
def test_same_application_alternates_core_and_managed_addresses_with_original_ownership(
    tmp_path, first_mode
):
    project = application(tmp_path)
    assert invoke(project, "seed") == {"seeded": 2}
    other_mode = "receipts" if first_mode == "core" else "core"
    modes = [first_mode, other_mode, first_mode, other_mode]
    formats = ["json", "toml", "toml", "json"]
    flags = [[], [], ["--async", "--borrowed"], ["--async"]]
    observed = []
    for index, mode in enumerate(modes):
        actual = invoke(
            project,
            "run",
            "--mode",
            mode,
            "--format",
            formats[index],
            "--command-id",
            f"alternate-{first_mode}-{index}",
            *flags[index],
        )
        assert actual["state"] == "succeeded", actual
        assert actual["result"]["history"][0] == {
            "role": "user",
            "content": "original seeded history",
        }
        assert actual["audit"]["model_calls"] == actual["audit"]["save_count"] == 1
        observed.append(actual)
    assert len({actual["run_id"] for actual in observed}) == 4
    with sqlite3.connect(project / ".ralf/runs.sqlite") as connection:
        runs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM runs")]
    assert {run["session_id"] for run in runs if "session_turn" not in run} == {"example-core"}
    assert {
        run["session_turn"]["session"]["key"]["session_id"] for run in runs if "session_turn" in run
    } == {"example"}
    with sqlite3.connect(project / ".ralf/sessions.sqlite") as connection:
        streams = dict(connection.execute("SELECT address,revision FROM session_streams"))
        assert streams == {"example-core": 3, "example": 3}
        assert connection.execute("SELECT count(*) FROM session_resource").fetchone()[0] == 1
    assert invoke(project, "seed") == {"seeded": 0}


@pytest.mark.parametrize("profile,count", [("core", 10), ("receipts", 14)])
def test_copied_fixture_checks_selected_public_catalog_without_repository_imports(
    tmp_path, profile, count
):
    actual = invoke(application(tmp_path), "check", "--profile", profile)
    assert actual["status"] == "passed", actual
    assert actual["role"] == "session-store" and actual["profile"] == profile
    assert len(actual["cases"]) == count
    assert all(case["status"] == "passed" for case in actual["cases"])


def sdk_env():
    # Source regression exposes the SDK only, never repository tests or secrets.
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
