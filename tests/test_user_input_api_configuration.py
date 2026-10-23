"""Configured marker registration composes and fails atomically."""

from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from relf_agent import AgentSpec, LocalEngine
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from relf_agent.runtime_config import RuntimeProfile
from relf_agent.tools import ToolRegistry, ToolSpec
from relf_agent.user_input import input_tool_policy
from relf_agent.user_input_factories import configured_user_input


def test_configured_markers_keep_custom_python_tools_and_selected_schema():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("lookup", "Original business lookup", {"type": "object"}),
        lambda arguments, context: 7,
    )
    before = registry.get("lookup")
    policies = configured_user_input(
        {
            "policies": {
                "environment": {
                    "reply_schema": {
                        "type": "object",
                        "required": ["environment"],
                        "properties": {"environment": {"enum": ["prod", "staging"]}},
                    },
                }
            },
            "tools": {"ask_environment": {"policy": "environment"}},
        },
        SimpleNamespace(tools=registry),
    )
    assert registry.get("lookup") == before
    policy = input_tool_policy(registry.get("ask_environment"))
    assert policy.identity == policies["environment"].identity
    assert policy.reply_schema["properties"]["environment"]["enum"] == ["prod", "staging"]


def test_one_collision_publishes_no_input_markers():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("reserved", "Business tool", {"type": "object"}),
        lambda arguments, context: "ordinary",
    )
    before = registry.manifests(["reserved"])
    with pytest.raises(DefinitionMismatch):
        configured_user_input(
            {
                "policies": {"ask": {}},
                "tools": {
                    "request_input": {"policy": "ask"},
                    "reserved": {"policy": "ask"},
                },
            },
            SimpleNamespace(tools=registry),
        )
    assert registry.manifests(["reserved"]) == before
    with pytest.raises(DefinitionMismatch):
        registry.get("request_input")


def test_declared_prefixed_http_collision_fails_before_provider_factory(tmp_path):
    calls = []
    registry = ComponentRegistry()
    registry.register("provider", "not-called", lambda config, context: calls.append(True))
    profile = RuntimeProfile(
        "collision",
        "1",
        {"default": {"adapter": "not-called"}},
        {
            "tools": {
                "adapter": "http-json",
                "config": {
                    "tools": [
                        {
                            "descriptor": {
                                "name": "ask",
                                "description": "Business HTTP",
                                "input_schema": {"type": "object"},
                            },
                            "url": "http://invalid.test/read",
                            "version": "1",
                            "prefix": "input_",
                            "policy": {
                                "version": "1",
                                "effect": "read_only",
                                "requires_approval": False,
                            },
                        }
                    ]
                },
            },
            "user_input_policies": {
                "adapter": "configured",
                "config": {
                    "policies": {"ask": {}},
                    "tools": {"input_ask": {"policy": "ask"}},
                },
            },
        },
    )
    with pytest.raises(ValidationError, match="collides"):
        RuntimeBuilder(registry).build(profile, tmp_path / "never.sqlite")
    assert calls == [] and not (tmp_path / "never.sqlite").exists()


def test_flat_model_planner_can_explicitly_select_input_conclusions():
    registry = ComponentRegistry()
    factory, options = registry.prepare(
        "planners",
        {
            "adapter": "model",
            "config": {
                "input_requests": True,
            },
        },
    )
    planner = factory(options, None)["model"]
    assert planner.identity["input_requests"] is True
    schema = Draft202012Validator(planner.agent.output_schema)
    assert schema.is_valid({"status": "needs_input", "reason": "Which environment?"})
    assert schema.is_valid({"status": "refused", "reason": "Forbidden operation"})
    assert not schema.is_valid({"status": "needs_input"})


def test_configuration_accepts_sdk_supported_unicode_registration_names():
    tools = ToolRegistry()
    policies = configured_user_input(
        {"policies": {"环境": {}}, "tools": {"询问环境": {"policy": "环境"}}},
        SimpleNamespace(tools=tools),
    )
    assert input_tool_policy(tools.get("询问环境")).identity == policies["环境"].identity


@pytest.mark.parametrize("construction", ["build", "abuild"])
@pytest.mark.parametrize("selection", ["policies", "marker"])
@pytest.mark.parametrize("capability", ["absent", "async"])
def test_selected_builder_requires_optional_control_without_requiring_legacy_defaults(
    tmp_path, construction, selection, capability
):
    import asyncio

    from relf_agent.runtime_builder import EchoProvider
    from relf_agent.storage import SQLiteStore
    from relf_agent.user_input import register_user_input

    closed = []

    class Resource:
        def __init__(self, ownership):
            self.ownership = ownership

        def close(self):
            closed.append(self.ownership)

    borrowed = Resource("borrowed")

    class LegacyFacade:
        def __init__(self, authority):
            self.authority = authority

        def __getattr__(self, name):
            if name == "send_input":
                if capability == "async":
                    return self.async_send_input
                raise AttributeError(name)
            return getattr(self.authority, name)

        async def async_send_input(self, *arguments, **options):
            return self.authority.send_input(*arguments, **options)

    def factory(store, *, providers, tools, scope, runtime_profile, **options):
        authority = LocalEngine(
            store, providers=providers, tools=tools, scope=scope, runtime_profile=runtime_profile
        )
        return LegacyFacade(authority)

    registry = ComponentRegistry()

    def provider_factory(config, context):
        context.own(Resource("owned"))
        assert borrowed.ownership == "borrowed"  # Borrowed client remains outside ownership.
        return EchoProvider("fixture")

    def tools_factory(config, context):
        tools = ToolRegistry()
        register_user_input(tools, name="arbitrary_ask_name")
        return tools

    registry.register("provider", "owned-provider", provider_factory)
    registry.register("tools", "custom-input-marker", tools_factory)
    builder = RuntimeBuilder(registry, engine_factory=factory)
    providers = {"default": {"adapter": "owned-provider"}}

    def build(profile, path):
        return (
            builder.build(profile, path)
            if construction == "build"
            else asyncio.run(builder.abuild(profile, path))
        )

    with build(RuntimeProfile("legacy", "1", providers), tmp_path / "legacy.sqlite") as built:
        handle = built.submit(AgentSpec("a", "Answer"), "original", command_id="start")
        assert asyncio.run(built.drive(handle.run_id)).result["echo"] == "original"
    components = (
        {"user_input_policies": {"adapter": "configured", "config": {"policies": {"ask": {}}}}}
        if selection == "policies"
        else {"tools": {"adapter": "custom-input-marker"}}
    )
    selected = RuntimeProfile("selected", "1", providers, components)
    path = tmp_path / "selected.sqlite"
    with pytest.raises(ValidationError, match="user input"):
        with build(selected, path):
            pass
    assert closed == ["owned", "owned"]
    # A failed selected-only guard must close the authority, releasing its lease.
    with LocalEngine(SQLiteStore(path), providers={}, tools=ToolRegistry()):
        pass
