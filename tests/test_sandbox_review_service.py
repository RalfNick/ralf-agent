"""Sole-review I2 against actual original native duplicate ownership."""

import asyncio
import os

import pytest

import ralf_agent as r

from .test_sandbox_tools import context

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires actual local Docker fixture"
)


def test_rejected_duplicate_source_close_cannot_stop_original_live_native_call():
    async def run():
        port = r.DockerSandbox(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="source-duplicate-review",
        )
        await port.aopen()
        first, second = (
            r.SandboxToolSource(port, version="1"),
            r.SandboxToolSource(port, version="1"),
        )
        task = None
        try:
            descriptor = (await first.list_tools())[0]
            arguments = {"argv": ["/bin/sleep", "30"]}
            task = asyncio.create_task(first.call_tool(descriptor, arguments, context()))
            for _ in range(500):
                if first._calls:
                    identifier = next(iter(first._calls))
                    if (await port.observe(r.Scope(), identifier)).state == "running":
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Original native container never reported running")
            with pytest.raises(r.SandboxUnavailable):
                await second.call_tool(descriptor, arguments, context())
            await second.aclose(wait_timeout=5)
            assert first._calls and not task.done()
            assert (await port.observe(r.Scope(), identifier)).state == "running"
            assert second._calls == {}
        finally:
            await first.aclose(wait_timeout=15)
            await second.aclose(wait_timeout=15)
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await port.aclose(wait_timeout=15)

    asyncio.run(run())
