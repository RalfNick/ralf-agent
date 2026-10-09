import asyncio
import copy

import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    MiddlewareProvider,
    MiddlewareToolExecutor,
    ModelResponse,
    ModelStreamEvent,
    RunEventSubscription,
    Scope,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.executors import DispatchEnvelope, EffectObservation
from ralf_agent.types import InvocationContext


class Provider:
    identity = {"kind": "review-fixture", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse("original", usage={"input_tokens": 1, "output_tokens": 1})

    async def stream(self, messages, tools):
        yield ModelStreamEvent("response", response=ModelResponse("original"))

    def validate_request(self, messages, tools):
        return None


@pytest.mark.parametrize("method", ["stream", "validate_request"])
def test_optional_delegate_entry_code_is_pinned(method):
    provider = Provider()
    wrapper = MiddlewareProvider(provider)
    original = copy.deepcopy(wrapper.identity)
    if method == "stream":

        async def replacement(messages, tools):
            yield ModelStreamEvent("response", response=ModelResponse("changed"))
    else:

        def replacement(messages, tools):
            raise AssertionError("must not execute")

    setattr(provider, method, replacement)
    assert wrapper.identity != original

    async def run():
        with pytest.raises(DefinitionMismatch):
            if method == "stream":
                await anext(wrapper.stream([], []))
            else:
                await wrapper.complete([], [])

    asyncio.run(run())


def test_optional_delegate_presence_changes_cannot_share_identity():
    class Plain:
        identity = {"kind": "plain-fixture"}

        async def complete(self, messages, tools):
            return ModelResponse("original")

    provider = Plain()
    wrapper = MiddlewareProvider(provider)
    original = copy.deepcopy(wrapper.identity)
    provider.validate_request = lambda *args: None
    assert wrapper.identity != original


@pytest.mark.parametrize("mode", ["complete", "stream"])
def test_changed_after_dispatch_preserves_model_response(mode):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Waiting(Provider):
            async def complete(self, messages, tools):
                entered.set()
                await release.wait()
                return await super().complete(messages, tools)

            async def stream(self, messages, tools):
                entered.set()
                await release.wait()
                yield ModelStreamEvent("response", response=ModelResponse("original"))

        wrapper = MiddlewareProvider(Waiting())

        async def operation():
            if mode == "complete":
                return await wrapper.complete([], [])
            return (await anext(wrapper.stream([], []))).response

        task = asyncio.create_task(operation())
        await entered.wait()

        def broken(*args):
            raise RuntimeError("AFTER_PRIVATE_SENTINEL")

        wrapper.pipeline.after = broken
        release.set()
        assert (await task).output == "original"

    asyncio.run(run())


def test_changed_after_dispatch_preserves_tool_observation():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Executor:
            identity = {"kind": "waiting-executor"}

            async def execute(self, envelope):
                entered.set()
                await release.wait()
                return EffectObservation({"written": 7})

            async def reconcile(self, envelope):
                return None

        wrapper = MiddlewareToolExecutor(Executor())
        envelope = DispatchEnvelope(
            InvocationContext(Scope(), "run", "a", "a:1", "key", "epoch"),
            {"name": "write"},
            {"value": 7},
            "digest",
        )
        task = asyncio.create_task(wrapper.execute(envelope))
        await entered.wait()

        def broken(*args):
            raise RuntimeError("AFTER_PRIVATE_SENTINEL")

        wrapper.pipeline.after = broken
        release.set()
        assert (await task).result == {"written": 7}

    asyncio.run(run())


def test_engine_stores_known_response_before_rejecting_after_code_drift(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Waiting(Provider):
            async def complete(self, messages, tools):
                entered.set()
                await release.wait()
                return await super().complete(messages, tools)

        wrapper = MiddlewareProvider(Waiting())
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": wrapper},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="first")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await entered.wait()

            def broken(*args):
                raise RuntimeError("AFTER_PRIVATE_SENTINEL")

            wrapper.pipeline.after = broken
            release.set()
            snapshot = await task
            action = snapshot.actions[0]
            assert action["status"] == "response_received"
            assert action["received_response"]["output"] == "original"
            assert snapshot.state == "failed" and snapshot.error["code"] == "definition_mismatch"
            assert action["received_response"]["usage"] == {"input_tokens": 1, "output_tokens": 1}

    asyncio.run(run())


def test_timeout_then_consumer_cancel_preserves_reader_cleanup_handle():
    async def run():
        cleaning, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Reader:
            scope = Scope()

            async def events(self, *args, **kwargs):
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
                    cleaned.set()

            async def status(self, *args):
                raise AssertionError("must not reach")

        stream = RunEventSubscription(Reader(), "r", read_timeout=0.01)
        task = asyncio.create_task(anext(stream))
        await cleaning.wait()
        task.cancel()
        # Cleanup must remain alive while the caller is cancelling observation.
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()
        assert cleaned.is_set() and stream._read_task is None

    asyncio.run(run())
