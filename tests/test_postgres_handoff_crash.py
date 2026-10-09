import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, LocalEngine, MessageEnvelope, Scope, SQLiteStore, ToolRegistry
from ralf_agent.handoff import EngineCommandDispatcher, LocalCommandAdapter, consume_delivery
from ralf_agent.postgres_handoff import PostgresInbox, PostgresOutbox
from ralf_agent.redis_streams import RedisStreamsBus
from ralf_agent.runtime_builder import EchoProvider

from .test_postgres_adapter import postgres_dsn as _postgres_dsn
from .test_redis_streams import redis_service as _redis_service

postgres_dsn, redis_service = _postgres_dsn, _redis_service


@pytest.mark.parametrize("mode", ["inbox", "outbox"])
def test_real_pg_redis_process_loss_repairs_stable_handoff(
    tmp_path, postgres_dsn, redis_service, mode
):
    async def run():
        scope = Scope("pg-crash-" + uuid.uuid4().hex, "owner")
        message = MessageEnvelope(
            "original", "commands", {"kind": "submit", "spec": "agent", "input": "hello"}
        )
        bus = await RedisStreamsBus.connect(redis_service, backend_id="crash", prefix="pg-crash")
        store = await (PostgresInbox if mode == "inbox" else PostgresOutbox).connect(
            postgres_dsn, backend_id="pg-crash"
        )
        database = tmp_path / "runs.sqlite"
        try:
            await store.initialize()
            await bus.ensure_group(scope, "commands", "workers")
            if mode == "inbox":
                await bus.publish(scope, message)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
                "RALF_TEST_POSTGRES_DSN": postgres_dsn,
                "RALF_TEST_REDIS_URL": redis_service,
            }
            crashed = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable,
                    "-m",
                    "tests.handoff_pg_crash_fixture",
                    mode,
                    str(database),
                    scope.workspace,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert crashed.returncode == 78, crashed.stderr
            original = json.loads(crashed.stdout.strip())
            assert len(await store.pending(scope)) == 1
            if mode == "inbox":
                with LocalEngine(
                    SQLiteStore(database),
                    providers={"default": EchoProvider("crash")},
                    tools=ToolRegistry(),
                    scope=scope,
                ) as engine:
                    dispatcher = EngineCommandDispatcher(
                        LocalCommandAdapter(engine), specs={"agent": AgentSpec("agent", "Answer")}
                    )
                    delivery = (
                        await bus.claim(scope, "commands", "workers", "replacement", min_idle_ms=0)
                    )[0]
                    replay = await consume_delivery(
                        bus, store, dispatcher, scope, "commands", "workers", delivery
                    )
                    assert replay == original
                    assert engine.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
                    assert (await engine.drive(replay["run_id"])).state == "succeeded"
                    assert engine.diagnostics(replay["run_id"]).budget["spent"] == 1
                    assert (
                        await bus.claim(scope, "commands", "workers", "later", min_idle_ms=0) == []
                    )
            else:
                assert await store.flush(bus, scope) == 1
                assert await store.result(scope, "original") == original
                assert (
                    len(await bus.receive(scope, "commands", "workers", "replacement", limit=100))
                    == 1
                )
                assert await store.flush(bus, scope) == 0
        finally:
            await store.aclose()
            await bus.aclose()

    asyncio.run(run())
