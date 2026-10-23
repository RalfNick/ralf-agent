"""Root resource wrappers reuse existing async backend factory ownership."""

import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import ComponentRegistry

from .composite_session_fixture import definitions
from .remote_session_fixture import RemoteMemory


def profile():
    return r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "conversation_resource": {
                "adapter": "session-resource",
                "config": {
                    "namespaces": ["red", "blue"],
                    "default_namespace": "red",
                    "backend": {"adapter": "foreign"},
                },
            }
        },
    )


def test_remote_root_wrapper_async_factory_and_owned_close(tmp_path):
    async def scenario():
        made = []

        class Backend(RemoteMemory):
            closes = 0

            async def aclose(self):
                self.closes += 1
                self.close()

        async def factory(config, context):
            backend = Backend(tmp_path / "data.sqlite")
            made.append(backend)
            return context.own_async(backend)

        registry = ComponentRegistry()
        registry.register_async("session_store", "foreign", factory)
        runtime = await r.Runtime.afrom_profile(
            profile(), tmp_path / "run.sqlite", builder=r.RuntimeBuilder(registry)
        )
        async with runtime:
            agent = runtime.create_agent(definitions()["team"])
            red = await agent.open_session("s", command_id="red")
            blue = await agent.open_session("s", namespace="blue", command_id="blue")
            for session in (red, blue):
                one = await session.submit(
                    "q", command_id="turn-" + session.ref.key.namespace, budget=128
                )
                assert (await one.wait(wait_timeout=2)).snapshot.state == "succeeded"
                assert made[0].memory.read(r.Scope(), session.ref.key.storage_key)[0] == 1
            assert made[0].closes == 0
        assert made[0].closes == 1

    asyncio.run(scenario())


def test_sync_builder_refuses_remote_async_wrapper_before_store(tmp_path):
    registry = ComponentRegistry()

    async def factory(config, context):
        pytest.fail("synchronous build entered async factory")

    registry.register_async("session_store", "foreign", factory)
    with pytest.raises(ValidationError):
        r.RuntimeBuilder(registry).build(profile(), tmp_path / "run.sqlite")
    assert not (tmp_path / "run.sqlite").exists()
