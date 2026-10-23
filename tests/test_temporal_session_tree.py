"""Tree address evidence must preserve actual membership, not slash prefixes."""

import copy
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TeamSpec, ToolRegistry
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.types import digest, submission_request

from .test_temporal_sessions import Provider, submit


def functions():
    from relf_agent.temporal_session_tree import project_lineage, root_lineage, validate_lineage

    return root_lineage, project_lineage, validate_lineage


def original(spec):
    from relf_agent import BindingCatalog

    host = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        enable_sessions=True,
        binding_catalog=BindingCatalog(scope=Scope()),
    )
    state = TemporalSessionState(
        {
            "scope": asdict(Scope()),
            "namespace_id": "actual-namespace-uuid",
            "session_namespace": "root",
            "session_id": "chat",
            "command_id": "open",
            "request": submission_request(spec, None),
            "manifest": host.orchestration_release,
            "task_queue": "q",
            "activity_timeout": 3,
        }
    )
    submit(state)
    accepted = state.active
    root_lineage, _, _ = functions()
    lineage = root_lineage(
        accepted["request"], accepted["run_id"], state.namespace_id, state.binding, state.scope
    )
    return state, {**accepted["request"], "session_lineage": lineage}


def project(parent, parent_id, member, call_id, child, *, proposal=None):
    _, project_lineage, _ = functions()
    request = submission_request(child, "task", budget=2)
    lineage = project_lineage(parent, parent_id, member, call_id, request, proposal=proposal)
    return {**request, "session_lineage": lineage}


def test_nested_members_keep_root_binding_and_structured_original_path():
    leaf = AgentSpec("writer", "Write")
    inner = TeamSpec("inner", {"writer": leaf})
    state, root = original(TeamSpec("outer", {"inner": inner}))
    mid = project(root, state.active["run_id"], "inner", "review", inner)
    middle_run = mid["session_lineage"]["links"][-1]["child_run_id"]
    child = project(mid, middle_run, "writer", "answer", leaf)
    _, _, validate = functions()
    accepted = validate(child, state.binding["manifest"], state.scope, parent_run_id=middle_run)
    assert accepted["path"] == [
        "team",
        "members",
        "inner",
        "calls",
        "review",
        "team",
        "members",
        "writer",
        "calls",
        "answer",
    ]
    assert accepted["root_ref"] == state.ref.to_dict()
    assert accepted["definition_digest"] == digest(asdict(leaf))
    assert accepted["root_run_id"] == state.active["run_id"]


def test_graph_member_name_remains_one_structured_atom():
    leaf = AgentSpec("writer", "Write")
    state, root = original(GraphWorkflowSpec("g", [GraphNode("a_b", agent=leaf)]))
    child = project(root, state.active["run_id"], "a_b", "a_b", leaf)
    accepted = functions()[2](child, state.binding["manifest"], state.scope)
    assert accepted["path"] == ["graph", "nodes", "a_b"]


@pytest.mark.parametrize(
    "damage", ["scope", "namespace", "root-binding", "member", "definition", "parent", "path"]
)
def test_forged_lineage_refuses_before_any_source_or_model(damage):
    leaf = AgentSpec("writer", "Write")
    state, root = original(TeamSpec("t", {"writer": leaf}))
    child = project(root, state.active["run_id"], "writer", "answer", leaf)
    altered = copy.deepcopy(child)
    lineage = altered["session_lineage"]
    if damage == "scope":
        lineage["root_turn"]["session_ref"]["key"]["principal"] = "other"
    elif damage == "namespace":
        lineage["namespace_id"] = "other-namespace"
    elif damage == "root-binding":
        lineage["root_binding"]["request"]["input"] = "different"
    elif damage == "member":
        lineage["links"][0]["member"] = "other"
    elif damage == "definition":
        altered["definition"]["steps"][0]["instructions"] = "different"
    elif damage == "parent":
        lineage["links"][0]["parent_run_id"] = "foreign"
    else:
        lineage["path"] = ["team", "members", "other"]
    with pytest.raises((ValidationError, DefinitionMismatch, AuthorizationDenied)):
        functions()[2](
            altered, state.binding["manifest"], state.scope, parent_run_id=state.active["run_id"]
        )


def test_dynamic_paths_use_adopted_node_id_and_authorized_member():
    from relf_agent import DAGNode, DAGProposal, DynamicWorkflowSpec

    leaf = AgentSpec("writer", "Write")
    state, root = original(DynamicWorkflowSpec("d", {"writer": leaf}))
    proposal = DAGProposal([DAGNode("diagnose", "writer"), DAGNode("resolve", "writer")]).to_dict()
    first = project(root, state.active["run_id"], "writer", "diagnose", leaf, proposal=proposal)
    second = project(root, state.active["run_id"], "writer", "resolve", leaf, proposal=proposal)
    validate = functions()[2]
    assert validate(first, state.binding["manifest"], state.scope)["path"] == [
        "dynamic",
        "nodes",
        "diagnose",
        "members",
        "writer",
    ]
    assert (
        validate(second, state.binding["manifest"], state.scope)["path"]
        != validate(first, state.binding["manifest"], state.scope)["path"]
    )
    with pytest.raises(ValidationError):
        project(root, state.active["run_id"], "writer", "not-adopted", leaf, proposal=proposal)


def test_unknown_member_and_different_child_definition_are_refused_at_projection():
    leaf = AgentSpec("writer", "Write")
    state, root = original(TeamSpec("t", {"writer": leaf}))
    with pytest.raises(ValidationError):
        project(root, state.active["run_id"], "unknown", "call", leaf)
    with pytest.raises(DefinitionMismatch):
        project(root, state.active["run_id"], "writer", "call", AgentSpec("writer", "Different"))


def test_sequence_members_have_distinct_leaf_paths_and_definition_identity():
    from relf_agent import WorkflowSpec
    from relf_agent.temporal_session_tree import member_projection

    first, second = AgentSpec("a", "A"), AgentSpec("b", "B")
    sequence = WorkflowSpec("steps", [first, second])
    state, root = original(TeamSpec("outer", {"steps": sequence}))
    child = project(root, state.active["run_id"], "steps", "execute", sequence)
    a = member_projection(child, state.binding["manifest"], state.scope, 0)
    b = member_projection(child, state.binding["manifest"], state.scope, 1)
    assert a["path"] == ["team", "members", "steps", "calls", "execute", "sequence", "steps", "0"]
    assert b["path"][-1] == "1" and a["path"] != b["path"]
    assert a["definition_digest"] == digest(asdict(first))
    assert b["definition_digest"] == digest(asdict(second))
    with pytest.raises(ValidationError):
        member_projection(child, state.binding["manifest"], state.scope, True)
    with pytest.raises(ValidationError):
        member_projection(child, state.binding["manifest"], state.scope, 2)


def test_root_parent_cannot_be_used_as_a_private_member():
    from relf_agent.temporal_session_tree import member_projection

    state, root = original(TeamSpec("t", {"writer": AgentSpec("writer", "Write")}))
    with pytest.raises(ValidationError):
        member_projection(root, state.binding["manifest"], state.scope, 0)


@pytest.mark.parametrize("member_choice", ["inherit", "disabled"])
def test_member_projection_preserves_original_session_selection(member_choice):
    from relf_agent import AgentBindingDescriptor, BindingSelection, BoundDefinition
    from relf_agent.temporal_bindings import normalize_request, project_child
    from relf_agent.temporal_session_tree import member_projection, root_lineage

    leaf = AgentSpec("writer", "Write")
    spec = TeamSpec("t", {"writer": leaf})
    state, root = original(spec)
    descriptor = AgentBindingDescriptor(session=getattr(BindingSelection, member_choice)())
    binding = copy.deepcopy(state.binding)
    binding["request"] = normalize_request(
        submission_request(BoundDefinition(spec, {"team/members/writer": descriptor}), None)
    )
    # Reopen through the real original Session authority, never fabricate a ref.
    rebound = TemporalSessionState(
        {
            "scope": state.scope,
            "namespace_id": state.namespace_id,
            "session_namespace": "root",
            "session_id": "selected",
            "command_id": "open",
            **binding,
        }
    )
    submit(rebound)
    accepted = rebound.active
    parent = {
        **accepted["request"],
        "session_lineage": root_lineage(
            accepted["request"], accepted["run_id"], rebound.namespace_id, binding, state.scope
        ),
    }
    child = project_child(parent, "writer", submission_request(leaf, "task", budget=2))
    child["session_lineage"] = functions()[1](parent, accepted["run_id"], "writer", "answer", child)
    selected = member_projection(child, binding["manifest"], state.scope, 0)
    assert selected["bindings"]["session"]["mode"] == member_choice


def test_lineage_projection_never_accepts_arbitrary_parent_id():
    state, root = original(TeamSpec("t", {"writer": AgentSpec("writer", "Write")}))
    with pytest.raises(DefinitionMismatch):
        project(root, "another-run", "writer", "answer", AgentSpec("writer", "Write"))


def test_unicode_lineage_is_bounded_by_serialized_bytes_before_projection():
    # Counting characters would let a transport payload exceed its byte bound.
    state, _ = original(TeamSpec("t", {"writer": AgentSpec("writer", "Write")}))
    binding = copy.deepcopy(state.binding)
    binding["task_queue"] = "汉" * 400_000
    replacement = TemporalSessionState(
        {
            "scope": state.scope,
            "namespace_id": state.namespace_id,
            "session_namespace": "root",
            "session_id": "bounded",
            "command_id": "open",
            **binding,
        }
    )
    submit(replacement)
    with pytest.raises(ValidationError):
        functions()[0](
            replacement.active["request"],
            replacement.active["run_id"],
            replacement.namespace_id,
            binding,
            replacement.scope,
        )


def test_lineage_refuses_changed_original_coordination_resource():
    state, request = original(TeamSpec("t", {"writer": AgentSpec("a", "Answer")}))
    request = copy.deepcopy(request)
    request["session_lineage"]["root_turn"]["session_ref"]["coordination_ref"] = "0" * 64
    _, _, validate = functions()
    with pytest.raises(DefinitionMismatch):
        validate(request, state.binding["manifest"], state.scope)
