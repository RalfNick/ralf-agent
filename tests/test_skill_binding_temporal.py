"""Original History performs pure Skills grant selection and release admission."""

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
    SkillBindingResource,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import effective_step, normalize_request, validate_bindings
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import submission_request

from .test_skill_bindings import registered as registered
from .test_skill_execution import Reader


def runtime(registry):
    catalog = BindingCatalog(scope=Scope())
    for root in ("a", "b"):
        catalog.register(
            "skills",
            root,
            "1",
            SkillBindingResource(registry, names=[root + "_skill_get"]),
        )
    return TemporalRuntime(providers={"default": Reader()}, tools=registry, binding_catalog=catalog)


def request(selection):
    spec = AgentSpec("reader", "Read", tools=("a_skill_get", "b_skill_get", "business"))
    return normalize_request(
        submission_request(AgentDefinition(spec, AgentBindingDescriptor(skills=selection)), "q")
    )


def test_native_history_pins_selected_grants_and_serializes_original_state(registered):
    execution = runtime(registered[0])
    req = request(BindingSelection.ref("b", "1"))
    state = TemporalRunState("run", asdict(Scope()), "submit", req, execution.manifest)
    step = state.step
    assert step["tools"] == ["b_skill_get", "business"]
    restored = copy.deepcopy(state)
    assert restored.step["tools"] == ["b_skill_get", "business"]
    assert execution.manifest["skills_binding_protocol"] == 1


def test_disabled_history_skills_keeps_business_tool(registered):
    execution = runtime(registered[0])
    req = request(BindingSelection.disabled())
    state = TemporalRunState("run", asdict(Scope()), "submit", req, execution.manifest)
    assert state.step["tools"] == ["business"]


def test_missing_protocol_cannot_accept_explicit_skills_selection(registered):
    execution = runtime(registered[0])
    manifest = copy.deepcopy(execution.manifest)
    manifest.pop("skills_binding_protocol", None)
    with pytest.raises(DefinitionMismatch):
        validate_bindings(request(BindingSelection.ref("a", "1")), manifest, asdict(Scope()))


@pytest.mark.parametrize("protocol", [True, 0, 2, "1", None])
def test_unknown_skills_protocol_refused_before_history_creation(registered, protocol):
    manifest = {**runtime(registered[0]).manifest, "skills_binding_protocol": protocol}
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_scope_and_subroot_selector_refused_before_acceptance(registered):
    manifest = runtime(registered[0]).manifest
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
    manifest = runtime(registered[0]).manifest
    manifest["tools"]["a_skill_get"]["config"]["source"] = manifest["tools"]["b_skill_get"][
        "config"
    ]["source"]
    req = request(BindingSelection.ref("a", "1"))
    with pytest.raises(DefinitionMismatch):
        effective_step(req["definition"]["steps"][0], manifest, req["agent_bindings"]["agent"])


def test_changed_catalog_resource_owner_refused_by_original_worker(registered):
    execution = runtime(registered[0])
    original = execution.manifest
    catalog = execution.binding_catalog
    catalog.unregister("skills", "a", "1")
    catalog.register("skills", "a", "1", SkillBindingResource(registered[0], names=["b_skill_get"]))
    with pytest.raises(DefinitionMismatch):
        execution.validate_release(original)
