"""Pure compact original facts, not SDK ancestry or physical-stop verification."""

import copy
import importlib
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec
from relf_agent import temporal_deployment_execution_state as deployment
from relf_agent.errors import RalfError
from relf_agent.temporal_bindings import request_release_digest
from relf_agent.temporal_parent_state import child_run_id
from relf_agent.types import canonical, digest, submission_request
from tests.test_temporal_deployment_coding_registry import coding_request
from tests.test_temporal_deployment_coding_registry import registry as make_registry
from tests.test_temporal_deployment_descendant_control_state import retire
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE


def api():
    name = "relf_agent.temporal_deployment_control_projection"
    assert importlib.util.find_spec(name), "Compact original-History projection is missing"
    return importlib.import_module(name)


def original(*, parent=False):
    submitted = coding_request()
    envelope = submitted["root_admission"]["submission"]
    manifest = copy.deepcopy(envelope["manifest"])
    request = copy.deepcopy(envelope["request"])
    if parent:
        from relf_agent.temporal_coding_composition_protocol import publish

        manifest = publish(
            manifest, SimpleNamespace(coding_execution=True, coding_composition=True)
        )
        request = submission_request(
            GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "answer"))]),
            "task",
            budget=32,
        )
    state = SimpleNamespace(
        scope=copy.deepcopy(SCOPE),
        run_id=submitted["target"],
        epoch="original-epoch",
        request=request,
        manifest=manifest,
        receipts={"one": {"kind": "submit"}},
        release_digest=request_release_digest(request, manifest),
        state="waiting_approval",
        revision=7,
        deployment_activity_timeout=envelope["activity_timeout"],
        deployment_task_queue=envelope["task_queue"],
        actions=[],
    )
    if parent:
        state.children = []
        state.composition_original_epoch = state.epoch
        state.composition_namespace = copy.deepcopy(NAMESPACE)
        state.composition_stop_intent = None
    root = {
        "version": 1,
        "registry_id": manifest["deployment_admission_protocol"]["registry_id"],
        "scope": copy.deepcopy(SCOPE),
        "command_id": "one",
        "run_id": state.run_id,
        "request_digest": digest(request),
        "manifest_digest": digest(manifest),
        "namespace": copy.deepcopy(NAMESPACE),
    }
    metadata = {
        "version": 1,
        "root": {
            **root,
            "proof_digest": digest(root),
            "state": "held-unbound",
            "execution_epoch": None,
        },
        "lineage": [],
    }
    deployment.initialize(
        state,
        metadata,
        namespace=NAMESPACE["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent=None,
    )
    result = {
        "version": 1,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "root": {**metadata["root"], "state": "held-bound", "execution_epoch": state.epoch},
        "metadata_digest": digest(metadata),
    }
    deployment.adopt(state, {**result, "proof_digest": digest(result)})
    return state


def add_child(state):
    base = submission_request(AgentSpec("a", "answer"), "child", budget=8)
    command = "child-command"
    run_id = child_run_id(state.scope, command)
    link = {
        "version": 1,
        "scope": copy.deepcopy(state.scope),
        "namespace": copy.deepcopy(NAMESPACE),
        "parent_run_id": state.run_id,
        "parent_execution_epoch": state.epoch,
        "parent_request_digest": digest(state.request),
        "parent_release_digest": state.release_digest,
        "call_id": "0:child",
        "command_id": command,
        "member": "a",
        "planning_revision": 0,
        "child_run_id": run_id,
        "child_projection_digest": digest(base),
        "cap": 8,
        "depth": 1,
    }
    call = {
        "id": "0:child",
        "call_id": "child",
        "member": "a",
        "input": "child",
        "command_id": command,
        "run_id": run_id,
        "request": {**base, "coding_parent": link},
        "cap": 8,
        "depth": 1,
        "planning_revision": 0,
        "dispatch_started": True,
        "deployment_execution_epoch": "child-epoch",
        "child_execution": {
            "namespace": copy.deepcopy(NAMESPACE),
            "execution_epoch": "child-epoch",
            "original_execution_epoch": "child-epoch",
        },
    }
    call["child_request_digest"] = digest(call["request"])
    state.children.append(call)
    call["deployment_admission"] = deployment.project_child(state, call)
    return call


def query(state, call=None):
    return {
        "kind": "deployment_coding_validation",
        "scope": copy.deepcopy(state.scope),
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "child_call_id": None if call is None else call["id"],
    }


def start(state):
    return {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "request_digest": digest(state.request),
        "manifest_digest": digest(state.manifest),
        "activity_timeout": state.deployment_activity_timeout,
        "task_queue": state.deployment_task_queue,
    }


def bound_registry():
    wrapper, submitted = make_registry(), coding_request()
    receipt = wrapper.reserve(submitted)
    root = receipt["root_admission"]
    root = wrapper.bind_deployment_root(
        {
            "scope": SCOPE,
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            **{
                name: root[name]
                for name in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": "original-epoch",
        }
    )
    state = wrapper.deployment
    state.deployment_registry_execution_epoch = "original-registry-epoch"
    request = {
        "kind": "deployment_coding_validation",
        "scope": copy.deepcopy(SCOPE),
        "admission_policy": POLICY.identity,
        "namespace": copy.deepcopy(NAMESPACE),
        **{
            name: root[name]
            for name in (
                "command_id",
                "run_id",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
    }
    return wrapper, state, submitted, root, request


def test_node_projection_is_compact_detached_read_only_and_matches_bootstrap():
    state = original()
    before = copy.deepcopy(vars(state))
    value = api().node(state, query(state))
    assert api().NODE_QUERY == "deployment_coding_validation"
    assert set(value) == {
        "version",
        "scope",
        "namespace",
        "run_id",
        "execution_epoch",
        "original_execution_epoch",
        "identity_digest",
        "revision",
        "state",
        "stop_requested",
        "sealed",
        "edge",
        "proof_digest",
    }
    assert value["identity_digest"] == api().node_identity_digest(
        deployment.view(state), start(state)
    )
    assert value["revision"] == 7 and value["edge"] is None
    assert value["stop_requested"] is False and value["sealed"] is False
    assert value["proof_digest"] == digest({k: v for k, v in value.items() if k != "proof_digest"})
    assert len(canonical(value)) < 1600
    assert "manifest" not in value and "request" not in value and "children" not in value
    value["scope"]["principal"] = "caller"
    assert vars(state) == before


def test_node_projects_one_original_pinned_edge_and_not_mutable_child_snapshots():
    from relf_agent.temporal_coding_composition_state import physical_stop_view

    state = original(parent=True)
    call = add_child(state)
    before = copy.deepcopy(vars(state))
    value = api().node(state, query(state, call))
    assert value["edge"] == {
        "call_id": call["id"],
        "child_run_id": call["run_id"],
        "child_execution_epoch": "child-epoch",
        "identity_digest": api().edge_identity_digest(call),
        "dispatch_started": True,
        "owned": True,
    }
    assert value["identity_digest"] == api().node_identity_digest(
        deployment.view(state), start(state), physical_stop_view(state)
    )
    identity = api().child_identity(call)
    call.update(snapshot={"huge": "x" * 100000}, state="cancelled", settled=True, spent=0)
    assert api().child_identity(call) == identity
    assert api().node(state, query(state, call)) == value
    assert {k: v for k, v in vars(state).items() if k != "children"} == {
        k: v for k, v in before.items() if k != "children"
    }


@pytest.mark.parametrize(
    "fault", ["kind", "scope", "run_id", "execution_epoch", "extra", "missing", "child"]
)
def test_node_refuses_malformed_or_foreign_requests_without_mutation(fault):
    state = original()
    request = query(state)
    if fault == "scope":
        request["scope"]["principal"] = "foreign"
    elif fault == "extra":
        request["expected_digest"] = "a" * 64
    elif fault == "missing":
        del request["child_call_id"]
    elif fault == "child":
        request["child_call_id"] = "invented"
    else:
        request[fault] = "foreign"
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        api().node(state, request)
    assert vars(state) == before


@pytest.mark.parametrize(
    "fault",
    [
        "receipt",
        "receipt_digest",
        "original_epoch",
        "source",
        "publication",
        "queue",
        "timeout",
        "release",
    ],
)
def test_node_requires_complete_original_server_identity(fault):
    state = original()
    if fault == "receipt":
        state.deployment_receipt = None
    elif fault == "receipt_digest":
        state.deployment_receipt["proof_digest"] = "a" * 64
    elif fault == "original_epoch":
        state.deployment_original_epoch = "replacement"
    elif fault == "source":
        state.manifest["deployment_admission_protocol"]["implementation"].pop(
            "temporal_workflow.py"
        )
    elif fault == "publication":
        state.manifest["deployment_admission_protocol"]["version"] = 2
    elif fault == "queue":
        state.deployment_task_queue = None
    elif fault == "timeout":
        state.deployment_activity_timeout = True
    elif fault == "release":
        state.release_digest = "a" * 64
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        api().node(state, query(state))
    assert vars(state) == before


@pytest.mark.parametrize(
    "fault", ["duplicate", "unbound", "split_epoch", "metadata", "request", "link", "dispatch_type"]
)
def test_node_refuses_ambiguous_or_changed_original_edge(fault):
    state = original(parent=True)
    call = add_child(state)
    if fault == "duplicate":
        state.children.append(copy.deepcopy(call))
    elif fault == "unbound":
        call["deployment_execution_epoch"] = None
    elif fault == "split_epoch":
        call["child_execution"]["execution_epoch"] = "foreign"
    elif fault == "metadata":
        call["deployment_admission"]["root"]["proof_digest"] = "a" * 64
    elif fault == "request":
        call["request"]["input"] = "foreign"
    elif fault == "link":
        call["request"]["coding_parent"]["parent_execution_epoch"] = "foreign"
        call["child_request_digest"] = digest(call["request"])
    else:
        call["dispatch_started"] = 1
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        api().node(state, query(state, call))
    assert vars(state) == before


def test_fresh_stop_and_seal_do_not_change_immutable_identity_or_claim_physical_end():
    state = original(parent=True)
    call = add_child(state)
    first = api().node(state, query(state, call))
    state.state = "cancelling"
    state.revision += 1
    state.composition_stop_intent = {"original": "stop"}
    state.deployment_seal = {"original": "seal"}
    after = api().node(state, query(state, call))
    assert after["identity_digest"] == first["identity_digest"]
    assert after["stop_requested"] is True and after["sealed"] is True
    assert "physical_stopped" not in after
    assert api().child_identity(call) == digest(
        {
            "id": call["id"],
            "call_id": call["call_id"],
            "member": call["member"],
            "input_digest": digest(call["input"]),
            "command_id": call["command_id"],
            "run_id": call["run_id"],
            "request_digest": digest(call["request"]),
            "cap": call["cap"],
            "depth": call["depth"],
            "planning_revision": call["planning_revision"],
            "deployment_metadata_digest": digest(call["deployment_admission"]),
        }
    )


def test_registry_projection_matches_first_envelope_and_actual_epoch_without_mutation():
    _, state, submitted, root, request = bound_registry()
    before = copy.deepcopy(vars(state))
    value = api().registry(state, request)
    assert set(value) == {
        "version",
        "registry_id",
        "registry_execution_epoch",
        "configuration_version",
        "policy",
        "scope",
        "namespace",
        "root_identity_digest",
        "submission_digest",
        "held",
        "retired",
        "close_requested",
        "admitted",
        "proof_digest",
    }
    assert value["registry_execution_epoch"] == "original-registry-epoch"
    assert value["root_identity_digest"] == api().root_identity_digest(root)
    assert value["submission_digest"] == api().submission_identity_digest(
        submitted["root_admission"]["submission"]
    )
    assert (
        value["held"]
        and value["admitted"]
        and not value["retired"]
        and not value["close_requested"]
    )
    assert value["proof_digest"] == digest({k: v for k, v in value.items() if k != "proof_digest"})
    assert state.deployment_coding_validation(request) == value
    value["policy"]["deployment_id"] = "caller"
    assert vars(state) == before


def test_registry_closed_and_retired_are_fresh_positive_facts_not_missing_roots():
    wrapper, state, _, root, request = bound_registry()
    first = api().registry(state, request)
    state.close_coding_submissions(
        {k: request[k] for k in ("scope", "admission_policy", "namespace", "manifest_digest")}
    )
    closed = api().registry(state, request)
    assert closed["held"] and closed["close_requested"] and not closed["admitted"]
    retire(wrapper, root)
    retired = api().registry(state, request)
    assert retired["retired"] and not retired["held"] and not retired["admitted"]
    assert retired["root_identity_digest"] == first["root_identity_digest"]
    assert retired["submission_digest"] == first["submission_digest"]
    state.retirements.clear()
    with pytest.raises(RalfError):
        api().registry(state, request)


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "namespace",
        "policy",
        "epoch",
        "root",
        "index",
        "envelope",
        "reservation",
        "missing_root",
        "double_root",
        "tombstone",
        "publication",
        "registry_epoch",
        "extra",
    ],
)
def test_registry_refuses_changed_or_missing_original_acceptance(fault):
    _, state, _, root, request = bound_registry()
    key = digest([SCOPE, root["command_id"]])
    if fault == "scope":
        request["scope"]["principal"] = "foreign"
    elif fault == "namespace":
        request["namespace"]["id"] = "87654321-4321-8765-4321-876543218765"
    elif fault == "policy":
        request["admission_policy"]["deployment_id"] = "foreign"
    elif fault == "epoch":
        request["execution_epoch"] = "replacement"
    elif fault == "root":
        state.roots[key]["scope"]["principal"] = "foreign"
    elif fault == "index":
        state.coding_index.clear()
    elif fault == "envelope":
        state.submissions[key]["submission"]["request"]["input"] = "changed"
    elif fault == "reservation":
        state.submissions[key]["reservation"]["target"] = "changed"
    elif fault == "missing_root":
        state.roots.clear()
    elif fault == "double_root":
        state.retirements[key] = {"root": copy.deepcopy(root), "released": True, "certificate": {}}
    elif fault == "tombstone":
        state.roots.clear()
        state.retirements[key] = {"root": root, "released": False, "certificate": {}}
    elif fault == "publication":
        state.submissions[key]["submission"]["manifest"]["deployment_admission_protocol"][
            "version"
        ] = 2
    elif fault == "registry_epoch":
        del state.deployment_registry_execution_epoch
    else:
        request["caller_retired"] = True
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        api().registry(state, request)
    assert vars(state) == before


@pytest.mark.parametrize("fault", ["input", "metadata", "foreign_link", "depth"])
def test_shared_child_identity_refuses_inconsistent_original_immutable_tuple(fault):
    state = original(parent=True)
    call = add_child(state)
    if fault == "input":
        call["input"] = "changed"
    elif fault == "metadata":
        call["deployment_admission"]["lineage"][-1]["child_run_id"] = "foreign"
    elif fault == "foreign_link":
        call["request"]["coding_parent"]["parent_request_digest"] = "f" * 64
        call["child_request_digest"] = digest(call["request"])
        call["deployment_admission"]["lineage"][-1]["child_request_digest"] = digest(
            call["request"]
        )
    else:
        call["depth"] += 1
    for function in (api().child_identity, api().edge_identity_digest):
        with pytest.raises(RalfError):
            function(call)


def granted_native_phases():
    from relf_agent.coding_execution_rules import adopt, grant
    from tests.test_coding_execution_rules import intent

    native, runner, binding = intent()
    native.update(stop_needed=False, stop_active=False)
    action = {"arguments": {"task": "fix"}}
    assert grant(native, action, runner, "prepare", {}, binding)["execute"]
    phases = [copy.deepcopy(native)]
    namespace = binding["environment"]
    adopt(
        native,
        runner,
        "prepared",
        {
            "identity": namespace,
            "generation": namespace["expected_generation"],
            "container_id": "a" * 64,
        },
    )
    params = {"cwd": "/workspace", "approvalPolicy": "never", "approvalsReviewer": "user"}
    assert grant(
        native, action, runner, "thread/start", {**params, "ephemeral": False}, native["binding"]
    )["execute"]
    phases.append(copy.deepcopy(native))
    adopt(native, runner, "thread", {"thread_id": "original-thread"})
    params.update(
        threadId="original-thread", input=[{"type": "text", "text": "fix", "text_elements": []}]
    )
    assert grant(native, action, runner, "turn/start", params, native["binding"])["execute"]
    phases.append(copy.deepcopy(native))
    return phases


@pytest.mark.parametrize("phase", range(3), ids=["prepare", "thread", "turn"])
def test_native_pending_stop_is_resource_debt_not_stop_intent_or_physical_end(phase):
    from relf_agent.temporal_coding_state import stopped_action

    state = original()
    state.state = "running"
    first = api().node(state, query(state))
    native = granted_native_phases()[phase]
    assert native["pending_stop"] is True
    action = {"id": "original-action", "delegated_execution": native}
    state.actions = [action]
    after = api().node(state, query(state))
    assert after["identity_digest"] == first["identity_digest"]
    assert after["stop_requested"] is False
    assert "physical_stopped" not in after and "spent" not in after
    # Even an ended invocation plus a fence does not erase pending native debt.
    native["fenced"] = True
    state.tool_executions = {action["id"]: {"execution_stopped": True}}
    assert stopped_action(state, action) is False


@pytest.mark.parametrize(
    "intent",
    [
        "cancel",
        "stop_needed",
        "stop_active",
        "parent_stop",
        "cancelling",
        "cancelled",
        "failed",
        "succeeded",
        "seal",
    ],
)
def test_actual_stop_intents_terminal_and_seal_still_restrict_grants(intent):
    state = original(parent=intent == "parent_stop")
    state.state = "running"
    native = granted_native_phases()[0]
    native["pending_stop"] = False
    state.actions = [{"delegated_execution": native}]
    if intent == "cancel":
        native["cancel"] = {"code": "original_stop_requested"}
    elif intent in {"stop_needed", "stop_active"}:
        native[intent] = True
    elif intent == "parent_stop":
        state.composition_stop_intent = {"original": "stop"}
    elif intent == "seal":
        state.deployment_seal = {"original": "seal"}
    else:
        state.state = intent
    after = api().node(state, query(state))
    assert after["stop_requested"] is (intent != "seal")
    assert after["sealed"] is (intent == "seal")


@pytest.mark.parametrize("field", ["pending_stop", "stop_needed", "stop_active"])
def test_native_stop_facts_keep_strict_boolean_validation(field):
    state = original()
    native = granted_native_phases()[0]
    native[field] = 1
    state.actions = [{"delegated_execution": native}]
    with pytest.raises(RalfError):
        api().node(state, query(state))


def test_node_bootstrap_identity_rejects_changed_start_or_composition_static_binding():
    from relf_agent.temporal_coding_composition_state import physical_stop_view

    state = original(parent=True)
    proof = deployment.view(state)
    physical = physical_stop_view(state)
    changed_start = {**start(state), "request_digest": "f" * 64}
    with pytest.raises(RalfError):
        api().node_identity_digest(proof, changed_start, physical)
    physical["original_execution_epoch"] = "foreign"
    with pytest.raises(RalfError):
        api().node_identity_digest(proof, start(state), physical)
