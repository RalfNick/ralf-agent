"""Actual CLI Activity, approval/restart and original Temporal History."""

import asyncio
import os
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

from .test_cli_tool_configuration import config

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Provider:
    identity = {"kind": "cli-activity-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if any(item["role"] == "tool" for item in messages):
            return ModelResponse(output="done")
        return ModelResponse(tool_calls=[ToolCall("cli_read", {"value": 7}, call_id="query")])


def test_actual_cli_activity_approval_restart_original_receipt_and_history(tmp_path):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "cli-" + uuid.uuid4().hex
        scope = Scope("cli", queue)
        declared = config(tmp_path)
        declared["tools"][0]["policy"]["requires_approval"] = True
        profile = TemporalProfile(
            "cli-service",
            "1",
            {"default": {"adapter": "cli-fixture"}},
            {"tools": {"adapter": "cli-json", "config": declared}},
        )
        registry = ComponentRegistry()
        registry.register("provider", "cli-fixture", lambda config, context: Provider())
        original = None
        for index in range(2):
            assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile, scope=scope
            )
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(
                    AgentSpec("query", "Use query", tools=("cli_read",)), "query", command_id="same"
                )
                if index == 0:
                    original = handle
                    pending = (await engine.drive(handle.run_id, wait_seconds=20)).pending[0]
                    assert not (tmp_path / "pid").exists()
                else:
                    assert handle == original
                    receipt = await engine.approve(
                        handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
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
                    result = await engine.drive(handle.run_id, wait_seconds=20)
                    assert result.state == "succeeded" and result.result == "done"
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
                    assert (tmp_path / "started").exists()
            finally:
                await assembly.aclose(wait_timeout=30)

    asyncio.run(run())


class WriteProvider:
    identity = {"kind": "cli-write-activity-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if any(item["role"] == "tool" for item in messages):
            return ModelResponse(output="written")
        return ModelResponse(tool_calls=[ToolCall("cli_write", {"value": 7}, call_id="apply")])


@pytest.mark.skipif(
    not os.getenv("RALF_TEST_POSTGRES_DSN"), reason="requires actual PostgreSQL EffectJournal"
)
def test_actual_cli_write_uses_durable_journal_and_once_business_effect(tmp_path):
    import hashlib
    import sqlite3
    import sys

    from ralf_agent.cli_starter import CLI_FILES

    async def run():
        from temporalio.client import Client

        program = tmp_path / "business_tool.py"
        program.write_text(CLI_FILES["business_tool.py"])
        schema = {
            "type": "object",
            "properties": {"value": {"type": "integer"}, "effect_key": {"type": "string"}},
            "required": ["value", "effect_key"],
            "additionalProperties": False,
        }
        declared = {
            "tools": [
                {
                    "descriptor": {
                        "name": "write",
                        "description": "Write once",
                        "input_schema": schema,
                        "output_schema": {"type": "object"},
                    },
                    "command": [sys.executable, str(program), str(tmp_path / "business.sqlite")],
                    "version": hashlib.sha256(program.read_bytes()).hexdigest(),
                    "prefix": "cli_",
                    "policy": {
                        "version": "1",
                        "effect": "idempotent_write",
                        "requires_approval": True,
                        "effect_key_argument": "effect_key",
                    },
                }
            ]
        }
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "cli-write-" + uuid.uuid4().hex
        scope = Scope("cli-write", queue)
        profile = TemporalProfile(
            "cli-write-service",
            "1",
            {"default": {"adapter": "cli-write-fixture"}},
            {
                "tools": {"adapter": "cli-json", "config": declared},
                "effect_journal": {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_TEST_POSTGRES_DSN",
                        "backend_id": "cli-effects",
                        "initialize": True,
                    },
                },
            },
        )
        registry = ComponentRegistry()
        registry.register("provider", "cli-write-fixture", lambda config, context: WriteProvider())
        original = None
        for index in range(2):
            assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile, scope=scope
            )
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(
                    AgentSpec("apply", "Use write", tools=("cli_write",)),
                    "apply",
                    command_id="same",
                )
                if index == 0:
                    original = handle
                    status = await engine.drive(handle.run_id, wait_seconds=20)
                    assert status.state == "waiting_approval"
                    pending = status.pending[0]
                    assert not (tmp_path / "business.sqlite").exists()
                else:
                    assert handle == original
                    receipt = await engine.approve(
                        handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
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
                    result = await engine.drive(handle.run_id, wait_seconds=20)
                    assert result.state == "succeeded" and result.result == "written"
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)
        with sqlite3.connect(tmp_path / "business.sqlite") as connection:
            assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
        assert (tmp_path / "call-audit").read_text().splitlines() == ["call"]

    asyncio.run(run())
