"""Actual MCP HTTP Activity, original durable journal and History recovery."""

import asyncio
import json
import os
import sqlite3
import uuid

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ToolCall,
)
from ralf_agent.temporal import replay_temporal_history

from .mcp_http_fixture import peer
from .test_mcp_http import business_calls
from .test_mcp_http_configuration import config

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Provider:
    identity = {"kind": "mcp-http-activity-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if any(item["role"] == "tool" for item in messages):
            return ModelResponse(output="done")
        return ModelResponse(
            tool_calls=[ToolCall(tools[0]["function"]["name"], {"value": 7}, call_id="apply")]
        )


@pytest.mark.parametrize(
    "mode,write", [("sse", False), ("json", True), ("sse", True), ("write-lost", True)]
)
def test_actual_mcp_http_approval_restart_effect_evidence_and_history(tmp_path, mode, write):
    if write and not os.getenv("RALF_TEST_POSTGRES_DSN"):
        pytest.skip("requires actual PostgreSQL EffectJournal")
    with peer(mode, root=tmp_path, write=write) as (url, calls, _, _):

        async def run():
            from temporalio.client import Client

            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            queue = "mcp-http-" + uuid.uuid4().hex
            declared = config(url, write=write)
            declared["servers"][0]["policies"]["write" if write else "read"][
                "requires_approval"
            ] = True
            components = {"tools": {"adapter": "mcp-http", "config": declared}}
            if write:
                components["effect_journal"] = {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_TEST_POSTGRES_DSN",
                        "backend_id": "mcp-http-effects",
                        "initialize": True,
                    },
                }
            profile = TemporalProfile(
                "mcp-http", "1", {"default": {"adapter": "mcp-fixture"}}, components
            )
            registry = ComponentRegistry()
            registry.register("provider", "mcp-fixture", lambda config, context: Provider())
            original = None
            scope = Scope("mcp-http-service", queue)
            for index in range(3 if mode == "write-lost" else 2):
                assembly = await TemporalRuntimeBuilder(registry).abuild(profile, scope=scope)
                try:
                    await assembly.start_worker(client, task_queue=queue)
                    engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                    handle = await engine.submit(
                        AgentSpec(
                            "query",
                            "Use declared tool",
                            tools=("mcp_write" if write else "mcp_read",),
                        ),
                        "query",
                        command_id="same",
                    )
                    if index == 0:
                        original = handle
                        status = await engine.drive(handle.run_id, wait_seconds=20)
                        assert status.state == "waiting_approval" and not business_calls(calls), (
                            status.error
                        )
                        pending = status.pending[0]
                    else:
                        assert handle == original
                        receipt = await engine.approve(
                            handle.run_id,
                            pending["action_id"],
                            pending["digest"],
                            command_id="approve",
                        )
                        assert (
                            await engine.approve(
                                handle.run_id,
                                pending["action_id"],
                                pending["digest"],
                                command_id="approve",
                            )
                            == receipt
                        )
                        status = await engine.drive(handle.run_id, wait_seconds=20)
                        if mode == "write-lost" and index == 1:
                            assert status.state == "waiting_reconciliation", status
                            assert len(business_calls(calls)) == 1
                        elif mode == "write-lost":
                            # Original Temporal reconciliation never resends an
                            # unknown handler, including an idempotent one.
                            assert status.state == "waiting_reconciliation", status
                            action = next(item for item in status.actions if item["kind"] == "tool")
                            await engine.reconcile(
                                handle.run_id, action["id"], command_id="query", query=True
                            )
                            assert (
                                await engine.drive(handle.run_id, wait_seconds=20)
                            ).state == "waiting_reconciliation"
                            assert len(business_calls(calls)) == 1
                            with sqlite3.connect(tmp_path / "business.sqlite") as connection:
                                output = json.loads(
                                    connection.execute(
                                        "SELECT result FROM effects WHERE key=?",
                                        (action["effect_key"],),
                                    ).fetchone()[0]
                                )
                            evidence = {
                                "content": [{"type": "text", "text": "confirmed"}],
                                "structuredContent": output,
                            }
                            receipt = await engine.reconcile(
                                handle.run_id,
                                action["id"],
                                evidence,
                                command_id="verified-business-receipt",
                            )
                            assert (
                                await engine.reconcile(
                                    handle.run_id,
                                    action["id"],
                                    evidence,
                                    command_id="verified-business-receipt",
                                )
                                == receipt
                            )
                            done = await engine.drive(handle.run_id, wait_seconds=20)
                            assert done.state == "succeeded" and done.result == "done", done
                        else:
                            assert status.state == "succeeded" and status.result == "done", status
                        await replay_temporal_history(
                            await client.get_workflow_handle(handle.run_id).fetch_history()
                        )
                finally:
                    await assembly.aclose(wait_timeout=30)

        asyncio.run(run())
        requests = business_calls(calls)
        assert len(requests) == 1
        if write:
            assert (
                len({item["message"]["params"]["arguments"]["effect_key"] for item in requests})
                == 1
            )
            with sqlite3.connect(tmp_path / "business.sqlite") as connection:
                assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
