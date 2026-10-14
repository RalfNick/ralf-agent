"""Actual original Registry History evidence; no business dispatch or release claims."""

import asyncio
import copy
import json
import os
import uuid
from datetime import timedelta

import pytest

from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal import replay_temporal_history
from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


async def _clients(count=1):
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
    from temporalio.client import Client

    name = os.getenv("RALF_TEST_TEMPORAL_NAMESPACE", "default")
    clients = [
        await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"], namespace=name)
        for _ in range(count)
    ]
    response = await clients[0].workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=name)
    )
    namespace = {"name": name, "id": response.namespace_info.id}
    assert str(uuid.UUID(namespace["id"])) == namespace["id"]
    return clients, namespace


def _worker(client, queue):
    from temporalio.worker import Worker

    from ralf_agent.temporal import _workflow_runner
    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow

    return Worker(
        client,
        task_queue=queue,
        workflows=[TemporalCommandRegistryWorkflow],
        workflow_runner=_workflow_runner(),
    )


async def _start(client, queue, policy, namespace):
    return await client.start_workflow(
        COMMAND_REGISTRY_NAME,
        {"deployment_admission": {"version": 1, "policy": policy, "namespace": namespace}},
        id=registry_id(policy["deployment_id"]),
        task_queue=queue,
    )


def _request(policy, namespace, scope, command_id, *, kind="submit", target=None):
    request = {
        "scope": scope,
        "command_id": command_id,
        "kind": kind,
        "target": target or root_run_id(policy["deployment_id"], scope, command_id),
        "payload_digest": "a" * 64,
        "admission_policy": policy,
        "namespace": namespace,
    }
    if kind == "submit":
        request["root_admission"] = {"version": 1, "manifest_digest": "b" * 64}
    return request


async def _update(handle, request, name="reserve"):
    return await handle.execute_update(name, request, rpc_timeout=timedelta(seconds=15))


async def _view(handle, policy, namespace, scope):
    return await handle.query(
        "view",
        {
            "kind": "deployment_admission",
            "scope": scope,
            "admission_policy": policy,
            "namespace": namespace,
        },
        rpc_timeout=timedelta(seconds=15),
    )


async def _reject(handle, request, error, name="reserve"):
    from temporalio.client import WorkflowUpdateFailedError
    from temporalio.exceptions import ApplicationError

    with pytest.raises(WorkflowUpdateFailedError) as rejected:
        await _update(handle, request, name)
    assert isinstance(rejected.value.cause, ApplicationError)
    assert rejected.value.cause.type == error


async def _evidence(handle, directory, namespace, observations):
    from temporalio.api.enums.v1 import EventType

    history = await handle.fetch_history()
    assert any(
        event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_COMPLETED
        for event in history.events
    )
    await replay_temporal_history(history, namespace=namespace["name"])
    (directory / "registry-history.json").write_text(history.to_json())
    (directory / "observations.json").write_text(
        json.dumps(
            {
                "registry_id": handle.id,
                "original_execution_run_id": handle.first_execution_run_id,
                "namespace": namespace,
                "observations": observations,
                "history_replayed": True,
                "business_dispatch_tested": False,
                "release_tested": False,
            },
            sort_keys=True,
        )
    )


async def _cleanup(handle, directory):
    from temporalio.client import WorkflowExecutionStatus

    await handle.terminate(reason="deployment admission test completed")
    description = await handle.describe()
    assert description.status == WorkflowExecutionStatus.TERMINATED
    (directory / "registry-cleanup.json").write_text(
        json.dumps(
            {
                "registry_id": handle.id,
                "terminated": True,
                "termination_is_test_cleanup_not_quota_release": True,
            }
        )
    )


def _worker_cleanup(directory, workers):
    assert all(worker.is_shutdown and not worker.is_running for worker in workers)
    (directory / "worker-cleanup.json").write_text(
        json.dumps({"workers_shutdown": len(workers), "workers_running": 0})
    )


def test_actual_clients_and_scopes_share_atomic_limits_without_phantom_refusals(tmp_path):
    async def scenario():
        from temporalio.client import WorkflowUpdateFailedError
        from temporalio.exceptions import WorkflowAlreadyStartedError

        clients, namespace = await _clients(3)
        queue = "deployment-concurrent-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(
            queue, max_active_root_runs=4, max_active_root_runs_per_scope=2
        ).identity
        scopes = [
            {"workspace": "service-concurrent", "principal": principal}
            for principal in ("alice", "bob", "charlie")
        ]
        moved_queue = queue + "-moved"
        workers = [
            _worker(clients[0], queue),
            _worker(clients[1], queue),
            _worker(clients[2], moved_queue),
        ]
        async with workers[0], workers[1], workers[2]:
            handle = await _start(clients[0], queue, policy, namespace)
            handles = [client.get_workflow_handle(handle.id) for client in clients]
            try:
                shared = await asyncio.gather(
                    *[
                        _update(handles[index], _request(policy, namespace, scope, "same-command"))
                        for index, scope in enumerate(scopes[:2])
                    ]
                )
                assert shared[0]["target"] != shared[1]["target"]
                refused = []
                for scope in scopes[:2]:
                    requests = [
                        _request(policy, namespace, scope, f"contender-{index}")
                        for index in range(5)
                    ]
                    results = await asyncio.gather(
                        *[
                            _update(handles[index % 3], request)
                            for index, request in enumerate(requests)
                        ],
                        return_exceptions=True,
                    )
                    assert sum(isinstance(result, dict) for result in results) == 1
                    for request, result in zip(requests, results, strict=True):
                        if isinstance(result, Exception):
                            assert isinstance(result, WorkflowUpdateFailedError)
                            assert result.cause.type == "capacity_exceeded"
                            refused.append(request)
                await _reject(
                    handles[2], _request(policy, namespace, scopes[2], "full"), "capacity_exceeded"
                )
                # A new queue cannot create another authority for this selected deployment.
                with pytest.raises(WorkflowAlreadyStartedError):
                    await _start(clients[2], moved_queue, policy, namespace)
                description = await handles[2].describe()
                assert description.task_queue == queue
                assert description.run_id == handle.first_execution_run_id
                views = [await _view(handle, policy, namespace, scope) for scope in scopes]
                assert [view["counts"]["held_root_runs_for_scope"] for view in views] == [2, 2, 0]
                assert all(
                    view["counts"]
                    == {
                        "held_root_runs": 4,
                        "held_root_runs_for_scope": own,
                        "command_records": 4,
                    }
                    for view, own in zip(views, [2, 2, 0], strict=True)
                )
                assert views[2]["held_roots"] == []
                assert shared[1]["target"] not in json.dumps(views[0])
                assert '"bob"' not in json.dumps(views[0])
                assert shared[0]["target"] not in json.dumps(views[1])
                # Reusing a refused ID for different content proves refusal stored no identity.
                control = _request(
                    policy,
                    namespace,
                    scopes[0],
                    refused[0]["command_id"],
                    kind="cancel",
                    target=shared[0]["target"],
                )
                await _update(handles[2], control)
                after = await _view(handle, policy, namespace, scopes[0])
                assert after["counts"] == {
                    "held_root_runs": 4,
                    "held_root_runs_for_scope": 2,
                    "command_records": 5,
                }
                for request, original in zip(
                    [_request(policy, namespace, scope, "same-command") for scope in scopes[:2]],
                    shared,
                    strict=True,
                ):
                    assert await _update(handles[2], request) == original
                await _evidence(
                    handle,
                    tmp_path,
                    namespace,
                    [
                        *views,
                        after,
                        {
                            "attempted_queue": moved_queue,
                            "original_task_queue": description.task_queue,
                        },
                    ],
                )
            finally:
                await _cleanup(handle, tmp_path)
        _worker_cleanup(tmp_path, workers)

    asyncio.run(scenario())


def test_actual_full_duplicate_alias_controls_and_original_binding_are_immutable(tmp_path):
    async def scenario():
        clients, namespace = await _clients(2)
        queue = "deployment-binding-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1).identity
        scope = {"workspace": "service-binding", "principal": "owner"}
        foreign = {**scope, "principal": "foreign"}
        worker = _worker(clients[0], queue)
        async with worker:
            handle = await _start(clients[0], queue, policy, namespace)
            other = clients[1].get_workflow_handle(handle.id)
            try:
                request = _request(policy, namespace, scope, "original")
                original = await _update(handle, request)
                assert original["record_state"] == "durably_recorded"
                assert original["apply_state"] == "not_applied"
                assert original["root_admission"]["state"] == "held-unbound"
                alias = copy.deepcopy(request)
                alias["root_admission"]["manifest_digest"] = "c" * 64
                assert await _update(other, alias) == original
                await _reject(
                    other, _request(policy, namespace, scope, "full"), "capacity_exceeded"
                )
                await _reject(
                    other, {**request, "payload_digest": "d" * 64}, "idempotency_conflict"
                )
                for kind in ("approve", "cancel", "reconcile", "drive", "send_input"):
                    receipt = await _update(
                        other,
                        _request(
                            policy, namespace, scope, kind, kind=kind, target=original["target"]
                        ),
                    )
                    assert receipt["apply_state"] == "not_applied"
                await _reject(
                    other,
                    _request(
                        policy,
                        namespace,
                        foreign,
                        "cancel-foreign",
                        kind="cancel",
                        target=original["target"],
                    ),
                    "authorization_denied",
                )
                root = original["root_admission"]
                binding = {
                    **{
                        key: root[key]
                        for key in (
                            "scope",
                            "command_id",
                            "run_id",
                            "request_digest",
                            "manifest_digest",
                            "proof_digest",
                        )
                    },
                    "admission_policy": policy,
                    "namespace": namespace,
                    "execution_epoch": "original-sdk-epoch",
                }
                bound = await _update(other, binding, "bind_deployment_root")
                assert bound["state"] == "held-bound"
                assert bound["execution_epoch"] == "original-sdk-epoch"
                assert await _update(handle, binding, "bind_deployment_root") == bound
                before = await _view(handle, policy, namespace, scope)
                mutations = {
                    "scope": foreign,
                    "run_id": "other-run",
                    "request_digest": "e" * 64,
                    "manifest_digest": "f" * 64,
                    "proof_digest": "0" * 64,
                    "namespace": {**namespace, "id": str(uuid.uuid4())},
                    "admission_policy": {**policy, "version": "changed"},
                    "execution_epoch": "replacement-sdk-epoch",
                }
                for key, value in mutations.items():
                    from temporalio.client import WorkflowUpdateFailedError

                    with pytest.raises(WorkflowUpdateFailedError):
                        await _update(other, {**binding, key: value}, "bind_deployment_root")
                    assert await _view(handle, policy, namespace, scope) == before
                assert before["counts"] == {
                    "held_root_runs": 1,
                    "held_root_runs_for_scope": 1,
                    "command_records": 6,
                }
                assert before["held_roots"] == [bound]
                assert await _update(other, alias) == original
                detached = copy.deepcopy(before)
                before["held_roots"][0]["manifest_digest"] = "changed-by-observer"
                assert await _view(handle, policy, namespace, scope) == detached
                malformed = await handle.query("view", {"kind": "unknown", "scope": foreign})
                assert set(malformed) == {"error"}
                await _evidence(handle, tmp_path, namespace, [original, bound, detached])
            finally:
                await _cleanup(handle, tmp_path)
        _worker_cleanup(tmp_path, [worker])

    asyncio.run(scenario())


def test_actual_worker_absence_and_restart_preserve_held_original_history(tmp_path):
    async def scenario():
        clients, namespace = await _clients(2)
        queue = "deployment-restart-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1).identity
        scope = {"workspace": "service-restart", "principal": "owner"}
        handle = await _start(clients[0], queue, policy, namespace)
        request = _request(policy, namespace, scope, "original")
        pending = asyncio.create_task(_update(handle, request))
        unavailable = None
        original_worker = _worker(clients[0], queue)
        restarted_worker = _worker(clients[1], queue)
        try:
            await asyncio.sleep(0.1)
            assert not pending.done()
            async with original_worker:
                original = await asyncio.wait_for(pending, 20)
                before = await _view(handle, policy, namespace, scope)
                assert before["held_roots"] == [original["root_admission"]]
            assert original_worker.is_shutdown and not original_worker.is_running
            # New client, fresh Worker cache, same original namespace and execution.
            other = clients[1].get_workflow_handle(handle.id)
            fresh = _request(policy, namespace, scope, "worker-absent-fresh")
            unavailable = asyncio.create_task(_update(other, fresh))
            await asyncio.sleep(0.1)
            assert not unavailable.done()
            async with restarted_worker:
                from temporalio.client import WorkflowUpdateFailedError

                with pytest.raises(WorkflowUpdateFailedError) as refused:
                    await asyncio.wait_for(unavailable, 20)
                assert refused.value.cause.type == "capacity_exceeded"
                assert await _update(other, request) == original
                assert await _view(other, policy, namespace, scope) == before
                assert (await other.describe()).run_id == handle.first_execution_run_id
                await _evidence(handle, tmp_path, namespace, [original, before])
        finally:
            for task in (pending, unavailable):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await _cleanup(handle, tmp_path)
        _worker_cleanup(tmp_path, [original_worker, restarted_worker])

    asyncio.run(scenario())
