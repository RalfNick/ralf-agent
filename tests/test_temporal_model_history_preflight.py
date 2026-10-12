"""New history bindings obey the original History admission boundary."""

from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request, validate_descriptor
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request


class Provider:
    identity = {"kind": "history-preflight-provider", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("Preflight must never dispatch a model")


def manifest(scope):
    catalog = r.BindingCatalog(scope=scope)
    catalog.register("model_history", "history", "1", r.CompleteModelHistory())
    return TemporalRuntime(
        providers={"default": Provider()},
        tools=r.ToolRegistry(),
        binding_catalog=catalog,
        model_continuation=True,
    ).manifest


@pytest.mark.parametrize("entrypoint", ["descriptor", "run"])
@pytest.mark.parametrize("invalid", ["foreign-scope", "missing-ref", "selector"])
def test_history_binding_rejected_by_original_preflight(entrypoint, invalid):
    scope = r.Scope()
    fixed = manifest(
        r.Scope(workspace="foreign", principal="foreign-owner")
        if invalid == "foreign-scope"
        else scope
    )
    descriptor = r.AgentBindingDescriptor(
        model_history=r.BindingSelection.ref(
            "missing" if invalid == "missing-ref" else "history",
            "1",
            selector={"namespace": "unapproved"} if invalid == "selector" else {},
        )
    ).to_dict()
    with pytest.raises((AuthorizationDenied, DefinitionMismatch, ValidationError)):
        if entrypoint == "descriptor":
            validate_descriptor(fixed, descriptor, asdict(scope))
        else:
            request = normalize_request(submission_request(r.AgentSpec("answer", "Answer"), "task"))
            request["agent_bindings"] = {"agent": descriptor}
            TemporalRunState("preflight-run", asdict(scope), "submit", request, fixed)


def test_current_scope_history_ref_is_accepted_without_changing_v1_defaults():
    fixed = manifest(r.Scope())
    legacy = r.AgentBindingDescriptor().to_dict()
    validate_descriptor(fixed, legacy, asdict(r.Scope()))
    assert legacy["schema_version"] == 1 and "model_history" not in legacy
    explicit = r.AgentBindingDescriptor(
        model_history=r.BindingSelection.ref("history", "1")
    ).to_dict()
    validate_descriptor(fixed, explicit, asdict(r.Scope()))
