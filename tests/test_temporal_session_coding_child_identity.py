"""Original Session origin remains beside the compact Coding business edge."""

import copy
import importlib
import warnings

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, TemporalRuntime, ToolRegistry
from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_control_projection as projection
from ralf_agent import temporal_deployment_control_transport as transport
from ralf_agent.errors import RalfError
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_session_state import TemporalSessionState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_deployment_control_projection import add_child, original
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_dto import origin, reservation
from tests.test_temporal_session_deployment_execution import admit, coordinator, initialize


def original_child(definition=None):
    seed, _ = coding_intent_request(registry_state(), composition=True)
    binding = copy.deepcopy(seed["binding"])
    host = TemporalRuntime(
        providers={"default": EchoProvider("child-identity")}, tools=ToolRegistry()
    )
    binding["manifest"]["orchestration"] = host.orchestration_release["orchestration"]
    binding["request"] = submission_request(
        definition or GraphWorkflowSpec("parent", [GraphNode("a", agent=AgentSpec("a", "answer"))]),
        None,
        budget=32,
    )
    key = seed["session_ref"]["key"]
    session = TemporalSessionState(
        {
            "scope": seed["scope"],
            "namespace_id": seed["namespace"]["id"],
            "session_namespace": key["namespace"],
            "session_id": key["session_id"],
            "command_id": "open",
            **binding,
        },
        deployment_context={
            "namespace": seed["namespace"],
            "coordinator_execution_epoch": seed["coordinator_execution_epoch"],
        },
    )
    session.command(
        {
            "kind": "submit",
            "scope": session.scope,
            "command_id": "turn",
            "session_ref": session.ref.to_dict(),
            "input": "task",
            "budget": 32,
        }
    )
    intent = session.deployment_turn().intent
    metadata = {
        "version": 2,
        "root": reservation(intent)["root_admission"],
        "lineage": [],
        "session_origin": origin(intent),
    }
    parent = TemporalParentState(
        intent["run_id"],
        intent["scope"],
        intent["run_command_id"],
        intent["submission"]["request"],
        intent["submission"]["manifest"],
        "business-epoch",
    )
    initialize(parent, metadata, coordinator(intent))
    admit(parent)
    composition.initialize(parent, namespace=intent["namespace"]["name"])
    composition.validate_child_link(
        parent,
        namespace=intent["namespace"]["name"],
        parent_namespace=intent["namespace"]["name"],
        parent_run_id=intent["coordinator_id"],
        parent_epoch=intent["coordinator_execution_epoch"],
        original_epoch=parent.epoch,
    )
    if parent.definition["kind"] == "team":
        member = next(iter(parent.definition["members"]))
        parent.accept_selection(
            {
                "calls": [{"id": "nested", "member": member, "input": parent.request["input"]}],
                "done": False,
                "result": None,
            }
        )
    return parent, parent.next_calls()[0]


def test_original_session_child_compact_request_retains_origin_and_business_edge():
    parent, call = original_child()
    before = copy.deepcopy(call)
    request = transport.request(parent, call, "register")
    assert request["child_intent_digest"] == projection.child_identity(call)
    assert len(projection.edge_identity_digest(call)) == 64
    assert call == before
    metadata = call["deployment_admission"]
    assert metadata["version"] == 2 and len(metadata["lineage"]) == 1
    assert metadata["lineage"][0]["parent_run_id"] == parent.run_id
    assert metadata["session_origin"]["coordinator_id"] != parent.run_id
    assert metadata["session_origin"] == parent.deployment_admission["session_origin"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing-origin",
        "origin-epoch",
        "origin-coordinator",
        "origin-scope",
        "origin-namespace",
        "root-scope",
        "root-namespace",
        "lineage",
        "coding-parent",
        "tag-only",
    ],
)
def test_session_child_rejects_forged_origin_or_disconnected_business_edge(fault):
    parent, call = original_child()
    metadata = call["deployment_admission"]
    selected_origin = metadata["session_origin"]
    if fault == "missing-origin":
        del metadata["session_origin"]
    elif fault == "origin-epoch":
        selected_origin["coordinator_original_execution_epoch"] = "reset"
    elif fault == "origin-coordinator":
        selected_origin["coordinator_id"] = "foreign"
    elif fault == "origin-scope":
        selected_origin["session_ref"]["key"]["principal"] = "foreign"
    elif fault == "origin-namespace":
        selected_origin["namespace"]["name"] = "foreign"
    elif fault in {"root-scope", "root-namespace"}:
        metadata["root"]["scope" if fault == "root-scope" else "namespace"][
            "principal" if fault == "root-scope" else "name"
        ] = "foreign"
        root = metadata["root"]
        root["proof_digest"] = digest(
            {k: v for k, v in root.items() if k not in {"proof_digest", "state", "execution_epoch"}}
        )
    elif fault == "lineage":
        metadata["lineage"][0]["parent_run_id"] = selected_origin["coordinator_id"]
    elif fault == "coding-parent":
        call["request"]["coding_parent"]["parent_execution_epoch"] = "foreign"
        call["child_request_digest"] = digest(call["request"])
        metadata["lineage"][0]["child_request_digest"] = call["child_request_digest"]
    else:
        metadata["session_origin"] = {"version": 1}
    with pytest.raises(RalfError):
        transport.request(parent, call, "register")


def test_legacy_metadata_one_keeps_identical_compact_child_identity():
    parent = original(parent=True)
    call = add_child(parent)
    before = copy.deepcopy(call)
    assert call["deployment_admission"]["version"] == 1
    assert transport.request(parent, call, "register")[
        "child_intent_digest"
    ] == projection.child_identity(call)
    assert call == before


def test_original_parent_activation_can_construct_session_child_control_request():
    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner

    parent, call = original_child()
    importlib.import_module("ralf_agent.temporal_parent_workflow")
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        importlib.import_module("ralf_agent.temporal_parent_workflow")
        product = importlib.import_module("ralf_agent.temporal_deployment_control_transport")
        context.is_runtime = True
        context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                assert product.request(parent, call, "register")["child_run_id"] == call["run_id"]
        finally:
            context.in_activation = False
            context.is_runtime = False
