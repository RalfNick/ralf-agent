"""Pure binding metadata preserves a Coordinator queue across idle rebind."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, TemporalProfile, TemporalProfileCatalog, TemporalRuntimeBuilder
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_state import SESSION_WORKFLOW, TemporalSessionState, workflow_id
from relf_agent.types import submission_request

from .test_temporal_profile_host import sdk as sdk_fixture

sdk = sdk_fixture


def profiles():
    result = TemporalProfileCatalog()
    for version in ("1", "2"):
        result.register(
            TemporalProfile(
                "sessions",
                version,
                {"default": {"adapter": "offline-echo"}},
                execution={"enable_sessions": True},
            ),
            default=version == "1",
        )
    return result


def test_profile_binding_query_is_scoped_detached_and_has_no_state_effect():
    pytest.importorskip("temporalio")
    from relf_agent import ToolRegistry
    from relf_agent.runtime_builder import EchoProvider
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_session_workflow import TemporalSessionWorkflow

    runtime = TemporalRuntime(
        providers={"default": EchoProvider("query")}, tools=ToolRegistry(), enable_sessions=True
    )
    accepted = {
        "scope": {"workspace": "local", "principal": "owner"},
        "namespace_id": "uuid",
        "session_namespace": None,
        "session_id": "wire",
        "command_id": "open",
        "request": submission_request(AgentSpec("a", "Answer"), None),
        "manifest": runtime.manifest,
        "task_queue": "original-queue",
        "activity_timeout": 10,
    }
    workflow = TemporalSessionWorkflow(accepted)
    state = workflow.state
    before = copy.deepcopy(state.__dict__)
    denied = workflow.view(
        {"scope": {"workspace": "other", "principal": "owner"}, "kind": "profile_binding"}
    )
    assert denied == {"error": "authorization_denied"}
    value = workflow.view({"scope": state.scope, "kind": "profile_binding"})
    assert value == state.profile_binding()
    value["session_ref"]["binding_revision"] = 99
    assert state.__dict__ == before


@pytest.mark.parametrize("rebind", [False, True])
def test_session_attach_uses_current_binding_on_original_coordinator_queue(tmp_path, sdk, rebind):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(profiles())
        await host.start_workers(sdk.client)
        try:
            first, second = [host.runtime(p.identity) for p in host.profiles]
            state = TemporalSessionState(
                {
                    "scope": asdict(host.scope),
                    "namespace_id": "namespace-uuid",
                    "session_namespace": None,
                    "session_id": "chat",
                    "command_id": "open",
                    "request": submission_request(AgentSpec("a", "Answer"), None),
                    "manifest": first.engine.release,
                    "task_queue": first.engine.task_queue,
                    "activity_timeout": 10,
                }
            )
            original_ref = state.ref
            identity = workflow_id(state.key)
            if rebind:
                receipt = state.command(
                    {
                        "scope": state.scope,
                        "kind": "rebind",
                        "command_id": "rebind",
                        "session_ref": original_ref.to_dict(),
                        "expected_binding_revision": 1,
                        "binding": {
                            "request": state.binding["request"],
                            "manifest": second.engine.release,
                            "task_queue": second.engine.task_queue,
                            "activity_timeout": 10,
                        },
                    }
                )
                assert receipt["apply_state"] == "applied"
            sdk.client.descriptions[identity] = SimpleNamespace(
                id=identity,
                namespace=sdk.client.namespace,
                workflow_type=SESSION_WORKFLOW,
                task_queue=first.engine.task_queue,
                run_id="coordinator-uuid",
            )
            sdk.client.queries[identity] = {
                "profile_binding": state.profile_binding(),
                "status": state.snapshot(),
            }
            host.select_default(host.profiles[1].identity)
            attached = await host.aattach_session(state.ref)
            assert attached.ref == state.ref
            assert attached.runtime.engine.release["runtime_profile"]["version"] == (
                "2" if rebind else "1"
            )
            assert state.profile_binding()["task_queue"] == (
                second.engine.task_queue if rebind else first.engine.task_queue
            )
            if rebind:
                with pytest.raises(DefinitionMismatch):
                    await host.aattach_session(original_ref)
        finally:
            await host.aclose()

    asyncio.run(run())
