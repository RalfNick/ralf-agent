import asyncio
import copy
import json
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    OpenAIResponsesProvider,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    evaluate_model_compatibility,
)
from ralf_agent.errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    ProviderError,
    ValidationError,
)
from ralf_agent.responses_stream import ResponsesStream

from .test_model_compatibility import Provider
from .test_responses_provider import call, completed, message


def test_nested_untyped_schema_cannot_trigger_remote_retrieval(monkeypatch):
    fetched = []

    def fetch(*args, **kwargs):
        fetched.append(args)
        raise AssertionError("Remote retrieval forbidden")

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    schema = {
        "type": "object",
        "properties": {"x": {"properties": {"y": {"$ref": "https://example.invalid/private"}}}},
        "required": ["x"],
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError):
        OpenAIResponsesProvider("fixture", api_key="fixture", output_schema=schema)
    assert fetched == []


@pytest.mark.parametrize("shape", ["properties", "$defs", "items", "anyOf"])
def test_remote_references_rejected_in_every_schema_location(shape):
    remote = {"$ref": "file:///review-private-schema.json"}
    nested = {
        shape: {"y": remote}
        if shape in {"properties", "$defs"}
        else [remote]
        if shape == "anyOf"
        else remote
    }
    schema = {
        "type": "object",
        "properties": {"x": nested},
        "required": ["x"],
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError):
        OpenAIResponsesProvider("fixture", api_key="fixture", output_schema=schema)


@pytest.mark.parametrize(
    "change",
    [
        "item_name",
        "item_call_id",
        "argument_done",
        "text_done",
        "part_done",
        "response_id",
        "added_id",
    ],
)
def test_stream_completion_metadata_must_agree(change):
    final = (
        completed([call()])
        if change in {"item_name", "item_call_id", "argument_done"}
        else completed()
    )
    if change.startswith("item_"):
        item = copy.deepcopy(final["output"][0])
        item["name" if change == "item_name" else "call_id"] = "different"
        event = {"type": "response.output_item.done", "output_index": 0, "item": item}
    elif change == "argument_done":
        event = {
            "type": "response.function_call_arguments.done",
            "output_index": 0,
            "item_id": "fc_item",
            "arguments": '{"value":9}',
        }
    elif change == "text_done":
        event = {
            "type": "response.output_text.done",
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_1",
            "text": "different",
        }
    elif change == "part_done":
        event = {
            "type": "response.content_part.done",
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_1",
            "part": {"type": "output_text", "text": "different", "annotations": []},
        }
    elif change == "response_id":
        event = {"type": "response.created", "response": {"id": "different"}}
    else:
        item = message("")
        item["id"] = "different"
        event = {"type": "response.output_item.added", "output_index": 0, "item": item}
    stream = ResponsesStream(lambda v: v)
    with pytest.raises(ValueError):
        stream.feed(event["type"], json.dumps({**event, "sequence_number": 0}))
        stream.feed(
            "response.completed",
            json.dumps({"type": "response.completed", "sequence_number": 1, "response": final}),
        )
        stream.finish()


def test_valid_complete_metadata_and_local_recursive_schema_are_supported():
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**call(""), "status": "in_progress"},
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "item_id": "fc_item",
            "delta": '{"value":7}',
        },
        {
            "type": "response.function_call_arguments.done",
            "output_index": 0,
            "item_id": "fc_item",
            "arguments": '{"value":7}',
        },
        {"type": "response.output_item.done", "output_index": 0, "item": call()},
        {"type": "response.completed", "response": completed([call()])},
    ]
    stream = ResponsesStream(lambda v: v)
    for i, event in enumerate(events):
        stream.feed(event["type"], json.dumps({**event, "sequence_number": i}))
    assert stream.finish() == completed([call()])
    schema = {
        "type": "object",
        "properties": {"next": {"anyOf": [{"$ref": "#"}, {"type": "null"}]}},
        "required": ["next"],
        "additionalProperties": False,
    }
    provider = OpenAIResponsesProvider("fixture", api_key="fixture", output_schema=schema)
    assert provider._parse(json.dumps(completed([message('{"next":{"next":null}}')]))).output


def test_explicit_schema_rejects_invalid_captured_default_before_registration():
    def fn(value: int = "invalid-default"):
        raise AssertionError("Must not execute")

    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        registry.register_function(
            fn,
            effect="read_only",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "additionalProperties": False,
            },
        )
    with pytest.raises(DefinitionMismatch):
        registry.get("fn")


def test_effective_default_arguments_are_validated_before_invocation():
    writes = []

    def fn(value: int = 7, guard: str = "safe"):
        writes.append(value)

    tools = ToolRegistry()
    tools.register_function(
        fn,
        effect="read_only",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}, "guard": {"type": "string"}},
            "additionalProperties": False,
            "not": {"required": ["value", "guard"]},
        },
    )
    with pytest.raises(ValidationError):
        tools.get("fn").handler({}, None)
    assert writes == []


def test_policy_sees_effective_defaults_before_business_write(tmp_path):
    writes, checked = [], []

    def write(target: str = "prod"):
        writes.append(target)
        return "written"

    class DefaultsProvider:
        identity = {"kind": "default-policy-fixture"}

        async def complete(self, messages, tools):
            if any(m["role"] == "tool" for m in messages):
                return ModelResponse("done")
            return ModelResponse(tool_calls=(ToolCall("write", {}, "call"),))

    def policy(scope, spec, arguments):
        checked.append(arguments)
        if arguments.get("target") == "prod":
            raise AuthorizationDenied("Production forbidden")

    tools = ToolRegistry()
    tools.register_function(write, effect="idempotent_write")
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": DefaultsProvider()},
        tools=tools,
        policy=policy,
    ) as engine:
        handle = engine.submit(AgentSpec("defaults", "Write", ("write",)), "write", command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and checked == [{"target": "prod"}]
    assert writes == []


def test_temporal_model_activity_resolves_defaults_before_history_adoption():
    from ralf_agent.temporal_activities import TemporalRuntime

    def write(target: str = "prod"):
        return target

    class DefaultsProvider:
        identity = {"kind": "default-temporal-fixture"}

        async def complete(self, messages, tools):
            return ModelResponse(tool_calls=(ToolCall("write", {}, "call"),))

    tools = ToolRegistry()
    tools.register_function(write, effect="read_only", requires_approval=True)
    runtime = TemporalRuntime(providers={"default": DefaultsProvider()}, tools=tools)
    result = asyncio.run(
        runtime.complete_model(
            {
                "runtime_manifest": runtime.manifest,
                "step": asdict(AgentSpec("defaults", "Write", ("write",))),
                "messages": [{"role": "user", "content": "Write"}],
            }
        )
    )
    assert result["ok"] and result["tool_calls"][0]["arguments"] == {"target": "prod"}


@pytest.mark.parametrize("field", ["generation", "kind", "model"])
def test_public_probe_identity_never_exports_arbitrary_nested_values(tmp_path, field):
    provider = Provider()
    provider.identity = {"kind": "fixture", field: {"api_key": "REVIEW_SENTINEL"}}
    report = asyncio.run(
        evaluate_model_compatibility(provider, cases=["text"], evidence_dir=tmp_path / "evidence")
    )
    assert report["passed"] == 1 and "REVIEW_SENTINEL" not in json.dumps(report)


def test_public_probe_normalizes_custom_error_codes(tmp_path):
    class Broken(Provider):
        async def complete(self, messages, tools):
            error = ProviderError("private body")
            error.code = "REVIEW_PRIVATE_ERROR_CODE"
            raise error

    report = asyncio.run(
        evaluate_model_compatibility(Broken(), cases=["text"], evidence_dir=tmp_path / "evidence")
    )
    assert report["passed"] == 0 and "REVIEW_PRIVATE_ERROR_CODE" not in json.dumps(report)
