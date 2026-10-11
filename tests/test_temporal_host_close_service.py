"""Every actual hosted version keeps end receivers until shared work stops."""

import asyncio
import os
import threading
import uuid

import pytest

from ralf_agent import (
    ComponentRegistry,
    InMemoryMemory,
    Scope,
    TemporalProfile,
    TemporalProfileCatalog,
    TemporalRuntimeBuilder,
    ThreadedMemoryAdapter,
)
from ralf_agent.errors import CloseIncomplete

from .test_composite_data_context import Provider, agent, registry

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("phase", ["model", "summary", "tool", "session-write"])
def test_actual_host_close_keeps_all_versions_until_shared_handler_and_original_ack(
    tmp_path, phase
):
    async def run():
        from temporalio import activity
        from temporalio.client import Client

        started, release = asyncio.Event(), asyncio.Event()
        thread_started, thread_release, thread_stopped = (threading.Event() for _ in range(3))
        events, identities = [], []

        async def hold():
            identities.append(activity.info().workflow_run_id)
            started.set()
            await release.wait()
            assert activity.info().workflow_run_id == identities[-1]

        def hold_thread():
            if phase != "session-write":
                identities.append(activity.info().workflow_run_id)
            else:
                assert identities  # Original SDK identity captured at the model boundary.
            thread_started.set()
            try:
                assert thread_release.wait(20)
            finally:
                thread_stopped.set()

        class OwnedProvider(Provider):
            async def complete(self, messages, tools):
                if phase == "session-write":
                    identities.append(activity.info().workflow_run_id)
                summary = messages[0]["content"].startswith("context-summary:")
                if (phase == "summary" and summary) or (phase == "model" and not summary):
                    await hold()
                return await super().complete(messages, tools)

            async def aclose(self):
                events.append("resource-closed")

        class Source(InMemoryMemory):
            def append(self, *args, **kwargs):
                if phase == "session-write":
                    hold_thread()
                return super().append(*args, **kwargs)

        factories = ComponentRegistry()
        provider = OwnedProvider()
        factories.register("provider", "held", lambda c, ctx: ctx.own_async(provider))
        source = ThreadedMemoryAdapter(Source(backend_id="profile-close-data"))
        factories.register(
            "session_store",
            "held",
            lambda c, ctx: source,
        )

        def tools_factory(config, context):
            tools = registry([])
            target = tools.get("lookup")
            original = target.handler

            def handler(arguments, invocation):
                if phase == "tool":
                    hold_thread()
                return original(arguments, invocation)

            result = type(tools)()
            result.register(target.spec, handler)
            return result

        factories.register("tools", "held", tools_factory)
        selected = TemporalProfile(
            "held",
            "1",
            {"default": {"adapter": "held"}},
            {
                "tools": {"adapter": "held"},
                "session_store": {"adapter": "held"},
                "context_assembler": {
                    "adapter": "managed-data",
                    "config": {"mode": "model", "summary_max_chars": 256},
                },
            },
            execution={"enable_sessions": True, "session_writes": True, "context_reads": True},
        )
        second = TemporalProfile(**{**selected.to_dict(), "version": "2"})
        catalog = TemporalProfileCatalog(base_dir=tmp_path)
        catalog.register(selected)
        catalog.register(second, default=True)
        queue = "profile-host-close-" + uuid.uuid4().hex
        assembled = await TemporalRuntimeBuilder(factories, base_dir=tmp_path).abuild_catalog(
            catalog, scope=Scope("profile-close", queue)
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        host = None
        try:
            await assembled.start_workers(
                client,
                queue_prefix=queue,
                engine_options={"activity_timeout": 2, "drive_timeout": 10},
            )
            host = assembled.runtime()
            entry = await host.open_session(agent(), "chat", command_id="open")
            turn = await entry.submit("task", command_id="turn", budget=32)
            if phase in {"tool", "session-write"}:
                assert await asyncio.to_thread(thread_started.wait, 15)
            else:
                await asyncio.wait_for(started.wait(), 15)
            assert identities
            with pytest.raises(CloseIncomplete):
                await assembled.aclose(wait_timeout=0)
            assert not events
            assert all(a._worker_stop is None for a in assembled._assemblies)
            assert not thread_stopped.is_set()
            release.set()
            thread_release.set()
            for version in assembled._assemblies:
                assert await version._calls.wait(wait_timeout=15)
                assert await version._runtime.wait_context_executions(wait_timeout=15)
                assert await version._runtime.wait_session_executions(wait_timeout=15)
            if phase in {"tool", "session-write"}:
                assert thread_stopped.is_set()
            # Pollers remain alive for the original end Updates and observation.
            raw = await client.get_workflow_handle(turn.turn.run.run_id).query(
                "view",
                {
                    "scope": {"workspace": "profile-close", "principal": queue},
                    "kind": "diagnostics",
                },
            )
            assert raw["manifest"]["runtime_profile"] == second.identity
            if phase == "session-write":
                assert raw["session_stages"][0]["execution_stopped"] is True
            if phase == "summary":
                assert any(stage.get("summary_response") for stage in raw["context_stages"])
            await assembled.aclose(wait_timeout=15)
            assert events == ["resource-closed"]
            history = await client.get_workflow_handle(turn.turn.run.run_id).fetch_history()
            assert history.events
        finally:
            release.set()
            thread_release.set()
            if host is not None:
                await host.aclose()
            await assembled.aclose(wait_timeout=20)

    asyncio.run(asyncio.wait_for(run(), 90))
