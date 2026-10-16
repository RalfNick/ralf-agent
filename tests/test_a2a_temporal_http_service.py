"""Installed real HTTP processes retain original Temporal/PG controls and events."""

import asyncio
import json
import os
import signal
import socket
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from ralf_agent import ModelResponse, ToolCall, ToolExecutionOwner, ToolRegistry, ToolSpec
from ralf_agent.a2a import A2AClient, A2ARemoteError
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.types import canonical
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal and PostgreSQL",
)


class HTTPProvider:
    identity = {"kind": "http-temporal-acceptance", "version": "1"}

    async def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return ModelResponse(output=json.loads(messages[-1]["content"]))
        return ModelResponse(tool_calls=(ToolCall("write", {}, "original-write"),))


@asynccontextmanager
async def http_host(directory):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    environment = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "TMPDIR", "RALF_TEST_TEMPORAL_ADDRESS")
        if k in os.environ
    }
    path = directory / f"http-{port}.log"
    with path.open("w") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(Path(__file__).with_name("a2a_temporal_http_fixture.py")),
            str(directory),
            str(listener.fileno()),
            pass_fds=(listener.fileno(),),
            env=environment,
            stdout=log,
            stderr=log,
        )
        client = A2AClient(
            f"http://127.0.0.1:{port}/rpc", headers={"Authorization": "Bearer owner"}
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as readiness:
                async with asyncio.timeout(15):
                    while process.returncode is None:
                        try:
                            result = await readiness.get(
                                f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=0.2
                            )
                            if result.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.02)
                    else:
                        pytest.fail("owned HTTP host startup failed; see captured local log")
            yield client, process, port
        finally:
            await client.aclose()
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()
            listener.close()
        assert process.returncode in (0, -signal.SIGTERM)
        closed = json.loads((directory / f"host-closed-{process.pid}.json").read_text())
        assert all(closed[k] is True for k in ("engine_closed", "inbox_closed"))


async def wait_task(client, run_id, expected):
    async with asyncio.timeout(30):
        while True:
            value = await client.get_task(run_id)
            if value["metadata"]["ralf"]["state"] == expected:
                return value
            await asyncio.sleep(0.05)


@pytest.mark.parametrize("mode", ["approval", "unknown-write", "cancel"])
def test_actual_http_restart_recovers_original_temporal_pg_control_and_event_cursor(tmp_path, mode):
    uncertain, cancelled = mode == "unknown-write", mode == "cancel"

    async def run():
        from psycopg import AsyncConnection, sql
        from psycopg.conninfo import make_conninfo

        schema = "ralf_http_" + uuid.uuid4().hex
        owner = await AsyncConnection.connect(os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True)
        journal = business = None
        verified = False
        try:
            await owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            dsn = make_conninfo(
                os.environ["RALF_TEST_POSTGRES_DSN"], options="-csearch_path=" + schema
            )
            journal = await PostgresEffectJournal.connect(dsn, backend_id=schema)
            await journal.initialize()
            business = await AsyncConnection.connect(dsn, autocommit=True)
            await business.execute(
                "CREATE TABLE business(effect_key TEXT PRIMARY KEY, result TEXT NOT NULL, calls INT NOT NULL)"
            )

            async def write(arguments, context):
                result = {"changed": True, "effect_key": context.effect_key}
                await business.execute(
                    "INSERT INTO business VALUES (%s,%s,1) ON CONFLICT(effect_key) DO UPDATE SET calls=business.calls+1",
                    (context.effect_key, canonical(result)),
                )
                if uncertain:
                    raise ConnectionError("genuine external commit before response loss")
                return result

            tools = ToolRegistry()
            tools.register(
                ToolSpec(
                    "write",
                    "Write once",
                    {"type": "object"},
                    effect="unqueryable_write",
                    requires_approval=not uncertain,
                ),
                write,
            )
            options = {
                "providers": {"default": HTTPProvider()},
                "tools": tools,
                "journal": journal,
                "tool_execution": ToolExecutionOwner(version="http-temporal-1"),
            }
            async with public_system(tmp_path, options=options) as system:
                (tmp_path / "host.json").write_text(
                    json.dumps(
                        {
                            "scope": asdict(system.scope),
                            "namespace": system.namespace["name"],
                            "queue": system.queue,
                            "release": system.runtime.orchestration_release,
                        }
                    )
                )
                run_id = root_run_id(system.policy.deployment_id, asdict(system.scope), "original")
                system.targets.add(run_id)
                async with system.worker():
                    async with http_host(tmp_path) as (client, first, port):
                        task = await client.send_message("original", "change")
                        assert task["id"] == run_id
                        waiting = await wait_task(
                            client,
                            run_id,
                            "waiting_reconciliation" if uncertain else "waiting_approval",
                        )
                        page = await client.get_events(run_id, limit=1)
                        assert len(page["events"]) == 1
                        cursor = page["cursor_token"]
                        seen = [page["events"][0]["event"]["seq"]]
                        async with httpx.AsyncClient(trust_env=False) as unauthorized:
                            denied = await unauthorized.post(
                                f"http://127.0.0.1:{port}/rpc",
                                json={
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "tasks/get",
                                    "params": {"id": run_id},
                                },
                            )
                            assert denied.status_code == 401
                        # Inbox is full, yet old identity and controls remain reachable.
                        with pytest.raises(A2ARemoteError) as full:
                            await client.send_message("other", "new business")
                        assert full.value.rpc_code == -32603
                        assert (await system.engine.deployment_diagnostics())["counts"][
                            "command_records"
                        ] == 1
                        assert (await client.get_by_message("original"))["id"] == run_id
                    assert first.returncode is not None
                    assert (await system.engine.status(run_id)).state == waiting["metadata"][
                        "ralf"
                    ]["state"]
                    async with http_host(tmp_path) as (client, second, _):
                        assert (await client.send_message("original", "change"))["id"] == run_id
                        assert (await client.resume_task(run_id))["metadata"]["ralf"][
                            "recoveryHint"
                        ]["durable"] is False
                        if cancelled:
                            cancelled_task = await client.cancel_task(run_id, command_id="control")
                            assert cancelled_task["metadata"]["ralf"]["state"] == "cancelled"
                            # Existing A2A cancellation returns a Task. Its native
                            # command receipt remains replayable in the authority.
                            native = await system.engine.cancel(run_id, command_id="control")
                            assert (
                                await system.engine.cancel(run_id, command_id="control") == native
                            )
                            with pytest.raises(A2ARemoteError) as terminal:
                                await client.cancel_task(run_id, command_id="control")
                            assert terminal.value.rpc_code == -32002
                        elif uncertain:
                            diagnostics = await system.engine.diagnostics(run_id)
                            action = next(
                                a for a in diagnostics.snapshot.actions if a["kind"] == "tool"
                            )
                            row = await (
                                await business.execute("SELECT result,calls FROM business")
                            ).fetchone()
                            assert row[1] == 1
                            genuine = json.loads(row[0])
                            receipt = await client.reconcile_task(
                                run_id, action["id"], genuine, command_id="control"
                            )
                            repeat = await client.reconcile_task(
                                run_id, action["id"], genuine, command_id="control"
                            )
                        else:
                            pending = waiting["metadata"]["ralf"]["pending"][0]
                            receipt = await client.approve_task(
                                run_id,
                                pending["action_id"],
                                pending["digest"],
                                command_id="control",
                            )
                            repeat = await client.approve_task(
                                run_id,
                                pending["action_id"],
                                pending["digest"],
                                command_id="control",
                            )
                        if not cancelled:
                            assert (
                                repeat == receipt and receipt["receipt"]["apply_state"] == "applied"
                            )
                        await wait_task(client, run_id, "cancelled" if cancelled else "succeeded")
                        await system.count(0)
                        while True:
                            page = await client.get_events(run_id, cursor=cursor, limit=3)
                            if not page["events"]:
                                break
                            seen.extend(record["event"]["seq"] for record in page["events"])
                            cursor = page["cursor_token"]
                        assert seen == list(range(1, len(seen) + 1))
                        original_events = await system.engine.events(run_id)
                        assert len(seen) == len(original_events)
                        await system.count(0)
                        rows = await (
                            await business.execute("SELECT calls FROM business")
                        ).fetchall()
                        assert rows == ([] if cancelled else [(1,)])
                        states = await (
                            await journal.connection.execute(
                                "SELECT state FROM ralf_temporal_effects"
                            )
                        ).fetchall()
                        assert states == ([] if cancelled else [("adopted",)])
                        assert await system.evidence(run_id) == 1
                    assert second.returncode is not None
                (tmp_path / "http-result.json").write_text(
                    json.dumps(
                        {
                            "case": mode,
                            "actual_http_hosts": 2,
                            "business_writes": 0 if cancelled else 1,
                            "postgres_effect_adopted": not cancelled,
                            "original_events_observed": len(seen),
                            "event_cursor_reconnected": True,
                            "root_retired": True,
                            "model_api_calls": 0,
                        },
                        indent=2,
                    )
                )
            verified = True
        finally:
            if journal is not None:
                await journal.aclose()
            if business is not None:
                await business.close()
            if verified:
                await owner.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
            await owner.close()
            (tmp_path / "postgres-cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_schema": schema,
                        "removed_after_verified_retirement": verified,
                        "retained_on_incomplete": not verified,
                    }
                )
            )

    asyncio.run(asyncio.wait_for(run(), 180))
