"""Sole-review regressions: original end, refusal, snapshots and native ownership."""

import asyncio
import threading

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, RalfError, ValidationError
from ralf_agent.types import digest

from .test_docker_sandbox import provider
from .test_sandbox_tools import Provider, context


@pytest.mark.parametrize("result", ["malformed", "exception", "lazy"])
def test_unresolved_native_responsibility_blocks_original_ambient_end(result):
    class Invalid(Provider):
        async def run(self, scope, request, *, invocation_id):
            self.live = True
            if result == "exception":
                raise r.SandboxUnavailable("unresolved native diagnostic")
            if result == "lazy":

                async def pending():
                    return None

                return pending()
            return {"not": "completed native evidence"}

        async def stop(self, scope, invocation_id):
            self.live = False
            return await self.observe(scope, invocation_id)

        async def observe(self, scope, invocation_id):
            return r.SandboxObservation(
                invocation_id,
                "a" * 64,
                "running" if self.live else "stopped",
                None if self.live else 0,
            )

    async def run():
        port = Invalid()
        source = r.SandboxToolSource(port, version="1")
        outer = r.ToolExecutionOwner(version="original")
        ended = []

        async def operation():
            return await source.call_tool(
                (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
            )

        proof = {
            "scope": {"workspace": "default", "principal": "local-owner"},
            "action_id": "action",
            "release_digest": "a" * 64,
            "request_digest": "b" * 64,
            "execution_epoch": "epoch",
        }
        try:
            with pytest.raises(RalfError):
                await outer.execute(
                    operation, proof=proof, on_end=lambda value: ended.append(value)
                )
            assert port.live and source._calls
            assert await outer.wait(wait_timeout=0.02) is False
            assert ended == []
        finally:
            await source.aclose(wait_timeout=5)
            await outer.aclose(wait_timeout=5)
        assert not port.live and len(ended) == 1

    asyncio.run(run())


def test_proven_no_start_refusal_is_distinct_from_unknown_dispatch():
    error = getattr(r, "SandboxExecutionRejected", None)
    assert error is not None, "Missing original typed Sandbox execution refusal"
    rejected = error(handler_not_started=True)
    assert isinstance(rejected, r.SandboxUnavailable) and rejected.handler_not_started is True
    with pytest.raises(RalfError):
        error(handler_not_started=1)


def test_native_request_label_uses_original_raw_command_without_projection_hook():
    value = provider()
    request = r.SandboxRequest(["/bin/echo", "second"])
    object.__setattr__(request, "to_dict", lambda: {"argv": ["/bin/echo", "first"], "timeout": 30})
    config = value._container_config(r.Scope(), "call", request)
    assert config["Entrypoint"] + config["Cmd"] == ["/bin/echo", "second"]
    assert config["Labels"]["ralf.sandbox.request"] == digest(r.SandboxRequest.to_dict(request))


def test_changed_live_scope_allowlist_refuses_before_any_native_authorization():
    value = provider()
    value._scopes = (r.Scope("foreign", "user"),)
    with pytest.raises(DefinitionMismatch):
        value._scope(r.Scope("foreign", "user"))


@pytest.mark.parametrize("name", ["request", "json", "close", "decode_logs", "native_lease"])
def test_native_helper_implementation_drift_cannot_reuse_fixed_release(monkeypatch, name):
    from ralf_agent import docker_sandbox as module

    value = provider()

    def changed(*args, **kwargs):
        return None

    if name in {"request", "json", "close"}:
        monkeypatch.setattr(module.DockerControl, name, changed)
    elif name == "decode_logs":
        monkeypatch.setattr(module, "decode_logs", changed)
    else:
        monkeypatch.setattr(module.NativeSandboxLease, "__init__", changed)
    with pytest.raises(DefinitionMismatch):
        value._assert_methods()


def test_create_unknown_keeps_actual_thread_slot_and_native_lease_until_cleanup(tmp_path):
    from ralf_agent.docker_sandbox_transport import NativeSandboxLease, lease_root

    created, inspect_blocked, release = threading.Event(), threading.Event(), threading.Event()
    native_id = "b" * 64

    class Control:
        def json(self, method, path, **kwargs):
            created.set()
            raise r.SandboxError("malformed accepted create response")

        def request(self, *args, **kwargs):
            return 204, b""

    class Native(r.DockerSandbox):
        def _check(self, *, closing=False):
            pass

        def _inspect(self, scope, identity, native=None):
            if not self.created.is_set():
                return None
            if not self.release.is_set():
                self.inspect_blocked.set()
                raise r.SandboxUnavailable("temporarily unavailable native query")
            return {
                "Id": native_id,
                "Config": {
                    "Labels": self._container_config(
                        scope, identity, r.SandboxRequest(["/bin/echo"])
                    )["Labels"]
                },
                "State": {"Running": False, "Status": "created"},
            }

        def _stop(self, scope, identity, native=None):
            return self._observation(scope, identity, native)

    value = Native("/missing/socket", "sha256:" + "a" * 64, version="1")
    value.created, value.release, value.inspect_blocked = created, release, inspect_blocked
    root = lease_root(str(tmp_path / "leases"))
    value._control, value._pin = Control(), {"leases": root}

    async def run():
        task = asyncio.create_task(
            value.run(r.Scope(), r.SandboxRequest(["/bin/echo"]), invocation_id="call")
        )
        try:
            for _ in range(100):
                if created.is_set():
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.03)
            assert created.is_set() and not task.done()
            assert value._jobs and value._tracker.has_active
            with pytest.raises(r.SandboxUnavailable):
                NativeSandboxLease(root, value._name(r.Scope(), "call"))
            with pytest.raises(r.CloseIncomplete):
                await value.aclose(wait_timeout=0)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            value._control = None
            await value.aclose(wait_timeout=5)

    asyncio.run(run())


def test_typed_proven_refusal_withdraws_source_and_original_owner_without_stop():
    class Refused(Provider):
        async def run(self, scope, request, *, invocation_id):
            raise r.SandboxExecutionRejected(handler_not_started=True)

        async def stop(self, scope, invocation_id):
            raise AssertionError("Rejected call has no native stop responsibility")

    async def run():
        source = r.SandboxToolSource(Refused(), version="1")
        owner = r.ToolExecutionOwner(version="1")

        async def operation():
            return await source.call_tool(
                (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
            )

        proof = {
            "scope": {"workspace": "default", "principal": "local-owner"},
            "action_id": "refused",
            "release_digest": "a" * 64,
            "request_digest": "b" * 64,
            "execution_epoch": "epoch",
        }
        with pytest.raises(r.SandboxExecutionRejected):
            await owner.execute(operation, proof=proof)
        assert source._calls == {} and not source._threads.has_active
        assert await owner.wait(wait_timeout=1)
        await source.aclose(wait_timeout=1)
        await owner.aclose(wait_timeout=1)

    asyncio.run(run())


def test_native_control_receiver_drift_refuses_pinned_methods(monkeypatch):
    from ralf_agent.task_controls import _binding

    class Control:
        def request(self, *args, **kwargs):
            pass

        def json(self, *args, **kwargs):
            pass

        def close(self):
            pass

    value = provider()
    value._control = Control()
    value._control_bindings = {
        name: _binding(getattr(value._control, name)) for name in ("request", "json", "close")
    }
    monkeypatch.setattr(value._control, "request", lambda *args, **kwargs: None)
    with pytest.raises(DefinitionMismatch):
        value._assert_methods()


def test_source_rejects_parallel_foreign_live_loop_and_allows_ended_loop_close():
    ready, release = threading.Event(), threading.Event()
    source = r.SandboxToolSource(Provider(), version="1")

    def host():
        async def run():
            source._claim_loop()
            ready.set()
            await asyncio.to_thread(release.wait)

        asyncio.run(run())

    thread = threading.Thread(target=host)
    thread.start()
    try:
        assert ready.wait(5)

        async def foreign():
            with pytest.raises(ValidationError):
                await source.call_tool(
                    (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
                )

        asyncio.run(foreign())
        assert source._calls == {}
    finally:
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        asyncio.run(source.aclose(wait_timeout=1))


def test_failed_but_proven_stopped_native_call_allows_original_owner_drain():
    class Cleaned(Provider):
        async def run(self, scope, request, *, invocation_id):
            raise r.SandboxError("Native cleanup finished after malformed control response")

        async def observe(self, scope, invocation_id):
            return r.SandboxObservation(invocation_id, None, "not_found")

        async def stop(self, scope, invocation_id):
            raise AssertionError("Native absence already proven; no stop needed")

    async def run():
        source = r.SandboxToolSource(Cleaned(), version="1")
        owner = r.ToolExecutionOwner(version="original")
        ended = []

        async def operation():
            return await source.call_tool(
                (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
            )

        proof = {
            "scope": {"workspace": "default", "principal": "local-owner"},
            "action_id": "cleaned",
            "release_digest": "a" * 64,
            "request_digest": "b" * 64,
            "execution_epoch": "epoch",
        }
        try:
            with pytest.raises(r.SandboxError):
                await owner.execute(
                    operation, proof=proof, on_end=lambda value: ended.append(value)
                )
            assert await owner.wait(wait_timeout=0.02), (
                "Completed native cleanup must not leave a synthetic bridge blocking Runtime shutdown"
            )
            assert len(ended) == 1 and source._calls == {}
        finally:
            # Old implementation needs explicit source stop. Avoid masking the RED
            # with a second error from the deliberately forbidden stop method.
            for call in source._calls.values():
                source._finish_bridge(call)
            source._calls.clear()
            await source.aclose(wait_timeout=1)
            await owner.aclose(wait_timeout=1)

    asyncio.run(run())


def test_nested_owner_no_start_does_not_prove_sandbox_handler_never_started():
    from ralf_agent.temporal_context_execution import ContextExecutionRejected

    class Nested(Provider):
        async def run(self, scope, request, *, invocation_id):
            self.live = True
            raise ContextExecutionRejected(handler_not_started=True)

        async def observe(self, scope, invocation_id):
            return r.SandboxObservation(
                invocation_id,
                "a" * 64,
                "running" if self.live else "stopped",
                None if self.live else 0,
            )

        async def stop(self, scope, invocation_id):
            self.live = False
            return await self.observe(scope, invocation_id)

    async def run():
        source = r.SandboxToolSource(Nested(), version="1")
        try:
            with pytest.raises(ContextExecutionRejected):
                await source.call_tool(
                    (await source.list_tools())[0], {"argv": ["/bin/echo"]}, context()
                )
            assert source._calls and source._threads.has_active
        finally:
            await source.aclose(wait_timeout=1)

    asyncio.run(run())
