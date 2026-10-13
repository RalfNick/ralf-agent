"""Opt-in Coding declarations preserve old releases and borrow original resources."""

import asyncio
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, BindingSelection, Scope, TemporalProfile, TemporalRuntimeBuilder
from ralf_agent.binding_definitions import AgentDefinition
from ralf_agent.binding_types import AgentBindingDescriptor
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.temporal_bindings import effective_step, key, normalize_request, validate_descriptor
from ralf_agent.types import submission_request


def profile(**kwargs):
    return TemporalProfile("coding", "1", {"default": {"adapter": "offline-echo"}}, **kwargs)


def manifest():
    from ralf_agent.temporal_coding_protocol import JOURNAL_METHODS, RUNNER_METHODS, implementation

    runner = {"kind": "codex-coding-runner", "version": "1", "resource": "original"}
    choice = BindingSelection.ref("native", "1")
    value = {
        "kernel": "temporal-3",
        "binding_protocol": 11,
        "dispatch_admission": "history-1",
        "tool_execution_protocol": {},
        "tools": {
            "coding": {"config": {"delegated_runner": {"version": 1, "runner": runner}}},
            "other": {
                "config": {
                    "delegated_runner": {"version": 1, "runner": {**runner, "resource": "other"}}
                }
            },
            "plain": {"config": {}},
        },
        "binding_catalog": {
            "records": {
                key("runner", choice): {
                    "role": "runner",
                    "scope": asdict(Scope()),
                    "identity": {
                        "kind": "runner-binding-resource",
                        "version": "1",
                        "runner": runner,
                    },
                    "configuration": {},
                }
            }
        },
    }
    value["coding_execution_protocol"] = {
        "version": 1,
        "implementation": implementation(),
        "tools": {
            name: {
                "runner": tool["config"]["delegated_runner"]["runner"],
                "journal": {"original": "pg"},
                "implementation": {method: "a" * 64 for method in RUNNER_METHODS},
                "journal_implementation": {method: "b" * 64 for method in JOURNAL_METHODS},
            }
            for name, tool in value["tools"].items()
            if "delegated_runner" in tool["config"]
        },
    }
    return value


def test_coding_flag_is_explicit_and_false_preserves_omitted_profile_bytes():
    omitted = profile()
    disabled = profile(execution={"coding_execution": False})
    enabled = profile(execution={"coding_execution": True})
    assert disabled.to_dict() == omitted.to_dict()
    assert disabled.identity == omitted.identity
    assert "coding_execution" not in omitted.execution
    assert enabled.execution["coding_execution"] is True


@pytest.mark.parametrize("value", [1, None, "true", {}])
def test_coding_flag_requires_boolean(value):
    with pytest.raises(ValidationError):
        profile(execution={"coding_execution": value})


def test_optin_bound_normalization_retains_original_runner_descriptor():
    choices = AgentBindingDescriptor(runner=BindingSelection.ref("native", "1"))
    request = submission_request(
        AgentDefinition(AgentSpec("a", "Task", tools=("coding",)), choices), "q"
    )
    normalized = normalize_request(request, manifest())
    assert normalized["definition"]["kind"] == "agent"
    assert normalized["agent_bindings"]["agent"] == choices.to_dict()
    with pytest.raises(ValidationError):
        normalize_request(request)


def test_runner_selection_checks_effective_grants_and_exact_resource():
    selected = manifest()
    choices = AgentBindingDescriptor(runner=BindingSelection.ref("native", "1")).to_dict()
    step = {"tools": ["coding", "plain"]}
    assert effective_step(step, selected, choices)["tools"] == ["coding", "plain"]
    with pytest.raises(DefinitionMismatch):
        effective_step({"tools": ["other"]}, selected, choices)
    with pytest.raises(AuthorizationDenied):
        effective_step({"tools": ["plain"]}, selected, choices)
    disabled = AgentBindingDescriptor(runner=BindingSelection.disabled()).to_dict()
    assert effective_step({"tools": ["plain"]}, selected, disabled)["tools"] == ["plain"]
    with pytest.raises(AuthorizationDenied):
        effective_step(step, selected, disabled)
    with pytest.raises(ValidationError):
        effective_step({"tools": ["coding", "other"]}, selected, AgentBindingDescriptor().to_dict())


@pytest.mark.parametrize(
    "change",
    [{"binding_protocol": 10}, {"coding_execution_protocol": None}, {"kernel": "temporal-2"}],
)
def test_runner_selection_requires_exact_optin_protocol(change):
    selected = {**manifest(), **change}
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_descriptor(
            selected, AgentBindingDescriptor(runner=BindingSelection.inherit()).to_dict()
        )


def test_postgres_coding_requires_optin_before_resource_construction(tmp_path):
    config = {
        "name": "coding",
        "description": "Contained task",
        "cost": 1,
        "runner_root": "/private/tmp/original",
        "fixed_dependencies": {"fixture": "1"},
        "docker_executable": "/private/tmp/docker",
        "docker_host": "unix:///unused.sock",
        "request_timeout": 1,
    }
    declaration = profile(
        components={"tools": {"adapter": "codex-coding-postgres", "config": config}}
    )
    with pytest.raises(ValidationError, match="explicit Coding execution"):
        asyncio.run(TemporalRuntimeBuilder(base_dir=tmp_path).abuild(declaration))
    assert list(tmp_path.iterdir()) == []


def test_coding_builder_acquires_exact_effect_owner_before_tools_and_closes_once(
    tmp_path, monkeypatch
):
    import ralf_agent.temporal_builder as builder_module
    from ralf_agent.runtime_builder import ComponentRegistry

    events = []

    class Journal:
        async def aclose(self):
            events.append("close-journal")

    original = Journal()
    registry = ComponentRegistry()

    async def journal_factory(config, context):
        events.append("journal")
        return context.own_async(original)

    def tools_factory(config, context):
        assert context.effect_journal is original
        assert context.coding_execution is True
        events.append("tools")
        from ralf_agent.tools import ToolRegistry

        return ToolRegistry()

    registry.register_async("effect_journal", "fixture-owner", journal_factory)
    registry.register("tools", "fixture-borrower", tools_factory)

    class Runtime:
        orchestration_release = {"kernel": "fixture", "version": 1}

        def __init__(self, **kwargs):
            assert kwargs["journal"] is original
            assert kwargs["coding_execution"] is True
            self._kwargs = kwargs

    monkeypatch.setattr(builder_module, "TemporalRuntime", Runtime)
    declaration = profile(
        components={
            "tools": {"adapter": "fixture-borrower"},
            "effect_journal": {"adapter": "fixture-owner"},
        },
        execution={"coding_execution": True},
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(declaration)
        await assembly._construction.aclose()

    asyncio.run(run())
    assert events == ["journal", "tools", "close-journal"]


def test_local_builder_refuses_temporal_postgres_adapter_before_store(tmp_path):
    from ralf_agent import RuntimeProfile
    from ralf_agent.runtime_builder import RuntimeBuilder
    from tests.test_temporal_coding_factories import entry

    selected = RuntimeProfile(
        "local",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "codex-coding-postgres", "config": entry(tmp_path)}},
    )
    acquisitions = []

    def store_factory(path):
        acquisitions.append(path)
        raise AssertionError("Temporal adapter acquired Local authority")

    with pytest.raises(ValidationError, match="original Temporal History"):
        asyncio.run(RuntimeBuilder(store_factory=store_factory).abuild(selected, tmp_path / "runs"))
    assert acquisitions == []
