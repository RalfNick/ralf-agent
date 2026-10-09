import asyncio
from dataclasses import replace

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.types import CommandReceipt, RunHandle, RunSnapshot


class Controls:
    scope = Scope()

    def submit(self, spec, input, *, command_id, **kwargs):
        return RunHandle("run", CommandReceipt(command_id, "run", "submit"))

    def status(self, run_id):
        return RunSnapshot(run_id, "queued", 0, None, None, (), ())

    def cancel(self, run_id, *, command_id):
        return CommandReceipt(command_id, run_id, "cancel")


def bridge(engine):
    from ralf_agent.task_controls import TaskControlBridge

    return TaskControlBridge(engine, engine.scope)


def test_completed_sync_controls_and_native_async_composition():
    class Async:
        scope = Scope()

        async def submit(self, *args, **kwargs):
            await asyncio.sleep(0)
            return Controls().submit(*args, **kwargs)

        async def status(self, *args, **kwargs):
            return Controls().status(*args, **kwargs)

        async def cancel(self, *args, **kwargs):
            return Controls().cancel(*args, **kwargs)

    async def run(engine):
        controls = bridge(engine)
        handle = await controls.submit(AgentSpec("a", "Answer"), "task", command_id="s")
        assert (await controls.status(handle.run_id)).state == "queued"
        assert (await controls.cancel(handle.run_id, command_id="c")).kind == "cancel"

    asyncio.run(run(Controls()))
    asyncio.run(run(Async()))


def test_mixed_controls_rejected_before_call():
    class Mixed(Controls):
        async def status(self, run_id):
            raise AssertionError("Must refuse before invoking")

    with pytest.raises(ValidationError, match="mode"):
        bridge(Mixed())


def test_lazy_sync_return_is_closed_without_execution():
    class Lazy(Controls):
        called = 0
        pending = None

        def status(self, run_id):
            async def later():
                self.called += 1

            self.pending = later()
            return self.pending

    engine = Lazy()
    with pytest.raises(ValidationError):
        asyncio.run(bridge(engine).status("run"))
    assert engine.called == 0 and engine.pending.cr_frame is None


def test_async_scope_or_method_drift_after_await_is_refused():
    class Async:
        scope = Scope()
        drift = "scope"

        async def status(self, run_id):
            if self.drift == "scope":
                self.scope = Scope("other", "owner")
            else:
                self.cancel = lambda *args, **kwargs: None
            return Controls().status(run_id)

        async def submit(self, *args, **kwargs):
            return Controls().submit(*args, **kwargs)

        async def cancel(self, *args, **kwargs):
            return Controls().cancel(*args, **kwargs)

    engine = Async()
    with pytest.raises(AuthorizationDenied):
        asyncio.run(bridge(engine).status("run"))
    engine = Async()
    engine.drift = "method"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(bridge(engine).status("run"))


@pytest.mark.parametrize("invalid", ["wrong_id", "negative_revision", "empty_state", "nan", "dict"])
def test_invalid_snapshots_fail_at_common_boundary(invalid):
    class Invalid(Controls):
        def status(self, run_id):
            snapshot = super().status(run_id)
            return {
                "wrong_id": replace(snapshot, run_id="other"),
                "negative_revision": replace(snapshot, state_revision=-1),
                "empty_state": replace(snapshot, state=" "),
                "nan": replace(snapshot, result=float("nan")),
                "dict": {"run_id": run_id},
            }[invalid]

    with pytest.raises(ValidationError):
        asyncio.run(bridge(Invalid()).status("run"))


def test_submit_receipt_must_match_original_command_and_run():
    class Invalid(Controls):
        def submit(self, *args, **kwargs):
            return RunHandle("run", CommandReceipt("other", "run", "submit"))

    with pytest.raises(ValidationError):
        asyncio.run(bridge(Invalid()).submit(AgentSpec("a", "Answer"), "task", command_id="s"))


def test_public_runtime_instance_delegation_works_without_concrete_inheritance(tmp_path):
    from ralf_agent import RuntimeBuilder, RuntimeProfile

    async def run():
        with RuntimeBuilder().build(
            RuntimeProfile("bridge", "1", {"default": {"adapter": "offline-echo"}}),
            tmp_path / "runtime.sqlite",
        ) as runtime:
            controls = bridge(runtime)
            handle = await controls.submit(AgentSpec("a", "Answer"), "task", command_id="start")
            assert (await controls.status(handle.run_id)).state == "queued"
            assert (await controls.cancel(handle.run_id, command_id="stop")).kind == "cancel"

    asyncio.run(run())


def test_replaced_python_method_body_is_refused_before_invocation():
    class Mutable(Controls):
        called = 0

        def status(self, run_id):
            return Controls().status(run_id)

    def replacement(self, run_id):
        self.called += 1
        return Controls().status(run_id)

    engine = Mutable()
    controls = bridge(engine)
    Mutable.status.__code__ = replacement.__code__
    with pytest.raises(DefinitionMismatch):
        asyncio.run(controls.status("run"))
    assert engine.called == 0


def test_callable_instance_implementation_drift_is_refused_before_execution():
    class Status:
        called = 0

        async def __call__(self, run_id):
            return Controls().status(run_id)

    class Async:
        scope = Scope()
        status = Status()

        async def submit(self, *args, **kwargs):
            return Controls().submit(*args, **kwargs)

        async def cancel(self, *args, **kwargs):
            return Controls().cancel(*args, **kwargs)

    async def replacement(self, run_id):
        self.called += 1
        return Controls().status(run_id)

    engine = Async()
    controls = bridge(engine)
    # Same async mode and same registered object, different implementation.
    Status.__call__ = replacement
    with pytest.raises(DefinitionMismatch):
        controls.verify()
    with pytest.raises(DefinitionMismatch):
        asyncio.run(controls.status("run"))
    assert engine.status.called == 0
