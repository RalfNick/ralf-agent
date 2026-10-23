import asyncio
import copy
import importlib
from contextlib import contextmanager

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    ModelStreamEvent,
    PythonToolExecutor,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.executors import DispatchEnvelope
from relf_agent.types import InvocationContext, Scope


def api(name):
    module = importlib.import_module("relf_agent")
    assert hasattr(module, name), "Missing middleware API: " + name
    return getattr(module, name)


class Provider:
    identity = {"kind": "middleware-fixture", "version": "1"}

    def __init__(self):
        self.calls, self.closed, self.preflight = 0, False, 0

    def validate_request(self, messages, tools):
        self.preflight += 1

    async def complete(self, messages, tools):
        self.calls += 1
        messages.clear()
        return ModelResponse({"answer": 7}, usage={"input_tokens": 1, "output_tokens": 1})

    async def aclose(self):
        self.closed = True


class Observer:
    identity = {"kind": "observer", "version": "1"}

    def __init__(self, name, seen):
        self.name, self.seen = name, seen

    def before(self, record):
        self.seen.append((self.name, record.phase, record.operation, record.payload))

    def after(self, record):
        self.seen.append((self.name, record.phase, record.operation, record.payload))


def test_model_pipeline_is_ordered_immutable_and_borrowed():
    async def run():
        seen = []
        original = [{"role": "user", "content": "q"}]
        p = Provider()
        wrapped = api("MiddlewareProvider")(p, [Observer("a", seen), Observer("b", seen)])
        wrapped.validate_request(original, [])
        assert seen == [] and p.preflight == 1
        result = await wrapped.complete(original, [])
        assert result.output == {"answer": 7} and original == [{"role": "user", "content": "q"}]
        assert [(n, phase) for n, phase, _, _ in seen] == [
            ("a", "before"),
            ("b", "before"),
            ("b", "after"),
            ("a", "after"),
        ]
        assert p.calls == 1 and p.closed is False
        assert not hasattr(wrapped, "aclose")

    asyncio.run(run())


def test_record_views_cannot_change_request_or_result():
    class Mutating(Observer):
        def before(self, record):
            record.payload["messages"].clear()

        def after(self, record):
            record.payload["response"]["output"]["answer"] = 9

    wrapped = api("MiddlewareProvider")(Provider(), [Mutating("m", [])])
    result = asyncio.run(wrapped.complete([{"role": "user", "content": "q"}], []))
    assert result.output == {"answer": 7}
    record = api("InvocationRecord")("model", "before", {"nested": []})
    record.payload["nested"].append("mutated")
    assert record.payload == {"nested": []}
    with pytest.raises((AttributeError, TypeError)):
        record.phase = "after"


@pytest.mark.parametrize("callback", ["async", "generator", "contextmanager", "value"])
def test_lazy_or_non_none_before_hook_cannot_dispatch(callback):
    class Broken(Observer):
        def before(self, record):
            return True

    if callback == "async":

        async def before(self, record):
            raise AssertionError("must not run")

        Broken.before = before
    elif callback == "generator":

        def before(self, record):
            yield "lazy"

        Broken.before = before
    elif callback == "contextmanager":

        @contextmanager
        def before(self, record):
            raise AssertionError("must not run")
            yield

        Broken.before = before
    p = Provider()
    with pytest.raises(ValidationError):
        wrapper = api("MiddlewareProvider")(p, [Broken("b", [])])
        asyncio.run(wrapper.complete([], []))
    assert p.calls == 0


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_after_observer_failure_does_not_erase_model_receipt(caplog, error):
    class Broken(Observer):
        def after(self, record):
            raise error("MIDDLEWARE_PRIVATE_SENTINEL")

    wrapped = api("MiddlewareProvider")(Provider(), [Broken("b", [])])
    result = asyncio.run(wrapped.complete([], []))
    assert result.output == {"answer": 7}
    assert "MIDDLEWARE_PRIVATE_SENTINEL" not in caplog.text
    assert "after" in caplog.text


def test_logging_default_does_not_log_payload(caplog):
    observer = api("LoggingMiddleware")()
    record = api("InvocationRecord")("model", "before", {"api_key": "MIDDLEWARE_PRIVATE_SENTINEL"})
    with caplog.at_level("INFO"):
        observer.before(record)
    assert record.payload_digest in caplog.text and "MIDDLEWARE_PRIVATE_SENTINEL" not in caplog.text
    noop = api("NoopMiddleware")()
    assert noop.before(record) is None and noop.after(record) is None


def test_changed_delegate_or_hook_code_is_refused_before_dispatch():
    p = Provider()
    hook = Observer("o", [])
    wrapped = api("MiddlewareProvider")(p, [hook])
    original = copy.deepcopy(wrapped.identity)
    p.identity = {**p.identity, "version": "2"}
    with pytest.raises(DefinitionMismatch):
        asyncio.run(wrapped.complete([], []))
    assert p.calls == 0 and wrapped.identity != original
    p.identity = {"kind": "middleware-fixture", "version": "1"}
    hook.before = lambda record: None
    with pytest.raises(DefinitionMismatch):
        asyncio.run(wrapped.complete([], []))
    assert p.calls == 0


def test_stream_forwarding_closes_iterator_and_observes_once():
    class Streaming(Provider):
        async def stream(self, messages, tools):
            try:
                yield ModelStreamEvent("text", text="hello")
                yield ModelStreamEvent("response", response=ModelResponse("hello"))
            finally:
                self.closed = True

    async def run():
        seen, p = [], Streaming()
        wrapped = api("MiddlewareProvider")(p, [Observer("o", seen)])
        events = [e async for e in wrapped.stream([], [])]
        assert events[-1].response.output == "hello" and p.closed
        assert [phase for _, phase, _, _ in seen] == ["before", "after"]
        p, seen = Streaming(), []
        wrapped = api("MiddlewareProvider")(p, [Observer("o", seen)])
        stream = wrapped.stream([], [])
        assert (await anext(stream)).text == "hello"
        await stream.aclose()
        assert p.closed and [phase for _, phase, _, _ in seen] == ["before"]

    asyncio.run(run())


def test_stream_extra_event_cannot_emit_a_complete_decision():
    class Bad(Provider):
        async def stream(self, messages, tools):
            yield ModelStreamEvent("response", response=ModelResponse("hello"))
            yield ModelStreamEvent("text", text="late")

    async def run():
        wrapped = api("MiddlewareProvider")(Bad())
        received = []
        with pytest.raises(ValidationError):
            async for event in wrapped.stream([], []):
                received.append(event)
        assert received == []

    asyncio.run(run())


def test_non_stream_provider_does_not_advertise_streaming():
    assert not hasattr(api("MiddlewareProvider")(Provider()), "stream")


def test_tool_observers_preserve_approved_arguments_effect_key_and_receipt(tmp_path, caplog):
    async def run():
        writes, seen = [], []
        tools = ToolRegistry()

        @tools.tool(effect="idempotent_write", requires_approval=True, context_parameter="context")
        def write(value: int, *, context):
            writes.append((value, context.effect_key))
            return {"written": value}

        class Model:
            identity = {"kind": "tool-middleware-fixture"}

            async def complete(self, messages, tools):
                if any(m["role"] == "tool" for m in messages):
                    return ModelResponse("done")
                return ModelResponse(tool_calls=(ToolCall("write", {"value": 7}, "call"),))

        class AfterFails(Observer):
            def before(self, record):
                super().before(record)
                record.payload["envelope"]["arguments"]["value"] = 9

            def after(self, record):
                raise RuntimeError("MIDDLEWARE_PRIVATE_SENTINEL")

        wrapped = api("MiddlewareToolExecutor")(PythonToolExecutor(tools), [AfterFails("o", seen)])
        path = tmp_path / "run.sqlite"
        spec = AgentSpec("a", "write7", ("write",))
        with LocalEngine(
            SQLiteStore(path), providers={"default": Model()}, tools=tools, tool_executor=wrapped
        ) as e:
            handle = e.submit(spec, "q", command_id="first")
            snapshot = await e.drive(handle.run_id)
            assert snapshot.state == "waiting_approval" and seen == [] and writes == []
            pending = snapshot.pending[0]
            e.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        with LocalEngine(
            SQLiteStore(path), providers={"default": Model()}, tools=tools, tool_executor=wrapped
        ) as e:
            assert (await e.drive(handle.run_id)).state == "succeeded"
            assert (await e.drive(handle.run_id)).state == "succeeded"
            assert writes == [(7, seen[0][3]["envelope"]["context"]["effect_key"])]
            assert seen[0][3]["envelope"]["arguments"] == {"value": 7}
        assert "MIDDLEWARE_PRIVATE_SENTINEL" not in caplog.text

    asyncio.run(run())


def test_before_tool_failure_preserves_unknown_intent_without_a_write(tmp_path):
    from relf_agent.executors import EffectObservation

    calls = []

    class Executor:
        identity = {"kind": "executor-fixture"}

        async def execute(self, envelope):
            calls.append(envelope)
            return EffectObservation("done")

        async def reconcile(self, envelope):
            return None

    class Reject(Observer):
        def before(self, record):
            raise ValidationError("blocked")

    wrapper = api("MiddlewareToolExecutor")(Executor(), [Reject("r", [])])
    context = InvocationContext(Scope(), "run", "a", "a:1", "key", "epoch")
    envelope = DispatchEnvelope(context, {"name": "write"}, {}, "digest")
    with pytest.raises(ValidationError):
        asyncio.run(wrapper.execute(envelope))
    assert calls == []


def test_reconcile_observers_keep_unknown_distinct_from_a_receipt():
    tools = ToolRegistry()
    seen = []
    wrapper = api("MiddlewareToolExecutor")(PythonToolExecutor(tools), [Observer("o", seen)])

    @tools.tool(effect="read_only")
    def read(value: int):
        return value

    context = InvocationContext(Scope(), "run", "a", "a:1", "key", "epoch")
    envelope = DispatchEnvelope(context, tools.get("read").manifest, {"value": 7}, "digest")
    assert asyncio.run(wrapper.reconcile(envelope)) is None
    assert seen[-1][2] == "reconcile" and seen[-1][3]["observation"] is None


@pytest.mark.parametrize("target", ["provider", "executor", "pipeline"])
def test_wrapper_entry_code_is_pinned(target):
    if target == "provider":
        wrapped = api("MiddlewareProvider")(Provider())
        function = type(wrapped).complete
    elif target == "executor":
        wrapped = api("MiddlewareToolExecutor")(PythonToolExecutor(ToolRegistry()))
        function = type(wrapped).execute
    else:
        wrapped = api("MiddlewareProvider")(Provider())
        function = type(wrapped.pipeline).before
    original = copy.deepcopy(wrapped.identity)
    before = function.__code__
    try:

        async def replacement(self, *args, **kwargs):
            return None

        function.__code__ = replacement.__code__
        assert wrapped.identity != original
    finally:
        function.__code__ = before


def test_after_diagnostic_logging_failure_cannot_discard_known_response():
    import logging

    class Broken(Observer):
        def after(self, record):
            raise RuntimeError("observer failure")

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError("logging failure")

    logger = logging.getLogger("relf_agent.middleware")
    handler = BrokenHandler()
    logger.addHandler(handler)
    try:
        wrapped = api("MiddlewareProvider")(Provider(), [Broken("b", [])])
        assert asyncio.run(wrapped.complete([], [])).output == {"answer": 7}
    finally:
        logger.removeHandler(handler)
