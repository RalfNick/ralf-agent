"""Original Session SDK parent beside the complete selected Coding publication."""

import copy
from types import SimpleNamespace

import pytest

from relf_agent import temporal_coding_composition_state as composition
from relf_agent.errors import DefinitionMismatch
from tests.test_temporal_coding_composition_state import parent as legacy_parent
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_dto import origin, reservation
from tests.test_temporal_session_deployment_execution import coordinator, initialize


def coding_original(*, composition=True):
    registry = registry_state()
    intent, request = coding_intent_request(registry, composition=composition)
    metadata = {
        "version": 2,
        "root": reservation(intent)["root_admission"],
        "lineage": [],
        "session_origin": origin(intent),
    }
    state = SimpleNamespace(
        scope=intent["scope"],
        run_id=intent["run_id"],
        epoch="business-epoch",
        request=intent["submission"]["request"],
        manifest=intent["submission"]["manifest"],
        receipts={intent["run_command_id"]: {"kind": "submit"}},
    )
    return intent, metadata, state


def session_root():
    intent, metadata, state = coding_original()
    actual_parent = coordinator(intent)
    initialize(state, metadata, actual_parent)
    assert state.deployment_admission == metadata
    assert state.deployment_sdk_parent == actual_parent
    composition.initialize(state, namespace=intent["namespace"]["name"])
    return (
        intent,
        state,
        {
            "namespace": intent["namespace"]["name"],
            "parent_namespace": intent["namespace"]["name"],
            "parent_run_id": actual_parent["workflow_id"],
            "parent_epoch": actual_parent["run_id"],
            "original_epoch": state.epoch,
        },
    )


def test_original_session_coordinator_is_allowed_beside_empty_business_lineage():
    intent, state, actual = session_root()
    before = copy.deepcopy(state.deployment_admission)
    composition.validate_child_link(state, **actual)
    assert state.deployment_admission == before
    assert state.deployment_admission["lineage"] == []
    assert "coding_parent" not in state.request
    assert state.composition_original_epoch == state.epoch
    assert state.composition_namespace == intent["namespace"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_run_id", "forged-coordinator"),
        ("parent_epoch", "reset-coordinator-epoch"),
        ("parent_namespace", "other-namespace"),
        ("namespace", "other-namespace"),
    ],
)
def test_forged_session_coordinator_tuple_stays_refused(monkeypatch, field, value):
    _, state, actual = session_root()
    actual[field] = value
    with pytest.raises(DefinitionMismatch):
        composition.validate_child_link(state, **actual)


def test_existing_legacy_coding_root_still_refuses_an_unlinked_sdk_parent():
    state = legacy_parent()
    with pytest.raises(DefinitionMismatch, match="Unlinked Coding execution"):
        composition.validate_child_link(
            state,
            namespace="test",
            parent_namespace="test",
            parent_run_id="unrelated-session",
            parent_epoch="unrelated-epoch",
            original_epoch=state.epoch,
        )
    composition.validate_child_link(
        state,
        namespace="test",
        parent_namespace=None,
        parent_run_id=None,
        parent_epoch=None,
        original_epoch=state.epoch,
    )


@pytest.mark.parametrize("parent_workflow", [False, True])
def test_session_metadata_is_validated_before_composition_sdk_parent_check(
    monkeypatch, parent_workflow
):
    from types import SimpleNamespace

    from relf_agent import temporal_parent_workflow, temporal_workflow

    intent, metadata, state = coding_original()
    info = SimpleNamespace(
        workflow_id=state.run_id,
        run_id=state.epoch,
        original_execution_run_id=state.epoch,
        namespace=intent["namespace"]["name"],
        parent=SimpleNamespace(**coordinator(intent)),
    )
    product = temporal_parent_workflow if parent_workflow else temporal_workflow
    workflow_class = (
        product.TemporalParentWorkflow if parent_workflow else product.TemporalRunWorkflow
    )
    monkeypatch.setattr(product.workflow, "info", lambda: info)
    monkeypatch.setattr(
        product,
        "TemporalParentState" if parent_workflow else "TemporalRunState",
        lambda *args: state,
    )

    def initialize_original(self, accepted, actual):
        initialize(self.state, accepted["deployment_admission"], coordinator(intent))

    monkeypatch.setattr(
        temporal_workflow.TemporalRunWorkflow, "_initialize_deployment", initialize_original
    )
    instance = workflow_class.__new__(workflow_class)
    instance.__init__(
        {
            "scope": state.scope,
            "command_id": intent["run_command_id"],
            "request": state.request,
            "manifest": state.manifest,
            "deployment_admission": metadata,
        }
    )
    assert state.composition_namespace == intent["namespace"]
    assert state.deployment_admission["lineage"] == []


def test_session_composition_uses_original_deployment_registry_and_seal_routes(monkeypatch):
    import asyncio

    from relf_agent import temporal_coding_composition_control as control
    from relf_agent import temporal_deployment_coding_bridge as bridge

    intent, _, state = coding_original()
    marker = object()
    monkeypatch.setattr(bridge, "registry", lambda *args: marker)
    assert control._registry(marker, state.scope, state.manifest) is marker
    calls = []

    async def admit(*args):
        calls.append("admit")
        return {"original": "admission"}

    async def sealed(*args):
        calls.append("sealed")
        return True

    monkeypatch.setattr(bridge, "root_admission", admit)
    monkeypatch.setattr(bridge, "sealed", sealed)

    async def run():
        assert await control.root_admission(
            marker, marker, {"runtime_manifest": state.manifest}, marker
        ) == {"original": "admission"}
        assert await control._deployment_sealed(
            marker, marker, {"manifest": state.manifest}, intent["namespace"]
        )
        assert calls == ["admit", "sealed"]

    asyncio.run(run())
