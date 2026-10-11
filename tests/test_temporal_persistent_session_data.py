from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    InMemoryMemory,
    Scope,
    SQLiteMemory,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.errors import ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_session_state import TemporalSessionState
from ralf_agent.types import submission_request

from .test_temporal_facts import Provider


def accepted(runtime, spec=None, namespace=None):
    return {
        "scope": asdict(Scope()),
        "namespace_id": "actual-namespace-uuid",
        "session_id": "s",
        "session_namespace": namespace,
        "command_id": "open",
        "request": normalize_request(submission_request(spec or AgentSpec("a", "Answer"), None)),
        "manifest": runtime.manifest,
        "task_queue": "q",
        "activity_timeout": 3,
    }


def runtime(source, **options):
    return TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        session_store=source,
        session_writes=True,
        enable_sessions=True,
        **options,
    )


def test_external_persistent_session_has_physical_dataset_identity():
    first = TemporalSessionState(accepted(runtime(InMemoryMemory(backend_id="same"))))
    second = TemporalSessionState(accepted(runtime(InMemoryMemory(backend_id="same"))))
    assert first.key.resource_id != second.key.resource_id
    assert first.ref.coordination_ref != second.ref.coordination_ref


def test_sqlite_dataset_identity_survives_reopen_and_alias(tmp_path):
    path = tmp_path / "data.sqlite"
    one = SQLiteMemory(path)
    try:
        first = TemporalSessionState(accepted(runtime(one))).key
    finally:
        one.store.close()
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(path)
    two = SQLiteMemory(alias)
    try:
        second = TemporalSessionState(accepted(runtime(two))).key
    finally:
        two.store.close()
    assert first == second


def test_sqlite_dataset_replacement_is_refused_before_model(tmp_path):
    import asyncio
    import uuid

    from ralf_agent.errors import DefinitionMismatch

    source = SQLiteMemory(tmp_path / "data.sqlite")
    execution = runtime(source)
    try:
        with source.store.transaction():
            source.store.conn.execute(
                "UPDATE memory_session_resource SET dataset_id=?", (uuid.uuid4().hex,)
            )
        with pytest.raises(DefinitionMismatch):
            execution.validate_release()
    finally:
        asyncio.run(execution.close_session_execution())
        source.store.close()


def test_sequence_cannot_mix_disabled_and_persistent_sources():
    spec = BoundDefinition(
        WorkflowSpec("s", [AgentSpec("a", "Answer"), AgentSpec("b", "Answer")]),
        {"sequence/steps/1": AgentBindingDescriptor(session=BindingSelection.disabled())},
    )
    with pytest.raises(ValidationError, match="same"):
        TemporalSessionState(accepted(runtime(InMemoryMemory()), spec))


def test_idle_rebind_can_change_definition_but_cannot_migrate_dataset():
    from ralf_agent.errors import DefinitionMismatch

    source = InMemoryMemory()
    session = TemporalSessionState(accepted(runtime(source)))
    binding = {
        k: accepted(runtime(source), AgentSpec("b", "New instructions"))[k]
        for k in ("request", "manifest", "task_queue", "activity_timeout")
    }
    receipt = session.command(
        {
            "kind": "rebind",
            "scope": session.scope,
            "command_id": "rebind",
            "session_ref": session.ref.to_dict(),
            "expected_binding_revision": 1,
            "binding": binding,
        }
    )
    assert receipt["apply_state"] == "applied" and session.binding_revision == 2
    other = accepted(runtime(InMemoryMemory()))
    other_binding = {k: other[k] for k in ("request", "manifest", "task_queue", "activity_timeout")}
    with pytest.raises(DefinitionMismatch, match="migrate"):
        session.command(
            {
                "kind": "rebind",
                "scope": session.scope,
                "command_id": "migrate",
                "session_ref": session.ref.to_dict(),
                "expected_binding_revision": 2,
                "binding": other_binding,
            }
        )
    from ralf_agent.types import digest

    assert session.binding_revision == 2 and digest(session.binding) == digest(binding)


def test_native_turn_reads_stable_root_address_across_runs():
    from ralf_agent.temporal_session_data_state import expected_read

    state = TemporalSessionState(accepted(runtime(InMemoryMemory())))
    ref = state.ref
    from ralf_agent.temporal_bindings import effective_manifest

    manifest = effective_manifest(state.binding["manifest"], AgentBindingDescriptor().to_dict())
    reads = []
    for command in ("first", "second"):
        receipt = state.command(
            {
                "kind": "submit",
                "scope": state.scope,
                "command_id": command,
                "session_ref": ref.to_dict(),
                "input": "task",
                "budget": 32,
            }
        )
        request = state.active["request"]
        reads.append(
            expected_read(
                manifest,
                {
                    "scope": state.scope,
                    "run_id": receipt["outcome"]["turn"]["run"]["run_id"],
                    "step": request["definition"]["steps"][0],
                    "session_data_node": 0,
                    **{k: request[k] for k in ("session_turn", "session_history")},
                },
            )["address"]
        )
        state.active = None  # This test isolates accepted identity from completion proof.
    assert reads[0] == reads[1] == state.key.storage_key


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("sequence", [False, True])
def test_complete_native_turns_save_and_recall_external_data_once(managed, sequence):
    import asyncio

    from ralf_agent.temporal_state import TemporalRunState

    from .test_temporal_memory_bindings import grant

    async def run():
        source = InMemoryMemory()
        options = {}
        if managed:
            from ralf_agent import InMemoryArtifactStore

            from .test_managed_data_context import context

            options["context_builder"] = context(InMemoryArtifactStore())
        execution = runtime(source, **options)
        spec = (
            WorkflowSpec("s", [AgentSpec("a", "Answer"), AgentSpec("b", "Answer")])
            if sequence
            else AgentSpec("a", "Answer")
        )
        session = TemporalSessionState(accepted(execution, spec))
        steps = 2 if sequence else 1
        for turn_index, command in enumerate(("first", "second")):
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
            intent = session.active
            run = TemporalRunState(
                intent["run_id"],
                session.scope,
                intent["command_id"],
                intent["request"],
                intent["manifest"],
                "original-" + command,
            )
            for _ in range(32):
                operation = run.next_operation()
                if operation is None:
                    break
                action, request = operation
                if action["kind"] == "context":
                    run.accept_context(action["id"], await execution.prepare_context(request))
                elif action["kind"] == "model":
                    run.accept_model(
                        action["id"],
                        await execution.complete_model(
                            request, dispatch_guard=lambda r, original=run: grant(original, r)
                        ),
                    )
                elif action["kind"] == "managed_context":
                    run.accept_managed_context(
                        action["id"],
                        await execution.manage_context(
                            request, dispatch_guard=lambda r, original=run: grant(original, r)
                        ),
                    )
                else:
                    run.accept_session(
                        action["id"],
                        await execution.manage_session(
                            request, dispatch_guard=lambda r, original=run: grant(original, r)
                        ),
                    )
            assert run.state == "succeeded", run.snapshot()
            assert run.context_snapshot["session_references"] == []
            assert len(run.context_snapshot["session_data"]["page"]["items"]) == (
                (turn_index + 1) * steps - 1
            )
            assert session.adopt_observation(
                {"scope": session.scope, "request": run.request, **run.diagnostics()}
            )
        assert source.read(Scope(), session.key.storage_key)[0] == 2 * steps
        assert not session.snapshot()["busy"] and len(session.history) == 4
        await execution.close_session_execution()

    asyncio.run(run())
