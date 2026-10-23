"""Actual old83 package ↔ current defaults and pre-Activity version admission.

The immutable old environments are selected explicitly through
RALF_TEST_OLD_CORE_PYTHON / RALF_TEST_OLD_SDK_PYTHON. A final installed package
can replace the current source by setting RALF_TEST_CURRENT_PYTHON.
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

import relf_agent as r
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.types import digest, submission_request

# These probes qualify the shared old namespace, not a6 cross-namespace recovery.
# Run the preserved a5 source/installed tests with its original SDK environments.
pytestmark = pytest.mark.skip(
    reason="Historical old83/a5 shared-namespace probes: use original a5 code; a6 cross-namespace migration is unsupported"
)


@pytest.fixture
def probe():
    from . import artifact_binding_old_worker

    return artifact_binding_old_worker


ROOT = Path(__file__).resolve().parents[1]
ENTRY = "from tests.artifact_binding_old_worker import main; main()"


def old_python(kind):
    value = os.getenv("RALF_TEST_OLD_" + kind.upper() + "_PYTHON")
    if not value:
        pytest.skip("requires explicitly selected immutable old83 " + kind + " environment")
    assert Path(value).is_file()
    return value


def current_python():
    return os.getenv("RALF_TEST_CURRENT_PYTHON", sys.executable)


def env_for(root, scope, *, current=False, **extra):
    paths = [str(ROOT)]
    if current and not os.getenv("RALF_TEST_CURRENT_PYTHON"):
        paths.insert(0, str(ROOT / "src"))
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": os.pathsep.join(paths),
        "PYTHONDONTWRITEBYTECODE": "1",
        "RALF_TEST_DATA_ROOT": str(root),
        "RALF_TEST_SCOPE": json.dumps(asdict(scope)),
        **extra,
    }


def call_probe(executable, operation, mode, root, scope, *, current=False):
    result = subprocess.run(
        [executable, "-c", ENTRY, operation, mode],
        cwd=root,
        env=env_for(root, scope, current=current),
        capture_output=True,
        text=True,
        timeout=90,
    )
    (root / (operation + "-" + mode + ".log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("operation", ["defaults", "local-session"])
def test_old83_current_local_releases_sessions_and_identical_22_starters(tmp_path, operation):
    old = old_python("core")
    scope = r.Scope("artifact-upgrade-local", uuid.uuid4().hex)
    for executable, mode, current in (
        (old, "old-first", False),
        (current_python(), "new", True),
        (old, "old-again", False),
        (current_python(), "new-again", True),
    ):
        call_probe(executable, operation, mode, tmp_path, scope, current=current)


def test_old83_cli_application_recovers_approval_under_current_and_old(tmp_path):
    old = old_python("core")
    scope = r.Scope("artifact-upgrade-cli", uuid.uuid4().hex)
    project = tmp_path / "original-cli"
    result = subprocess.run(
        [
            old,
            "-c",
            "from ralf_agent.starter import create_starter; import sys; create_starter(sys.argv[1],template='cli')",
            str(project),
        ],
        cwd=tmp_path,
        env=env_for(tmp_path, scope),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    fixed = subprocess.check_output(
        [old, "-c", "import sys; print(sys.executable)"],
        cwd=tmp_path,
        env=env_for(tmp_path, scope),
        text=True,
    ).strip()

    def call(executable, *args, current=False):
        result = subprocess.run(
            [
                executable,
                "-c",
                "import sys,runpy; fixed=sys.argv[1]; args=sys.argv[2:]; sys.executable=fixed; sys.argv=['agent_app',*args]; runpy.run_module('agent_app',run_name='__main__')",
                fixed,
                *args,
            ],
            cwd=project,
            env=env_for(tmp_path, scope, current=current),
            capture_output=True,
            text=True,
            timeout=30,
        )
        with (tmp_path / "cli.log").open("a") as out:
            out.write(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    first = call(old, "run", "--value", "3", "--command-id", "same")
    assert first["state"] == "waiting_approval"
    pending = first["pending"][0]
    args = (
        "approve",
        first["run_id"],
        pending["action_id"],
        "--digest",
        pending["digest"],
        "--command-id",
        "approve",
    )
    receipt = call(current_python(), *args, current=True)
    assert call(current_python(), *args, current=True) == receipt
    assert call(current_python(), "resume", first["run_id"], current=True)["state"] == "succeeded"
    assert call(old, "resume", first["run_id"])["state"] == "succeeded"
    assert (
        call(current_python(), "run", "--value", "3", "--command-id", "same", current=True)[
            "run_id"
        ]
        == first["run_id"]
    )
    with sqlite3.connect(project / ".ralf/business.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    assert (project / ".ralf/read-audit").read_text().splitlines() == ["read"]
    assert (project / ".ralf/call-audit").read_text().splitlines() == ["call"]


class Workers:
    def __init__(self, root, scope, queue, address):
        self.root, self.scope, self.queue, self.address = root, scope, queue, address
        self.processes = []

    async def start(self, label, executable, mode, *, current=False):
        log = self.root / (label + ".log")
        manifest = self.root / (label + ".manifest.json")
        extra = {
            "RALF_TEST_TEMPORAL_ADDRESS": self.address,
            "RALF_TEST_TEMPORAL_QUEUE": self.queue,
            "RALF_TEST_MANIFEST_FILE": str(manifest),
        }
        if mode == "sandbox4":
            extra.update(
                {
                    name: os.environ[name]
                    for name in ("RALF_TEST_DOCKER_SOCKET", "RALF_TEST_DOCKER_IMAGE")
                }
            )
        with log.open("w") as out:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [executable, "-u", "-c", ENTRY, "worker", mode],
                cwd=self.root,
                env=env_for(self.root, self.scope, current=current, **extra),
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        self.processes.append((process, log))
        async with asyncio.timeout(30):
            while "COMPAT_READY" not in log.read_text():
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
        return process, json.loads(manifest.read_text())

    async def stop(self, process):
        if process.poll() is None:
            process.terminate()
        try:
            await asyncio.to_thread(process.wait, timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
            raise AssertionError(
                "Owned Worker needed kill instead of completed graceful shutdown"
            ) from None
        log = next(log for candidate, log in self.processes if candidate is process)
        assert process.returncode == 0 and "COMPAT_STOPPED" in log.read_text(), log.read_text()

    async def close(self):
        failures = []
        for process, _log in self.processes:
            try:
                await self.stop(process)
            except AssertionError as error:
                failures.append(str(error))
        (self.root / "workers-exited.json").write_text(
            json.dumps(
                [
                    {"pid": process.pid, "returncode": process.returncode, "log": str(log)}
                    for process, log in self.processes
                ]
            )
        )
        assert not failures, failures


def audit(root):
    path = root / "audit.sqlite"
    if not path.exists():
        return {}
    with sqlite3.connect(path) as conn:
        return dict(conn.execute("SELECT kind, count(*) FROM calls GROUP BY kind"))


async def terminate_owned(client, ids):
    from temporalio.service import RPCError, RPCStatusCode

    for identifier in ids:
        try:
            await client.get_workflow_handle(identifier).terminate(
                "owned compatibility probe cleanup"
            )
        except RPCError as error:
            if error.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                raise


async def clean_all(*operations):
    errors = []
    for operation in operations:
        try:
            await operation()
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("Owned compatibility cleanup failed", errors)


@pytest.mark.parametrize("mode", ["default", "native", "binding1", "context2", "tool3", "sandbox4"])
def test_old83_current_old_temporal_history_receipts_and_legacy_protocols(
    tmp_path, mode, monkeypatch, probe
):
    old = old_python("sdk")
    address = os.getenv("RALF_TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("requires actual Temporal Service")
    if mode == "sandbox4" and not all(
        os.getenv(name) for name in ("RALF_TEST_DOCKER_SOCKET", "RALF_TEST_DOCKER_IMAGE")
    ):
        pytest.skip("requires actual explicit installed Docker image and socket")
    queue = "artifact-upgrade-" + uuid.uuid4().hex
    scope = r.Scope("artifact-upgrade-temporal", queue)
    monkeypatch.setenv("RALF_TEST_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("RALF_TEST_SCOPE", json.dumps(asdict(scope)))

    async def run():
        from temporalio.client import Client

        from relf_agent.temporal_session_state import workflow_id

        client = await Client.connect(address)
        execution, resources = await probe.runtime(mode)
        engine = TemporalEngine(
            client, task_queue=queue, release=execution.manifest, scope=scope, activity_timeout=5
        )
        workers = Workers(tmp_path, scope, queue, address)
        owned = {engine.command_registry_id}
        host = None
        try:
            first, old_release = await workers.start("old-first", old, mode)
            assert old_release == execution.manifest
            assert "artifacts_binding_protocol" not in old_release
            if mode in {"binding1", "context2", "tool3", "sandbox4"}:
                assert (
                    old_release["binding_protocol"]
                    == {"binding1": 1, "context2": 2, "tool3": 3, "sandbox4": 4}[mode]
                )
            if mode == "native":
                host = r.Runtime.from_temporal(engine)
                session = await host.open_session(
                    probe.definition(mode), "native", command_id="open"
                )
                owned.add(workflow_id(session.ref.key))
                accepted = await session.submit("task", command_id="turn-first")
                handle = accepted.turn.run
            else:
                handle = await engine.submit(probe.definition(mode), "task", command_id="submit")
            owned.add(handle.run_id)
            waiting = await engine.drive(handle.run_id, wait_seconds=20)
            assert waiting.state == "waiting_approval" and audit(tmp_path) == {"model": 1}, waiting
            pending = waiting.pending[0]
            await workers.stop(first)
            second, new_release = await workers.start(
                "current", current_python(), mode, current=True
            )
            assert new_release == old_release
            receipt = await engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            assert (
                await engine.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                == receipt
            )
            done = await engine.drive(handle.run_id, wait_seconds=20)
            assert done.state == "succeeded" and done.result == "answer", done
            history = await client.get_workflow_handle(handle.run_id).fetch_history()
            (tmp_path / "run-history.json").write_text(history.to_json())
            await replay_temporal_history(history)
            if mode == "native":
                async with asyncio.timeout(20):
                    while (await session.status()).busy:  # noqa: ASYNC110 -- poll actual remote state
                        await asyncio.sleep(0.05)
                assert (await engine.diagnostics(handle.run_id)).workflow["quiescent"] is True
            await workers.stop(second)
            _, old_again = await workers.start("old-again", old, mode)
            assert old_again == old_release
            assert (await engine.status(handle.run_id)).result == "answer"
            if mode == "native":
                assert (await session.submit("task", command_id="turn-first")).turn == accepted.turn
                assert not (await session.status()).busy
                assert execution.session_store.read(scope, session.ref.key.storage_key)[0] == 1
            else:
                assert (
                    await engine.submit(probe.definition(mode), "task", command_id="submit")
                    == handle
                )
            assert audit(tmp_path) == {"model": 2, "sandbox" if mode == "sandbox4" else "tool": 1}
            if mode == "sandbox4":
                with sqlite3.connect(tmp_path / "audit.sqlite") as conn:
                    result = json.loads(
                        conn.execute("SELECT value FROM calls WHERE kind='sandbox'").fetchone()[0]
                    )
                assert result["stdout"] == "compat\n" and result["exit_code"] == 0
                assert result["observation"]["state"] == "stopped" and result["native_id"]
                observation = await resources[0].observe(scope, result["invocation_id"])
                assert observation.state == "not_found"
                (tmp_path / "sandbox-native-cleanup.json").write_text(
                    json.dumps(observation.to_dict())
                )
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "mode": mode,
                        "run_id": handle.run_id,
                        "scope": asdict(scope),
                        "queue": queue,
                        "audit": audit(tmp_path),
                        "release": old_release,
                    },
                    sort_keys=True,
                )
            )
        finally:
            operations = [lambda: terminate_owned(client, owned), workers.close]
            if host is not None:
                operations.append(host.aclose)
            await clean_all(
                *operations, engine.aclose, lambda: probe.close_runtime(execution, resources)
            )

    asyncio.run(asyncio.wait_for(run(), timeout=150))


def test_actual_old83_worker_refuses_joint_artifact_manifest_before_any_activity(
    tmp_path, monkeypatch, probe
):
    old = old_python("sdk")
    address = os.getenv("RALF_TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("requires actual Temporal Service")
    queue = "artifact-refusal-" + uuid.uuid4().hex
    scope = r.Scope("artifact-upgrade-refusal", queue)
    monkeypatch.setenv("RALF_TEST_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("RALF_TEST_SCOPE", json.dumps(asdict(scope)))

    async def run():
        from temporalio.api.enums.v1 import EventType
        from temporalio.client import Client

        from relf_agent.temporal_state import WORKFLOW_NAME

        client = await Client.connect(address)
        workers = Workers(tmp_path, scope, queue, address)
        artifact = r.SQLiteArtifactStore(
            tmp_path / "selected-artifacts.sqlite", backend_id="selected"
        )
        original = r.InMemoryArtifactStore(backend_id="original")
        catalog = r.BindingCatalog(scope=scope)
        catalog.register(
            "artifacts", "selected", "1", r.ArtifactBindingResource(artifact, version="1")
        )
        execution = TemporalRuntime(
            providers={"default": probe.Provider("refusal")},
            tools=r.ToolRegistry(),
            context_builder=r.ManagedDataContext(original, scope=scope),
            binding_catalog=catalog,
        )
        manifest = execution.manifest
        assert manifest["kernel"] == "temporal-3" and manifest["binding_protocol"] == 5
        assert manifest["artifacts_binding_protocol"] == 1
        definition = r.AgentDefinition(
            r.AgentSpec("compat", "Never execute"),
            bindings=r.AgentBindingDescriptor(artifacts=r.BindingSelection.ref("selected", "1")),
        )
        run_id = "ralf-temporal-" + digest([asdict(scope), "joint-refusal"])
        try:
            await workers.start("old83-refusal", old, "refusal")
            handle = await client.start_workflow(
                WORKFLOW_NAME,
                {
                    "scope": asdict(scope),
                    "command_id": "joint-refusal",
                    "request": submission_request(definition, "task", budget=32),
                    "manifest": manifest,
                    "activity_timeout": 3,
                },
                id=run_id,
                task_queue=queue,
            )
            failures = []
            async with asyncio.timeout(25):
                while not failures:
                    history = await handle.fetch_history()
                    failures = [
                        event
                        for event in history.events
                        if event.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED
                    ]
                    await asyncio.sleep(0.05)
            assert "Unsupported Temporal binding/memory protocol" in str(failures)
            history = await handle.fetch_history()
            activities = [
                event
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
            ]
            assert activities == [] and audit(tmp_path) == {}
            with sqlite3.connect(tmp_path / "selected-artifacts.sqlite") as conn:
                assert conn.execute("SELECT count(*) FROM ralf_artifacts").fetchone()[0] == 0
            (tmp_path / "refusal-history.json").write_text(history.to_json())
            (tmp_path / "refusal-evidence.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "scope": asdict(scope),
                        "queue": queue,
                        "workflow_task_failed": len(failures),
                        "activities_scheduled": 0,
                        "model_tool_calls": 0,
                        "queryable_ralf_state": False,
                    }
                )
            )
        finally:
            try:
                await clean_all(
                    lambda: terminate_owned(client, {run_id}),
                    workers.close,
                    execution.close_context_execution,
                )
            finally:
                artifact.close()
                original.close()

    asyncio.run(asyncio.wait_for(run(), timeout=70))
