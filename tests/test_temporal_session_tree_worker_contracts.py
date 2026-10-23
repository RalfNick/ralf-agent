"""Original SDK parent and host namespace guards, before Session data I/O."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_session_state import TemporalSessionState
from tests.test_temporal_session_tree_admission import candidate, turn
from tests.test_temporal_session_tree_sources import setup


def original():
    host, request, _ = setup()
    session = TemporalSessionState(candidate(host, request))
    request = turn(session)
    return TemporalParentState(
        session.active["run_id"],
        session.scope,
        session.active["command_id"],
        request,
        session.binding["manifest"],
    )


def test_root_lineage_cannot_drop_its_coordinator_turn():
    state = original()
    request = dict(state.request)
    request.pop("session_turn")
    request.pop("session_history")
    with pytest.raises(DefinitionMismatch):
        TemporalParentState(state.run_id, state.scope, "first", request, state.manifest)


def test_sdk_checks_direct_parent_for_tree_members():
    pytest.importorskip("temporalio")
    from temporalio.exceptions import ApplicationError

    from relf_agent.temporal_workflow import TemporalRunWorkflow

    state = original()
    # Root read is not needed for the relationship check: use a minimal original link.
    child = SimpleNamespace(
        request={"session_lineage": {"links": [{"parent_run_id": state.run_id}]}}
    )
    owner = SimpleNamespace(state=child)
    with pytest.raises(ApplicationError):
        TemporalRunWorkflow._check_session_parent(
            owner, SimpleNamespace(parent=SimpleNamespace(workflow_id="other"))
        )
    TemporalRunWorkflow._check_session_parent(
        owner, SimpleNamespace(parent=SimpleNamespace(workflow_id=state.run_id))
    )


def test_actual_namespace_guard_rejects_before_root_data_dispatch():
    from relf_agent.temporal_session_activities import validate_tree_activity

    state = original()
    _, request = state.next_session_operation()

    class Service:
        async def describe_namespace(self, value):
            return SimpleNamespace(namespace_info=SimpleNamespace(id="different-namespace"))

    client = SimpleNamespace(namespace="default", workflow_service=Service())
    with pytest.raises(DefinitionMismatch):
        asyncio.run(validate_tree_activity(client, request, workflow_id=state.run_id))
