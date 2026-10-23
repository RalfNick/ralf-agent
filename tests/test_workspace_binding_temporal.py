"""Original History performs pure Workspace grant selection and release admission."""

import copy
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    Scope,
    WorkspaceBindingResource,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import effective_step, normalize_request, validate_bindings
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import submission_request

from .test_workspace_binding_execution import Reader
from .test_workspace_bindings import registered as registered


def runtime(registry):
    catalog = BindingCatalog(scope=Scope())
    for root in ("a", "b"):
        catalog.register(
            "workspace",
            root,
            "1",
            WorkspaceBindingResource(registry, names=[root + "_workspace_read_text"]),
        )
    return TemporalRuntime(providers={"default": Reader()}, tools=registry, binding_catalog=catalog)


def request(selection):
    spec = AgentSpec(
        "reader", "Read", tools=("a_workspace_read_text", "b_workspace_read_text", "business")
    )
    return normalize_request(
        submission_request(AgentDefinition(spec, AgentBindingDescriptor(workspace=selection)), "q")
    )


def test_native_history_pins_selected_grants_and_serializes_original_state(registered):
    execution = runtime(registered)
    req = request(BindingSelection.ref("b", "1"))
    state = TemporalRunState("run", asdict(Scope()), "submit", req, execution.manifest)
    step = state.step
    assert step["tools"] == ["b_workspace_read_text", "business"]
    restored = copy.deepcopy(state)
    assert restored.step["tools"] == ["b_workspace_read_text", "business"]
    assert execution.manifest["workspace_binding_protocol"] == 1


def test_disabled_history_workspace_keeps_business_tool(registered):
    execution = runtime(registered)
    req = request(BindingSelection.disabled())
    state = TemporalRunState("run", asdict(Scope()), "submit", req, execution.manifest)
    assert state.step["tools"] == ["business"]


def test_missing_protocol_cannot_accept_explicit_workspace_selection(registered):
    execution = runtime(registered)
    manifest = copy.deepcopy(execution.manifest)
    manifest.pop("workspace_binding_protocol", None)
    with pytest.raises(DefinitionMismatch):
        validate_bindings(request(BindingSelection.ref("a", "1")), manifest, asdict(Scope()))


@pytest.mark.parametrize("protocol", [True, 0, 2, "1", None])
def test_unknown_workspace_protocol_refused_before_history_creation(registered, protocol):
    manifest = {**runtime(registered).manifest, "workspace_binding_protocol": protocol}
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_scope_and_subroot_selector_refused_before_acceptance(registered):
    manifest = runtime(registered).manifest
    with pytest.raises(AuthorizationDenied):
        validate_bindings(
            request(BindingSelection.ref("a", "1")), manifest, asdict(Scope("other", "caller"))
        )
    with pytest.raises(ValidationError):
        validate_bindings(
            request(BindingSelection.ref("a", "1", selector={"path": "sub"})),
            manifest,
            asdict(Scope()),
        )


def test_granted_name_with_another_root_cannot_match_selected_resource(registered):
    manifest = runtime(registered).manifest
    manifest["tools"]["a_workspace_read_text"]["config"]["source"] = manifest["tools"][
        "b_workspace_read_text"
    ]["config"]["source"]
    req = request(BindingSelection.ref("a", "1"))
    with pytest.raises(DefinitionMismatch):
        effective_step(req["definition"]["steps"][0], manifest, req["agent_bindings"]["agent"])


def test_changed_catalog_resource_owner_refused_by_original_worker(registered):
    execution = runtime(registered)
    original = execution.manifest
    catalog = execution.binding_catalog
    catalog.unregister("workspace", "a", "1")
    catalog.register(
        "workspace", "a", "1", WorkspaceBindingResource(registered, names=["b_workspace_read_text"])
    )
    with pytest.raises(DefinitionMismatch):
        execution.validate_release(original)
