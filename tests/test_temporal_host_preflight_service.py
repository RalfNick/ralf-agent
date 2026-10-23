"""Actual SDK receives validated options and retains original command receipts."""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest

from relf_agent import AgentSpec, Scope, TemporalRuntimeBuilder
from relf_agent.errors import ValidationError
from relf_agent.temporal import replay_temporal_history

from .test_temporal_catalog_assembly import catalog

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_sdk_validated_options_retry_restart_and_original_receipt(tmp_path):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        scope = Scope("startup", uuid.uuid4().hex)
        prefix = "startup-" + scope.principal
        selected = catalog()
        original = None
        # Zero task-queue rate is SDK-valid but suppresses activity execution.
        # Verify constructor compatibility on separate queues, then run normally.
        zero_host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(
            selected, scope=scope
        )
        try:
            await zero_host.start_workers(
                client,
                queue_prefix=prefix + "-zero",
                worker_options={
                    "nonsticky_to_sticky_poll_ratio": 0,
                    "max_task_queue_activities_per_second": 0,
                    "identity": "ralf-startup-preflight",
                },
            )
        finally:
            await zero_host.aclose(wait_timeout=30)
        for index in range(2):
            host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(
                selected, scope=scope
            )
            try:
                with pytest.raises(ValidationError):
                    await host.start_workers(client, engine_options={"unknown": True})
                assert host._client is None and host._start_task is None
                await host.start_workers(
                    client,
                    queue_prefix=prefix,
                    engine_options={"activity_timeout": 2, "drive_timeout": 30},
                    worker_options={
                        "max_cached_workflows": 0,
                        "max_concurrent_workflow_tasks": 1,
                        "graceful_shutdown_timeout": timedelta(seconds=1),
                        "debug_mode": False,
                        "nonsticky_to_sticky_poll_ratio": 0,
                        "identity": "ralf-startup-preflight",
                    },
                )
                run = await host.runtime().submit(
                    AgentSpec("a", "Answer"), "question", command_id="original"
                )
                result = await run.wait(wait_timeout=30, terminal_only=True)
                assert result.snapshot.state == "succeeded"
                if index == 0:
                    original = run.ref, run.receipt
                else:
                    assert (run.ref, run.receipt) == original
                    await replay_temporal_history(
                        await client.get_workflow_handle(run.ref.run_id).fetch_history()
                    )
            finally:
                await host.aclose(wait_timeout=30)

    asyncio.run(run())
