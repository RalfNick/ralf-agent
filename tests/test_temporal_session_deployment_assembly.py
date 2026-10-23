"""Owned Session deployment closes original histories before its receiver."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent import (
    ComponentRegistry,
    DeploymentAdmissionPolicy,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from relf_agent.errors import CloseIncomplete
from relf_agent.runtime_builder import EchoProvider


def test_session_close_keeps_receiver_and_owned_resources_for_retry(tmp_path, monkeypatch):
    async def run():
        from relf_agent import temporal
        from relf_agent import temporal_session_deployment_close as closing

        events = []

        class Provider(EchoProvider):
            async def aclose(self):
                events.append("provider-close")

        class Worker:
            async def __aenter__(self):
                events.append("worker-start")

            async def __aexit__(self, *args):
                events.append("worker-stop")

        async def close(runtime, *, client, scope, task_queue, wait_timeout):
            assert client.namespace == "original" and task_queue == "original"
            assert "worker-stop" not in events and "provider-close" not in events
            events.append("session-close")
            if events.count("session-close") == 1:
                raise CloseIncomplete("original session ACK remains pending")

        registry = ComponentRegistry()
        registry.register(
            "provider", "owned", lambda config, context: context.own_async(Provider("owned"))
        )
        profile = TemporalProfile(
            "session",
            "1",
            {"default": {"adapter": "owned"}},
            execution={"enable_sessions": True, "deployment_sessions": True},
        )
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile, admission_policy=DeploymentAdmissionPolicy("close-session")
        )
        monkeypatch.setattr(temporal, "build_temporal_worker", lambda *args, **kw: Worker())
        monkeypatch.setattr(closing, "close", close)
        await assembly.start_worker(SimpleNamespace(namespace="original"), task_queue="original")
        with pytest.raises(CloseIncomplete):
            await assembly.aclose(wait_timeout=1)
        assert events == ["worker-start", "session-close"]
        await assembly.aclose(wait_timeout=1)
        assert events == [
            "worker-start",
            "session-close",
            "session-close",
            "worker-stop",
            "provider-close",
        ]

    asyncio.run(run())
