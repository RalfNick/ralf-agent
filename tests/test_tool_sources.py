import asyncio

import pytest

import ralf_agent as api
from ralf_agent import InvocationContext, Scope, ToolRegistry, ToolSpec
from ralf_agent.errors import DefinitionMismatch, ValidationError


def public():
    for name in ("ToolDescriptor", "ToolPolicy", "ToolSource", "register_tool_source"):
        assert hasattr(api, name), f"Missing tool-source API: {name}"
    return api


def context():
    return InvocationContext(Scope(), "run", "action", "attempt", "stable-key", "epoch")


class Source:
    identity = {"kind": "custom-source", "version": "1"}

    def __init__(self, descriptors):
        self.descriptors = descriptors
        self.calls = []

    async def list_tools(self):
        return tuple(self.descriptors)

    async def call_tool(self, descriptor, arguments, ctx):
        self.calls.append((descriptor.name, arguments, ctx.effect_key))
        return {"accepted": arguments}


def descriptor(a, name="write", **options):
    return a.ToolDescriptor(
        name,
        "Business operation",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        **options,
    )


def test_selected_source_dispatches_with_explicit_host_policy():
    a = public()
    source = Source([descriptor(a), descriptor(a, "unused")])
    registry = ToolRegistry()
    names = asyncio.run(
        a.register_tool_source(
            registry,
            source,
            policies={
                "write": a.ToolPolicy(version="1", effect="read_only", requires_approval=False)
            },
            prefix="business_",
        )
    )
    assert names == ("business_write",)
    tool = registry.get(names[0])
    assert tool.spec.effect == "read_only" and not tool.spec.requires_approval
    assert asyncio.run(tool.handler({"value": 7}, context())) == {"accepted": {"value": 7}}
    assert source.calls == [("write", {"value": 7}, "stable-key")]
    with pytest.raises(DefinitionMismatch):
        registry.get("unused")


def test_default_policy_requires_approval_and_does_not_claim_idempotency():
    a = public()
    registry = ToolRegistry()
    asyncio.run(
        a.register_tool_source(
            registry, Source([descriptor(a)]), policies={"write": a.ToolPolicy(version="1")}
        )
    )
    assert registry.get("write").spec.requires_approval
    assert registry.get("write").spec.effect == "unqueryable_write"


@pytest.mark.parametrize("bad", ["missing", "duplicate", "collision", "policy"])
def test_source_registration_is_atomic(bad):
    a = public()
    registry = ToolRegistry()

    def original(arguments, ctx):
        return "original"

    registry.register(ToolSpec("occupied", "old", {"type": "object"}), original)
    items = [descriptor(a, "first"), descriptor(a, "second")]
    policies = {name: a.ToolPolicy(version="1") for name in ["first", "second"]}
    if bad == "missing":
        items.pop()
    elif bad == "duplicate":
        items.append(descriptor(a, "first"))
    elif bad == "collision":
        items[1] = descriptor(a, "occupied")
        policies = {"first": a.ToolPolicy(version="1"), "occupied": a.ToolPolicy(version="1")}
    else:
        policies["second"] = object()
    with pytest.raises((ValidationError, DefinitionMismatch)):
        asyncio.run(a.register_tool_source(registry, Source(items), policies=policies))
    assert registry.get("occupied").handler is original
    with pytest.raises(DefinitionMismatch):
        registry.get("first")


def test_descriptor_and_identity_views_cannot_mutate_pinned_tool():
    a = public()
    schema = {"type": "object", "properties": {"value": {"type": "integer"}}}
    item = a.ToolDescriptor("read", "Read", schema)
    schema["type"] = "string"
    item.input_schema["type"] = "array"
    source = Source([item])
    registry = ToolRegistry()
    asyncio.run(a.register_tool_source(registry, source, policies={"read": a.ToolPolicy("1")}))
    registry.get("read").spec.config.clear()
    assert registry.get("read").spec.input_schema["type"] == "object"


@pytest.mark.parametrize("change", ["before", "during", "discovery"])
def test_actual_source_identity_change_rejected(change):
    a = public()

    class Drifting(Source):
        async def list_tools(self):
            result = await super().list_tools()
            if change == "discovery":
                self.identity = {"kind": "custom-source", "version": "2"}
            return result

        async def call_tool(self, *args):
            result = await super().call_tool(*args)
            if change == "during":
                self.identity = {"kind": "custom-source", "version": "2"}
            return result

    source = Drifting([descriptor(a)])
    registry = ToolRegistry()
    if change == "discovery":
        with pytest.raises(DefinitionMismatch):
            asyncio.run(
                a.register_tool_source(registry, source, policies={"write": a.ToolPolicy("1")})
            )
        return
    asyncio.run(a.register_tool_source(registry, source, policies={"write": a.ToolPolicy("1")}))
    if change == "before":
        source.identity = {"kind": "custom-source", "version": "2"}
    with pytest.raises(DefinitionMismatch):
        asyncio.run(registry.get("write").handler({"value": 1}, context()))
    assert len(source.calls) == (0 if change == "before" else 1)


def test_reserved_effect_key_is_injected_and_cannot_be_supplied():
    a = public()
    item = a.ToolDescriptor(
        "write",
        "Write",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}, "request_id": {"type": "string"}},
            "required": ["value", "request_id"],
            "additionalProperties": False,
        },
    )
    source = Source([item])
    registry = ToolRegistry()
    asyncio.run(
        a.register_tool_source(
            registry,
            source,
            policies={
                "write": a.ToolPolicy(
                    "1", effect="idempotent_write", effect_key_argument="request_id"
                )
            },
        )
    )
    tool = registry.get("write")
    tool.validate({"value": 3})
    assert "request_id" not in tool.spec.input_schema["properties"]
    assert asyncio.run(tool.handler({"value": 3}, context())) == {
        "accepted": {"value": 3, "request_id": "stable-key"}
    }
    with pytest.raises(ValidationError):
        asyncio.run(tool.handler({"value": 3, "request_id": "forged"}, context()))
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"version": ""},
        {"version": "1", "effect": "idempotent_write"},
        {"version": "1", "effect": "queryable_write"},
        {"version": "1", "requires_approval": 1},
        {"version": "1", "cost": True},
        {"version": "1", "effect": "invalid"},
    ],
)
def test_invalid_effect_policy_rejected(kwargs):
    a = public()
    with pytest.raises(ValidationError):
        a.ToolPolicy(**kwargs)


def test_queryable_source_uses_explicit_reconciler():
    a = public()

    async def reconcile(arguments, ctx):
        return {"proof": ctx.effect_key}

    registry = ToolRegistry()
    asyncio.run(
        a.register_tool_source(
            registry,
            Source([descriptor(a)]),
            policies={"write": a.ToolPolicy("1", effect="queryable_write", reconciler=reconcile)},
        )
    )
    assert asyncio.run(registry.get("write").reconciler({"value": 1}, context())) == {
        "proof": "stable-key"
    }


@pytest.mark.parametrize("result", [float("nan"), object()])
def test_source_must_return_completed_finite_json(result):
    a = public()

    class Invalid(Source):
        async def call_tool(self, *args):
            return result

    registry = ToolRegistry()
    asyncio.run(
        a.register_tool_source(
            registry, Invalid([descriptor(a)]), policies={"write": a.ToolPolicy("1")}
        )
    )
    with pytest.raises(ValidationError):
        asyncio.run(registry.get("write").handler({"value": 1}, context()))


@pytest.mark.parametrize("additional", [True, None])
def test_reserved_key_rejected_by_registry_while_other_extra_fields_remain_valid(additional):
    a = public()
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}, "request_id": {"type": "string"}},
        "required": ["value", "request_id"],
    }
    if additional is not None:
        schema["additionalProperties"] = additional
    source = Source([a.ToolDescriptor("write", "Write", schema)])
    registry = ToolRegistry()
    asyncio.run(
        a.register_tool_source(
            registry,
            source,
            policies={
                "write": a.ToolPolicy(
                    "1", effect="idempotent_write", effect_key_argument="request_id"
                )
            },
        )
    )
    tool = registry.get("write")
    tool.validate({"value": 1, "extra": "retained"})
    with pytest.raises(ValidationError):
        tool.validate({"value": 1, "request_id": "forged"})
    assert asyncio.run(tool.handler({"value": 1, "extra": "retained"}, context())) == {
        "accepted": {"value": 1, "extra": "retained", "request_id": "stable-key"}
    }


@pytest.mark.parametrize("property_schema", [True, False])
def test_boolean_reserved_property_schema_is_rejected_with_validation_error(property_schema):
    a = public()
    source = Source(
        [
            a.ToolDescriptor(
                "write", "Write", {"type": "object", "properties": {"request_id": property_schema}}
            )
        ]
    )
    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        asyncio.run(
            a.register_tool_source(
                registry,
                source,
                policies={
                    "write": a.ToolPolicy(
                        "1", effect="idempotent_write", effect_key_argument="request_id"
                    )
                },
            )
        )
    with pytest.raises(DefinitionMismatch):
        registry.get("write")
