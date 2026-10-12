"""Original SandboxToolSource against the actual default native service."""

import asyncio
import os

import pytest

import ralf_agent as r
from ralf_agent.types import InvocationContext

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires explicit actual local Docker fixture"
)


def provider():
    return r.DockerSandbox(
        os.environ["RALF_TEST_DOCKER_SOCKET"],
        os.environ["RALF_TEST_DOCKER_IMAGE"],
        version="original-source-test",
    )


def context():
    import uuid

    return InvocationContext(r.Scope(), uuid.uuid4().hex, "action", "attempt", "effect", "epoch")


def test_actual_declared_default_original_tool_approval_policy_and_native_completion(tmp_path):
    async def run():
        profile = r.RuntimeProfile(
            "sandbox",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {
                "tools": {
                    "adapter": "sandbox-docker",
                    "config": {
                        "version": "1",
                        "socket_path": os.environ["RALF_TEST_DOCKER_SOCKET"],
                        "image": os.environ["RALF_TEST_DOCKER_IMAGE"],
                        "max_timeout": 2,
                        "prefix": "native_",
                    },
                }
            },
        )
        runtime = await r.RuntimeBuilder().abuild(profile, tmp_path / "runs.sqlite")
        try:
            tool = runtime.tools.get("native_sandbox_run")
            assert (
                tool.spec.effect == "read_only"
                and tool.spec.requires_approval is True
                and tool.spec.cost == 1
            )
            value = await tool.handler({"argv": ["/bin/sh", "-c", "id -u; echo native"]}, context())
            assert (
                value["stdout"] == "65534\nnative\n" and value["observation"]["state"] == "stopped"
            )
        finally:
            await runtime.aclose()

    asyncio.run(run())


def test_actual_observer_cancel_retains_owned_call_then_source_close_stops_only_borrowed_invocation():
    async def run():
        port = provider()
        source, task = None, None
        try:
            await port.aopen()
            source = r.SandboxToolSource(port, version="1")
            task = asyncio.create_task(
                source.call_tool(
                    (await source.list_tools())[0], {"argv": ["/bin/sleep", "30"]}, context()
                )
            )
            for _ in range(500):
                if source._calls:
                    identifier = next(iter(source._calls))
                    if (await port.observe(r.Scope(), identifier)).state == "running":
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Original native call never started")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert source._calls and port._tracker.has_active
            assert (await port.observe(r.Scope(), identifier)).state == "running"
            with pytest.raises(r.CloseIncomplete):
                await source.aclose(wait_timeout=0)
            await source.aclose(wait_timeout=15)
            assert source._calls == {} and not port._tracker.has_active
            assert (await port.observe(r.Scope(), identifier)).state == "not_found"
            result = await port.run(
                r.Scope(),
                r.SandboxRequest(["/bin/echo", "shared"]),
                invocation_id=identifier + "-borrowed",
            )
            assert result.stdout == "shared\n"
        finally:
            if source is not None:
                await source.aclose(wait_timeout=15)
            await port.aclose(wait_timeout=15)
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
