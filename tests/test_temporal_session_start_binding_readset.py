"""Coding4 aggregates original Session reads around a read-only start binding."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import temporal_deployment_execution as execution
from ralf_agent.errors import DefinitionMismatch
from tests.test_temporal_coding_aggregate_readset import environment


def test_coding_start_binding_retains_one_complete_terminal_session_readset(monkeypatch):
    async def run():
        runtime, client, session, _, _ = environment(monkeypatch)
        # The existing fixture returns the original pure Run proof. The start
        # binding and all seven coordinator SDK fact reads below remain real.
        proof = await execution._proof()
        root = proof["admission"]["root"]
        await execution._public_start_binding(
            client,
            proof["manifest"]["deployment_admission_protocol"]["policy"],
            proof,
            client.descriptions["root"],
            runtime=runtime,
        )
        assert client.session_root_reads == 1
        assert root["run_id"] == proof["run_id"]
        assert session.events == [
            "describe",
            "deployment_session_intent",
            "deployment_session_command",
            "history",
            "describe",
        ]
        assert client.namespace_reads == 3  # Intermediate namespace + terminal pair.

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["namespace", "runtime", "reset", "intent", "reader", "cancel"])
def test_changed_original_facts_in_intermediate_start_read_never_return_binding(monkeypatch, fault):
    from tests.test_temporal_deployment_coding_validation import Handle

    async def run():
        runtime, client, session, _, _ = environment(monkeypatch)
        proof = await execution._proof()
        query = Handle.query
        entered, accepted = [], []

        async def changed(handle, name, selector):
            if selector["kind"] == "deployment_start":
                entered.append(True)
                if fault == "namespace":
                    client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
                elif fault == "runtime":
                    runtime.changed = True
                elif fault == "reset":
                    session.epoch = "replacement-coordinator-epoch"
                elif fault == "intent":
                    session.intent["session_command_id"] = "replaced-original-command"
                elif fault == "reader":
                    raise RuntimeError("Original start SDK read failed")
                else:
                    raise asyncio.CancelledError("Original start SDK read cancelled")
            return await query(handle, name, selector)

        monkeypatch.setattr(Handle, "query", changed)
        with pytest.raises((DefinitionMismatch, RuntimeError, asyncio.CancelledError)):
            await execution._public_start_binding(
                client,
                proof["manifest"]["deployment_admission_protocol"]["policy"],
                proof,
                client.descriptions["root"],
                runtime=runtime,
            )
            accepted.append(True)
        assert entered == [True] and not accepted

    asyncio.run(run())


def test_ordinary_session_four_keeps_both_complete_origin_readsets():
    from ralf_agent import temporal_deployment_execution_state as pure
    from tests.test_temporal_session_deployment_control import Client, Runtime
    from tests.test_temporal_session_deployment_dto import origin, reservation
    from tests.test_temporal_session_deployment_execution import (
        coordinator,
        initialize,
        original,
    )

    async def run():
        intent, metadata, state = original()
        initialize(state, metadata, coordinator(intent))
        proof = pure.view(state)
        client = Client(
            {
                "intent": intent,
                "namespace": intent["namespace"],
                "coordinator_execution_epoch": intent["coordinator_execution_epoch"],
            }
        )
        runtime = Runtime(intent["binding"]["manifest"])
        original_handle = client.get_workflow_handle
        record = {
            "reservation": reservation(intent),
            "submission": intent["submission"],
            "run_receipt": None,
            "execution_epoch": state.epoch,
            "intent": intent,
            "session_origin": origin(intent),
        }
        start = {
            **{
                key: proof[key]
                for key in (
                    "scope",
                    "run_id",
                    "execution_epoch",
                    "request_digest",
                    "manifest_digest",
                )
            },
            **{key: intent["submission"][key] for key in ("activity_timeout", "task_queue")},
        }

        async def query(name, selector):
            assert name == "view"
            if selector["kind"] == "deployment_session_root":
                return copy.deepcopy(record)
            assert selector["kind"] == "deployment_start"
            return copy.deepcopy(start)

        def handle(identity, **options):
            if identity in (metadata["root"]["registry_id"], state.run_id):
                return SimpleNamespace(query=query)
            return original_handle(identity, **options)

        client.get_workflow_handle = handle
        await execution._public_start_binding(
            client,
            state.manifest["deployment_admission_protocol"]["policy"],
            proof,
            SimpleNamespace(task_queue=intent["submission"]["task_queue"]),
            runtime=runtime,
        )
        facts = [
            "namespace",
            "describe",
            "history",
            "deployment_session_intent",
            "deployment_session_command",
            "describe",
            "namespace",
        ]
        assert client.events == facts + ["namespace"] + facts

    asyncio.run(run())
