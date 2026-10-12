"""Actual owned Docker containers; no mock result is used as isolation evidence."""

import asyncio
import os
import threading
import uuid

import pytest

import ralf_agent as r

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_DOCKER_IMAGE"),
    reason="requires explicit local Docker image and socket",
)


def sandbox(*, cls=r.DockerSandbox, **values):
    return cls(
        os.environ["RALF_TEST_DOCKER_SOCKET"],
        os.environ["RALF_TEST_DOCKER_IMAGE"],
        version="test-1",
        **values,
    )


def test_actual_ephemeral_nonroot_readonly_root_private_scratch_and_no_network():
    async def run():
        provider = sandbox()
        identity = "native-" + uuid.uuid4().hex
        try:
            await provider.aopen()
            assert provider.identity["native"]["image"] == os.environ["RALF_TEST_DOCKER_IMAGE"]
            request = r.SandboxRequest(
                [
                    "/bin/sh",
                    "-c",
                    "id -u; echo private >/workspace/data; cat /workspace/data; "
                    "if touch /etc/ralf-forbidden 2>/dev/null; then exit 44; fi; "
                    "test $(ip route | wc -l) -eq 0; echo restricted",
                ]
            )
            result = await provider.run(r.Scope(), request, invocation_id=identity)
            assert result.exit_code == 0 and result.stdout == "65534\nprivate\nrestricted\n"
            assert result.observation.state == "stopped" and not result.timed_out
            assert (await provider.observe(r.Scope(), identity)).state == "not_found"
        finally:
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_timeout_kills_native_environment_and_requires_exit_proof():
    async def run():
        provider = sandbox()
        identity = "timeout-" + uuid.uuid4().hex
        try:
            await provider.aopen()
            result = await provider.run(
                r.Scope(),
                r.SandboxRequest(["/bin/sleep", "10"], timeout=0.1),
                invocation_id=identity,
            )
            assert result.timed_out and result.exit_code != 0
            assert (
                result.observation.state == "stopped"
                and result.observation.native_id == result.native_id
            )
            assert (await provider.observe(r.Scope(), identity)).state == "not_found"
        finally:
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_output_bound_stops_before_returning_unbounded_evidence():
    async def run():
        provider = sandbox(max_output_bytes=100)
        identity = "output-" + uuid.uuid4().hex
        try:
            await provider.aopen()
            result = await provider.run(
                r.Scope(),
                r.SandboxRequest(["/bin/sh", "-c", "yes x"], timeout=3),
                invocation_id=identity,
            )
            assert result.truncated and len((result.stdout + result.stderr).encode()) <= 100
            assert result.observation.state == "stopped"
            assert (await provider.observe(r.Scope(), identity)).state == "not_found"
        finally:
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_cancel_retains_live_container_thread_and_capacity_until_stop():
    class BlockingDocker(r.DockerSandbox):
        def _stop(self, *args, **kwargs):
            self.entered.set()
            assert self.release.wait(15)
            return super()._stop(*args, **kwargs)

    async def run():
        provider = sandbox(cls=BlockingDocker, max_calls=1)
        identity = "cancel-" + uuid.uuid4().hex
        entered, release = threading.Event(), threading.Event()
        provider.entered, provider.release = entered, release

        task = None
        try:
            await provider.aopen()
            task = asyncio.create_task(
                provider.run(
                    r.Scope(),
                    r.SandboxRequest(["/bin/sleep", "30"]),
                    invocation_id=identity,
                )
            )
            async with asyncio.timeout(10):
                for _ in range(500):
                    if (await provider.observe(r.Scope(), identity)).state == "running":
                        break
                    await asyncio.sleep(0.02)
                else:
                    pytest.fail("Owned native container never reported running")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            async with asyncio.timeout(5):
                for _ in range(500):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert entered.is_set()
            assert provider._tracker.has_active
            assert (await provider.observe(r.Scope(), identity)).state == "running"
            with pytest.raises(r.SandboxUnavailable):
                await provider.run(
                    r.Scope(), r.SandboxRequest(["/bin/echo"]), invocation_id="second"
                )
            with pytest.raises(r.CloseIncomplete):
                await provider.aclose(wait_timeout=0)
            assert provider._tracker.has_active and len(provider._jobs) == 1
            release.set()
            await provider.aclose(wait_timeout=15)
            assert not provider._tracker.has_active and provider._jobs == {}
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_native_resource_and_namespace_configuration_applied_to_live_container():
    async def run():
        provider = sandbox(memory_bytes=67108864, nano_cpus=250000000, pids_limit=8)
        identity = "limits-" + uuid.uuid4().hex
        task = None
        try:
            await provider.aopen()
            task = asyncio.create_task(
                provider.run(
                    r.Scope(),
                    r.SandboxRequest(["/bin/sleep", "30"]),
                    invocation_id=identity,
                )
            )
            async with asyncio.timeout(10):
                for _ in range(500):
                    if (await provider.observe(r.Scope(), identity)).state == "running":
                        break
                    await asyncio.sleep(0.02)
                else:
                    pytest.fail("Owned quota container never started")
            actual = await provider._tracked(provider._inspect, r.Scope(), identity)
            host = actual["HostConfig"]
            assert host["ReadonlyRootfs"] is True and host["NetworkMode"] == "none"
            assert host["Memory"] == host["MemorySwap"] == 67108864
            assert host["NanoCpus"] == 250000000 and host["PidsLimit"] == 8
            assert host["CapDrop"] == ["ALL"] and host["SecurityOpt"] == ["no-new-privileges"]
            assert not host["Privileged"] and not host.get("Binds") and not actual["Mounts"]
            assert actual["Config"]["User"] == "65534:65534"
            assert actual["Config"]["NetworkDisabled"] is True
            await provider.stop(r.Scope(), identity)
            result = await task
            assert result.observation.state == "stopped" and result.exit_code != 0
        finally:
            await provider.aclose(wait_timeout=15)
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_actual_closed_provider_rejects_observation_without_using_closed_client():
    async def run():
        provider = sandbox()
        await provider.aopen()
        await provider.aclose(wait_timeout=15)
        with pytest.raises(r.SandboxUnavailable):
            await provider.observe(r.Scope(), "closed")

    asyncio.run(run())


def test_actual_pid_quota_blocks_fork_expansion_before_timeout():
    async def run():
        provider = sandbox(pids_limit=4)
        identity = "pids-" + uuid.uuid4().hex
        try:
            await provider.aopen()
            result = await provider.run(
                r.Scope(),
                r.SandboxRequest(
                    [
                        "/bin/sh",
                        "-c",
                        "i=0; while [ $i -lt 100 ]; do /bin/sleep 10 & i=$((i+1)); done",
                    ],
                    timeout=3,
                ),
                invocation_id=identity,
            )
            assert result.exit_code != 0 and not result.timed_out
            assert "fork" in result.stderr.lower()
            assert result.observation.state == "stopped"
            assert (await provider.observe(r.Scope(), identity)).state == "not_found"
        finally:
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_image_with_implicit_volume_is_refused_before_any_command():
    async def run():
        provider = sandbox()
        container, image, rejected = None, None, None
        try:
            await provider.aopen()
            config = provider._container_config(
                r.Scope(), "image-" + uuid.uuid4().hex, r.SandboxRequest(["/bin/true"])
            )
            config["Volumes"] = {"/ralf-declared-volume": {}}
            created = await provider._tracked(
                lambda: provider._control.json(
                    "POST", "containers/create", body=config, accepted=(201,)
                )
            )
            container = created["Id"]
            committed = await provider._tracked(
                lambda: provider._control.json(
                    "POST",
                    "commit?container=" + container,
                    body={"Volumes": {"/ralf-declared-volume": {}}},
                    accepted=(201,),
                )
            )
            image = committed["Id"]
            rejected = r.DockerSandbox(
                os.environ["RALF_TEST_DOCKER_SOCKET"], image, version="volume-test"
            )
            with pytest.raises(r.SandboxIsolationViolation):
                await rejected.aopen()
            assert rejected._pin is None and rejected._jobs == {}
        finally:
            if rejected is not None:
                await rejected.aclose(wait_timeout=15)
            if container is not None:
                await provider._tracked(
                    lambda: provider._control.request(
                        "DELETE", "containers/" + container + "?v=1", accepted=(204, 404)
                    )
                )
            if image is not None:
                await provider._tracked(
                    lambda: provider._control.request(
                        "DELETE", "images/" + image, accepted=(200, 404)
                    )
                )
            await provider.aclose(wait_timeout=15)

    asyncio.run(run())


def test_actual_closed_event_loop_does_not_release_native_thread_or_container():
    class BlockingDocker(r.DockerSandbox):
        def _stop(self, *args, **kwargs):
            self.entered.set()
            assert self.release.wait(20)
            return super()._stop(*args, **kwargs)

    provider = sandbox(cls=BlockingDocker)
    provider.entered, provider.release = threading.Event(), threading.Event()
    identity = "loop-" + uuid.uuid4().hex
    old = asyncio.new_event_loop()
    executor, task = None, None

    async def first():
        nonlocal task
        await provider.aopen()
        task = asyncio.create_task(
            provider.run(
                r.Scope(),
                r.SandboxRequest(["/bin/sleep", "30"]),
                invocation_id=identity,
            )
        )
        for _ in range(500):
            if (await provider.observe(r.Scope(), identity)).state == "running":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Original loop did not start native task")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(500):
            if provider.entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert provider.entered.is_set() and provider._tracker.has_active

    async def second():
        assert (await provider.observe(r.Scope(), identity)).state == "running"
        with pytest.raises(r.CloseIncomplete):
            await provider.aclose(wait_timeout=0)
        assert provider._tracker.has_active
        provider.release.set()
        await provider.aclose(wait_timeout=15)
        assert not provider._tracker.has_active and provider._jobs == {}

    try:
        old.run_until_complete(first())
        executor = old._default_executor
        old.close()
        asyncio.run(second())
    finally:
        provider.release.set()
        if not old.is_closed():
            if task is not None:
                task.cancel()
                old.run_until_complete(asyncio.gather(task, return_exceptions=True))
            executor = old._default_executor
            old.close()
        asyncio.run(provider.aclose(wait_timeout=15))
        if executor is not None:
            executor.shutdown(wait=True)


def test_actual_independent_providers_cannot_restart_same_completed_invocation():
    async def run():
        first, second = sandbox(), sandbox()
        identity = "exclusive-" + uuid.uuid4().hex
        request = r.SandboxRequest(["/bin/sh", "-c", "echo once; sleep 30"])
        original = None
        try:
            await first.aopen()
            await second.aopen()
            original = asyncio.create_task(first.run(r.Scope(), request, invocation_id=identity))
            async with asyncio.timeout(5):
                for _ in range(500):
                    if (await second.observe(r.Scope(), identity)).state == "running":
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("Original invocation never began")
            with pytest.raises(r.SandboxUnavailable):
                await second.run(r.Scope(), request, invocation_id=identity)
            await first.stop(r.Scope(), identity)
            result = await original
            assert result.stdout == "once\n"
            assert result.observation.state == "stopped" and result.exit_code != 0
        finally:
            if original is not None:
                await asyncio.gather(original, return_exceptions=True)
            await first.aclose(wait_timeout=15)
            await second.aclose(wait_timeout=15)

    asyncio.run(run())
