"""Replacement Providers must obey the same adoption boundary on both authorities."""

import asyncio
import json
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolCall
from relf_agent.tools import ToolRegistry, ToolSpec


class Provider:
    def __init__(self, value, *, drift=False):
        self.value, self.drift = value, drift
        self.identity = {"kind": "adoption-contract-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if self.drift:
            self.identity = {**self.identity, "version": "2"}
        return self.value


def read(arguments, context):
    return arguments


def tools():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "read",
            "Read",
            {
                "type": "object",
                "required": ["n"],
                "properties": {"n": {"type": "integer"}},
                "additionalProperties": False,
            },
        ),
        read,
    )
    return registry


async def temporal_case(spec, response, *, cancel=False, drift=False):
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    runtime = TemporalRuntime(providers={"default": Provider(response, drift=drift)}, tools=tools())
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "first",
        submission_request(spec, "task", budget=8),
        runtime.manifest,
    )
    action, request = state.next_operation()
    if cancel:
        state.command("stop", {"kind": "cancel", "scope": asdict(Scope())})
    evidence = await runtime.complete_model(request)
    state.accept_model(action["id"], evidence)
    return state, action, evidence


@pytest.mark.parametrize("backend", ["local", "temporal"])
@pytest.mark.parametrize(
    "value,schema,code",
    [
        (
            ModelResponse(
                tool_calls=(ToolCall("read", {"n": 1}, "same"), ToolCall("read", {"n": 2}, "same"))
            ),
            None,
            "validation_error",
        ),
        (ModelResponse(output={"wrong": 1}), {"type": "integer"}, "validation_error"),
        (
            ModelResponse(tool_calls=(ToolCall("read", {"n": "wrong"}, "c"),)),
            None,
            "validation_error",
        ),
        (ModelResponse(tool_calls=(ToolCall("secret", {}, "c"),)), None, "authorization_denied"),
        (ModelResponse(tool_calls=(ToolCall("read", {"n": 1}, True),)), None, "validation_error"),
        (ModelResponse(output="   "), None, "validation_error"),
        (ModelResponse(), None, "validation_error"),
    ],
    ids=[
        "duplicate-id",
        "invalid-schema",
        "invalid-args",
        "undeclared",
        "invalid-id",
        "empty",
        "missing",
    ],
)
def test_received_rejected_decisions_keep_evidence_and_never_adopt_tools(
    tmp_path, backend, value, schema, code
):
    async def run():
        response = ModelResponse(
            value.output, value.tool_calls, {"input_tokens": 4, "output_tokens": 2}
        )
        spec = AgentSpec("a", "Answer", ("read",), output_schema=schema)
        if backend == "local":
            with LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": Provider(response)},
                tools=tools(),
            ) as engine:
                handle = engine.submit(spec, "task", command_id="first", budget=8)
                result = await engine.drive(handle.run_id)
                record = engine.store.run(handle.run_id)
                action = record["actions"][0]
                budget = engine.store.budget(handle.run_id)
                assert result.state == "failed" and result.error["code"] == code
                assert budget["spent"] == 1 and budget["held"] == 0
                assert not [a for a in record["actions"] if a["kind"] == "tool"]
        else:
            state, action, _ = await temporal_case(spec, response)
            assert state.state == "failed" and state.error["code"] == code
            assert state.budget["spent"] == 1 and state.budget["unknown"] == 0
            assert not [a for a in state.actions if a["kind"] == "tool"]
            assert state.quiescent
        assert action["status"] == "rejected"
        assert action["received_response"] == json.loads(json.dumps(asdict(response)))

    asyncio.run(run())


@pytest.mark.parametrize("cancel,drift", [(True, False), (False, True)])
def test_temporal_completed_response_survives_cancel_or_release_refusal(cancel, drift):
    async def run():
        response = ModelResponse(output={"wrong": 1}, usage={"input_tokens": 4, "output_tokens": 2})
        state, action, _ = await temporal_case(
            AgentSpec("a", "Answer", output_schema={"type": "integer"}),
            response,
            cancel=cancel,
            drift=drift,
        )
        assert state.state == ("cancelled" if cancel else "failed")
        assert action["received_response"] == json.loads(json.dumps(asdict(response)))
        assert state.budget["spent"] == 1 and state.budget["unknown"] == 0
        assert not [a for a in state.actions if a["kind"] == "tool"]

    asyncio.run(run())


def test_shared_validation_detaches_valid_proposals_and_checks_fallback_ids():
    from relf_agent import decisions
    from relf_agent.errors import ValidationError
    from relf_agent.harness import DecisionProposal

    validator = getattr(decisions, "validate_decision", None)
    assert callable(validator), "Missing common decision acceptance boundary"
    proposal = DecisionProposal(tool_calls=(ToolCall("read", {"n": 7}, "one"),))
    result = validator(AgentSpec("a", "Answer", ("read",)), proposal, tools().manifests(("read",)))
    result.tool_calls[0].arguments["n"] = 8
    assert proposal.tool_calls[0].arguments == {"n": 7}
    with pytest.raises(ValidationError):
        decisions.validate_call_ids(["generated", "generated"])


def test_legacy_temporal_response_replays_its_recorded_result():
    async def run():
        state, _, _ = await temporal_case(AgentSpec("a", "Answer"), ModelResponse(output="ok"))
        from relf_agent.temporal_state import TemporalRunState
        from relf_agent.types import submission_request

        legacy = TemporalRunState(
            "old",
            asdict(Scope()),
            "first",
            submission_request(AgentSpec("a", "Answer"), "task", budget=8),
            state.manifest,
        )
        action, _ = legacy.next_operation()
        legacy.accept_model(
            action["id"], {"ok": False, "code": "validation_error", "dispatched": True}
        )
        assert legacy.state == "failed" and legacy.budget["unknown"] == 1
        assert action["status"] == "outcome_unknown"

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["schema", "duplicate-id"])
def test_actual_temporal_rejected_receipt_replays_without_unknown_execution(kind):
    import os
    import uuid

    address = os.getenv("RALF_TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("requires actual Temporal Service")

    async def run():
        from temporalio.client import Client, WorkflowHistory

        from relf_agent import (
            TemporalEngine,
            TemporalRuntime,
            build_temporal_worker,
            replay_temporal_history,
        )

        value = (
            ModelResponse(output={"wrong": 1}, usage={"input_tokens": 4, "output_tokens": 2})
            if kind == "schema"
            else ModelResponse(
                tool_calls=(ToolCall("read", {"n": 1}, "same"), ToolCall("read", {"n": 2}, "same")),
                usage={"input_tokens": 4, "output_tokens": 2},
            )
        )
        spec = AgentSpec(
            "a",
            "Answer",
            ("read",),
            output_schema={"type": "integer"} if kind == "schema" else None,
        )
        runtime = TemporalRuntime(providers={"default": Provider(value)}, tools=tools())
        client = await Client.connect(address)
        queue = "adoption-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.manifest,
            scope=Scope("adoption", queue),
            drive_timeout=20,
        )
        async with build_temporal_worker(client, task_queue=queue, runtime=runtime):
            handle = await engine.submit(spec, "task", command_id="first", budget=8)
            result = await engine.drive(handle.run_id)
            assert result.state == "failed" and result.error["code"] == "validation_error"
            diagnostics = await engine.diagnostics(handle.run_id)
            assert diagnostics.budget["spent"] == 1 and diagnostics.budget["unknown"] == 0
            assert diagnostics.workflow["quiescent"]
            assert len(diagnostics.snapshot.actions) == 1
            assert diagnostics.snapshot.actions[0]["received_response"] == json.loads(
                json.dumps(asdict(value))
            )
            history = await client.get_workflow_handle(handle.run_id).fetch_history()
        await replay_temporal_history(WorkflowHistory.from_json(handle.run_id, history.to_json()))
        async with build_temporal_worker(client, task_queue=queue, runtime=runtime):
            assert (await engine.status(handle.run_id)).state == "failed"
            assert (await engine.diagnostics(handle.run_id)).budget["unknown"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("backend", ["local", "temporal"])
@pytest.mark.parametrize("field", ["output_nan", "output_lazy", "calls_lazy", "usage_nan"])
def test_completed_malformed_response_retains_known_completion_and_closes_lazy_fields(
    tmp_path, backend, field
):
    import inspect

    async def lazy():
        pytest.fail("lazy model field must never be awaited")

    async def run():
        pending = lazy() if field in {"output_lazy", "calls_lazy"} else None
        usage = (
            {"input_tokens": 4, "output_tokens": 2}
            if field != "usage_nan"
            else {"input_tokens": float("nan")}
        )
        response = ModelResponse(
            output=float("nan")
            if field == "output_nan"
            else pending
            if field == "output_lazy"
            else "ok",
            tool_calls=pending if field == "calls_lazy" else (),
            usage=usage,
        )
        try:
            if backend == "local":
                with LocalEngine(
                    SQLiteStore(tmp_path / "malformed.sqlite"),
                    providers={"default": Provider(response)},
                    tools=tools(),
                ) as engine:
                    handle = engine.submit(
                        AgentSpec("a", "Answer"), "task", command_id="first", budget=8
                    )
                    result = await engine.drive(handle.run_id)
                    budget = engine.store.budget(handle.run_id)
                    action = engine.store.run(handle.run_id)["actions"][0]
                    assert result.state == "failed" and result.error["code"] == "validation_error"
                    assert budget["spent"] == 1 and budget["held"] == 0
            else:
                state, action, _ = await temporal_case(AgentSpec("a", "Answer"), response)
                assert state.state == "failed" and state.error["code"] == "validation_error"
                assert state.budget["spent"] == 1 and state.budget["unknown"] == 0
                assert state.quiescent
            assert action["status"] == "rejected"
            expected_field = {"calls_lazy": "tool_calls"}.get(field, field.split("_")[0])
            assert expected_field in action["received_response"]["invalid_fields"]
            if field != "usage_nan":
                assert action["received_response"]["usage"] == usage
            if pending is not None:
                assert inspect.getcoroutinestate(pending) == inspect.CORO_CLOSED
        finally:
            if pending is not None:
                pending.close()

    asyncio.run(run())
