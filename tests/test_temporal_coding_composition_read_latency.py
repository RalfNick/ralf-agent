"""Concurrent same-walk reads retain original identity and fresh authority."""

import asyncio

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import digest
from tests.test_temporal_coding_composition_control import NAMESPACE, Handle, linked_client

MANIFEST = {
    "kernel": "temporal-3",
    "binding_protocol": 23,
    "coding_composition_protocol": {"version": 7},
}


def environment(monkeypatch, *, barrier=False):
    from ralf_agent import temporal_session_activities

    client, leaf_id = linked_client()
    client.children[0]["planning_revision"] = 0
    parent = client.proofs["root"]
    parent["manifest"] = MANIFEST
    parent["release_digest"] = digest(
        {"definition": parent["request"]["definition"], "manifest": MANIFEST}
    )
    client.proofs[leaf_id]["request"]["coding_parent"]["parent_release_digest"] = parent[
        "release_digest"
    ]
    client.children[0]["child_request_digest"] = digest(client.proofs[leaf_id]["request"])
    for proof in client.proofs.values():
        proof["manifest"] = MANIFEST
        proof["request_digest"] = digest(proof["request"])
        proof["release_digest"] = digest(
            {"definition": proof["request"]["definition"], "manifest": MANIFEST}
        )
        proof["proof_digest"] = digest(
            {key: value for key, value in proof.items() if key != "proof_digest"}
        )
    client.children[0]["child_execution"] = {
        "namespace": NAMESPACE,
        "execution_epoch": "child-epoch",
        "original_execution_epoch": "child-epoch",
    }
    client.namespace_uuid = NAMESPACE["id"]
    client.read_events, client.arrivals, client.namespace_reads = [], set(), 0
    client.ready = asyncio.Event()

    class ParallelHandle(Handle):
        async def query(self, name, request):
            if self.run_id == "root" and request["kind"] in {
                "coding_composition_proof",
                "coding_composition_children",
            }:
                client.read_events.append(("start", request["kind"]))
                client.arrivals.add(request["kind"])
                if len(client.arrivals) == 2:
                    client.ready.set()
                if barrier:
                    await asyncio.wait_for(client.ready.wait(), 0.1)
                result = await super().query(name, request)
                client.read_events.append(("end", request["kind"]))
                return result
            return await super().query(name, request)

    client.get_workflow_handle = lambda workflow_id, **options: ParallelHandle(
        client, workflow_id, options.get("run_id")
    )

    async def namespace_id(original):
        assert original is client
        client.namespace_reads += 1
        client.read_events.append(("namespace", client.namespace_uuid))
        return client.namespace_uuid

    monkeypatch.setattr(temporal_session_activities, "namespace_id", namespace_id)
    return client, leaf_id


def test_parent_proof_and_children_start_concurrently_then_namespace_is_checked(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch, barrier=True)
        chain = await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert len(chain) == 1
        assert client.namespace_reads == 1
        assert client.read_events[-1][0] == "namespace"
        assert client.read_events[:2] == [
            ("start", "coding_composition_proof"),
            ("start", "coding_composition_children"),
        ]
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["namespace", "parent-epoch", "children-shape", "call-id", "request", "child-epoch"]
)
def test_same_walk_parallel_reads_reject_changed_namespace_epoch_or_intent(monkeypatch, fault):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        if fault == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif fault == "parent-epoch":
            client.proofs["root"]["execution_epoch"] = "changed"
            client.proofs["root"]["proof_digest"] = digest(
                {
                    key: value
                    for key, value in client.proofs["root"].items()
                    if key != "proof_digest"
                }
            )
        elif fault == "children-shape":
            client.children = {"caller_claim": "no-child"}
        elif fault == "call-id":
            client.children[0]["id"] = "changed"
        elif fault == "request":
            client.children[0]["request"] = {**client.children[0]["request"], "input": "changed"}
        elif fault == "child-epoch":
            client.children[0]["child_execution"]["execution_epoch"] = "changed"
        with pytest.raises(DefinitionMismatch):
            await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert not any(call[0] == "update" for call in client.calls)

    asyncio.run(run())


def test_parent_cancellation_is_read_fresh_on_every_walk(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        first = await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert first[0][0]["state"] == "running"
        parent = client.proofs["root"]
        parent["state"] = "cancelling"
        parent["proof_digest"] = digest(
            {key: value for key, value in parent.items() if key != "proof_digest"}
        )
        second = await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert second[0][0]["state"] == "cancelling"
        assert client.namespace_reads == 2

    asyncio.run(run())


def test_missing_child_pin_keeps_before_after_update_checks_and_original_reread(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        client.children[0]["child_execution"] = None
        result = await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert result[0][1]["child_execution"]["execution_epoch"] == "child-epoch"
        updates = [i for i, call in enumerate(client.calls) if call[0] == "update"]
        assert len(updates) == 1 and client.calls[updates[0]][3] == "coding_composition_child_epoch"
        assert any(
            call[0] == "query" and call[3]["kind"] == "coding_composition_children"
            for call in client.calls[updates[0] + 1 :]
        )
        assert client.namespace_reads >= 4

    asyncio.run(run())


def test_read_failure_waits_for_sibling_before_propagating_original_exception(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        original = client.get_workflow_handle
        started, finish = asyncio.Event(), asyncio.Event()
        failure = RuntimeError("original SDK proof query failed")

        class FaultHandle:
            def __init__(self, handle):
                self.handle = handle

            async def query(self, name, request):
                if request["kind"] == "coding_composition_proof":
                    raise failure
                started.set()
                await finish.wait()
                return await self.handle.query(name, request)

        client.get_workflow_handle = lambda *args, **kwargs: FaultHandle(original(*args, **kwargs))
        task = asyncio.create_task(
            control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        )
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        was_pending = not task.done()
        finish.set()
        with pytest.raises(RuntimeError) as caught:
            await task
        assert caught.value is failure
        assert was_pending, "The verifier ended while its sibling SDK read was still alive"
        assert client.namespace_reads == 0

    asyncio.run(run())


def test_namespace_drift_during_child_read_is_checked_after_both_reads(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        original = client.get_workflow_handle

        class DriftingHandle:
            def __init__(self, handle):
                self.handle = handle

            async def query(self, name, request):
                value = await self.handle.query(name, request)
                if request["kind"] == "coding_composition_children":
                    client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
                return value

        client.get_workflow_handle = lambda *args, **kwargs: DriftingHandle(
            original(*args, **kwargs)
        )
        with pytest.raises(DefinitionMismatch):
            await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert client.namespace_reads == 1

    asyncio.run(run())


def test_epoch_adoption_still_checks_namespace_after_mutating_await(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as control

    async def run():
        client, leaf = environment(monkeypatch)
        client.children[0]["child_execution"] = None
        original = client.get_workflow_handle

        class DriftingHandle:
            def __init__(self, handle):
                self.handle = handle

            def __getattr__(self, name):
                return getattr(self.handle, name)

            async def execute_update(self, name, value, **options):
                result = await self.handle.execute_update(name, value, **options)
                client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
                return result

        client.get_workflow_handle = lambda *args, **kwargs: DriftingHandle(
            original(*args, **kwargs)
        )
        with pytest.raises(DefinitionMismatch):
            await control._ancestry(client, client.proofs[leaf], MANIFEST, NAMESPACE)
        assert len([call for call in client.calls if call[0] == "update"]) == 1
        assert client.read_events[-1] == ("namespace", client.namespace_uuid)

    asyncio.run(run())
