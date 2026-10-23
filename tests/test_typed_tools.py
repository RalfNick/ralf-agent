import asyncio
import importlib
from typing import Annotated, Literal

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolCall, ToolRegistry
from relf_agent.errors import DefinitionMismatch, ValidationError


def infer(function, **kwargs):
    api = importlib.import_module("relf_agent")
    assert hasattr(api, "infer_tool_schema"), "Typed Schema inference is missing"
    return api.infer_tool_schema(function, **kwargs)


def register(registry, function, **kwargs):
    assert hasattr(registry, "register_function"), "Typed registration is missing"
    return registry.register_function(function, **kwargs)


def test_inferred_schema_covers_json_types_and_keeps_defaults_private():
    def search(
        query: str,
        count: int = 3,
        *,
        flag: bool = False,
        items: list[str] = (),
        metadata: dict[str, float] | None = None,
        point: tuple[int, str] = (1, "a"),
        mode: Literal["brief", "full"] = "brief",
        tag: Annotated[str, "hint"] = "x",
    ):
        return query

    schema = infer(search)
    assert schema["required"] == ["query"] and schema["additionalProperties"] is False
    assert schema["properties"]["count"] == {"type": "integer"}
    assert schema["properties"]["metadata"] == {
        "anyOf": [{"type": "object", "additionalProperties": {"type": "number"}}, {"type": "null"}]
    }
    assert schema["properties"]["point"] == {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "string"}],
        "minItems": 2,
        "maxItems": 2,
    }
    assert schema["properties"]["mode"] == {"enum": ["brief", "full"]}
    assert "default" not in str(schema) and "hint" not in str(schema)
    with pytest.raises(ValidationError):
        registry = ToolRegistry()
        register(registry, search, effect="read_only")
        registry.get("search").validate({"query": "x", "count": True})


def test_postponed_annotations_are_parsed_without_evaluating_code():
    calls = []

    def malicious():
        calls.append("evaluated")
        return str

    def fn(value):
        return value

    fn.__annotations__ = {"value": "malicious()"}
    with pytest.raises(ValidationError):
        infer(fn)
    assert calls == []
    fn.__annotations__ = {"value": "list[dict[str, int | None]]"}
    assert infer(fn)["properties"]["value"]["items"]["additionalProperties"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }


@pytest.mark.parametrize(
    "annotation",
    [
        "UnknownType",
        '__import__("os").getenv("TOKEN")',
        "typing.Any",
        "list",
        "dict[int,str]",
        "Literal[True,1]",
    ],
)
def test_unsupported_annotations_fail_before_registration(annotation):
    def fn(value):
        return value

    fn.__annotations__ = {"value": annotation}
    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        register(registry, fn, effect="read_only")
    with pytest.raises(DefinitionMismatch):
        registry.get("fn")


def test_explicit_schema_supports_unannotated_functions_without_evaluation():
    def fn(value):
        return value

    fn.__annotations__ = {"value": "should_not_execute()"}
    registry = ToolRegistry()
    assert (
        register(
            registry,
            fn,
            effect="read_only",
            input_schema={
                "type": "object",
                "required": ["value"],
                "additionalProperties": False,
                "properties": {"value": {"type": "string"}},
            },
        )
        is fn
    )
    assert registry.get("fn").handler({"value": "ok"}, None) == "ok"


def test_missing_types_bad_defaults_and_non_keyword_signatures_are_rejected():
    def missing(value):
        return value

    def invalid(value: int = "secret-default"):
        return value

    def positional(value: int, /):
        return value

    def variadic(*values: int):
        return values

    for fn in [missing, invalid, positional, variadic]:
        with pytest.raises(ValidationError):
            infer(fn)

    def finite(value: float = float("nan")):
        return value

    with pytest.raises(ValidationError):
        infer(finite)


def test_context_is_host_injected_and_cannot_be_spoofed_by_model():
    def fn(value: str, *, context):
        return {"value": value, "run": context}

    registry = ToolRegistry()
    register(registry, fn, effect="read_only", context_parameter="context")
    tool = registry.get("fn")
    assert "context" not in tool.spec.input_schema["properties"]
    assert tool.handler({"value": "ok"}, "host") == {"value": "ok", "run": "host"}
    with pytest.raises(ValidationError):
        tool.handler({"value": "ok", "context": "spoof"}, "host")
    with pytest.raises(ValidationError):
        register(ToolRegistry(), fn, effect="read_only", context_parameter="absent")


def test_decorator_returns_original_function_and_requires_effect_declaration():
    registry = ToolRegistry()
    assert hasattr(registry, "tool"), "Typed decorator is missing"

    @registry.tool(effect="read_only", name="lookup", description="Lookup")
    def fn(value: int):
        return value + 1

    assert fn(2) == 3 and registry.get("lookup").handler({"value": 2}, None) == 3
    assert registry.descriptions(["lookup"])[0]["function"]["description"] == "Lookup"
    with pytest.raises(ValidationError):
        register(ToolRegistry(), fn)


def test_wrapper_implementation_and_default_changes_cannot_share_a_release():
    def first(value: int = 1):
        return value + 1

    def second(value: int = 1):
        return value + 2

    one, two = ToolRegistry(), ToolRegistry()
    register(one, first, effect="read_only", name="f")
    register(two, second, effect="read_only", name="f")
    assert one.manifests(["f"]) != two.manifests(["f"])
    before = one.manifests(["f"])
    first.__defaults__ = (2,)
    three = ToolRegistry()
    register(three, first, effect="read_only", name="f")
    assert three.manifests(["f"]) != before
    assert one.get("f").handler({}, None) == 2


def test_typed_async_tool_uses_existing_approval_and_restart_contract(tmp_path):
    async def run():
        writes = []

        async def write(value: int, *, context):
            writes.append((value, context.run_id))
            return {"written": value}

        class Provider:
            identity = {"kind": "fixture-typed", "version": "1"}

            async def complete(self, messages, tools):
                if any(m["role"] == "tool" for m in messages):
                    return ModelResponse({"written": 7})
                return ModelResponse(tool_calls=(ToolCall("write", {"value": 7}, "call"),))

        tools = ToolRegistry()
        register(
            tools,
            write,
            effect="idempotent_write",
            requires_approval=True,
            context_parameter="context",
        )
        spec = AgentSpec("typed", "Write7", ("write",))
        path = tmp_path / "run.sqlite"
        with LocalEngine(
            SQLiteStore(path), providers={"default": Provider()}, tools=tools
        ) as engine:
            handle = engine.submit(spec, "write7", command_id="s")
            result = await engine.drive(handle.run_id)
            assert result.state == "waiting_approval" and writes == []
            approval = result.pending[0]
            engine.approve(handle.run_id, approval["action_id"], approval["digest"], command_id="a")
        with LocalEngine(
            SQLiteStore(path), providers={"default": Provider()}, tools=tools
        ) as engine:
            assert (await engine.drive(handle.run_id)).result == {"written": 7}
            assert (await engine.drive(handle.run_id)).state == "succeeded" and writes == [
                (7, handle.run_id)
            ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "metadata",
    [
        {"name": 3},
        {"version": False},
        {"description": {}},
        {"requires_approval": 1},
        {"effect": []},
    ],
)
def test_typed_metadata_fails_before_publishing_a_tool(metadata):
    def fn(value: int):
        return value

    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        register(registry, fn, **{"effect": "read_only", **metadata})
    with pytest.raises(DefinitionMismatch):
        registry.get("fn")


def test_annotated_metadata_can_be_unhashable_without_being_executed():
    def fn(value: Annotated[str, {"max_length": 10}]):
        return value

    assert infer(fn)["properties"]["value"] == {"type": "string"}
