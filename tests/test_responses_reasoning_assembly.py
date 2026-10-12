"""Explicit native Responses selection through the original assembly authorities."""

import asyncio
import importlib
import json

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    ComponentRegistry,
    RuntimeBuilder,
    RuntimeProfile,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_bindings import provider_alias


def declaration(**config):
    return {
        "adapter": "openai-responses-reasoning",
        "config": {"model": "explicit-fixture-model", **config},
    }


def bindings(component=None):
    return [
        {
            "role": "provider",
            "component_id": "reasoner",
            "version": "2",
            "component": declaration(reasoning_effort="medium") if component is None else component,
        }
    ]


def bound_agent():
    return AgentDefinition(
        AgentSpec("a", "Answer"),
        AgentBindingDescriptor(provider=BindingSelection.ref("reasoner", "2")),
    )


def test_sdk_exports_independent_responses_reasoning_adapter():
    api = importlib.import_module("ralf_agent")
    cls = getattr(api, "OpenAIResponsesReasoningProvider", None)
    assert cls is not None, "The dedicated Responses reasoning adapter must be exported"
    assert cls is not api.OpenAIResponsesProvider
    assert (
        cls("explicit-fixture-model", api_key="fixture").identity["kind"]
        == "openai-responses-reasoning"
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_local_profile_pins_options_and_per_agent_continuation_owner(
    tmp_path, monkeypatch, asynchronous
):
    monkeypatch.setenv("OPENAI_API_KEY", "ASSEMBLY_PRIVATE_FIXTURE")
    selected = RuntimeProfile(
        "reasoning",
        "1",
        {
            "default": declaration(
                reasoning_effort="max",
                reasoning_context="all_turns",
                reasoning_summary="detailed",
                reasoning_mode="pro",
            )
        },
        {"model_continuation": {"adapter": "native"}},
        binding_components=bindings(),
    )

    def check(instance):
        handle = instance.submit(bound_agent(), "question", command_id="submit")
        manifest = instance.diagnostics(handle.run_id).manifest
        effective = next(iter(manifest["agent_bindings"]["steps"].values()))["manifest"]
        assert manifest["model_continuation_protocol"] == 1
        assert effective["providers"]["default"]["reasoning_effort"] == "medium"
        assert (
            effective["provider_continuations"]["default"]["protocol"]
            == "openai-responses-reasoning-v1"
        )
        assert instance.providers["default"].identity["reasoning_context"] == "all_turns"
        assert instance.providers["default"].identity["reasoning_summary"] == "detailed"
        assert instance.providers["default"].identity["reasoning_mode"] == "pro"
        assert "ASSEMBLY_PRIVATE_FIXTURE" not in json.dumps(manifest)

    async def run():
        instance = await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")
        try:
            check(instance)
        finally:
            await instance.aclose()

    if asynchronous:
        asyncio.run(run())
    else:
        with RuntimeBuilder().build(selected, tmp_path / "runs.sqlite") as instance:
            check(instance)


def test_temporal_profile_explicit_execution_continuation_pins_default_and_ref(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "TEMPORAL_PRIVATE_FIXTURE")
    selected = TemporalProfile(
        "reasoning",
        "1",
        {"default": declaration()},
        binding_components=bindings(),
        execution={"model_continuation": True},
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            selected, data_path=tmp_path / "data"
        )
        try:
            release = assembly.release
            alias = provider_alias(BindingSelection.ref("reasoner", "2"))
            assert release["runtime_profile"] == selected.identity
            assert release["model_continuation_protocol"] == 1
            assert "reasoning_effort" not in release["providers"]["default"]
            assert release["providers"][alias]["reasoning_effort"] == "medium"
            assert (
                release["provider_continuations"][alias]["protocol"]
                == "openai-responses-reasoning-v1"
            )
            assert (
                release["provider_continuations"][alias]
                != release["provider_continuations"]["default"]
            )
            assert "TEMPORAL_PRIVATE_FIXTURE" not in json.dumps(release)
        finally:
            await assembly.aclose()
        assert list(tmp_path.iterdir()) == []

    asyncio.run(run())


@pytest.mark.parametrize("authority", ["sync", "async", "temporal"])
@pytest.mark.parametrize("bound", [False, True])
def test_missing_opt_in_rejects_before_owned_factories(tmp_path, authority, bound):
    events = []

    def factory(config, context):
        events.append("constructed")
        return EchoProvider("owned")

    registry = ComponentRegistry()
    registry.register("provider", "owned-before-reasoning", factory)
    providers = {"default": {"adapter": "owned-before-reasoning"}}
    if not bound:
        providers["reasoner"] = declaration()
    options = {"binding_components": bindings()} if bound else {}
    cls = TemporalProfile if authority == "temporal" else RuntimeProfile
    selected = cls("p", "1", providers, **options)
    path = tmp_path / "must-not-exist.sqlite"

    async def run():
        with pytest.raises(ValidationError, match="continuation"):
            if authority == "temporal":
                await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                    selected, data_path=path
                )
            else:
                await RuntimeBuilder(registry).abuild(selected, path)

    if authority == "sync":
        with pytest.raises(ValidationError, match="continuation"):
            RuntimeBuilder(registry).build(selected, path)
    else:
        asyncio.run(run())
    assert events == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        {"model": ""},
        {"reasoning_effort": "urgent"},
        {"reasoning_effort": True},
        {"reasoning_context": "thread"},
        {"reasoning_summary": "full"},
        {"reasoning_mode": "fast"},
        {"temperature": 0.5},
        {"top_p": 1},
        {"stop": "END"},
        {"seed": 42},
        {"api_key": "inline-secret"},
        {"ignored": True},
    ],
)
def test_invalid_bound_configuration_preflight_creates_no_resources(tmp_path, temporal, invalid):
    events = []

    def factory(config, context):
        events.append("constructed")
        return EchoProvider("owned")

    registry = ComponentRegistry()
    registry.register("provider", "before-invalid", factory)
    cls = TemporalProfile if temporal else RuntimeProfile
    options = (
        {"execution": {"model_continuation": True}}
        if temporal
        else {"components": {"model_continuation": {"adapter": "native"}}}
    )
    selected = cls(
        "p",
        "1",
        {"default": {"adapter": "before-invalid"}},
        binding_components=bindings(declaration(**invalid)),
        **options,
    )

    async def run():
        with pytest.raises(ValidationError):
            if temporal:
                await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(selected)
            else:
                await RuntimeBuilder(registry).abuild(selected, tmp_path / "unused.sqlite")

    asyncio.run(run())
    assert events == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_catalog_loads_reasoning_default_and_per_agent_provider_ref(
    tmp_path, monkeypatch, extension
):
    from ralf_agent.runtime_config import load_catalog

    monkeypatch.setenv("OPENAI_API_KEY", "CATALOG_FIXTURE")
    selected = RuntimeProfile(
        "reasoning",
        "1",
        {"default": declaration(reasoning_effort="xhigh")},
        {"model_continuation": {"adapter": "native"}},
        binding_components=bindings(),
    )
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
        value = json.loads(selected._data_json)
        value.pop("schema_version")
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "reasoning", "version": "1"},
                    "profiles": [value],
                }
            )
        )
    else:
        path.write_text("""schema_version = 2
[default]
name = "reasoning"
version = "1"
[[profiles]]
name = "reasoning"
version = "1"
[profiles.providers.default]
adapter = "openai-responses-reasoning"
[profiles.providers.default.config]
model = "explicit-fixture-model"
reasoning_effort = "xhigh"
[profiles.components.model_continuation]
adapter = "native"
[[profiles.binding_components]]
role = "provider"
component_id = "reasoner"
version = "2"
[profiles.binding_components.component]
adapter = "openai-responses-reasoning"
[profiles.binding_components.component.config]
model = "explicit-fixture-model"
reasoning_effort = "medium"
""")
    catalog = load_catalog(path)
    assert catalog.default.identity == selected.identity
    with RuntimeBuilder().build(catalog.default, tmp_path / "runs.sqlite") as instance:
        handle = instance.submit(bound_agent(), "question", command_id="submit")
        manifest = instance.diagnostics(handle.run_id).manifest
        effective = next(iter(manifest["agent_bindings"]["steps"].values()))["manifest"]
        assert effective["providers"]["default"]["reasoning_effort"] == "medium"


def test_replacement_adapter_preserves_old_default_profile_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "REPLACEMENT_FIXTURE")
    selected = RuntimeProfile(
        "p", "1", {"default": declaration()}, {"model_continuation": {"adapter": "native"}}
    )
    replacement = RuntimeProfile("p", "2", {"default": {"adapter": "offline-echo"}})
    assert selected.identity != replacement.identity
    with RuntimeBuilder().build(selected, tmp_path / "original.sqlite") as instance:
        handle = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        original = instance.diagnostics(handle.run_id).manifest
        assert original["providers"]["default"]["kind"] == "openai-responses-reasoning"
        assert (
            original["provider_continuations"]["default"]["protocol"]
            == "openai-responses-reasoning-v1"
        )
    with RuntimeBuilder().build(replacement, tmp_path / "replacement.sqlite") as instance:
        handle = instance.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(instance.drive(handle.run_id)).result == {
            "echo": "q",
            "label": "offline",
        }
        assert "model_continuation_protocol" not in instance.diagnostics(handle.run_id).manifest
    assert (
        replacement._data_json
        == '{"components":{},"name":"p","providers":{"default":{"adapter":"offline-echo","config":{}}},"version":"2"}'
    )
