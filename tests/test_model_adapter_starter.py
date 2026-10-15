"""Editable business app exercised through actual subprocess consumers."""

import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_generated_application_modules():
    def clear():
        for name in list(sys.modules):
            if name == "agent_app" or name.startswith("agent_app."):
                sys.modules.pop(name)

    clear()
    try:
        yield
    finally:
        clear()


def application(tmp_path):
    try:
        module = importlib.import_module("ralf_agent.model_adapter_contract_starter")
    except ModuleNotFoundError:
        pytest.fail("Independent editable ModelProvider application is missing")
    project = tmp_path / "application"
    project.mkdir()
    for name, content in module.model_contract_files().items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return project


def sdk_env():
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }


def invoke(project, *args):
    result = subprocess.run(
        [sys.executable, "-m", "agent_app", *args],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def test_same_business_data_has_four_modes_and_provider_only_replacements(tmp_path):
    project = application(tmp_path)
    assert invoke(project, "seed") == {"seeded": 1}
    assert invoke(project, "seed") == {"seeded": 0}
    runs = []
    for index, kind in enumerate(("agent", "rag", "plan", "team")):
        format = ("sdk", "json", "toml", "json")[index]
        flags = ["--async", "--borrowed"] if index % 2 else []
        actual = invoke(
            project,
            "run",
            "--kind",
            kind,
            "--format",
            format,
            "--provider",
            "alternate" if index % 2 else "primary",
            "--command-id",
            kind + "-first",
            *flags,
        )
        assert actual["state"] == "succeeded", actual
        assert (
            actual["result"]["recommendation"]
            == "Inspect connection pool before changing cache timeout."
        )
        assert actual["tool_receipts"] >= (2 if kind in {"plan", "team"} else 1)
        assert actual["references_disclosed"] >= int(kind != "agent")
        assert actual["member_receipts"] >= (2 if kind in {"plan", "team"} else 0)
        if kind in {"plan", "team"}:
            assert len(actual["result"]["members"]) == 1
            assert (
                actual["result"]["members"][0]["recommendation"]
                == actual["result"]["recommendation"]
            )
            assert actual["parent_verdicts"][0]["status"] == "accept"
        assert actual["audit"]["close_calls"] == int(index % 2 == 0)
        assert actual["model_quality"] is actual["semantic_quality"] is None
        assert actual["adapter_module"] == "agent_app.adapter"
        runs.append(actual["run_id"])
    assert len(set(runs)) == 4
    with sqlite3.connect(project / ".ralf/business.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM business_documents").fetchone()[0] == 1
    copied = (project / "agent_app/adapter.py").read_text()
    assert "ralf_agent.model_adapter_contract_reference" not in copied


def test_observation_factory_never_opens_or_seeds_business_source(tmp_path):
    project = application(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent_app.runtime import create_engine, source_path; engine=create_engine('.ralf/runs.sqlite'); assert not source_path().exists(); engine.close(); assert not source_path().exists()",
        ],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "agent_app", "run"],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    actual = json.loads(result.stdout)
    assert actual["state"] == "failed"
    with sqlite3.connect(project / ".ralf/business.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM business_documents").fetchone()[0] == 0


def test_flat_rule_plan_and_sdk_json_toml_profile_equivalence(tmp_path):
    project = application(tmp_path)
    invoke(project, "seed")
    actual = invoke(
        project, "run", "--kind", "plan", "--plan-mode", "flat", "--command-id", "flat-first"
    )
    assert actual["state"] == "succeeded"
    assert actual["member_receipts"] == 2
    program = """
from agent_app.runtime import sdk_profile
from ralf_agent import load_catalog
for kind in ('agent','rag','plan','team'):
    for variant in ('primary','alternate'):
        sdk = sdk_profile(kind, variant)
        for extension in ('json','toml'):
            catalog = load_catalog('runtime.' + extension)
            catalog.set_default('external-model-' + kind + '-' + variant, '1')
            assert catalog.default.identity == sdk.identity
        primary, alternate = sdk_profile(kind), sdk_profile(kind,'alternate')
        assert primary.components == alternate.components
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_same_mode_replaces_only_provider_and_duplicate_original_command_has_no_call(tmp_path):
    project = application(tmp_path)
    invoke(project, "seed")
    primary = invoke(project, "run", "--format", "sdk", "--command-id", "primary-original")
    alternate = invoke(
        project,
        "run",
        "--format",
        "json",
        "--provider",
        "alternate",
        "--command-id",
        "alternate-original",
    )
    repeated = invoke(
        project,
        "run",
        "--format",
        "toml",
        "--provider",
        "alternate",
        "--command-id",
        "alternate-original",
    )
    assert primary["result"]["supplier"] == "primary"
    assert alternate["result"]["supplier"] == "alternate"
    assert primary["result"]["lookup"] == alternate["result"]["lookup"]
    assert primary["run_id"] != alternate["run_id"] == repeated["run_id"]
    assert repeated["audit"]["model_calls"] == repeated["audit"]["tool_calls"] == 0


def test_business_verifier_rejects_plausible_completion_without_actual_tool_receipt(tmp_path):
    project = application(tmp_path)
    invoke(project, "seed")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent_app.adapter import BusinessCompletionVerifier; from ralf_agent.completion import CompletionRequest; assert BusinessCompletionVerifier().verify(CompletionRequest('cache', {'recommendation':'Inspect connection pool before changing cache timeout.'}, [])).status == 'reject'",
        ],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_parent_business_gate_refuses_result_that_disagrees_with_original_tool_receipt(tmp_path):
    project = application(tmp_path)
    invoke(project, "seed")
    actual = invoke(project, "run", "--kind", "team", "--command-id", "parent-proof")
    program = """import copy,json
from agent_app.adapter import BusinessParentGate
from ralf_agent import SQLiteStore
from ralf_agent.parent_completion import ParentCompletionRequest
from ralf_agent.types import digest
with SQLiteStore(".ralf/runs.sqlite", readonly=True) as store:
    run=store.run(RUN_ID)
    source=copy.deepcopy(next(iter(run["parent_completion_stages"].values()))["source"])
    supervisor=next(child for child in source["children"] if child["member_path"] == ["supervisor"])
    supervisor["result"]["recommendation"]="Invented remedy unsupported by the actual receipt"
    supervisor["result_digest"]=digest(supervisor["result"])
    source["candidate"]=copy.deepcopy(supervisor["result"])
    assert BusinessParentGate().verify(ParentCompletionRequest.from_dict(source)).status == "reject"
""".replace("RUN_ID", repr(actual["run_id"]))
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_cancelled_application_retains_original_supplier_and_retry_owner_until_runtime_drains(
    tmp_path, monkeypatch, asynchronous, owned
):
    import asyncio

    from ralf_agent import Runtime as ActualRuntime

    project = application(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.syspath_prepend(str(project))
    runtime_module = importlib.import_module("agent_app.runtime")
    adapter = importlib.import_module("agent_app.adapter")

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        providers, runtimes = [], []
        original_provider = adapter.ReferenceSQLiteModelProvider

        class PausedProvider(original_provider):
            async def complete(self, messages, tools):
                providers.append(self)
                entered.set()
                await release.wait()
                return await super().complete(messages, tools)

        def runtime_factory(engine, **kwargs):
            runtime = ActualRuntime(engine, close_timeout=0.01, **kwargs)
            runtimes.append(runtime)
            return runtime

        monkeypatch.setattr(adapter, "ReferenceSQLiteModelProvider", PausedProvider)
        monkeypatch.setattr(runtime_module, "Runtime", runtime_factory)
        runtime_module.seed()
        operation = asyncio.create_task(
            runtime_module.run(asynchronous=asynchronous, owned=owned, command_id="cancel-original")
        )
        await entered.wait()
        source = providers[0].source
        descriptor = source._file_descriptor
        baseline = source.audit()["close_calls"]
        operation.cancel()
        try:
            with pytest.raises(asyncio.CancelledError) as captured:
                await operation
            assert runtimes[0].state == "quiescing"
            assert runtimes[0]._supervisor.tasks
            assert source._closed is False
            assert source.audit()["close_calls"] == baseline
            os.fstat(descriptor)
            cleanup = captured.value.application_cleanup
            assert cleanup.runtime is runtimes[0] and cleanup.source is source
            release.set()
            await cleanup.aclose(close_timeout=2)
            assert runtimes[0].state == "closed"
            assert source._closed and source.audit()["close_calls"] == baseline + 1
            with pytest.raises(OSError):
                os.fstat(descriptor)
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]
        finally:
            release.set()
            await runtimes[0].aclose(close_timeout=2)
            source.close()

    try:
        asyncio.run(exercise())
    finally:
        for name in list(sys.modules):
            if name == "agent_app" or name.startswith("agent_app."):
                sys.modules.pop(name)


@pytest.mark.parametrize("owned", [False, True])
def test_application_close_error_retains_original_owner_for_same_loop_retry(
    tmp_path, monkeypatch, owned
):
    import asyncio

    from ralf_agent.errors import CloseIncomplete

    project = application(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.syspath_prepend(str(project))
    runtime_module = importlib.import_module("agent_app.runtime")
    adapter = importlib.import_module("agent_app.adapter")
    original_source = adapter.ReferenceModelSource
    sources = []

    class FailingSource(original_source):
        def __init__(self, path):
            super().__init__(path)
            self.allow_close = False
            sources.append(self)

        def close(self):
            if not self.allow_close:
                raise ConnectionError("actual supplier close failure")
            return super().close()

    async def exercise():
        runtime_module.seed()
        monkeypatch.setattr(adapter, "ReferenceModelSource", FailingSource)
        monkeypatch.setattr(runtime_module, "ReferenceModelSource", FailingSource)
        try:
            with pytest.raises(CloseIncomplete if owned else ConnectionError) as captured:
                await runtime_module.run(
                    asynchronous=True, owned=owned, command_id="actual-close-error"
                )
            source = sources[0]
            cleanup = captured.value.application_cleanup
            descriptor = source._file_descriptor
            baseline = source.audit()["close_calls"]
            assert source._closed is False
            assert cleanup.source is source and cleanup.instance is cleanup.runtime.engine
            assert cleanup.runtime.state == ("close_failed" if owned else "closed")
            if owned:
                assert isinstance(captured.value.__cause__, ConnectionError)
            os.fstat(descriptor)
            source.allow_close = True
            await cleanup.aclose(close_timeout=2)
            assert cleanup.runtime.state == "closed"
            assert source._closed and source.audit()["close_calls"] == baseline + 1
            with pytest.raises(OSError):
                os.fstat(descriptor)
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]
        finally:
            if sources:
                sources[0].allow_close = True
                if "cleanup" in locals():
                    await cleanup.aclose(close_timeout=2)
                sources[0].close()

    try:
        asyncio.run(exercise())
    finally:
        for name in list(sys.modules):
            if name == "agent_app" or name.startswith("agent_app."):
                sys.modules.pop(name)


_PROCESS_WORKER = """import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from agent_app.adapter import ReferenceModelSource
from agent_app.runtime import components, create_engine, definition, sdk_profile, source_path
from ralf_agent import AgentSpec, RuntimeBuilder, SQLiteStore

window = sys.argv[1]


class WindowStore(SQLiteStore):
    @contextmanager
    def transaction(self):
        outermost = not self.conn.in_transaction
        with super().transaction():
            yield
        if outermost:
            event = "tool_receipt_recorded" if window == "approved-effect" else "model_response_recorded"
            row = self.conn.execute("SELECT run_id FROM events WHERE kind=? ORDER BY rowid DESC LIMIT 1", (event,)).fetchone()
            source_count = sqlite_count()
            if row and (window == "approved-effect" or window == "recorded-response" and source_count == 2):
                Path("window.json").write_text(json.dumps({"pid": os.getpid(), "window": window}))
                os._exit(77)


def sqlite_count():
    import sqlite3
    with sqlite3.connect(source_path()) as connection:
        return connection.execute("SELECT count(*) FROM supplier_responses").fetchone()[0]


async def crash():
    source = ReferenceModelSource(source_path())
    if window == "approved-effect":
        source.configure("tools", {"name": "record_resolution", "arguments": {"incident": "cache"}, "call_id": "actual-resolution"})
    instance = RuntimeBuilder(components(source=source), base_dir=Path.cwd(),
        store_factory=WindowStore).build(sdk_profile(), ".ralf/runs.sqlite")
    spec = AgentSpec("resolution", "Record an actual approved incident resolution", tools=("record_resolution",)) if window == "approved-effect" else definition()
    handle = instance.submit(spec, {"incident": "cache"}, command_id="process-original", budget=40)
    Path("refs.json").write_text(json.dumps({"run_id": handle.run_id, "receipt": asdict(handle.receipt), "spec": asdict(spec), "pid": os.getpid()}))
    if window == "lost-response":
        instance.providers["default"]._fault = "response-lost"
    snapshot = await instance.drive(handle.run_id)
    if window == "approved-effect":
        assert snapshot.state == "waiting_approval", snapshot
        action = instance.store.run(handle.run_id)["actions"][-1]
        first = instance.approve(handle.run_id, action["id"], action["digest"], command_id="original-approve")
        second = instance.approve(handle.run_id, action["id"], action["digest"], command_id="original-approve")
        assert first == second
        await instance.drive(handle.run_id)
    if window == "lost-response":
        assert snapshot.state == "waiting_reconciliation", snapshot
        Path("window.json").write_text(json.dumps({"pid": os.getpid(), "window": window}))
        os._exit(77)
    raise AssertionError("The actual original process window was not reached")


asyncio.run(crash())
"""


@pytest.mark.parametrize("window", ["recorded-response", "lost-response", "approved-effect"])
def test_actual_installed_app_process_windows_preserve_original_authority(tmp_path, window):
    project = application(tmp_path)
    invoke(project, "seed")
    (project / "process_probe.py").write_text(_PROCESS_WORKER, encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, "process_probe.py", window],
        cwd=project,
        env=sdk_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 77, stdout + stderr
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    refs = json.loads((project / "refs.json").read_text())
    marker = json.loads((project / "window.json").read_text())
    assert marker["pid"] == refs["pid"] == child.pid
    with sqlite3.connect(project / ".ralf/business.sqlite") as connection:
        before_calls = connection.execute("SELECT count(*) FROM supplier_requests").fetchone()[0]
    with sqlite3.connect(project / ".ralf/runs.sqlite") as connection:
        before_record = json.loads(
            connection.execute("SELECT data FROM runs WHERE id=?", (refs["run_id"],)).fetchone()[0]
        )
    action = before_record["actions"][-1]
    if window == "recorded-response":
        assert action["kind"] == "model" and action["status"] == "response_received"
        assert action["attempts"][-1]["status"] == "completed"
    elif window == "approved-effect":
        assert action["kind"] == "tool" and action["status"] == "receipt_received"
        assert action["effect_observation"]["result"]["recorded"] is True
    else:
        assert action["kind"] == "model" and action["attempts"][-1]["status"] == "unknown"
        assert action.get("received_response") is None
    if window == "lost-response":
        program = """import json
from agent_app.runtime import create_engine
refs=json.load(open("refs.json"))
with create_engine(".ralf/runs.sqlite") as engine:
    snapshot=engine.status(refs["run_id"])
    diagnostic=engine.diagnostics(refs["run_id"])
    assert engine._active is None
    print(json.dumps({"run_id":snapshot.run_id,"state":snapshot.state,"budget":diagnostic.budget}))
"""
    else:
        program = """import asyncio,json
from dataclasses import asdict
from agent_app.runtime import create_engine
from ralf_agent import AgentSpec
async def run():
    refs=json.load(open("refs.json"))
    with create_engine(".ralf/runs.sqlite") as engine:
        snapshot=await engine.drive(refs["run_id"])
        duplicate=engine.submit(AgentSpec(**refs["spec"]),{"incident":"cache"},command_id="process-original",budget=40)
        assert asdict(duplicate.receipt)==refs["receipt"]
        print(json.dumps({"run_id":snapshot.run_id,"state":snapshot.state,"result":snapshot.result}))
asyncio.run(run())
"""
    resumed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project,
        env=sdk_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stderr + resumed.stdout
    result = json.loads(resumed.stdout)
    assert result["run_id"] == refs["run_id"]
    with sqlite3.connect(project / ".ralf/business.sqlite") as connection:
        after_calls = connection.execute("SELECT count(*) FROM supplier_requests").fetchone()[0]
        write_count = connection.execute("SELECT count(*) FROM business_effects").fetchone()[0]
    assert after_calls == before_calls + int(window == "approved-effect")
    assert write_count == int(window == "approved-effect")
    with sqlite3.connect(project / ".ralf/runs.sqlite") as connection:
        after_record = json.loads(
            connection.execute("SELECT data FROM runs WHERE id=?", (refs["run_id"],)).fetchone()[0]
        )
    if window == "lost-response":
        assert result["state"] == "waiting_reconciliation"
        assert result["budget"]["held"] == 1
        assert after_record == before_record
    else:
        assert result["state"] == "succeeded", result
    print(
        json.dumps(
            {
                "window": window,
                "run_id": refs["run_id"],
                "pid": child.pid,
                "reaped": True,
                "calls_before": before_calls,
                "calls_after": after_calls,
                "writes": write_count,
            }
        )
    )
