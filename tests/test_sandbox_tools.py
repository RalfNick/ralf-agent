"""Borrowed replaceable Sandbox port in the original managed tool lane."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, RalfError
from ralf_agent.types import InvocationContext


class Provider:
    identity = {
        "kind": "contract-test-sandbox",
        "version": "1",
        "isolation": {"network": "none", "host_mounts": False, "persistent_files": False},
    }

    def __init__(self):
        self.calls, self.closed = [], False

    async def run(self, scope, request, *, invocation_id):
        self.calls.append((scope, request, invocation_id))
        if hasattr(self, "entered"):
            self.entered.set()
            await self.release.wait()
        return r.SandboxResult(
            invocation_id,
            "a" * 64,
            0,
            "result",
            "",
            False,
            False,
            r.SandboxObservation(invocation_id, "a" * 64, "stopped", 0),
        )

    async def observe(self, scope, invocation_id):
        return r.SandboxObservation(invocation_id, "a" * 64, "stopped", 0)

    async def stop(self, scope, invocation_id):
        if hasattr(self, "release"):
            self.release.set()
        return await self.observe(scope, invocation_id)

    async def aclose(self, wait_timeout=30):
        self.closed = True


def api():
    value = getattr(r, "SandboxToolSource", None)
    assert value is not None, "Missing original SandboxToolSource"
    return value


def context():
    return InvocationContext(r.Scope(), "run", "action", "attempt", "effect", "epoch")


def test_original_tool_registration_keeps_host_approval_and_borrowed_provider():
    async def run():
        provider, registry = Provider(), r.ToolRegistry()
        source = api()(provider, version="1")
        try:
            descriptors = await source.list_tools()
            assert len(descriptors) == 1 and descriptors[0].name == "sandbox_run"
            await r.register_tool_source(
                registry,
                source,
                policies={
                    "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
                prefix="isolated_",
            )
            registration = registry.get("isolated_sandbox_run")
            assert registration.spec.requires_approval and registration.spec.effect == "read_only"
            result = await registration.handler({"argv": ["/bin/echo", "hi"]}, context())
            assert result["stdout"] == "result" and result["observation"]["state"] == "stopped"
            assert provider.calls[0][0] == r.Scope() and provider.calls[0][1].timeout == 30
            assert provider.calls[0][2] not in {"run", "action", "effect", "attempt"}
        finally:
            await source.aclose()
        assert provider.closed is False

    asyncio.run(run())


@pytest.mark.parametrize(
    "args",
    [
        {"argv": ["/bin/echo"], "image": "other"},
        {"argv": ["/bin/echo"], "host_path": "/"},
        {"argv": ["/bin/echo"], "timeout": 31},
        {"argv": ["echo"]},
        {"argv": []},
    ],
)
def test_model_cannot_expand_native_profile_or_command_allowance(args):
    async def run():
        provider = Provider()
        source = api()(provider, version="1")
        try:
            descriptor = (await source.list_tools())[0]
            with pytest.raises(RalfError):
                await source.call_tool(descriptor, args, context())
            assert provider.calls == []
        finally:
            await source.aclose()

    asyncio.run(run())


def test_provider_method_or_identity_drift_refuses_before_io():
    async def run():
        provider = Provider()
        source = api()(provider, version="1")
        descriptor = (await source.list_tools())[0]
        provider.identity = {**provider.identity, "version": "2"}
        with pytest.raises(DefinitionMismatch):
            await source.call_tool(descriptor, {"argv": ["/bin/echo"]}, context())
        assert provider.calls == []
        await source.aclose()
        assert not provider.closed

    asyncio.run(run())


def test_observer_cancel_does_not_cancel_owned_port_operation_and_close_is_retriable():
    async def run():
        provider = Provider()
        provider.entered, provider.release = asyncio.Event(), asyncio.Event()
        source = api()(provider, version="1")
        descriptor = (await source.list_tools())[0]
        task = asyncio.create_task(source.call_tool(descriptor, {"argv": ["/bin/echo"]}, context()))
        await provider.entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not provider.release.is_set()
        with pytest.raises(r.CloseIncomplete):
            await source.aclose(wait_timeout=0)
        await source.aclose(wait_timeout=5)
        assert not provider.closed

    asyncio.run(run())


def test_unrestricted_custom_provider_is_not_accepted_as_readonly_sandbox_source():
    provider = Provider()
    provider.identity = {
        **provider.identity,
        "isolation": {"network": "host", "host_mounts": True, "persistent_files": True},
    }
    with pytest.raises(RalfError):
        api()(provider, version="1")


def test_raw_completed_result_is_projected_without_instance_copy_or_wire_hooks():
    class HookProvider(Provider):
        async def run(self, scope, request, *, invocation_id):
            value = await super().run(scope, request, invocation_id=invocation_id)
            object.__setattr__(value, "to_dict", lambda: {"stdout": "forged"})
            return value

    async def run():
        source = api()(HookProvider(), version="1")
        try:
            result = await source.call_tool(
                (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
            )
            assert result["stdout"] == "result" and result["observation"]["state"] == "stopped"
        finally:
            await source.aclose()

    asyncio.run(run())


def test_source_runtime_allowance_drift_cannot_hide_behind_saved_identity():
    async def run():
        provider = Provider()
        source = api()(provider, version="1", max_output_bytes=100)
        descriptor = (await source.list_tools())[0]
        source._output = 1000
        with pytest.raises(DefinitionMismatch):
            await source.call_tool(descriptor, {"argv": ["/bin/echo"]}, context())
        assert provider.calls == []
        await source.aclose()

    asyncio.run(run())


def test_stable_native_invocation_excludes_attempt_and_execution_epoch():
    async def run():
        provider = Provider()
        source = api()(provider, version="1")
        try:
            descriptor = (await source.list_tools())[0]
            first = context()
            second = InvocationContext(
                first.scope, first.run_id, first.action_id, "retry", first.effect_key, "new-epoch"
            )
            await source.call_tool(descriptor, {"argv": ["/bin/echo"]}, first)
            await source.call_tool(descriptor, {"argv": ["/bin/echo"]}, second)
            assert provider.calls[0][2] == provider.calls[1][2]
        finally:
            await source.aclose()

    asyncio.run(run())


def test_omitted_command_timeout_uses_host_configured_default():
    async def run():
        provider = Provider()
        source = api()(provider, version="1", max_timeout=2)
        try:
            await source.call_tool(
                (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
            )
            assert provider.calls[0][1].timeout == 2
        finally:
            await source.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "lazy", ["coroutine", "generator", "async-generator", "wrong-id", "wrong-scope"]
)
def test_custom_port_unfinished_or_mismatched_result_is_rejected_and_keeps_stop_ownership(lazy):
    class BadProvider(Provider):
        async def run(self, scope, request, *, invocation_id):
            async def pending():
                return None

            def generator():
                yield None

            async def async_generator():
                yield None

            if lazy == "coroutine":
                return pending()
            if lazy == "generator":
                return generator()
            if lazy == "async-generator":
                return async_generator()
            value = await super().run(scope, request, invocation_id=invocation_id)
            if lazy == "wrong-id":
                object.__setattr__(value, "invocation_id", "wrong")
            else:
                self.identity = {**self.identity, "version": "replaced"}
            return value

    async def run():
        provider = BadProvider()
        source = api()(provider, version="1")
        descriptor = (await source.list_tools())[0]
        try:
            with pytest.raises(RalfError):
                await source.call_tool(descriptor, {"argv": ["/bin/echo"]}, context())
            assert source._calls
        finally:
            if lazy == "wrong-scope":
                provider.identity = Provider.identity
            await source.aclose(wait_timeout=5)
        assert not provider.closed

    asyncio.run(run())


def test_actual_custom_native_thread_survives_global_cancel_until_original_stop_and_drain():
    import threading

    from ralf_agent.tools import current_thread_group, current_thread_tracker

    class ThreadProvider(Provider):
        def __init__(self):
            super().__init__()
            self.entered, self.release, self.exited = (
                threading.Event(),
                threading.Event(),
                threading.Event(),
            )

        async def run(self, scope, request, *, invocation_id):
            def native():
                self.entered.set()
                assert self.release.wait(10)
                self.exited.set()

            await current_thread_tracker.get().run(native, group=current_thread_group.get())
            return await super().run(scope, request, invocation_id=invocation_id)

        async def stop(self, scope, invocation_id):
            self.release.set()
            return await self.observe(scope, invocation_id)

    provider = ThreadProvider()
    source = api()(provider, version="1")
    loop = asyncio.new_event_loop()

    async def start():
        task = asyncio.create_task(
            source.call_tool((await source.list_tools())[0], {"argv": ["/bin/echo"]}, context())
        )
        for _ in range(500):
            if provider.entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert provider.entered.is_set()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        assert task.cancelled() and source._threads.has_active and not provider.exited.is_set()

    try:
        loop.run_until_complete(start())
        loop.close()

        async def close():
            with pytest.raises(r.CloseIncomplete):
                await source.aclose(wait_timeout=0)
            await source.aclose(wait_timeout=5)
            assert (
                provider.exited.is_set() and not source._threads.has_active and not provider.closed
            )

        asyncio.run(close())
    finally:
        provider.release.set()
        if not loop.is_closed():
            loop.close()
        asyncio.run(source.aclose(wait_timeout=5))


def test_close_timeout_does_not_cancel_real_async_stop_or_allow_false_completion():
    class SlowStop(Provider):
        async def stop(self, scope, invocation_id):
            self.stop_entered.set()
            try:
                await self.stop_release.wait()
            except asyncio.CancelledError:
                self.stop_cancelled = True
                raise
            return await super().stop(scope, invocation_id)

    async def run():
        provider = SlowStop()
        provider.entered, provider.release = asyncio.Event(), asyncio.Event()
        provider.stop_entered, provider.stop_release = asyncio.Event(), asyncio.Event()
        provider.stop_cancelled = False
        source = api()(provider, version="1")
        task = asyncio.create_task(
            source.call_tool((await source.list_tools())[0], {"argv": ["/bin/echo"]}, context())
        )
        await provider.entered.wait()
        try:
            with pytest.raises(r.CloseIncomplete):
                await source.aclose(wait_timeout=0.02)
            assert provider.stop_entered.is_set() and not provider.stop_cancelled
        finally:
            provider.stop_release.set()
            await source.aclose(wait_timeout=5)
            await asyncio.gather(task, return_exceptions=True)
        assert not provider.closed

    asyncio.run(run())
