"""Original native members retain private identity and root provenance."""

import copy

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_data_state import expected_read
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import digest

from .test_temporal_parent_session import parent, prepare_read


def child():
    owner, session, root_store = parent()
    prepare_read(owner, session, root_store)
    owner.accept_selection(
        {
            "calls": [{"id": "writer", "member": "writer", "input": "task"}],
            "done": False,
            "result": None,
        }
    )
    call = owner.next_calls()[0]
    state = TemporalRunState(
        call["run_id"], owner.scope, call["command_id"], call["request"], owner.manifest
    )
    return state, owner, session


def test_native_member_reads_private_address_and_preserves_original_root_snapshot():
    state, owner, session = child()
    action, request = state.next_operation()
    assert action["kind"] == "context"
    expected = expected_read(state.step_manifest, request)
    assert expected["address"].startswith('ralf-session-v1:["write","ralf-temporal-member-v1:')
    assert expected["address"] != session.key.storage_key
    assert request["session_root_snapshot"] == owner.root_session_snapshot
    assert request["session_lineage"] == state.request["session_lineage"]


def test_missing_root_snapshot_is_rejected_before_native_member_model_or_data():
    state, owner, _ = child()
    request = copy.deepcopy(state.request)
    del request["session_root_snapshot"]
    with pytest.raises(DefinitionMismatch):
        TemporalRunState(state.run_id, owner.scope, "new", request, owner.manifest)


@pytest.mark.parametrize("damage", ["coordinator", "root-source", "member", "scope"])
def test_forged_native_member_lineage_is_refused_before_model_or_data(damage):
    state, owner, _ = child()
    request = copy.deepcopy(state.request)
    if damage == "coordinator":
        request["session_observer"]["coordinator_id"] = "ralf-temporal-session-" + "0" * 64
    elif damage == "root-source":
        request["session_root_snapshot"]["session_data"]["address"] = "foreign"
    elif damage == "member":
        request["session_lineage"]["links"][-1]["member"] = "reader"
    else:
        request["session_lineage"]["root_turn"]["session_ref"]["key"]["principal"] = "foreign"
    from relf_agent.errors import AuthorizationDenied, ValidationError

    with pytest.raises((DefinitionMismatch, AuthorizationDenied, ValidationError)):
        TemporalRunState(state.run_id, owner.scope, "new", request, owner.manifest)


def test_external_root_projection_is_once_and_distinct_from_private_session():
    from relf_agent.temporal_session_state import context_evidence

    state, owner, _ = child()
    source = copy.deepcopy(owner.root_session_snapshot)
    # A real, bounded root record is accepted separately by the original Parent
    # in later tests. Here the empty first snapshot still has protected provenance.
    evidence = context_evidence(state.request)
    assert evidence["session_projection"]["root_snapshot_digest"] == digest(source)
    assert evidence["session_projection"]["lineage_digest"] == digest(
        state.request["session_lineage"]
    )
    assert evidence["session_references"] == []
    state.request["session_history"] = [
        {"role": "user", "content": "same root"},
        {"role": "assistant", "content": "same root answer"},
    ]
    projected = context_evidence(state.request)
    assert projected["session_references"] == []  # External root is sourced only once.


def test_private_save_request_keeps_accepted_lineage_and_root_snapshot():
    from relf_agent.temporal_session_save_state import prepare

    state, _, _ = child()
    action, request = state.next_operation()
    expected = expected_read(state.step_manifest, request)
    from dataclasses import asdict

    from relf_agent import InMemoryMemory, Scope
    from relf_agent.recall import RecallQuery
    from relf_agent.temporal_session_data_state import references

    page = InMemoryMemory().read_page(
        Scope(), expected["address"], RecallQuery(**expected["query"])
    )
    source = {**expected, "page": asdict(page), "revision": 0}
    from relf_agent.temporal_session_state import context_evidence

    state.accept_context(
        action["id"],
        {
            "ok": True,
            "messages": request["messages"],
            "references": [],
            "context_identity": {},
            **context_evidence(state.request),
            "session_data": source,
            "session_data_references": references(source),
        },
    )
    model, _ = state.next_operation()
    state._settle(model)
    model.update(
        status="completed", response={"ok": True, "output": "answer", "tool_calls": [], "usage": {}}
    )
    assert prepare(state, "answer")
    _, save = state.next_operation()
    assert save["session_lineage"] == state.request["session_lineage"]
    assert save["session_root_snapshot"] == state.request["session_root_snapshot"]
    assert save["intent"]["address"] == expected["address"]


def test_managed_context_plan_keeps_the_same_private_and_root_evidence_fields():
    from relf_agent import ManagedContextPipeline, Scope, ToolRegistry
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_parent_state import TemporalParentState
    from relf_agent.temporal_session_state import TemporalSessionState

    from .test_temporal_session_tree_admission import candidate, turn
    from .test_temporal_session_tree_sources import setup

    original, root_request, stores = setup()
    host = TemporalRuntime(
        providers=original.providers,
        tools=ToolRegistry(),
        context_builder=ManagedContextPipeline(),
        binding_catalog=original.binding_catalog,
        session_store=original.session_store,
        enable_sessions=True,
        session_writes=True,
    )
    session = TemporalSessionState(candidate(host, root_request))
    turn(session)
    accepted = session.active
    owner = TemporalParentState(
        accepted["run_id"],
        session.scope,
        accepted["command_id"],
        accepted["request"],
        accepted["manifest"],
    )
    prepare_read(owner, session, stores[0])
    owner.accept_selection(
        {
            "calls": [{"id": "writer", "member": "writer", "input": "task"}],
            "done": False,
            "result": None,
        }
    )
    call = owner.next_calls()[0]
    state = TemporalRunState(
        call["run_id"], session.scope, call["command_id"], call["request"], owner.manifest
    )
    action, request = state.next_operation()
    assert action["kind"] == "managed_context" and request["phase"] == "plan"
    assert request["session_root_snapshot"] == owner.root_session_snapshot
    assert request["session_lineage"] == state.request["session_lineage"]
    read = expected_read(state.step_manifest, request)
    assert read["address"] != session.key.storage_key
    assert read["address"].startswith('ralf-session-v1:["write","ralf-temporal-member-v1:')
    assert stores[1].read(Scope(), read["address"])[0] == 0


def test_two_original_turns_recall_separate_root_and_private_records_without_aliasing():
    import json
    from dataclasses import asdict

    from relf_agent import Scope
    from relf_agent.recall import RecallQuery
    from relf_agent.temporal_parent_state import TemporalParentState
    from relf_agent.temporal_session_data_state import references
    from relf_agent.temporal_session_state import TemporalSessionState, context_evidence

    from .test_temporal_parent_session import apply_save
    from .test_temporal_session_tree_admission import candidate
    from .test_temporal_session_tree_sources import setup

    host, root_request, stores = setup()
    session = TemporalSessionState(candidate(host, root_request))
    addresses = []
    for index, command in enumerate(("first", "second")):
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": command,
                "session_ref": session.ref.to_dict(),
                "input": command,
                "budget": 32,
            }
        )
        accepted = session.active
        owner = TemporalParentState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        root_action, root_read = owner.next_session_operation()
        root_expected = expected_read(owner.manifest, root_read)
        page = stores[0].read_page(
            Scope(), root_expected["address"], RecallQuery(**root_expected["query"])
        )
        root_source = {
            **root_expected,
            "page": asdict(page),
            "revision": json.loads(page.snapshot_id)["revision"],
        }
        owner.accept_session_root(
            root_action["id"],
            {
                "ok": True,
                "session_data": root_source,
                "session_data_references": references(root_source),
            },
        )
        owner.accept_selection(
            {
                "calls": [{"id": "writer", "member": "writer", "input": command}],
                "done": False,
                "result": None,
            }
        )
        call = owner.next_calls()[0]
        owner.children[0]["dispatch_started"] = True
        owner.mark_started(call["run_id"])
        state = TemporalRunState(
            call["run_id"], session.scope, call["command_id"], call["request"], owner.manifest
        )
        action, request = state.next_operation()
        expected = expected_read(state.step_manifest, request)
        addresses.append(expected["address"])
        page = stores[1].read_page(Scope(), expected["address"], RecallQuery(**expected["query"]))
        source = {
            **expected,
            "page": asdict(page),
            "revision": json.loads(page.snapshot_id)["revision"],
        }
        assert len(page.items) == index
        evidence = context_evidence(state.request)
        assert len(evidence["session_references"]) == index
        if index:
            assert evidence["session_references"][0]["key"].startswith("session:root-data:")
            assert references(source)[0]["key"].startswith("session:data:")
        state.accept_context(
            action["id"],
            {
                "ok": True,
                "messages": request["messages"],
                "references": [],
                "context_identity": {},
                **evidence,
                "session_data": source,
                "session_data_references": references(source),
            },
        )
        model, _ = state.next_operation()
        state.accept_model(
            model["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}}
        )
        for _ in range(4):
            action, request = state.next_operation()
            intent, phase = request["intent"], request["phase"]
            if phase in {"inspect", "verify"}:
                response = {
                    "ok": True,
                    "dispatched": False,
                    "inspection": stores[1].inspect_message(
                        Scope(), intent["address"], intent["message_id"]
                    ),
                }
            elif phase == "session-write":
                state.admit_context_dispatch(
                    {
                        "scope": state.scope,
                        "action_id": action["id"],
                        "release_digest": state.release_digest,
                        "phase": phase,
                        "request_digest": digest(request),
                    }
                )
                response = {
                    "ok": True,
                    "dispatched": True,
                    "execution_stopped": True,
                    "revision": stores[1].append(
                        Scope(),
                        intent["address"],
                        intent["message"],
                        expected_revision=intent["expected_revision"],
                        message_id=intent["message_id"],
                    ),
                }
            else:
                assert phase == "adopt"
                response = {"ok": True, "dispatched": False, "intent_digest": digest(intent)}
            state.accept_session(action["id"], response)
        assert state.state == "succeeded" and state.quiescent
        proof = {"scope": session.scope, "request": state.request, **state.diagnostics()}
        owner.observe(call["run_id"], proof)
        owner.accept_selection({"calls": [], "done": True, "result": "answer"})
        for _ in range(4):
            apply_save(owner, stores[0])
        assert owner.state == "succeeded" and owner.budget["spent"] == 3
        assert session.adopt_observation(
            {
                "scope": session.scope,
                "request": owner.request,
                **owner.diagnostics(),
                "descendants": [proof],
            }
        )
    assert addresses[0] == addresses[1] != session.key.storage_key
    assert stores[0].read(Scope(), session.key.storage_key)[0] == 2
    assert stores[1].read(Scope(), addresses[0])[0] == 2
    assert stores[2].read(Scope(), addresses[0])[0] == 0


def test_dropping_legacy_observer_fields_cannot_bypass_member_lineage_validation():
    state, owner, _ = child()
    request = copy.deepcopy(state.request)
    del request["session_history"]
    del request["session_observer"]
    from relf_agent.errors import ValidationError

    with pytest.raises((DefinitionMismatch, ValidationError)):
        TemporalRunState(state.run_id, owner.scope, "dropped", request, owner.manifest)


def test_model_request_keeps_the_original_adopted_private_snapshot():
    from dataclasses import asdict

    from relf_agent import InMemoryMemory, Scope
    from relf_agent.recall import RecallQuery
    from relf_agent.temporal_session_data_state import references
    from relf_agent.temporal_session_state import context_evidence

    state, _, _ = child()
    action, request = state.next_operation()
    expected = expected_read(state.step_manifest, request)
    page = InMemoryMemory().read_page(
        Scope(), expected["address"], RecallQuery(**expected["query"])
    )
    evidence = {**expected, "page": asdict(page), "revision": 0}
    state.accept_context(
        action["id"],
        {
            "ok": True,
            "messages": request["messages"],
            "references": [],
            "context_identity": {},
            **context_evidence(state.request),
            "session_data": evidence,
            "session_data_references": references(evidence),
        },
    )
    _, model = state.next_operation()
    assert model["session_private_snapshot"] == {
        "session_data": evidence,
        "session_data_references": references(evidence),
    }


def test_adopted_private_snapshot_survives_restore_and_refuses_new_revision():
    import json
    from dataclasses import asdict

    from relf_agent import InMemoryMemory, Scope
    from relf_agent.recall import RecallQuery
    from relf_agent.temporal_session_data_state import references, validate_snapshot
    from relf_agent.temporal_session_tree_reads import adopt, request_fields

    state, _, _ = child()
    _, request = state.next_operation()
    expected = expected_read(state.step_manifest, request)
    page = InMemoryMemory().read_page(
        Scope(), expected["address"], RecallQuery(**expected["query"])
    )
    source = {**expected, "page": asdict(page), "revision": 0}
    evidence = {"session_data": source, "session_data_references": references(source)}
    adopt(state, evidence)
    restored = copy.deepcopy(state)
    protected = {**request, **request_fields(restored)}
    assert protected["session_private_snapshot"] == evidence
    fresh = copy.deepcopy(evidence)
    fresh["session_data"]["revision"] = 1
    snapshot = json.loads(fresh["session_data"]["page"]["snapshot_id"])
    snapshot["revision"] = 1
    fresh["session_data"]["page"]["snapshot_id"] = json.dumps(snapshot)
    # The replacement is otherwise a valid page for the same source and address.
    validate_snapshot(fresh, state.step_manifest, request)
    with pytest.raises(DefinitionMismatch, match="original private snapshot"):
        validate_snapshot(fresh, state.step_manifest, protected)
    with pytest.raises(DefinitionMismatch):
        adopt(restored, fresh)
    assert restored.session_private_snapshots == state.session_private_snapshots
