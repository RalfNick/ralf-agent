"""Editable installed-SDK Facts applications in all configured modes."""

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
        module = importlib.import_module("relf_agent.facts_adapter_contract_starter")
    except ModuleNotFoundError:
        pytest.fail("The editable Facts application is missing")
    project = tmp_path / "application"
    project.mkdir()
    for name, content in module.facts_contract_files().items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return project


def sdk_env():
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }


def invoke(project, *arguments):
    done = subprocess.run(
        [sys.executable, "-m", "agent_app", *arguments],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr + done.stdout
    return json.loads(done.stdout)


@pytest.mark.parametrize("format", ["json", "toml"])
@pytest.mark.parametrize("mode", ["core", "pipeline", "managed"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_copied_application_reads_actual_facts_and_retains_original_execution(
    tmp_path, format, mode, asynchronous, owned
):
    project = application(tmp_path)
    assert invoke(project, "seed") == {"seeded": 4}
    assert invoke(project, "seed") == {"seeded": 0}
    flags = ["--async"] if asynchronous else []
    if not owned:
        flags.append("--borrowed")
    actual = invoke(
        project,
        "run",
        "--mode",
        mode,
        "--format",
        format,
        "--command-id",
        f"facts-{mode}-{format}-{asynchronous}-{owned}",
        *flags,
    )
    assert actual["state"] == "succeeded", actual
    assert actual["result"]["facts"] == [
        {"key": "seed", "value": "original seeded fact", "version": 1, "expires_at": None}
    ]
    assert actual["audit"]["model_calls"] == 1
    assert actual["audit"]["close_calls"] == int(owned)
    assert actual["adapter_module"] == "agent_app.adapter" and actual["model_quality"] is None
    assert actual["execution_authority"] == "local"
    if mode == "pipeline":
        assert actual["memory"]["status"] == "completed"
        assert actual["audit"]["write_count"] == 2
    elif mode == "managed":
        assert actual["memory"][0]["status"] == "completed"
        assert actual["audit"]["write_count"] == 1
    else:
        assert actual["memory"] is None and actual["audit"]["write_count"] == 0


def test_generated_observation_factory_is_lazy_and_run_never_seeds(tmp_path):
    project = application(tmp_path)
    program = """import json
from agent_app.runtime import create_engine, source_path
engine = create_engine('.ralf/runs.sqlite')
before = source_path().exists()
engine.close()
print(json.dumps({'before': before, 'after': source_path().exists()}))
"""
    done = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"before": False, "after": False}
    assert (
        invoke(project, "run", "--mode", "core", "--command-id", "unseeded-core")["result"]["facts"]
        == []
    )


def test_mixed_modes_share_one_actual_dataset_with_distinct_original_commands(tmp_path):
    project = application(tmp_path)
    assert invoke(project, "seed") == {"seeded": 4}
    observed = []
    for index, mode in enumerate(("core", "pipeline", "managed", "core", "managed", "pipeline")):
        flags = ["--async", "--borrowed"] if index % 2 else []
        actual = invoke(
            project,
            "run",
            "--mode",
            mode,
            "--format",
            "json" if index % 2 else "toml",
            "--command-id",
            f"mixed-facts-{index}-{mode}",
            *flags,
        )
        assert actual["state"] == "succeeded", actual
        assert actual["result"]["facts"][0]["value"] == "original seeded fact"
        observed.append(actual)
    assert len({item["run_id"] for item in observed}) == 6
    with sqlite3.connect(project / ".ralf/facts.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM facts_resource").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM facts WHERE namespace='reader'").fetchone()[0]
            == 4
        )
    assert invoke(project, "seed") == {"seeded": 0}


@pytest.mark.parametrize("profile,count", [("core", 10), ("managed", 16)])
def test_copied_fixture_checks_public_facts_catalog(tmp_path, profile, count):
    actual = invoke(application(tmp_path), "check", "--profile", profile)
    assert actual["status"] == "passed", actual
    assert actual["role"] == "facts-store" and actual["profile"] == profile
    assert len(actual["cases"]) == count and all(
        item["status"] == "passed" for item in actual["cases"]
    )
