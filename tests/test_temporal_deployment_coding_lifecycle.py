"""Owned SDK close retains its fixed queue before releasing component clients."""

import asyncio
from types import SimpleNamespace

from relf_agent import Scope, TemporalProfile
from relf_agent.runtime_lifecycle import BuildContext
from relf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly


def test_owned_coding_close_supplies_original_queue_before_client_cleanup(tmp_path, monkeypatch):
    from relf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        events = []
        scope = Scope("original", "owner")
        client = SimpleNamespace(namespace="original")

        class Resource:
            async def aclose(self):
                events.append("client-close")

        async def drain(**kwargs):
            events.append("drain")

        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        context.own_async(Resource())
        runtime = SimpleNamespace(
            orchestration_release={
                "binding_protocol": 22,
                "deployment_admission_protocol": {"version": 3},
            },
            coding_execution=True,
            _deployment_public_execution=True,
            close_deployment_execution=drain,
            close_context_execution=drain,
            close_session_execution=drain,
        )
        profile = TemporalProfile("original-profile", "1", {"default": {"adapter": "echo"}})
        assembly = TemporalRuntimeAssembly(runtime, context, profile, scope)
        assembly._bind_client(client, "original-queue")

        async def close(runtime, *, client, scope, task_queue=None):
            assert client is assembly._client and scope is assembly.scope
            assert task_queue == "original-queue"
            assert "client-close" not in events
            events.append("original-registry-close")

        monkeypatch.setattr(bridge, "close", close)
        await assembly.aclose()
        assert events == ["original-registry-close", "drain", "drain", "drain", "client-close"]

    asyncio.run(run())
