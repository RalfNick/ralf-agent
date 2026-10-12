"""Coordinated admission forgeries and explicit disabled-only publication."""

import asyncio
import copy
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import effective_manifest, validate_bindings
from ralf_agent.temporal_state import TemporalRunState, validate_manifest

from .test_artifact_binding_temporal import host, request


@pytest.mark.parametrize(
    "corruption",
    ["backend", "namespace", "threshold", "provider", "implementation", "validator", "disabled"],
)
def test_coordinated_policy_forgery_refuses_before_original_history_acceptance(corruption):
    runtime, _ = host()
    manifest = runtime.manifest
    context = next(iter(manifest["artifact_contexts"]["contexts"].values()))
    choice = next(
        item
        for item in context["choices"].values()
        if (item["resource"] is None if corruption == "disabled" else item["resource"])
    )
    config = choice["configuration"]
    policy = copy.deepcopy(config["context_builder"])
    if corruption == "backend":
        policy["artifacts"] = copy.deepcopy(policy["artifacts"])
        policy["artifacts"]["backend_id"] = "foreign"
    elif corruption == "namespace":
        policy["namespace"] = "foreign"
    elif corruption == "threshold":
        policy["tool_result_chars"] += 1
    elif corruption == "provider":
        policy["provider"] = "foreign"
    elif corruption == "implementation":
        config["context_registration"]["implementation_digest"] = "invented"
    elif corruption == "validator":
        config["context_registration"]["request_validator"] = "invented"
    else:
        policy["kind"] = "managed-data-context"
        policy["artifacts"] = manifest["context_builder"]["artifacts"]
    config["context_builder"] = copy.deepcopy(policy)
    config["context_registration"]["identity"] = copy.deepcopy(policy)
    config["managed_context"]["policy"] = copy.deepcopy(policy)
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)
    with pytest.raises(DefinitionMismatch):
        TemporalRunState("run", asdict(r.Scope()), "s", request(), manifest)


def test_unused_incompatible_inherited_default_ports_do_not_break_publication():
    class Incompatible(r.ManagedDataContext):
        def prepare(self, *args, **kwargs):
            return r.ManagedDataContext.prepare(self, *args, **kwargs)

    runtime, stores = host()
    runtime.binding_catalog.register("context", "unused", "1", Incompatible(stores["original"]))
    published = TemporalRuntime(
        providers=runtime.providers,
        tools=runtime.tools,
        context_builder=runtime.context,
        binding_catalog=runtime.binding_catalog,
    )
    validate_manifest(published.manifest)
    req = request()
    req["agent_bindings"]["agent"]["context"] = r.BindingSelection.ref("unused", "1").to_dict()
    with pytest.raises(DefinitionMismatch):
        validate_bindings(req, published.manifest, asdict(r.Scope()))
    assert effective_manifest(runtime.manifest, request()["agent_bindings"]["agent"])


def test_custom_prediction_failure_is_not_hidden_as_unused_incompatibility():
    class Broken(r.ManagedDataContext):
        def artifact_binding_identity(self, metadata):
            raise RuntimeError("genuine custom predictor failure")

        def bind_artifacts(self, target):
            return self

    runtime, stores = host()
    runtime.binding_catalog.register("context", "broken", "1", Broken(stores["original"]))
    with pytest.raises(RuntimeError, match="genuine custom predictor failure"):
        TemporalRuntime(
            providers=runtime.providers,
            tools=runtime.tools,
            context_builder=runtime.context,
            binding_catalog=runtime.binding_catalog,
        )


def test_explicit_disabled_only_opt_in_needs_no_artifact_resource_and_legacy_stays_equal():
    runtime, _ = host()
    values = dict(
        providers=runtime.providers,
        tools=runtime.tools,
        context_builder=runtime.context,
        binding_catalog=r.BindingCatalog(scope=r.Scope()),
    )
    legacy = TemporalRuntime(**values)
    with pytest.raises(DefinitionMismatch):
        validate_bindings(request("disabled"), legacy.manifest, asdict(r.Scope()))
    opted = TemporalRuntime(**values, artifact_bindings=True)
    assert legacy.manifest == TemporalRuntime(**values, artifact_bindings=False).manifest
    assert opted.manifest["binding_protocol"] == 5
    assert opted.manifest["artifacts_binding_protocol"] == 1
    assert not opted.manifest["binding_catalog"]["records"]
    validate_bindings(request("disabled"), opted.manifest, asdict(r.Scope()))
    state = TemporalRunState("run", asdict(r.Scope()), "s", request("disabled"), opted.manifest)
    assert state.state == "queued"
    with pytest.raises(DefinitionMismatch):
        validate_bindings(request(), opted.manifest, asdict(r.Scope()))


def test_profile_disabled_only_flag_is_explicit_and_never_allocates_an_unused_store(tmp_path):
    profile = r.TemporalProfile(
        "disabled-only",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "context_assembler": {
                "adapter": "managed-data",
                "config": {"artifacts": {"adapter": "memory", "config": {"backend_id": "origin"}}},
            }
        },
        execution={"artifact_bindings": True},
    )

    async def run():
        assembly = await r.TemporalRuntimeBuilder(base_dir=tmp_path).abuild(profile)
        try:
            manifest = assembly.release
            assert manifest["binding_protocol"] == 5
            assert manifest["binding_catalog"]["records"] == {}
            validate_bindings(request("disabled"), manifest, asdict(r.Scope()))
            assert not list(tmp_path.iterdir())
        finally:
            await assembly.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_disabled_only_opt_in_requires_ordinary_boolean(value):
    runtime, _ = host()
    with pytest.raises(RalfError):
        TemporalRuntime(
            providers=runtime.providers,
            tools=runtime.tools,
            context_builder=runtime.context,
            binding_catalog=runtime.binding_catalog,
            artifact_bindings=value,
        )
