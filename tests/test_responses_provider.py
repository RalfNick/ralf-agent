import asyncio
import importlib
import json
from contextlib import aclosing

import httpx
import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    RuntimeBuilder,
    RuntimeProfile,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import ProviderError, ValidationError

from .test_model_chat import Frames


def provider_type():
    api = importlib.import_module("relf_agent")
    assert hasattr(api, "OpenAIResponsesProvider"), "Native Responses Provider is missing"
    return api.OpenAIResponsesProvider


def completed(output=None):
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": output if output is not None else [message("hello")],
        "usage": {"input_tokens": 11, "output_tokens": 3},
    }


def message(text):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def call(arguments='{"value":7}'):
    return {
        "id": "fc_item",
        "type": "function_call",
        "call_id": "call_7",
        "name": "set_value",
        "arguments": arguments,
        "status": "completed",
    }


def frames(events):
    values = [{**v, "sequence_number": i} for i, v in enumerate(events)]
    return Frames(
        "".join(
            "event: " + v["type"] + "\ndata: " + json.dumps(v) + "\n\n" for v in values
        ).encode()
    )


def test_responses_request_preserves_call_ids_stateless_history_and_function_schema():
    async def run():
        captured = []

        def serve(request):
            captured.append(request)
            return httpx.Response(200, json=completed())

        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            provider = provider_type()(
                "fixture", api_key="fixture-secret", client=client, temperature=0.2
            )
            schema = {"type": "object", "properties": {"value": {"type": "integer"}}}
            tools = [
                {
                    "type": "function",
                    "function": {"name": "set_value", "description": "Set", "parameters": schema},
                }
            ]
            history = [
                {"role": "system", "content": "Policy"},
                {"role": "user", "content": "q"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_7",
                            "type": "function",
                            "function": {"name": "set_value", "arguments": '{"value":7}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_7", "content": '{"done":true}'},
            ]
            result = await provider.complete(history, tools)
            assert result.output == "hello" and result.usage == {
                "input_tokens": 11,
                "output_tokens": 3,
            }
            payload = json.loads(captured[0].content)
            assert str(captured[0].url) == "https://api.openai.com/v1/responses"
            assert captured[0].headers["authorization"] == "Bearer fixture-secret"
            assert payload["store"] is False and "previous_response_id" not in payload
            assert payload["temperature"] == 0.2 and payload["max_output_tokens"] == 1024
            assert payload["input"] == [
                {"role": "system", "content": "Policy"},
                {"role": "user", "content": "q"},
                {
                    "type": "function_call",
                    "call_id": "call_7",
                    "name": "set_value",
                    "arguments": '{"value":7}',
                },
                {"type": "function_call_output", "call_id": "call_7", "output": '{"done":true}'},
            ]
            assert payload["tools"] == [
                {
                    "type": "function",
                    "name": "set_value",
                    "description": "Set",
                    "parameters": schema,
                    "strict": False,
                }
            ]
            assert "fixture-secret" not in json.dumps(provider.identity)

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "incomplete",
        "failed",
        "refusal",
        "reasoning",
        "server_tool",
        "empty",
        "duplicate",
        "invalid_args",
        "invalid_usage",
    ],
)
def test_responses_refuses_incomplete_unsupported_and_malformed_results(change):
    async def run():
        value = completed()
        if change in {"incomplete", "failed"}:
            value["status"] = change
        elif change == "refusal":
            value["output"][0]["content"] = [{"type": "refusal", "refusal": "secret"}]
        elif change == "reasoning":
            value["output"].insert(0, {"type": "reasoning", "id": "rs", "summary": []})
        elif change == "server_tool":
            value["output"] = [{"type": "web_search_call", "status": "completed"}]
        elif change == "empty":
            value["output"] = [message("   ")]
        elif change == "duplicate":
            value["output"] = [call(), call()]
        elif change == "invalid_args":
            value["output"] = [call('{"value":NaN}')]
        elif change == "invalid_usage":
            value["usage"]["input_tokens"] = True
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=value))
        ) as client:
            with pytest.raises(ProviderError) as error:
                await provider_type()("fixture", api_key="fixture-secret", client=client).complete(
                    [], []
                )
            assert "secret" not in str(error.value)

    asyncio.run(run())


def test_responses_json_formats_are_explicit_detached_and_validated():
    async def run():
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        }
        captured = []

        def serve(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=completed([message('{"ok":true}')]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            cls = provider_type()
            provider = cls("fixture", api_key="fixture", client=client, output_schema=schema)
            schema["properties"]["ok"]["type"] = "string"
            value = await provider.complete([{"role": "user", "content": "Return JSON"}], [])
            assert json.loads(value.output)["ok"] is True
            assert captured[0]["text"]["format"] == {
                "type": "json_schema",
                "name": "ralf_output",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                },
            }
            native = cls("fixture", api_key="fixture", client=client, json_mode=True)
            await native.complete([{"role": "user", "content": "Return JSON"}], [])
            assert captured[1]["text"]["format"] == {"type": "json_object"}
            with pytest.raises(ValidationError):
                native.validate_request([{"role": "user", "content": "hello"}], [])
            with pytest.raises(ValidationError):
                cls("fixture", api_key="fixture", json_mode=True, output_schema={"type": "object"})
            with pytest.raises(ValidationError):
                cls("fixture", api_key="fixture", output_schema={"type": "NOT_JSON"})

    asyncio.run(run())


def test_responses_stream_requires_final_snapshot_matching_received_fragments():
    async def run():
        stream = frames(
            [
                {"type": "response.created", "response": {"id": "resp_1"}},
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "item_id": "msg_1",
                    "delta": "hel",
                },
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "item_id": "msg_1",
                    "delta": "lo",
                },
                {"type": "response.completed", "response": completed()},
            ]
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))
        ) as client:
            provider = provider_type()("fixture", api_key="fixture", client=client)
            async with aclosing(provider.stream([], [])) as events:
                values = [v async for v in events]
            assert [v.text for v in values if v.kind == "text"] == ["hel", "lo"]
            assert values[-1].response.output == "hello" and stream.closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    ["mismatch", "missing_final", "after_final", "bad_sequence", "event_type", "tool_mismatch"],
)
def test_responses_stream_corruption_cannot_become_a_decision(change):
    async def run():
        events = [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_1",
                "delta": "hello",
            },
            {"type": "response.completed", "response": completed()},
        ]
        if change == "mismatch":
            events[1]["response"] = completed([message("different")])
        elif change == "missing_final":
            events.pop()
        elif change == "after_final":
            events.append(events[0])
        elif change == "bad_sequence":
            events[0]["sequence_number"] = 9
        elif change == "event_type":
            events.insert(0, {"type": "response.reasoning_text.delta", "delta": "opaque"})
        elif change == "tool_mismatch":
            events = [
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "item_id": "fc_item",
                    "delta": '{"value":9}',
                },
                {"type": "response.completed", "response": completed([call()])},
            ]
        stream = frames(events)
        if change == "bad_sequence":
            stream = Frames(
                b"event: response.completed\ndata: "
                + json.dumps(
                    {"type": "response.completed", "sequence_number": -1, "response": completed()}
                ).encode()
                + b"\n\n"
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))
        ) as client:
            with pytest.raises(ProviderError):
                await provider_type()(
                    "fixture", api_key="fixture", client=client, stream=True
                ).complete([], [])
        assert stream.closed

    asyncio.run(run())


def test_responses_agent_approval_survives_restart_and_echoes_original_call_id(tmp_path):
    async def run():
        writes = []
        requests = []

        def write(arguments, context):
            writes.append(arguments["value"])
            return {"written": arguments["value"]}

        def serve(request):
            payload = json.loads(request.content)
            requests.append(payload)
            output = (
                [message('{"written":7}')]
                if any(x.get("type") == "function_call_output" for x in payload["input"])
                else [call()]
            )
            return httpx.Response(200, json=completed(output))

        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "set_value",
                "Set",
                {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "integer"}},
                },
                effect="idempotent_write",
                requires_approval=True,
            ),
            write,
        )
        spec = AgentSpec(
            "responses-test",
            "Use set_value, then return JSON.",
            ("set_value",),
            output_schema={
                "type": "object",
                "required": ["written"],
                "properties": {"written": {"const": 7}},
            },
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            provider = provider_type()("fixture", api_key="fixture", client=client)
            with LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"), providers={"default": provider}, tools=tools
            ) as engine:
                handle = engine.submit(spec, "write7", command_id="s")
                result = await engine.drive(handle.run_id)
                assert result.state == "waiting_approval" and writes == []
                pending = result.pending[0]
                engine.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="a"
                )
            with LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"), providers={"default": provider}, tools=tools
            ) as engine:
                result = await engine.drive(handle.run_id)
                assert result.state == "succeeded" and result.result == {"written": 7}
                assert engine.submit(spec, "write7", command_id="s") == handle
                assert (await engine.drive(handle.run_id)).state == "succeeded" and writes == [7]
            assert requests[-1]["input"][-1] == {
                "type": "function_call_output",
                "call_id": "call_7",
                "output": '{"written":7}',
            }

    asyncio.run(run())


def test_responses_profile_builds_additively_and_rejects_secrets_before_creating_store(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FIXTURE_RESPONSES_KEY", "private-fixture")
    profile = RuntimeProfile(
        "native",
        "1",
        {
            "default": {
                "adapter": "openai-responses",
                "config": {
                    "model": "fixture",
                    "api_key_env": "FIXTURE_RESPONSES_KEY",
                    "stream": True,
                },
            }
        },
    )
    with RuntimeBuilder().build(profile, tmp_path / "ok.sqlite") as engine:
        handle = engine.submit(AgentSpec("a", "q"), "q", command_id="s")
        assert (
            engine.diagnostics(handle.run_id).manifest["providers"]["default"]["kind"]
            == "openai-responses"
        )
    invalid = RuntimeProfile(
        "native",
        "1",
        {
            "default": {
                "adapter": "openai-responses",
                "config": {"model": "fixture", "api_key": "embedded-secret"},
            }
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(invalid, tmp_path / "absent.sqlite")
    assert not (tmp_path / "absent.sqlite").exists()


@pytest.mark.parametrize("effort", [[], {}, 1, "high"])
def test_unsupported_reasoning_configuration_is_a_typed_preflight_error(effort):
    with pytest.raises(ValidationError):
        provider_type()("fixture", api_key="fixture", reasoning_effort=effort)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {}},
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"x": {"type": "string"}},
            "required": [],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"x": {"type": "object", "properties": {}}},
            "required": ["x"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"x": {"$ref": "https://example.invalid/private"}},
            "required": ["x"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
            "allOf": [{"type": "object"}],
        },
    ],
)
def test_native_strict_schema_constraints_are_rejected_before_network(schema):
    with pytest.raises(ValidationError):
        provider_type()("fixture", api_key="fixture", output_schema=schema)
