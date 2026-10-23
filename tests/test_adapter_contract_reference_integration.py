"""Editable external application and real JSON/TOML consumer assembly."""

import importlib
import json
import os
import subprocess
import sys

import pytest


def application(tmp_path):
    try:
        module = importlib.import_module("relf_agent.adapter_contract_starter")
    except ModuleNotFoundError:
        pytest.fail("The independent external adapter application is missing")
    files = module.adapter_contract_files()
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
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("format", ["json", "toml"])
@pytest.mark.parametrize("kind", ["agent", "rag", "plan", "team"])
def test_editable_external_adapter_uses_final_references_for_all_consumers(tmp_path, format, kind):
    project = application(tmp_path)
    seeded = invoke(project, "seed")
    assert seeded["seeded"] == 1
    flags = ["--async", "--borrowed"] if format == "json" else []
    actual = invoke(project, "run", "--kind", kind, "--format", format, *flags)
    assert actual["state"] == "succeeded", actual
    expected = 2 if kind in {"plan", "team"} else 1
    assert actual["references_disclosed"] == expected
    assert actual["audit"]["model_calls"] == expected
    assert actual["audit"]["retrieve_calls"] == expected
    assert actual["audit"]["close_calls"] == (0 if flags else 1)
    assert actual["adapter_module"] == "agent_app.adapter"
    assert actual["model_quality"] is None and actual["semantic_quality"] is None
    copied = (project / "agent_app/adapter.py").read_text()
    assert "class ReferenceSQLiteRetriever:" in copied
    assert "class ReferenceKnowledgeSource:" in copied
    assert "LexicalRetriever(" not in copied and "SQLiteKnowledgeStore(" not in copied
    assert "from relf_agent.adapter_contract_reference" not in copied


def test_external_application_source_seed_is_explicit_and_never_restores_deleted_source(tmp_path):
    project = application(tmp_path)
    empty = invoke(project, "run", "--kind", "agent")
    assert empty["state"] == "succeeded" and empty["references_disclosed"] == 0
    assert empty["result"]["sources"] == []


def test_external_editable_fixture_runs_public_suite_without_repository_tests(tmp_path):
    project = application(tmp_path)
    report = invoke(project, "check")
    assert report["status"] == "passed", report
    assert len(report["cases"]) == 12
    assert all(case["status"] == "passed" for case in report["cases"])
    assert report["model_quality"] is None and report["semantic_quality"] is None


def test_external_check_returns_nonzero_for_an_actual_invalid_adapter(tmp_path):
    project = application(tmp_path)
    program = """
import sys
import agent_app.__main__ as app
from agent_app.adapter import OfflineKnowledgeFixture
class InvalidFixture(OfflineKnowledgeFixture):
    def prepare(self, case_id, workspace):
        session = super().prepare(case_id, workspace)
        session.retriever._fault = "invalid-validation-return"
        return session
app.offline_knowledge_fixture = InvalidFixture
sys.argv = ["agent_app", "check"]
raise SystemExit(app.main())
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "failed"
    assert any(case["status"] == "failed" for case in report["cases"])


def test_external_check_retries_same_original_owner_cleanup_on_the_same_loop(tmp_path):
    project = application(tmp_path)
    program = """
import asyncio
import json
import sys
from pathlib import Path
import agent_app.__main__ as app
from agent_app.adapter import OfflineKnowledgeFixture
observed = {"closes": 0, "closed": False, "same_loop": False, "prepared": 0}
class FailOnceFixture(OfflineKnowledgeFixture):
    def prepare(self, case_id, workspace):
        observed["prepared"] += 1
        session = super().prepare(case_id, workspace)
        source = session.resources[0].resource
        original_close = source.close
        creation_loop = asyncio.get_running_loop()
        def close():
            observed["closes"] += 1
            observed["same_loop"] = asyncio.get_running_loop() is creation_loop
            if observed["closes"] == 1:
                raise RuntimeError("private cleanup failure detail")
            original_close()
            observed["closed"] = source._closed
        source.close = close
        return session
app.offline_knowledge_fixture = FailOnceFixture
sys.argv = ["agent_app", "check"]
try:
    code = app.main()
except Exception as exc:
    observed["uncaught"] = type(exc).__name__
    code = 1
finally:
    Path("cleanup-observation.json").write_text(json.dumps(observed))
raise SystemExit(code)
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads((project / "cleanup-observation.json").read_text())
    assert observed["closes"] == 2 and observed["closed"] and observed["same_loop"], observed
    assert observed["prepared"] == 1 and "uncaught" not in observed
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "failed"
    assert "private cleanup failure detail" not in completed.stdout + completed.stderr


def test_external_profiled_factory_does_not_create_an_unowned_source_for_observation(tmp_path):
    project = application(tmp_path)
    program = """
import json
from pathlib import Path
from agent_app.runtime import create_engine, source_path
engine = create_engine(".ralf/runs.sqlite")
before = source_path().exists()
engine.close()
print(json.dumps({"created_before_activation": before, "exists_after_close": source_path().exists()}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    assert observed == {"created_before_activation": False, "exists_after_close": False}


def test_external_profiled_factory_closes_the_actual_source_after_business_activation(tmp_path):
    project = application(tmp_path)
    invoke(project, "seed")
    program = """
import asyncio
import json
import sqlite3
from relf_agent import AgentSpec
from agent_app.runtime import create_engine, source_path
with sqlite3.connect(source_path()) as connection:
    before = dict(connection.execute("SELECT kind,count FROM audit"))
with create_engine(".ralf/runs.sqlite") as engine:
    handle = engine.submit(AgentSpec("factory-reader", "Use original references"), "cache", command_id="factory")
    result = asyncio.run(engine.drive(handle.run_id))
with sqlite3.connect(source_path()) as connection:
    after = dict(connection.execute("SELECT kind,count FROM audit"))
print(json.dumps({"state": result.state, "answer": result.result["answer"],
                  "closed": after.get("close", 0) - before.get("close", 0)}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    assert observed == {
        "state": "succeeded",
        "answer": "cache timeout inspect connection pool",
        "closed": 1,
    }


@pytest.mark.parametrize("phase", ["registration", "initial-audit"])
def test_external_application_partial_setup_keeps_no_unowned_physical_source(tmp_path, phase):
    project = application(tmp_path)
    program = """
import asyncio
import json
import os
import sys
import agent_app.runtime as runtime
from agent_app.adapter import ReferenceKnowledgeSource
from relf_agent.errors import ValidationError
created = []
original_init = ReferenceKnowledgeSource.__init__
def initialize(source, path):
    original_init(source, path)
    created.append((source, source._file_descriptor))
ReferenceKnowledgeSource.__init__ = initialize
phase = sys.argv[1]
if phase == "initial-audit":
    def audit(source):
        raise ValidationError("private initial audit failure")
    ReferenceKnowledgeSource.audit = audit
try:
    if phase == "registration":
        runtime.components(asynchronous="invalid")
    else:
        asyncio.run(runtime.run("agent"))
except ValidationError:
    pass
observations = []
for source, descriptor in created:
    try:
        os.fstat(descriptor)
        fd_live = True
    except OSError:
        fd_live = False
    observations.append({"closed": source._closed, "fd_live": fd_live})
    source.close()
print(json.dumps(observations))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, phase],
        cwd=project,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [{"closed": True, "fd_live": False}]
