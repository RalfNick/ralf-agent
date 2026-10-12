"""Real process death releases native ownership without restarting its container."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from functools import partial

import pytest

import ralf_agent as r

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"), reason="requires explicit actual Docker fixture"
)


def test_actual_dead_dispatcher_queries_same_running_native_container(tmp_path):
    identifier = "cold-" + uuid.uuid4().hex
    marker = tmp_path / "running.json"
    child_code = """
import asyncio,json,os,sys
from pathlib import Path
import ralf_agent as r
async def main():
 p=r.DockerSandbox(os.environ['RALF_TEST_DOCKER_SOCKET'],os.environ['RALF_TEST_DOCKER_IMAGE'],version='cold-test')
 await p.aopen()
 task=asyncio.create_task(p.run(r.Scope(),r.SandboxRequest(['/bin/sh','-c','echo once; sleep 4']),invocation_id=sys.argv[1]))
 for _ in range(1000):
  state=await p.observe(r.Scope(),sys.argv[1])
  if state.state=='running':
   Path(sys.argv[2]).write_text(json.dumps(state.to_dict()))
   break
  await asyncio.sleep(.01)
 else:raise AssertionError('native container never started')
 await task
 await p.aclose()
asyncio.run(main())
"""

    async def run():
        child = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-c", child_code, identifier, str(marker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "PYTHONPATH": str(__import__("pathlib").Path(r.__file__).parent.parent),
            },
        )
        provider = r.DockerSandbox(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="cold-test",
        )
        try:
            for _ in range(1000):
                if marker.exists():
                    break
                if child.poll() is not None:
                    pytest.fail(child.communicate()[1].decode())
                await asyncio.sleep(0.01)
            assert marker.exists()
            original = json.loads(marker.read_text())
            child.kill()
            assert await asyncio.to_thread(child.wait, 5) < 0
            await provider.aopen()
            result = await provider.run(
                r.Scope(),
                r.SandboxRequest(["/bin/sh", "-c", "echo once; sleep 4"]),
                invocation_id=identifier,
            )
            assert (
                result.native_id == original["native_id"]
                and result.stdout == "once\n"
                and result.exit_code == 0
            )
            assert (await provider.observe(r.Scope(), identifier)).state == "not_found"
        finally:
            if child.poll() is None:
                child.kill()
            await asyncio.to_thread(child.wait, 5)
            child.communicate()
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_created_orphan_is_not_stop_evidence_and_resumes_original_first_start():
    async def run():
        provider = r.DockerSandbox(
            os.environ["RALF_TEST_DOCKER_SOCKET"],
            os.environ["RALF_TEST_DOCKER_IMAGE"],
            version="orphan-test",
        )
        identifier = "orphan-" + uuid.uuid4().hex
        native = None
        try:
            await provider.aopen()
            request = r.SandboxRequest(["/bin/echo", "original"])
            created = await provider._tracked(
                partial(
                    provider._control.json,
                    "POST",
                    "containers/create?name=" + provider._name(r.Scope(), identifier),
                    body=provider._container_config(r.Scope(), identifier, request),
                    accepted=(201,),
                )
            )
            native = created["Id"]
            observed = await provider.observe(r.Scope(), identifier)
            stopped = await provider.stop(r.Scope(), identifier)
            assert observed.state == stopped.state == "created" and stopped.exit_code is None
            result = await provider.run(r.Scope(), request, invocation_id=identifier)
            assert (
                result.native_id == native
                and result.stdout == "original\n"
                and result.exit_code == 0
            )
            assert (await provider.observe(r.Scope(), identifier)).state == "not_found"
        finally:
            if (
                native is not None
                and (await provider.observe(r.Scope(), identifier)).state != "not_found"
            ):
                await provider.stop(r.Scope(), identifier)
                await provider._tracked(
                    partial(
                        provider._control.request,
                        "DELETE",
                        "containers/" + native + "?force=false",
                        accepted=(204, 404),
                    )
                )
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())
