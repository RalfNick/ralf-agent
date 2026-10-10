import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import Runtime, Scope
from ralf_agent.errors import NotFound
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_memory_worker import definition, runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Workers:
    def __init__(self, root, queue, window):
        self.root, self.queue, self.window, self.processes = root, queue, window, []

    async def start(self, mode):
        log = self.root / f"worker-{mode}.log"
        import ralf_agent

        source = str(Path(ralf_agent.__file__).parents[1])
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join([source, str(Path(__file__).parents[1])]),
            "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
            "RALF_TEST_TEMPORAL_QUEUE": self.queue,
            "RALF_MEMORY_ROOT": str(self.root),
            "RALF_MEMORY_MODE": mode,
            "RALF_MEMORY_WINDOW": self.window,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import asyncio; from tests.temporal_memory_worker import run; asyncio.run(run())",
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        self.processes.append(process)
        for _ in range(400):
            if "TEMPORAL_MEMORY_READY" in log.read_text():
                return process
            assert process.poll() is None, log.read_text()
            await asyncio.sleep(0.05)
        pytest.fail(log.read_text())

    async def marker(self, name):
        for _ in range(600):
            if (self.root / name).exists():
                return
            await asyncio.sleep(0.05)
        pytest.fail(
            "Missing marker "
            + name
            + "\n"
            + "\n".join(p.read_text() for p in self.root.glob("worker-*.log"))
        )

    async def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, timeout=5)


def counts(root):
    with sqlite3.connect(root / "audit.sqlite") as db:
        return dict(db.execute("SELECT kind, COUNT(*) FROM calls GROUP BY kind"))


@pytest.mark.parametrize(
    "kind", ["native", "sequence", "parallel", "team", "dynamic-dag", "nested"]
)
@pytest.mark.parametrize("window", ["selector", "cas"])
def test_real_worker_restarts_without_repeating_selector_or_cas(tmp_path, kind, window):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "memory-" + uuid.uuid4().hex
        execution, memory = runtime(tmp_path, queue)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("temporal-memory", queue),
            activity_timeout=2,
            drive_timeout=30,
        )
        facade = Runtime.from_temporal(engine)
        workers = Workers(tmp_path, queue, window)
        try:
            first = await workers.start("crash")
            handle = await facade.submit(definition(kind), "task", command_id="s", budget=32)
            await workers.marker("pause-ready")
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            await workers.start("resume")
            done = await engine.drive(handle.ref.run_id)
            assert done.state == "succeeded", done
            assert counts(tmp_path) == {
                "business": 1 if kind == "native" else 2,
                "selector": 1,
                "cas": 1 if kind == "native" else 2,
            }
            with sqlite3.connect(tmp_path / "audit.sqlite") as db:
                labels = [r[0] for r in db.execute("SELECT label FROM calls WHERE kind='business'")]
            assert sorted(labels) == (["second"] if kind == "native" else ["first", "second"])
            run_ids = [handle.ref.run_id]
            for run_id in run_ids:
                info = await engine.diagnostics(run_id)
                assert info.budget["unknown"] == info.budget["reserved"] == 0
                assert info.workflow["quiescent"]
                run_ids.extend(c["run_id"] for c in info.workflow.get("children", []))
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
            facts = memory.facts(Scope("temporal-memory", queue), "two")
            assert len(facts) == 1 and facts[0]["value"]["value"] == "second-result"
            if kind != "native":
                one = memory.facts(Scope("temporal-memory", queue), "one")
                assert len(one) == 1 and one[0]["value"]["value"] == "first-result"
            before = counts(tmp_path)
            duplicate = await facade.submit(definition(kind), "task", command_id="s", budget=32)
            assert duplicate.ref == handle.ref
            await facade.resume(handle.ref)
            assert counts(tmp_path) == before
        finally:
            await workers.close()
            await facade.aclose()
            memory.close()

    asyncio.run(run())


def test_real_cancel_during_fact_read_never_dispatches_selector_or_cas(tmp_path):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "cancel-memory-" + uuid.uuid4().hex
        execution, memory = runtime(tmp_path, queue)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("temporal-memory", queue),
            activity_timeout=5,
            drive_timeout=20,
        )
        workers = Workers(tmp_path, queue, "cas")
        try:
            await workers.start("cancel-read")
            handle = await engine.submit(definition("native"), "task", command_id="s")
            await workers.marker("read-ready")
            await engine.cancel(handle.run_id, command_id="cancel")
            (tmp_path / "read-release").touch()
            for _ in range(300):
                info = await engine.diagnostics(handle.run_id)
                if info.workflow["quiescent"]:
                    break
                await asyncio.sleep(0.05)
            assert info.snapshot.state == "cancelled" and info.workflow["quiescent"]
            assert counts(tmp_path) == {"business": 1, "selector": 1}
            assert memory.facts(Scope("temporal-memory", queue), "two") == []
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            await workers.close()
            memory.close()

    asyncio.run(run())


@pytest.mark.parametrize("nested", [False, True])
def test_explicit_root_resume_recovers_original_terminal_child_facts(tmp_path, nested):
    async def run():
        from temporalio.client import Client

        from ralf_agent import (
            AgentBindingDescriptor,
            AgentSpec,
            BindingSelection,
            BoundDefinition,
            SQLiteMemory,
            TeamSpec,
        )

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "late-memory-" + uuid.uuid4().hex
        execution, memory = runtime(tmp_path, queue)
        scope = Scope("temporal-memory", queue)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=10,
        )
        workers = Workers(tmp_path, queue, "plain")
        try:
            await workers.start("no-fact")
            descriptor = AgentBindingDescriptor(stage_policy=BindingSelection.ref("first", "1"))
            member = (
                TeamSpec("inner", {"x": AgentSpec("a", "first-result")}, child_budget=6)
                if nested
                else AgentSpec("a", "first-result")
            )
            spec = BoundDefinition(
                TeamSpec("outer", {"a": member}, child_budget=12),
                {"team/members/a/team/members/x" if nested else "team/members/a": descriptor},
            )
            h = await engine.submit(spec, "task", command_id="s", budget=24)
            leaf = None
            for _ in range(300):
                root = await engine.diagnostics(h.run_id)
                if root.workflow.get("children"):
                    current = root.workflow["children"][0]["run_id"]
                    try:
                        child = await engine.diagnostics(current)
                    except NotFound:
                        await asyncio.sleep(0.05)
                        continue
                    if nested and child.workflow.get("children"):
                        current = child.workflow["children"][0]["run_id"]
                        try:
                            child = await engine.diagnostics(current)
                        except NotFound:
                            await asyncio.sleep(0.05)
                            continue
                    if child.snapshot.state == "succeeded" and child.budget["unknown"] == 1:
                        leaf = current
                        break
                await asyncio.sleep(0.05)
            assert leaf is not None
            fact = (await engine.memory_stages(leaf))[0]["facts"][0]
            SQLiteMemory.put_fact(
                memory, scope, "one", fact["key"], fact["value"], expected_version=0
            )
            before = counts(tmp_path)
            await engine.drive(h.run_id, wait_seconds=0)
            for _ in range(150):
                root = await engine.diagnostics(h.run_id)
                if root.snapshot.state == "succeeded" and root.workflow["quiescent"]:
                    break
                await asyncio.sleep(0.05)
            assert root.snapshot.state == "succeeded" and root.workflow["quiescent"]
            assert root.budget["reserved"] == root.budget["unknown"] == 0
            assert counts(tmp_path) == before == {"business": 1, "dispatch": 1}
            for run_id in [h.run_id, leaf]:
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            await workers.close()
            memory.close()

    asyncio.run(run())


def test_cas_worker_timeout_keeps_parent_allowance_despite_fact_proof(tmp_path):
    async def run():
        from temporalio.client import Client

        from ralf_agent import (
            AgentBindingDescriptor,
            AgentSpec,
            BindingSelection,
            BoundDefinition,
            TeamSpec,
        )

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "unknown-stop-" + uuid.uuid4().hex
        execution, memory = runtime(tmp_path, queue)
        scope = Scope("temporal-memory", queue)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=10,
        )
        workers = Workers(tmp_path, queue, "plain")
        try:
            first = await workers.start("cas-active")
            spec = BoundDefinition(
                TeamSpec("t", {"a": AgentSpec("a", "first-result")}, child_budget=12),
                {
                    "team/members/a": AgentBindingDescriptor(
                        stage_policy=BindingSelection.ref("first", "1")
                    )
                },
            )
            h = await engine.submit(spec, "task", command_id="s", budget=24)
            await workers.marker("cas-ready")
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            await workers.start("resume")
            for _ in range(300):
                root = await engine.diagnostics(h.run_id)
                child_id = root.workflow["children"][0]["run_id"]
                child = await engine.diagnostics(child_id)
                if (
                    child.snapshot.state == "succeeded"
                    and child.budget["reserved"] == child.budget["unknown"] == 0
                ):
                    break
                await asyncio.sleep(0.05)
            assert child.snapshot.state == "succeeded" and child.budget["spent"] == 2
            assert child.workflow["unknown_remote_execution"] and not child.workflow["quiescent"]
            for _ in range(100):
                root = await engine.diagnostics(h.run_id)
                if root.budget["unknown"] == 12:
                    break
                await asyncio.sleep(0.05)
            assert root.budget["unknown"] == 12 and not root.workflow["quiescent"]
            assert counts(tmp_path) == {"business": 1, "cas": 1}
            assert len(memory.facts(scope, "one")) == 1
            await replay_temporal_history(
                await client.get_workflow_handle(child_id).fetch_history()
            )
        finally:
            await workers.close()
            memory.close()

    asyncio.run(run())
