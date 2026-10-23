"""Actual fixed HTTP Activity, durable effects and original History replay."""

import asyncio
import os
import sqlite3
import uuid

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ToolCall,
)
from relf_agent.temporal import replay_temporal_history

from .http_tool_fixture import endpoint
from .test_http_tool_configuration import config, write_config

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Provider:
    identity = {"kind": "http-activity-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if any(item["role"] == "tool" for item in messages):
            return ModelResponse(output="done")
        return ModelResponse(
            tool_calls=[ToolCall(tools[0]["function"]["name"], {"value": 7}, call_id="apply")]
        )


@pytest.mark.parametrize("write", [False, True])
def test_actual_http_activity_approval_restart_once_effect_and_history(tmp_path, write):
    if write and not os.getenv("RALF_TEST_POSTGRES_DSN"):
        pytest.skip("requires actual PostgreSQL EffectJournal")
    with endpoint(tmp_path) as (url, calls, _, _):

        async def run():
            from temporalio.client import Client

            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            queue = "http-" + uuid.uuid4().hex
            declared = write_config(url + "/write") if write else config(url + "/normal")
            declared["tools"][0]["policy"]["requires_approval"] = True
            components = {"tools": {"adapter": "http-json", "config": declared}}
            if write:
                components["effect_journal"] = {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_TEST_POSTGRES_DSN",
                        "backend_id": "http-effects",
                        "initialize": True,
                    },
                }
            profile = TemporalProfile(
                "http-service", "1", {"default": {"adapter": "http-fixture"}}, components
            )
            registry = ComponentRegistry()
            registry.register("provider", "http-fixture", lambda config, context: Provider())
            original = None
            scope = Scope("http-service", queue)
            tool = "http_write" if write else "http_read"
            for index in range(2):
                assembly = await TemporalRuntimeBuilder(registry).abuild(profile, scope=scope)
                try:
                    await assembly.start_worker(client, task_queue=queue)
                    engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                    handle = await engine.submit(
                        AgentSpec("query", "Use declared tool", tools=(tool,)),
                        "query",
                        command_id="same",
                    )
                    if index == 0:
                        original = handle
                        status = await engine.drive(handle.run_id, wait_seconds=20)
                        assert status.state == "waiting_approval" and not calls, status.error
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
                        assert status.state == "succeeded" and status.result == "done"
                        await replay_temporal_history(
                            await client.get_workflow_handle(handle.run_id).fetch_history()
                        )
                finally:
                    await assembly.aclose(wait_timeout=30)

        asyncio.run(run())
        assert len(calls) == 1
        if write:
            with sqlite3.connect(tmp_path / "business.sqlite") as connection:
                assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
