"""Real native write threads keep their original root lease through cancellation."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

import ralf_agent as r
from ralf_agent.errors import CloseIncomplete, CoordinatorBusy
from ralf_agent.temporal import replay_temporal_history

from .test_workspace_write_configuration import Writer
from .test_workspace_write_execution import definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS") or not os.getenv("RALF_TEST_POSTGRES_DSN"),
    reason="requires owned actual Temporal and PostgreSQL EffectJournal",
)


@pytest.mark.parametrize(
    "kind,fault_receipt",
    [
        *[(kind, False) for kind in ("agent", "sequence", "graph", "team", "dynamic", "nested")],
        ("agent", True),
        ("graph", True),
    ],
)
def test_actual_native_cancel_close_original_thread_and_root_lease(
    tmp_path, monkeypatch, kind, fault_receipt
):
    roots = {name: tmp_path / name for name in ("alpha", "beta")}
    for root in roots.values():
        root.mkdir()
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    calls, ports, sources, identities = [], {}, {}, []
    original = os.replace
    receiver_available = threading.Event()

    class LostReceipt:
        def __init__(self, journal):
            self.journal = journal

        @property
        def identity(self):
            return {
                "kind": "test-lost-receipt-transport",
                "version": "1",
                "delegate": self.journal.identity,
            }

        async def begin(self, envelope):
            return await self.journal.begin(envelope)

        async def observation(self, envelope):
            return await self.journal.observation(envelope)

        async def received(self, envelope, observation):
            if not receiver_available.is_set():
                raise ConnectionError("injected receipt receiver unavailable")
            return await self.journal.received(envelope, observation)

        async def acknowledge(self, envelope, observation):
            return await self.journal.acknowledge(envelope, observation)

    def replace(source, destination, **options):
        if destination != "note" or "dst_dir_fd" not in options:
            return original(source, destination, **options)
        descriptor = os.fstat(options["dst_dir_fd"])
        if not any(descriptor.st_ino == root.stat().st_ino for root in roots.values()):
            return original(source, destination, **options)
        entered.set()
        try:
            assert release.wait(30), "original native write was never released"
            return original(source, destination, **options)
        finally:
            ended.set()

    monkeypatch.setattr(os, "replace", replace)

    class Tracked(r.FileSystemWritableWorkspace):
        def write_text(self, scope, path, text, *, expected_version, effect_key):
            calls.append((Path(self._root).name, scope, effect_key))
            return super().write_text(
                scope, path, text, expected_version=expected_version, effect_key=effect_key
            )

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "native-write-lifetime-" + uuid.uuid4().hex
        scope = r.Scope("write-lifetime", queue)
        factories = r.ComponentRegistry()
        factories.register("provider", "writer", lambda c, ctx: Writer())

        async def tools(config, context):
            registry = r.ToolRegistry()
            for name, root in roots.items():
                port = context.own(Tracked(root, version="1", scopes=[context.scope]))
                source = context.own_async(r.WritableWorkspaceToolSource(port, version="1"))
                ports[name], sources[name] = port, source
                await r.register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "workspace_write_text": r.ToolPolicy(
                            "1",
                            effect="idempotent_write",
                            requires_approval=True,
                            effect_key_argument="effect_key",
                            reconciler=source.reconcile,
                        )
                    },
                )
            registry.register(
                r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "ok"
            )
            return registry

        factories.register_async("tools", "roots", tools)

        async def journal(config, context):
            from ralf_agent.temporal_journal import PostgresEffectJournal

            original_journal = context.own_async(
                await PostgresEffectJournal.connect(
                    os.environ["RALF_TEST_POSTGRES_DSN"],
                    backend_id="native-write-lifetime",
                )
            )
            await original_journal.initialize()
            return LostReceipt(original_journal)

        factories.register_async("effect_journal", "lost-receipt", journal)
        profile = r.TemporalProfile(
            "native-write-lifetime",
            "1",
            {"default": {"adapter": "writer"}},
            {
                "tools": {"adapter": "roots"},
                "effect_journal": {
                    "adapter": "lost-receipt" if fault_receipt else "postgres",
                    "config": {
                        "dsn_env": "RALF_TEST_POSTGRES_DSN",
                        "backend_id": "native-write-lifetime",
                        "initialize": True,
                    },
                },
                **(
                    {"tool_execution": {"adapter": "tracked", "config": {"version": "1"}}}
                    if fault_receipt
                    else {}
                ),
            },
            binding_components=[
                {
                    "role": "workspace",
                    "component_id": name,
                    "version": "1",
                    "component": {
                        "adapter": "registered-tools",
                        "config": {"names": [name + "_workspace_write_text"]},
                    },
                }
                for name in roots
            ],
        )
        assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
        restarted = None
        try:
            await assembly.start_worker(client, task_queue=queue)
            engine = assembly.create_engine(client, task_queue=queue, activity_timeout=10)
            handle = await engine.submit(definition(kind), "write", command_id="same", budget=64)
            waiting = await engine.drive(handle.run_id, wait_seconds=20)
            assert waiting.state == "waiting_approval" and calls == [], waiting
            item = waiting.pending[0]
            target = item.get("run_id", handle.run_id)
            approval = await engine.approve(
                target, item["action_id"], item["digest"], command_id="approve"
            )
            assert await asyncio.to_thread(entered.wait, 15), (
                "actual original native handler did not start"
            )
            assert (
                await engine.approve(
                    target, item["action_id"], item["digest"], command_id="approve"
                )
                == approval
            )
            assert len(calls) == 1 and not ended.is_set()
            name, original_scope, effect_key = calls[0]
            assert original_scope == scope
            cancellation = await engine.cancel(handle.run_id, command_id="cancel")
            assert await engine.cancel(handle.run_id, command_id="cancel") == cancellation
            assert (await engine.status(handle.run_id)).state in {"cancelling", "cancelled"}
            blocked = asdict(await engine.diagnostics(handle.run_id))
            identities.append(blocked)
            assert blocked["workflow"]["quiescent"] is False
            assert blocked["workflow"]["remote_stop_confirmed"] is False
            with pytest.raises(CloseIncomplete):
                await assembly.aclose(wait_timeout=0)
            assert assembly._worker_stop is None and not ended.is_set()
            assert ports[name]._root_fd is not None and sources[name]._tracker.has_active
            with pytest.raises(CoordinatorBusy):
                r.FileSystemWritableWorkspace(roots[name], version="1", scopes=[scope])
            command = (
                "import sys; from ralf_agent import FileSystemWritableWorkspace; "
                "from ralf_agent.errors import CoordinatorBusy; "
                "\ntry: FileSystemWritableWorkspace(sys.argv[1], version='1')"
                "\nexcept CoordinatorBusy: sys.exit(18)"
                "\nelse: sys.exit(0)"
            )
            child = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", command, str(roots[name])],
                cwd=tmp_path,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(Path(r.__file__).parent.parent),
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert child.returncode == 18, child.stderr
            release.set()
            assert await assembly._calls.wait(wait_timeout=15)
            assert ended.is_set() and not sources[name]._tracker.has_active
            await assembly.aclose(wait_timeout=15)
            assert ports[name]._root_fd is None
            replacement = r.FileSystemWritableWorkspace(roots[name], version="1", scopes=[scope])
            try:
                receipt = replacement.query_write(scope, effect_key)
                assert receipt is not None and receipt["effect_key"] == effect_key
            finally:
                replacement.close()
            assert (roots[name] / "note").read_text() == "A"
            if fault_receipt:
                import psycopg

                async with await psycopg.AsyncConnection.connect(
                    os.environ["RALF_TEST_POSTGRES_DSN"]
                ) as connection:
                    cursor = await connection.execute(
                        "SELECT result FROM ralf_temporal_effects WHERE workspace=%s AND principal=%s AND effect_key=%s",
                        (scope.workspace, scope.principal, effect_key),
                    )
                    assert await cursor.fetchone() == (None,)
                receiver_available.set()
            restarted = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            await restarted.start_worker(client, task_queue=queue)
            recovered = restarted.create_engine(client, task_queue=queue, activity_timeout=10)
            assert (
                await recovered.submit(definition(kind), "write", command_id="same", budget=64)
                == handle
            )
            if fault_receipt:
                query = await recovered.reconcile(
                    target, item["action_id"], query=True, command_id="query-receipt"
                )
                assert (
                    await recovered.reconcile(
                        target, item["action_id"], query=True, command_id="query-receipt"
                    )
                    == query
                )
                deadline = asyncio.get_running_loop().time() + 15
                while asyncio.get_running_loop().time() < deadline:
                    verified = await recovered.diagnostics(target)
                    if verified.workflow["quiescent"]:
                        break
                    await asyncio.sleep(0.05)
                (tmp_path / "recovery-diagnostics.json").write_text(
                    json.dumps(asdict(verified), ensure_ascii=False, indent=2)
                )
                assert verified.workflow["quiescent"] is True, asdict(verified)
                assert verified.workflow["remote_stop_confirmed"] is True
                assert verified.budget["unknown"] == 0
                assert verified.snapshot.state == "cancelled"
            done = await recovered.drive(handle.run_id, wait_seconds=20)
            assert done.state == "cancelled", done
            assert await recovered.cancel(handle.run_id, command_id="cancel") == cancellation
            assert len(calls) == 1
            history = await client.get_workflow_handle(handle.run_id).fetch_history()
            await replay_temporal_history(history)
            for root_name, root in roots.items():
                with sqlite3.connect(root / ".ralf/workspace-writes/journal.sqlite") as connection:
                    count = connection.execute(
                        "SELECT count(*) FROM workspace_write_effects WHERE receipt IS NOT NULL"
                    ).fetchone()[0]
                    assert count == (1 if root_name == name else 0)
        finally:
            release.set()
            if restarted is not None:
                await restarted.aclose(wait_timeout=20)
            await assembly.aclose(wait_timeout=20)

    asyncio.run(asyncio.wait_for(run(), 90))
