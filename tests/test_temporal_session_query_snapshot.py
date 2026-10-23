"""Large original Session selectors detach once within each synchronous method."""

import copy

import pytest

from relf_agent import temporal_session_deployment_state as deployment
from relf_agent.errors import RalfError
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.temporal_session_workflow import TemporalSessionWorkflow
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request


def original(*, composition=False):
    intent, _ = coding_intent_request(registry_state(), composition=composition)
    key = intent["session_ref"]["key"]
    state = TemporalSessionState(
        {
            "scope": intent["scope"],
            "namespace_id": intent["namespace"]["id"],
            "session_namespace": key["namespace"],
            "session_id": key["session_id"],
            "command_id": "open",
            **copy.deepcopy(intent["binding"]),
        },
        deployment_context={
            "namespace": intent["namespace"],
            "coordinator_execution_epoch": intent["coordinator_execution_epoch"],
        },
    )
    state.command(
        {
            "kind": "submit",
            "scope": state.scope,
            "command_id": intent["session_command_id"],
            "session_ref": state.ref.to_dict(),
            "input": intent["submission"]["request"]["input"],
            "budget": intent["submission"]["request"]["budget"],
        }
    )
    entry = state.deployment_turn()
    fixed = entry.intent
    selector = {name: fixed[name] for name in deployment.START_SELECTOR_FIELDS}
    workflow = TemporalSessionWorkflow.__new__(TemporalSessionWorkflow)
    workflow.state = state
    return state, entry, selector, workflow


def invoke(method, state, entry, selector, workflow):
    if method == "selector":
        return entry.check_selector(selector)
    if method == "command":
        return state.deployment_command(selector)
    return workflow.view(
        {
            "kind": "deployment_session_intent",
            **{name: value for name, value in selector.items() if name != "intent_digest"},
        }
    )


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("method,want", [("selector", 1), ("command", 2), ("intent", 2)])
def test_full_intent_clone_count_is_bounded_per_synchronous_method(
    monkeypatch, composition, method, want
):
    state, entry, selector, workflow = original(composition=composition)
    count = 0
    detached = deployment.detached

    def tracked(value):
        nonlocal count
        if value is entry._intent:
            count += 1
        return detached(value)

    monkeypatch.setattr(deployment, "detached", tracked)
    result = invoke(method, state, entry, selector, workflow)
    assert result and not (isinstance(result, dict) and "error" in result)
    assert count == want


@pytest.mark.parametrize(
    "method,field",
    [
        (method, field)
        for method in ("selector", "command", "intent")
        for field in sorted(deployment.START_SELECTOR_FIELDS)
        if (method, field) != ("intent", "intent_digest")
    ],
)
def test_each_original_selector_field_still_refuses_tampering(method, field):
    state, entry, selector, workflow = original()
    selector[field] = {"forged": True} if isinstance(selector[field], dict) else "forged"
    try:
        value = invoke(method, state, entry, selector, workflow)
    except RalfError:
        return
    assert value is None or isinstance(value, dict) and "error" in value


@pytest.mark.parametrize("method", ["selector", "command", "intent"])
@pytest.mark.parametrize("shape", ["missing", "extra"])
def test_original_selector_shape_remains_exact(method, shape):
    state, entry, selector, workflow = original()
    if shape == "missing":
        selector.pop("turn_id")
    else:
        selector["caller_flag"] = True
    try:
        result = invoke(method, state, entry, selector, workflow)
    except RalfError:
        return
    assert isinstance(result, dict) and "error" in result


@pytest.mark.parametrize("method", ["command", "intent"])
def test_repeated_queries_return_detached_results_without_mutating_original_intent(method):
    state, entry, selector, workflow = original(composition=True)
    frozen = entry.intent
    first = invoke(method, state, entry, selector, workflow)
    expected = copy.deepcopy(first)
    if method == "command":
        first["session_ref"]["key"]["session_id"] = "forged"
        first["receipt"]["outcome"].clear()
    else:
        first["binding"]["manifest"].clear()
        first["scope"]["workspace"] = "forged"
    assert invoke(method, state, entry, selector, workflow) == expected
    assert entry.intent == frozen
