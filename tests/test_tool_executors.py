import asyncio
import threading
from dataclasses import FrozenInstanceError

import pytest

from ralf_agent import Scope, ToolRegistry, ToolSpec
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ThreadExecutionTracker, current_thread_tracker
from ralf_agent.types import InvocationContext


def executor_types():
    from ralf_agent.executors import DispatchEnvelope, EffectObservation, PythonToolExecutor

    return DispatchEnvelope, EffectObservation, PythonToolExecutor


def invocation_context():
    return InvocationContext(Scope(), "run", "action", "attempt", "effect-key", "owner")


def registry_with(handler, reconciler=None, *, version="1"):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "change",
            "Change an offline record",
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            version=version,
            effect="queryable_write",
            requires_approval=True,
        ),
        handler,
        reconciler=reconciler,
    )
    return registry


def envelope_for(registry, arguments=None):
    envelope, _, _ = executor_types()
    return envelope(
        invocation_context(),
        registry.get("change").manifest,
        {"value": 42} if arguments is None else arguments,
        "operation-digest",
    )


@pytest.mark.parametrize("mode", ["sync", "async", "sync-returning-coroutine"])
def test_python_executor_invokes_once_with_original_effect_context(mode):
    calls = []

    def change(arguments, context):
        calls.append((arguments["value"], context.effect_key, context.attempt_id))
        arguments["value"] = -1
        return {"effect": context.effect_key, "applied": 42}

    async def asynchronous(arguments, context):
        return change(arguments, context)

    def returns_coroutine(arguments, context):
        return asynchronous(arguments, context)

    handler = {
        "sync": change,
        "async": asynchronous,
        "sync-returning-coroutine": returns_coroutine,
    }[mode]
    registry = registry_with(handler)
    _, observation, executor = executor_types()
    envelope = envelope_for(registry)
    result = asyncio.run(executor(registry).execute(envelope))
    assert isinstance(result, observation)
    assert result.source == "tool-handler"
    assert result.result == {"effect": "effect-key", "applied": 42}
    assert calls == [(42, "effect-key", "attempt")]
    assert envelope.arguments == {"value": 42}


@pytest.mark.parametrize("result", [None, {"committed": True}, False, 0])
def test_reconciler_observes_existing_effect_without_executing_a_write(result):
    writes = []
    lookups = []

    def handler(arguments, context):
        writes.append(context.effect_key)
        return {"committed": True}

    async def reconciler(arguments, context):
        lookups.append((context.effect_key, arguments["value"]))
        return result

    registry = registry_with(handler, reconciler)
    _, _, executor = executor_types()
    receipt = asyncio.run(executor(registry).reconcile(envelope_for(registry)))
    assert writes == []
    assert lookups == [("effect-key", 42)]
    if result is None:
        assert receipt is None
    else:
        assert receipt.result == result
        assert receipt.source == "tool-reconciler"


def test_missing_reconciler_returns_no_observation():
    registry = registry_with(lambda arguments, context: arguments)
    _, _, executor = executor_types()
    assert asyncio.run(executor(registry).reconcile(envelope_for(registry))) is None


@pytest.mark.parametrize("operation", ["execute", "reconcile"])
def test_changed_tool_manifest_is_rejected_before_any_downstream_call(operation):
    calls = []

    def handler(arguments, context):
        calls.append("write")
        return arguments

    def reconciler(arguments, context):
        calls.append("query")
        return arguments

    original = registry_with(handler, reconciler)
    changed = registry_with(handler, reconciler, version="2")
    _, _, executor = executor_types()
    execute = getattr(executor(changed), operation)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(execute(envelope_for(original)))
    assert calls == []


@pytest.mark.parametrize("operation", ["execute", "reconcile"])
def test_arguments_are_validated_before_a_downstream_call(operation):
    calls = []

    def handler(arguments, context):
        calls.append("called")
        return arguments

    registry = registry_with(handler, handler)
    _, _, executor = executor_types()
    execute = getattr(executor(registry), operation)
    with pytest.raises(ValidationError):
        asyncio.run(execute(envelope_for(registry, {"value": "wrong"})))
    assert calls == []


def test_dispatch_envelope_snapshots_nested_data_and_prevents_rebinding():
    envelope, _, _ = executor_types()
    manifest = {"name": "change", "config": {"backend": ["primary"]}}
    arguments = {"value": {"parts": [1]}}
    dispatch = envelope(invocation_context(), manifest, arguments, "digest")
    manifest["config"]["backend"].append("replacement")
    arguments["value"]["parts"].append(2)
    dispatch.tool_manifest["config"]["backend"].append("view-change")
    dispatch.arguments["value"]["parts"].append(3)
    assert dispatch.tool_manifest == {"name": "change", "config": {"backend": ["primary"]}}
    assert dispatch.arguments == {"value": {"parts": [1]}}
    assert dispatch.tool_name == "change"
    with pytest.raises(FrozenInstanceError):
        dispatch.operation_digest = "replacement"
    with pytest.raises(FrozenInstanceError):
        dispatch.context = invocation_context()


def test_effect_observation_snapshots_result_and_prevents_source_rebinding():
    _, observation, _ = executor_types()
    result = {"receipt": {"parts": [1]}}
    observed = observation(result, source="business-lookup")
    result["receipt"]["parts"].append(2)
    observed.result["receipt"]["parts"].append(3)
    assert observed.result == {"receipt": {"parts": [1]}}
    assert observed.source == "business-lookup"
    with pytest.raises(FrozenInstanceError):
        observed.source = "replacement"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("context", None),
        ("tool_manifest", []),
        ("tool_manifest", {}),
        ("tool_manifest", {"name": " "}),
        ("tool_manifest", {"name": "change", "config": {"value": float("nan")}}),
        ("arguments", []),
        ("arguments", {"value": float("inf")}),
        ("operation_digest", None),
        ("operation_digest", " "),
    ],
)
def test_dispatch_rejects_invalid_or_non_json_requests(field, invalid):
    envelope, _, _ = executor_types()
    request = {
        "context": invocation_context(),
        "tool_manifest": {"name": "change"},
        "arguments": {"value": 42},
        "operation_digest": "digest",
    }
    request[field] = invalid
    with pytest.raises(ValidationError):
        envelope(**request)


@pytest.mark.parametrize("source", [None, "", " ", 42])
def test_effect_observation_requires_a_text_source(source):
    _, observation, _ = executor_types()
    with pytest.raises(ValidationError):
        observation({"committed": True}, source=source)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object()])
def test_non_json_observations_are_rejected(invalid):
    _, observation, _ = executor_types()
    with pytest.raises(ValidationError):
        observation({"value": invalid})


@pytest.mark.parametrize("result", [None, False, 0, [], {}])
def test_execution_observation_preserves_legal_json_results(result):
    registry = registry_with(lambda arguments, context: result)
    _, _, executor = executor_types()
    observed = asyncio.run(executor(registry).execute(envelope_for(registry)))
    assert observed.result == result
    assert observed.source == "tool-handler"


@pytest.mark.parametrize("operation", ["execute", "reconcile"])
def test_cancelled_executor_keeps_ownership_of_a_real_running_thread(operation):
    execution = ThreadExecutionTracker()
    loop = asyncio.new_event_loop()
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def handler(arguments, context):
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(5)
            return arguments
        finally:
            finished.set()

    registry = registry_with(handler, handler)
    _, _, executor = executor_types()
    execute = getattr(executor(registry), operation)

    async def begin_and_cancel():
        token = current_thread_tracker.set(execution)
        try:
            task = asyncio.create_task(execute(envelope_for(registry)))
        finally:
            current_thread_tracker.reset(token)
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        loop.run_until_complete(begin_and_cancel())
        loop.close()
        assert not finished.is_set()
        assert execution.has_active_for("run")
        release.set()
        asyncio.run(execution.drain())
        assert finished.is_set()
        assert not execution.has_active
    finally:
        release.set()
        if not loop.is_closed():
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
        assert finished.wait(5)
