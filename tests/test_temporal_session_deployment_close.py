"""Owned Session close preserves original pending/ACK debt without new roots."""

import asyncio
import copy

import pytest

from relf_agent import AgentSpec, Scope
from relf_agent.errors import CapacityExceeded, CloseIncomplete, DefinitionMismatch
from relf_agent.session_types import SessionRef
from relf_agent.temporal_session_client import TemporalSessionClient
from relf_agent.types import digest
from tests.test_temporal_deployment_session_registry import NAMESPACE, POLICY, command
from tests.test_temporal_session_deployment_client import Backend, Handle


class CloseHandle(Handle):
    async def query(self, name, value):
        if self.id in self.backend.sessions:
            session = self.backend.sessions[self.id]
            if value["kind"] == "status":
                return session.snapshot()
            if value["kind"] == "deployment_session_lifecycle":
                return session.deployment_turn(
                    {k: v for k, v in value.items() if k != "kind"}
                ).lifecycle()
        return await super().query(name, value)

    async def execute_update(self, name, value, **options):
        if self.id == self.backend.registry_id and name == "close_deployment_sessions":
            return self.backend.registry.close_deployment_sessions(value)
        return await super().execute_update(name, value, **options)


class CloseBackend(Backend):
    def get_workflow_handle(self, identity, *, run_id=None):
        return CloseHandle(self, identity, run_id)


class Runtime:
    def __init__(self, manifest):
        self.orchestration_release = copy.deepcopy(manifest)

    def validate_release(self, value=None):
        if value is not None and value != self.orchestration_release:
            raise DefinitionMismatch("Original release changed")


def fixture():
    from relf_agent import TemporalEngine

    backend = CloseBackend()
    manifest = command()["session_submission"]["binding"]["manifest"]
    runtime = Runtime(manifest)
    scope = Scope("workspace", "owner")
    engine = TemporalEngine(
        backend, task_queue="original-queue", release=manifest, scope=scope, activity_timeout=30
    )
    return runtime, backend, TemporalSessionClient(engine, NAMESPACE["id"]), scope


async def close(runtime, backend, scope):
    from relf_agent.temporal_session_deployment_close import close as close_sessions

    return await close_sessions(
        runtime, client=backend, scope=scope, task_queue="original-queue", wait_timeout=0
    )


def test_empty_original_registry_can_close_without_session_or_business_start():
    async def run():
        runtime, backend, _, scope = fixture()
        await close(runtime, backend, scope)
        assert not backend.sessions and not backend.starts and not backend.registry.roots
        assert len(backend.registry.session_closed) == 1

    asyncio.run(run())


def test_idle_zero_root_session_is_inventoried_before_receiver_can_stop():
    async def run():
        runtime, backend, api, scope = fixture()
        await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        await close(runtime, backend, scope)
        with pytest.raises(DefinitionMismatch, match="closed"):
            backend.registry.reserve(command("new-open"))
        assert len(backend.starts) == 1 and not backend.registry.roots

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["capacity-deferred", "reserve-unknown", "held-unbound"])
def test_pending_original_intent_retains_receiver_and_exact_capacity(phase):
    async def run():
        runtime, backend, api, scope = fixture()
        opened = await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        ref = SessionRef.from_dict(opened.outcome["session_ref"])
        with pytest.raises(CapacityExceeded):
            await api.submit(ref, "question", command_id="turn", budget=4)
        session = next(iter(backend.sessions.values()))
        entry = session.deployment_turn()
        if phase == "held-unbound":
            from tests.test_temporal_session_deployment_dto import origin

            intent = entry.intent
            request = {
                "scope": intent["scope"],
                "admission_policy": POLICY.identity,
                "namespace": NAMESPACE,
                "command_id": intent["run_command_id"],
                "kind": "submit",
                "target": intent["run_id"],
                "payload_digest": digest(intent["submission"]["request"]),
                "root_admission": {
                    "version": 4,
                    "manifest_digest": digest(intent["submission"]["manifest"]),
                    "submission": intent["submission"],
                    "session_origin": origin(intent),
                },
            }
            receipt = backend.registry.commit_session_root(
                request, intent, {"intent": intent, "session_origin": origin(intent)}
            )
            entry.start["reservation"] = {k: v for k, v in receipt.items() if k != "submission"}
        entry.start["phase"] = phase
        held = copy.deepcopy(backend.registry.roots)
        with pytest.raises(CloseIncomplete):
            await close(runtime, backend, scope)
        assert backend.registry.roots == held
        assert session.active is not None and len(session.records) == 1
        assert len(backend.starts) == 1 and not backend.registry.session_fences

    asyncio.run(run())


def test_retired_root_with_unended_original_observer_keeps_session_receiver():
    async def run():
        from tests.test_temporal_session_deployment_dto import call

        runtime, backend, api, scope = fixture()
        opened = await api.open(AgentSpec("ordinary", "Answer"), "chat", command_id="open")
        ref = SessionRef.from_dict(opened.outcome["session_ref"])
        with pytest.raises(CapacityExceeded):
            await api.submit(ref, "question", command_id="turn", budget=4)
        session = next(iter(backend.sessions.values()))
        entry = session.deployment_turn()
        identity = call(entry.intent)
        identity["request_digest"] = digest(entry.control_request("observe"))
        entry.begin_call(identity)
        # Positive Session publication was followed by a queued original observer.
        entry.published = True
        entry.start["phase"] = "started"
        session.active = None
        with pytest.raises(CloseIncomplete):
            await close(runtime, backend, scope)
        assert not backend.registry.roots and len(backend.registry.commands) == 2
        assert next(iter(entry.calls.values()))["end"] is None

    asyncio.run(run())
