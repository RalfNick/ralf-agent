"""Artifact selection stays pure in original History and actual runtime adoption."""

import asyncio
import copy
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import (
    effective_manifest,
    normalize_request,
    selected_runtime,
    validate_bindings,
)
from ralf_agent.temporal_state import TemporalRunState, validate_manifest
from ralf_agent.types import submission_request

from .test_artifact_binding_execution import Reader, definition


def host():
    catalog = r.BindingCatalog(scope=r.Scope())
    stores = {
        name: r.InMemoryArtifactStore(backend_id=name) for name in ("original", "alpha", "beta")
    }
    for name in ("alpha", "beta"):
        catalog.register(
            "artifacts",
            name,
            "1",
            r.ArtifactBindingResource(
                stores[name], version="1", namespaces=[name], default_namespace=name
            ),
        )
    context = r.ManagedDataContext(stores["original"], tool_result_chars=1024, preview_chars=64)
    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec("lookup", "Read", {"type": "object"}, effect="read_only", cost=0),
        lambda args, ctx: "EVIDENCE" * 1600,
    )
    runtime = TemporalRuntime(
        providers={"default": Reader()},
        tools=tools,
        context_builder=context,
        binding_catalog=catalog,
    )
    return runtime, stores


def request(mode="ref"):
    return normalize_request(submission_request(definition("agent", mode), "read"))


def test_publish_joint_protocol_and_fixed_selected_context_without_io():
    runtime, stores = host()
    manifest = runtime.manifest
    assert manifest["binding_protocol"] == 5 and manifest["artifacts_binding_protocol"] == 1
    req = request()
    selected = effective_manifest(manifest, req["agent_bindings"]["agent"])
    actual = selected_runtime(
        runtime,
        {**req, "scope": asdict(r.Scope()), "step_bindings": req["agent_bindings"]["agent"]},
    )
    assert selected["context_builder"] == actual.context.identity
    assert selected["managed_context"]["policy"]["artifacts"]["backend_id"] == "alpha"
    assert actual.context.artifacts.namespace == "alpha"
    assert actual.context.identity["artifact_binding"]["origin"] == runtime.context.identity
    state = TemporalRunState("run", asdict(r.Scope()), "s", req, manifest)
    assert copy.deepcopy(state).manifest == manifest
    assert all(not store._records for store in stores.values())


@pytest.mark.parametrize("mode", ["disabled", "inherit"])
def test_disabled_and_inherit_keep_original_summary_semantics(mode):
    runtime, _ = host()
    req = (
        request(mode)
        if mode == "disabled"
        else normalize_request(
            submission_request(r.AgentDefinition(r.AgentSpec("a", "Answer")), "read")
        )
    )
    descriptor = req["agent_bindings"]["agent"]
    result = effective_manifest(runtime.manifest, descriptor)
    selected = selected_runtime(runtime, {"scope": asdict(r.Scope()), "step_bindings": descriptor})
    if mode == "inherit":
        assert (
            selected.context is runtime.context
            and result["context_builder"] == runtime.context.identity
        )
    else:
        assert not hasattr(selected.context, "artifacts")
        assert result["managed_context"]["policy"]["artifact_binding"]["mode"] == "disabled"
        assert result["context_builder"] == selected.context.identity


@pytest.mark.parametrize(
    "field,value",
    [
        ("binding_protocol", 4),
        ("binding_protocol", True),
        ("binding_protocol", 6),
        ("artifacts_binding_protocol", None),
        ("artifacts_binding_protocol", True),
        ("artifacts_binding_protocol", 2),
    ],
)
def test_partial_unknown_joint_markers_refuse_history(field, value):
    runtime, _ = host()
    manifest = runtime.manifest
    manifest[field] = value
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_missing_protocol_and_invalid_namespace_reject_before_run():
    runtime, _ = host()
    manifest = runtime.manifest
    manifest.pop("artifacts_binding_protocol", None)
    with pytest.raises(DefinitionMismatch):
        validate_bindings(request(), manifest, asdict(r.Scope()))
    req = request()
    req["agent_bindings"]["agent"]["artifacts"]["selector"] = {"namespace": "foreign"}
    with pytest.raises(AuthorizationDenied):
        validate_bindings(req, runtime.manifest, asdict(r.Scope()))
    with pytest.raises(AuthorizationDenied):
        validate_bindings(request(), runtime.manifest, asdict(r.Scope("other", "user")))


def test_runtime_bound_method_drift_is_rejected_before_storage(monkeypatch):
    runtime, _ = host()
    monkeypatch.setattr(runtime.context, "bind_artifacts", lambda target: runtime.context)
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_pure_history_evidence_selects_actual_store_and_adopts_receipt():
    from .test_temporal_managed_context import step

    runtime, stores = host()
    state = TemporalRunState("run", asdict(r.Scope()), "s", request(), runtime.manifest)

    async def run():
        for _ in range(40):
            if state.state in {"succeeded", "failed", "cancelled"}:
                break
            await step(runtime, state)
        assert state.state == "succeeded", state.snapshot()
        assert (
            stores["alpha"]._records
            and not stores["original"]._records
            and not stores["beta"]._records
        )
        receipts = [
            event for event in state.event_log if event["kind"] == "context_artifact_verified"
        ]
        assert receipts

    asyncio.run(run())


def test_unbound_legacy_default_release_is_unchanged():
    runtime = TemporalRuntime(providers={"default": Reader()}, tools=r.ToolRegistry())
    assert runtime.manifest["kernel"] == "temporal-1"
    assert "artifacts_binding_protocol" not in runtime.manifest
    assert "binding_protocol" not in runtime.manifest


def test_context_without_binding_port_rejects_explicit_artifacts_before_history():
    runtime, _ = host()
    plain = TemporalRuntime(
        providers=runtime.providers, tools=runtime.tools, binding_catalog=runtime.binding_catalog
    )
    with pytest.raises(RalfError):
        TemporalRunState("run", asdict(r.Scope()), "s", request(), plain.manifest)


@pytest.mark.parametrize("corruption", ["target", "origin", "choice-key", "provider"])
def test_forged_template_cannot_disagree_with_registered_source(corruption):
    runtime, _ = host()
    manifest = runtime.manifest
    templates = manifest["artifact_contexts"]["contexts"]
    origin = next(iter(templates.values()))
    choice_key, choice = next(
        (k, v) for k, v in origin["choices"].items() if v["resource"] is not None
    )
    if corruption == "target":
        choice["resource"]["target"]["backend"]["backend_id"] = "foreign"
    elif corruption == "origin":
        origin["origin"]["namespace"] = "foreign"
    elif corruption == "choice-key":
        origin["choices"]["wrong"] = origin["choices"].pop(choice_key)
    else:
        choice["configuration"]["managed_context"]["provider"] = {"kind": "foreign"}
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_same_prediction_with_replaced_port_receiver_is_still_definition_drift(monkeypatch):
    runtime, _ = host()
    original = runtime.context.bind_artifacts
    monkeypatch.setattr(runtime.context, "bind_artifacts", lambda target: original(target))
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_context_read_owner_is_jointly_published_with_artifact_selection():
    runtime, _ = host()
    execution = TemporalRuntime(
        providers=runtime.providers,
        tools=runtime.tools,
        context_builder=runtime.context,
        binding_catalog=runtime.binding_catalog,
        context_reads=True,
    )
    assert execution.manifest["binding_protocol"] == 5
    assert execution.manifest["context_read_protocol"]["version"] == 1
    validate_manifest(execution.manifest)


def test_selected_context_and_selected_artifact_remain_independent():
    runtime, stores = host()
    alternate = r.ManagedDataContext(
        stores["original"], tool_result_chars=2048, preview_chars=128, reference_chars=512
    )
    runtime.binding_catalog.register("context", "alternate", "2", alternate)
    execution = TemporalRuntime(
        providers=runtime.providers,
        tools=runtime.tools,
        context_builder=runtime.context,
        binding_catalog=runtime.binding_catalog,
    )
    req = request()
    req["agent_bindings"]["agent"]["context"] = r.BindingSelection.ref("alternate", "2").to_dict()
    state = TemporalRunState("run", asdict(r.Scope()), "s", req, execution.manifest)
    selected = selected_runtime(
        execution, {"scope": asdict(r.Scope()), "step_bindings": state.step_bindings}
    )
    assert state.step_manifest["context_builder"] == selected.context.identity
    assert selected.context.artifacts.backend_id == "alpha"
    assert (
        selected.context.tool_result_chars,
        selected.context.preview_chars,
        selected.context.reference_chars,
    ) == (2048, 128, 512)


def test_temporal_artifact_selector_capability_is_reported_for_joint_release():
    from types import SimpleNamespace

    from ralf_agent.temporal import TemporalEngine

    runtime, _ = host()
    engine = TemporalEngine(
        SimpleNamespace(namespace="default"),
        task_queue="test",
        release=runtime.orchestration_release,
    )
    assert engine.binding_capabilities["resource_selector_roles"]["artifacts"] == ["namespace"]


def test_temporal_profile_reuses_nested_scoped_store_factory(tmp_path):
    from .test_artifact_binding_configuration import declaration

    async def run():
        profile = r.TemporalProfile(
            "artifacts",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {
                "context_assembler": {
                    "adapter": "managed-data",
                    "config": {
                        "artifacts": {"adapter": "memory", "config": {"backend_id": "origin"}}
                    },
                }
            },
            binding_components=[
                declaration(
                    {
                        "backend": {
                            "adapter": "sqlite",
                            "config": {
                                "path": str(tmp_path / "artifacts.sqlite"),
                                "backend_id": "evidence",
                            },
                        }
                    }
                )
            ],
        )
        assembly = await r.TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            profile, scope=r.Scope()
        )
        try:
            assert assembly._runtime.manifest["artifacts_binding_protocol"] == 1
            selected, _ = assembly._runtime.binding_catalog.resolve(
                "artifacts", r.BindingSelection.ref("evidence", "1"), r.Scope()
            )
            receipt = await selected.put(r.Scope(), "evidence", "data")
            assert await selected.get(r.Scope(), receipt) == "data"
        finally:
            await assembly.aclose()
        assert not (tmp_path / "temporal-data.sqlite").exists()

    asyncio.run(run())


@pytest.mark.parametrize(
    "corruption",
    ["policy-target", "policy-namespace", "missing-source", "missing-target", "list-policy"],
)
def test_malformed_artifact_template_has_typed_admission_refusal(corruption):
    runtime, _ = host()
    manifest = runtime.manifest
    context = next(iter(manifest["artifact_contexts"]["contexts"].values()))
    choice = next(v for v in context["choices"].values() if v["resource"] is not None)
    policy = choice["configuration"]["context_builder"]
    if corruption == "policy-target":
        policy["artifacts"]["backend_id"] = "foreign"
    elif corruption == "policy-namespace":
        policy["namespace"] = "foreign"
    elif corruption == "missing-source":
        manifest.pop("context_builder")
    elif corruption == "missing-target":
        for record in manifest["binding_catalog"]["records"].values():
            if record["role"] == "artifacts":
                record.pop("identity")
                break
    else:
        choice["configuration"]["context_builder"] = []
        choice["configuration"]["context_registration"]["identity"] = []
        choice["configuration"]["managed_context"]["policy"] = []
    with pytest.raises(RalfError):
        validate_manifest(manifest)


def test_legacy_temporal_release_does_not_advertise_new_artifact_binding():
    from types import SimpleNamespace

    from ralf_agent.temporal import TemporalEngine

    execution = TemporalRuntime(
        providers={"default": Reader()},
        tools=r.ToolRegistry(),
        binding_catalog=r.BindingCatalog(scope=r.Scope()),
    )
    engine = TemporalEngine(
        SimpleNamespace(namespace="default"),
        task_queue="test",
        release=execution.orchestration_release,
    )
    assert "artifacts" not in engine.binding_capabilities["supported_binding_roles"]


@pytest.mark.parametrize("phase", ["read", "verify"])
@pytest.mark.parametrize("admitted", [False, True])
def test_undispatched_artifact_read_timeout_is_fenced_and_recreated_once(phase, admitted):
    from .test_temporal_context_read_runtime import call
    from .test_temporal_context_read_state import admission
    from .test_temporal_managed_context import grant

    async def run():
        runtime, _ = host()
        execution = TemporalRuntime(
            providers=runtime.providers,
            tools=runtime.tools,
            context_builder=runtime.context,
            binding_catalog=runtime.binding_catalog,
            context_reads=True,
        )
        state = TemporalRunState("run", asdict(r.Scope()), "s", request(), execution.manifest)
        try:
            for _ in range(20):
                action, req = state.next_operation()
                if action.get("phase") == phase:
                    break
                if action["kind"] == "managed_context":
                    response = await call(execution, state, action, req)
                    state.accept_managed_context(action["id"], response)
                    assert await execution.wait_context_executions(wait_timeout=3)
                elif action["kind"] == "model":
                    state.accept_model(
                        action["id"],
                        await execution.complete_model(
                            req, dispatch_guard=lambda value: grant(state, value)
                        ),
                    )
                else:
                    state.accept_tool(action["id"], await execution.execute_tool(req))
            else:
                raise AssertionError("did not reach artifact read")
            if admitted:
                assert state.admit_context_dispatch(admission(req))["allowed"]
            state.accept_managed_context(
                action["id"], {"ok": False, "code": "activity_outcome_unknown", "dispatched": False}
            )
            if admitted:
                assert state.state == "failed" and not state.quiescent
                assert state.next_operation() is None
                assert len([a for a in state.actions if a.get("phase") == phase]) == 1
                return
            assert state.state == "running", state.snapshot()
            assert state.context_read_stages[action["id"]]["status"] == "not_dispatched"
            assert state.admit_context_dispatch(admission(req))["allowed"] is False
            restored = copy.deepcopy(state)
            retry, replacement = restored.next_operation()
            assert retry["id"] != action["id"] and retry["phase"] == phase
            assert replacement["artifact"] == req["artifact"]
            # A second unadmitted timeout terminates; restoration cannot reset its budget.
            restored.accept_managed_context(
                retry["id"], {"ok": False, "code": "activity_outcome_unknown", "dispatched": False}
            )
            assert restored.state == "failed" and restored.quiescent
            assert restored.next_operation() is None
            assert len([a for a in restored.actions if a.get("phase") == phase]) == 2
        finally:
            await execution.close_context_execution(wait_timeout=3)

    asyncio.run(run())
