"""Explicit tool Schemas must respect the actual callable's required inputs."""

import asyncio
import copy
import inspect
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolCall, ToolRegistry
from ralf_agent.errors import ValidationError


@pytest.mark.parametrize("required", [None, [], ["limit"]])
def test_explicit_schema_cannot_allow_missing_required_callable_inputs(required):
    def lookup(record_id: str, *, limit: int = 5, context):
        return {"record_id": record_id, "limit": limit, "owner": context}

    schema = {
        "type": "object",
        "properties": {"record_id": {"type": "string"}, "limit": {"type": "integer"}},
        "additionalProperties": False,
    }
    if required is not None:
        schema["required"] = required
    original = copy.deepcopy(schema)
    tools = ToolRegistry()
    tools.register_function(
        lookup, effect="read_only", input_schema=schema, context_parameter="context"
    )
    tool = tools.get("lookup")
    assert schema == original
    assert tools.descriptions(["lookup"])[0]["function"]["parameters"] == original
    with pytest.raises(ValidationError):
        tool.resolve_arguments({"limit": 3})
    args = {"record_id": "A-1", **({"limit": 3} if required == ["limit"] else {})}
    assert tool.handler(args, "host") == {
        "record_id": "A-1",
        "limit": 3 if required == ["limit"] else 5,
        "owner": "host",
    }


class MissingArgumentProvider:
    identity = {"kind": "missing-required-argument", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(tool_calls=(ToolCall("lookup", {}, "call"),))


def required_tool(*, mutate_defaults=False, mutate_signature=False):
    tools = ToolRegistry()

    def lookup(record_id: str):
        raise AssertionError("Missing arguments must be refused before invocation")

    tools.register_function(
        lookup,
        effect="read_only",
        requires_approval=True,
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    if mutate_defaults:
        lookup.__defaults__ = ("replacement-target",)
    if mutate_signature:
        lookup.__signature__ = inspect.Signature()
    return tools


@pytest.mark.parametrize(
    "mutate_defaults,mutate_signature", [(False, False), (True, False), (True, True)]
)
def test_local_refuses_missing_callable_argument_before_approval(
    tmp_path, mutate_defaults, mutate_signature
):
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": MissingArgumentProvider()},
        tools=required_tool(mutate_defaults=mutate_defaults, mutate_signature=mutate_signature),
    ) as engine:
        run = engine.submit(AgentSpec("lookup", "Lookup", ("lookup",)), "find", command_id="one")
        result = asyncio.run(engine.drive(run.run_id))
        assert result.state == "failed"
        assert result.pending == ()
        assert all(action["kind"] == "model" for action in result.actions)


@pytest.mark.parametrize(
    "mutate_defaults,mutate_signature", [(False, False), (True, False), (True, True)]
)
def test_temporal_model_activity_refuses_missing_callable_argument(
    mutate_defaults, mutate_signature
):
    from ralf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(
        providers={"default": MissingArgumentProvider()},
        tools=required_tool(mutate_defaults=mutate_defaults, mutate_signature=mutate_signature),
    )
    result = asyncio.run(
        runtime.complete_model(
            {
                "runtime_manifest": runtime.manifest,
                "step": asdict(AgentSpec("lookup", "Lookup", ("lookup",))),
                "messages": [{"role": "user", "content": "find"}],
            }
        )
    )
    assert result["ok"] is False
    assert not result.get("tool_calls")


@pytest.mark.parametrize("keyword_only", [False, True])
def test_added_live_defaults_cannot_supply_originally_required_arguments(keyword_only):
    def positional(record_id: str):
        return record_id

    def keyword(*, record_id: str):
        return record_id

    lookup = keyword if keyword_only else positional
    tools = ToolRegistry()
    tools.register_function(
        lookup,
        name="lookup",
        effect="read_only",
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    original = tools.manifests(["lookup"])
    if keyword_only:
        lookup.__kwdefaults__ = {"record_id": "replacement-target"}
    else:
        lookup.__defaults__ = ("replacement-target",)
    assert tools.manifests(["lookup"]) == original
    with pytest.raises(ValidationError):
        tools.get("lookup").resolve_arguments({})
    assert tools.get("lookup").resolve_arguments({"record_id": "A-1"}) == {"record_id": "A-1"}


@pytest.mark.parametrize("signature", ["hidden", "extra", "invalid"])
def test_registered_defaults_do_not_depend_on_live_signature_metadata(signature):
    def lookup(record_id: str = "A-1"):
        return record_id

    tools = ToolRegistry()
    tools.register_function(lookup, effect="read_only")
    original = tools.manifests(["lookup"])
    lookup.__signature__ = {
        "hidden": inspect.Signature(),
        "extra": inspect.Signature([inspect.Parameter("ghost", inspect.Parameter.KEYWORD_ONLY)]),
        "invalid": "not-a-python-signature",
    }[signature]
    tool = tools.get("lookup")
    # A detached descriptor is also not the original parameter declaration.
    tool.spec.input_schema["properties"].clear()
    assert tool.resolve_arguments({}) == {"record_id": "A-1"}
    assert tools.manifests(["lookup"]) == original


@pytest.mark.parametrize("composite", [False, True])
def test_complete_schema_keeps_original_registration_identity(composite):
    from ralf_agent.tool_functions import TypedFunctionHandler
    from ralf_agent.tools import ToolSpec

    def lookup(record_id: str, limit: int = 5):
        return record_id, limit

    schema = {
        "type": "object",
        "properties": {"record_id": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["record_id"],
        "additionalProperties": False,
    }
    if composite:
        schema["allOf"] = [{"required": schema.pop("required")}]
    old, current = ToolRegistry(), ToolRegistry()
    old.register(ToolSpec("lookup", "lookup", schema), TypedFunctionHandler(lookup, schema, None))
    current.register_function(lookup, effect="read_only", input_schema=schema)
    assert current.manifests(["lookup"]) == old.manifests(["lookup"])


@pytest.mark.parametrize("required", ["record_id", [1], ["record_id", "record_id"]])
def test_invalid_required_declaration_is_not_repaired(required):
    def lookup(record_id: str):
        return record_id

    with pytest.raises(ValidationError):
        ToolRegistry().register_function(
            lookup,
            effect="read_only",
            input_schema={
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": required,
                "additionalProperties": False,
            },
        )


def test_bound_method_and_composite_schema_keep_defaults_and_constraints():
    class Lookup:
        def find(self, *, record_id: str, limit: int = 5):
            return {"record_id": record_id, "limit": limit}

    registry = ToolRegistry()
    registry.register_function(
        Lookup().find,
        effect="read_only",
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}, "limit": {"type": "integer"}},
            "additionalProperties": False,
            "allOf": [{"properties": {"limit": {"maximum": 10}}, "required": ["record_id"]}],
        },
    )
    tool = registry.get("find")
    assert tool.handler({"record_id": "A-1"}, None) == {"record_id": "A-1", "limit": 5}
    with pytest.raises(ValidationError):
        tool.resolve_arguments({"record_id": "A-1", "limit": 11})
    with pytest.raises(ValidationError):
        tool.resolve_arguments({})


def test_original_valid_tool_approval_recovers_with_unchanged_identity(tmp_path):
    from ralf_agent.tool_functions import TypedFunctionHandler
    from ralf_agent.tools import ToolSpec

    writes = []

    def apply(record_id: str, limit: int = 5):
        writes.append(record_id)
        return {"record_id": record_id, "limit": limit}

    schema = {
        "type": "object",
        "properties": {"record_id": {"type": "string"}, "limit": {"type": "integer"}},
        "additionalProperties": False,
        "allOf": [{"required": ["record_id"]}],
    }
    original, current = ToolRegistry(), ToolRegistry()
    original.register(
        ToolSpec("apply", "Apply", schema, effect="idempotent_write", requires_approval=True),
        TypedFunctionHandler(apply, schema, None),
    )
    current.register_function(
        apply,
        description="Apply",
        effect="idempotent_write",
        requires_approval=True,
        input_schema=schema,
    )
    assert original.manifests(["apply"]) == current.manifests(["apply"])

    class Provider:
        identity = {"kind": "required-argument-recovery", "version": "1"}

        async def complete(self, messages, tools):
            if any(message["role"] == "tool" for message in messages):
                return ModelResponse("done")
            return ModelResponse(tool_calls=(ToolCall("apply", {"record_id": "A-1"}, "call"),))

    path = tmp_path / "runs.sqlite"
    definition = AgentSpec("apply", "Apply", ("apply",))
    with LocalEngine(
        SQLiteStore(path), providers={"default": Provider()}, tools=original
    ) as engine:
        run = engine.submit(definition, "apply", command_id="submit")
        waiting = asyncio.run(engine.drive(run.run_id))
        assert waiting.state == "waiting_approval"
        approval = waiting.pending[0]
    with LocalEngine(SQLiteStore(path), providers={"default": Provider()}, tools=current) as engine:
        replay = engine.submit(definition, "apply", command_id="submit")
        assert replay == run
        receipt = engine.approve(
            run.run_id, approval["action_id"], approval["digest"], command_id="approve"
        )
        assert (
            engine.approve(
                run.run_id, approval["action_id"], approval["digest"], command_id="approve"
            )
            == receipt
        )
        assert asyncio.run(engine.drive(run.run_id)).state == "succeeded"
        assert asyncio.run(engine.drive(run.run_id)).state == "succeeded"
    assert writes == ["A-1"]
