"""Completed supplier values remain known evidence despite encoding limits."""

import asyncio
import inspect

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore
from ralf_agent.model_evidence import snapshot_model_response
from ralf_agent.tools import ToolRegistry


class CompletedProvider:
    identity = {"kind": "completed-evidence-test", "version": "1"}

    def __init__(self, output):
        self.output, self.calls = output, 0

    async def complete(self, messages, tools):
        self.calls += 1
        return ModelResponse(output=self.output)


def deep_value(leaf=None):
    value = leaf
    for _ in range(1500):
        value = [value]
    return value


@pytest.mark.parametrize("lazy", [False, True])
def test_completed_deep_original_run_is_rejected_and_settled(tmp_path, lazy):
    async def unused():
        return "never executed"

    leaf = unused() if lazy else "finite"
    provider = CompletedProvider(deep_value(leaf))

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            snapshot = await engine.drive(handle.run_id)
            original = engine.store.run(handle.run_id)
            assert snapshot.state == "failed" and snapshot.error == {"code": "validation_error"}
            action = original["actions"][0]
            assert action["status"] == "rejected"
            assert action["attempts"][0]["status"] == "completed"
            assert action["received_response"] == {
                "output": None,
                "tool_calls": [],
                "usage": None,
                "invalid_fields": ["output"],
            }
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert provider.calls == 1
            return handle.run_id

    try:
        asyncio.run(run())
        if lazy:
            assert inspect.getcoroutinestate(leaf) == inspect.CORO_CLOSED
    finally:
        if lazy:
            leaf.close()


def test_invalid_cyclic_completed_value_closes_lazy_descendants():
    async def unused():
        return None

    leaf = unused()
    value = {"self": None, "lazy": deep_value(leaf)}
    value["self"] = value
    try:
        assert snapshot_model_response(ModelResponse(output=value))["invalid_fields"] == ["output"]
        assert inspect.getcoroutinestate(leaf) == inspect.CORO_CLOSED
    finally:
        leaf.close()


def test_failed_generator_close_retains_completed_original_response_and_drains_siblings(tmp_path):
    def faulty():
        try:
            yield "started"
        finally:
            raise RuntimeError("private lazy supplier teardown")

    async def sibling():
        return None

    generator, coroutine = faulty(), sibling()
    next(generator)
    provider = CompletedProvider([coroutine, generator])

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "lazy.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            result = await engine.drive(handle.run_id)
            assert result.state == "failed" and result.error == {"code": "validation_error"}
            action = engine.store.run(handle.run_id)["actions"][0]
            assert action["status"] == "rejected"
            assert action["attempts"][0]["status"] == "completed"
            assert action["received_response"]["invalid_fields"] == ["output"]
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert provider.calls == 1
            assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
            assert inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED

    try:
        asyncio.run(run())
    finally:
        coroutine.close()
        generator.close()


@pytest.mark.parametrize("nested", [False, True])
def test_completed_unpaired_unicode_is_known_invalid_and_original_run_is_settled(tmp_path, nested):
    value = chr(0xD800)
    output = {"items": [value]} if nested else value
    provider = CompletedProvider(output)

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "unicode.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            result = await engine.drive(handle.run_id)
            assert result.state == "failed" and result.error == {"code": "validation_error"}
            action = engine.store.run(handle.run_id)["actions"][0]
            assert action["status"] == "rejected"
            assert action["received_response"] == {
                "output": None,
                "tool_calls": [],
                "usage": None,
                "invalid_fields": ["output"],
            }
            assert action["attempts"][0]["status"] == "completed"
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert provider.calls == 1
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert provider.calls == 1

    asyncio.run(run())


def test_supplier_lazy_finalizer_cancel_is_not_original_task_cancellation(tmp_path):
    async def sibling():
        return None

    def faulty():
        try:
            yield "started"
        finally:
            raise asyncio.CancelledError("private supplier lazy cleanup cancellation")

    generator, coroutine = faulty(), sibling()
    next(generator)
    provider = CompletedProvider([coroutine, generator])

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "lazy-cancel.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="submit", budget=4)
            cancelled = False
            try:
                result = await engine.drive(handle.run_id)
            except asyncio.CancelledError:
                cancelled = True
                result = engine.status(handle.run_id)
            action = engine.store.run(handle.run_id)["actions"][0]
            assert not cancelled
            assert result.state == "failed" and result.error == {"code": "validation_error"}
            assert action["status"] == "rejected"
            assert action["attempts"][0]["status"] == "completed"
            assert action["received_response"]["invalid_fields"] == ["output"]
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
            assert inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED
            assert provider.calls == 1
            await engine.wait_for_threads()

    try:
        asyncio.run(run())
    finally:
        coroutine.close()
        generator.close()


def test_returned_response_container_depth_policy_and_original_run_boundary_sweep(tmp_path):
    """New received evidence has a 128-container bound; valid JSON can be deeper."""
    observations = []

    async def run():
        for depth in [0, 1, 64, 127, 128, 129, 130, 256, *range(450, 510), 1500]:
            output = "completed"
            for _ in range(depth):
                output = [output]
            provider = CompletedProvider(output)
            with LocalEngine(
                SQLiteStore(tmp_path / f"depth-{depth}.sqlite"),
                providers={"default": provider},
                tools=ToolRegistry(),
            ) as engine:
                handle = engine.submit(
                    AgentSpec("a", "Answer"), "task", command_id="submit", budget=4
                )
                result = await engine.drive(handle.run_id)
                action = engine.store.run(handle.run_id)["actions"][0]
                budget = engine.store.budget(handle.run_id)
                observations.append(
                    {
                        "depth": depth,
                        "state": result.state,
                        "error": result.error,
                        "status": action["status"],
                        "attempt": action["attempts"][0]["status"],
                        "received": action.get("received_response") is not None,
                        "budget": budget,
                        "calls": provider.calls,
                    }
                )
                await engine.wait_for_threads()
        from ralf_agent.types import canonical

        (tmp_path / "depth-sweep.json").write_text(canonical(observations))
        for item in observations:
            assert item["received"] and item["attempt"] == "completed" and item["calls"] == 1
            assert item["budget"] == {"limit": 4, "held": 0, "spent": 1}
            assert item["state"] == ("succeeded" if item["depth"] <= 128 else "failed")
            assert item["status"] == ("completed" if item["depth"] <= 128 else "rejected")
            assert item["error"] == (None if item["depth"] <= 128 else {"code": "validation_error"})

    asyncio.run(run())


@pytest.mark.parametrize("field", ["tool_calls", "usage", "continuation"])
def test_depth_bound_on_every_new_response_field_keeps_original_completed_evidence(tmp_path, field):
    from ralf_agent import ToolCall, ToolSpec
    from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
    from ralf_agent.types import digest

    deep = "completed"
    for _ in range(129):
        deep = [deep]

    class Provider:
        identity = {"kind": "bounded-original-response-field", "version": "1"}
        calls = 0
        continuation_identity = (
            {"protocol": "field-test", "owner_digest": "a" * 64}
            if field == "continuation"
            else None
        )

        async def complete(self, messages, tools):
            self.calls += 1
            if field == "tool_calls":
                return ModelResponse(tool_calls=(ToolCall("read", {"deep": deep}),))
            if field == "usage":
                return ModelResponse(output={"completed": True}, usage={"metadata": deep})
            output = {"completed": True}
            return ContinuedModelResponse(
                output=output,
                continuation=ModelContinuation(
                    protocol="field-test",
                    owner_digest="a" * 64,
                    decision_digest=digest({"output": output, "tool_calls": []}),
                    data={"deep": deep},
                ),
            )

    async def run():
        provider = Provider()
        registry = ToolRegistry()
        registry.register(
            ToolSpec("read", "Read actual supplied arguments", {"type": "object"}),
            lambda arguments, context: arguments,
        )
        with LocalEngine(
            SQLiteStore(tmp_path / f"{field}.sqlite"),
            providers={"default": provider},
            tools=registry,
            model_continuation=field == "continuation",
        ) as engine:
            handle = engine.submit(
                AgentSpec("a", "Answer", ("read",)), "task", command_id="submit", budget=4
            )
            result = await engine.drive(handle.run_id)
            record = engine.store.run(handle.run_id)
            action = record["actions"][0]
            assert result.state == "failed" and result.error == {"code": "validation_error"}
            assert len(record["actions"]) == 1 and action["status"] == "rejected"
            assert action["received_response"]["invalid_fields"] == [field]
            assert action["attempts"][0]["status"] == "completed"
            assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
            assert provider.calls == 1
            await engine.wait_for_threads()

    asyncio.run(run())
