"""Public declarative parent policies before any owned construction."""

import asyncio

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import ComponentRegistry, EchoProvider, RuntimeBuilder
from ralf_agent.runtime_config import RuntimeProfile
from ralf_agent.temporal_profile import TemporalProfile


def build_mode(mode, profile, registry, path, calls):
    if mode == "temporal":
        from ralf_agent.temporal_builder import TemporalRuntimeBuilder

        return asyncio.run(TemporalRuntimeBuilder(registry, base_dir=path.parent).abuild(profile))
    builder = RuntimeBuilder(registry, store_factory=lambda p: calls.append("store"))
    if mode == "async":
        return asyncio.run(builder.abuild(profile, path))
    return builder.build(profile, path)


def declaration():
    return {
        "adapter": "configured",
        "config": {
            "policies": {
                "business": {
                    "gate": {
                        "adapter": "receipt-rules",
                        "config": {
                            "rules": [
                                {
                                    "id": "total",
                                    "member_path": ["worker"],
                                    "tool": "calculator",
                                    "output_bindings": {
                                        "/total": {"source": "candidate", "pointer": "/total"}
                                    },
                                }
                            ]
                        },
                    }
                }
            }
        },
    }


@pytest.mark.parametrize("cls", [RuntimeProfile, TemporalProfile])
def test_local_and_temporal_profiles_accept_same_explicit_policy_declaration(cls):
    component = declaration()
    profile = cls(
        "business",
        "1",
        {"default": {"adapter": "echo"}},
        {"parent_completion_policies": component},
    )
    assert profile.components["parent_completion_policies"] == component
    component["config"]["policies"].clear()
    assert profile.components["parent_completion_policies"]["config"]["policies"]


def test_configured_parent_policy_factory_is_registered_and_validated():
    factory, config = ComponentRegistry().prepare("parent_completion_policies", declaration())
    policies = factory(config, None)
    assert set(policies) == {"business"}
    assert policies["business"].model_stage is None
    assert policies["business"].gate.identity["kind"]


def test_parent_completion_sdk_exports_public_contracts():
    import ralf_agent as sdk
    from ralf_agent.parent_completion import (
        ParentCompletionPolicy,
        ParentCompletionRequest,
        ParentCompletionVerdict,
    )
    from ralf_agent.parent_completion_rules import (
        InventoryParentCompletionGate,
        ReceiptParentCompletionGate,
    )
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    for public in (
        ParentCompletionPolicy,
        ParentCompletionRequest,
        ParentCompletionVerdict,
        ReceiptParentCompletionGate,
        InventoryParentCompletionGate,
        ModelParentVerificationStage,
    ):
        assert getattr(sdk, public.__name__, None) is public


@pytest.mark.parametrize(
    "config",
    [{}, {"policies": {}}, {"policies": {"bad": {}}}, {"policies": {}, "unknown": 1}],
)
def test_invalid_policy_catalog_fails_during_pure_adapter_preparation(config):
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare(
            "parent_completion_policies", {"adapter": "configured", "config": config}
        )


def test_missing_stage_provider_rejected_before_owned_factories(tmp_path):
    calls = []
    registry = ComponentRegistry()
    registry.register(
        "provider", "guard", lambda c, ctx: calls.append("provider") or EchoProvider("fixture")
    )
    component = declaration()
    component["config"]["policies"]["business"]["model_stage"] = {
        "adapter": "model",
        "config": {"provider": "unregistered"},
    }
    profile = RuntimeProfile(
        "business",
        "1",
        {"default": {"adapter": "guard"}},
        {"parent_completion_policies": component},
    )
    builder = RuntimeBuilder(
        registry,
        store_factory=lambda path: calls.append("store"),
    )
    with pytest.raises(ValidationError, match="Parent verification provider alias is unavailable"):
        builder.build(profile, tmp_path / "not-created.sqlite")
    assert calls == []
    assert not (tmp_path / "not-created.sqlite").exists()


@pytest.mark.parametrize("mode", ["sync", "async", "temporal"])
@pytest.mark.parametrize("missing", ["alias", "provider-ref", "context-ref", "pure-context"])
def test_parent_stage_preflight_is_zero_io_for_each_assembly_mode(tmp_path, mode, missing):
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection

    calls = []
    registry = ComponentRegistry().register(
        "provider", "guard", lambda c, ctx: calls.append("provider") or EchoProvider("fixture")
    )
    component = declaration()
    config = {}
    if missing == "alias":
        config["provider"] = "absent"
    elif missing in {"provider-ref", "context-ref"}:
        role = "provider" if missing == "provider-ref" else "context"
        config["bindings"] = AgentBindingDescriptor(
            **{role: BindingSelection.ref("absent", "1")}
        ).to_dict()
    components = {"parent_completion_policies": component}
    if missing == "pure-context":
        components["context_assembler"] = {"adapter": "managed"}
    component["config"]["policies"]["business"]["model_stage"] = {
        "adapter": "model",
        "config": config,
    }
    cls = TemporalProfile if mode == "temporal" else RuntimeProfile
    profile = cls("business", "1", {"default": {"adapter": "guard"}}, components)
    with pytest.raises(ValidationError, match="Parent verification"):
        build_mode(mode, profile, registry, tmp_path / "absent.sqlite", calls)
    assert calls == [] and not any(tmp_path.iterdir())


@pytest.mark.parametrize("cls", [RuntimeProfile, TemporalProfile])
def test_explicit_pure_context_ref_can_replace_a_managed_host_context(cls):
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
    from ralf_agent.parent_completion_factories import preflight_parent_completion_providers

    component = declaration()
    component["config"]["policies"]["business"]["model_stage"] = {
        "adapter": "model",
        "config": {
            "bindings": AgentBindingDescriptor(
                context=BindingSelection.ref("review-context", "1"),
                provider=BindingSelection.ref("review-model", "1"),
            ).to_dict(),
        },
    }
    profile = cls(
        "business",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"context_assembler": {"adapter": "managed"}, "parent_completion_policies": component},
        binding_components=[
            {
                "role": "context",
                "component_id": "review-context",
                "version": "1",
                "component": {"adapter": "budgeted"},
            },
            {
                "role": "provider",
                "component_id": "review-model",
                "version": "1",
                "component": {"adapter": "offline-echo"},
            },
        ],
    )
    preflight_parent_completion_providers(profile)
    _, config = ComponentRegistry().prepare("parent_completion_policies", component)
    assert (
        config["policies"]["business"]["model_stage"]["config"]["bindings"]["provider"][
            "component_id"
        ]
        == "review-model"
    )
