"""Actual owner callbacks and SDK reads authorize original root retirement."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.temporal_context_execution import ContextExecutionOwner
from ralf_agent.types import digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


def module():
    name = "ralf_agent.temporal_deployment_release"
    assert importlib.util.find_spec(name), "Original SDK release transport is missing"
    return importlib.import_module(name)


def environment(monkeypatch):
    from ralf_agent import temporal_deployment_execution_state as admission
    from ralf_agent import temporal_deployment_release_state as release
    from tests.test_temporal_deployment_execution import (
        POLICY,
        SCOPE,
        Handle,
        sealed,
        setup,
    )

    runtime, client, value, info = setup()
    manifest = copy.deepcopy(runtime.manifest)
    manifest["deployment_admission_protocol"]["version"] = 2
    runtime.manifest = manifest
    proof = client.proofs[value["run_id"]]
    root = copy.deepcopy(proof["admission"]["root"])
    root["manifest_digest"] = digest(manifest)
    root["proof_digest"] = digest(
        {
            key: item
            for key, item in root.items()
            if key not in {"proof_digest", "state", "execution_epoch"}
        }
    )
    client.registry.roots[digest([SCOPE, root["command_id"]])] = {
        **root,
        "state": "held-bound",
        "execution_epoch": info.workflow_run_id,
    }
    metadata = {"version": 1, "root": root, "lineage": []}
    receipt = sealed(
        {
            "version": 1,
            "run_id": proof["run_id"],
            "execution_epoch": proof["execution_epoch"],
            "root": {**root, "state": "held-bound", "execution_epoch": proof["execution_epoch"]},
            "metadata_digest": digest(metadata),
        }
    )
    proof = sealed(
        {
            **proof,
            "manifest": manifest,
            "manifest_digest": digest(manifest),
            "admission": metadata,
            "admission_receipt": receipt,
        }
    )
    client.proofs[proof["run_id"]] = proof
    client.descriptions[proof["run_id"]].task_queue = "original-queue"
    state = SimpleNamespace(
        manifest=manifest,
        scope=copy.deepcopy(SCOPE),
        run_id=proof["run_id"],
        epoch=proof["execution_epoch"],
        state="succeeded",
        actions=[],
        reservations={},
        children=[],
        active_action=None,
        remote_uncertain=False,
    )
    monkeypatch.setattr(
        admission, "view", lambda original: copy.deepcopy(client.proofs[original.run_id])
    )
    monkeypatch.setattr(admission, "admitted", lambda original: True)
    release.initialize(state)
    client.states = {state.run_id: state}
    client.end_failures = 0
    client.begin_failure = False
    client.retirements = []
    registry_id = client.registry.registry_id
    client.descriptions[registry_id] = SimpleNamespace(
        id=registry_id,
        run_id="registry-epoch",
        namespace=client.namespace,
        parent_id=None,
        parent_run_id=None,
        raw_info=SimpleNamespace(first_run_id="registry-epoch"),
    )

    class OwnedHandle(Handle):
        async def query(self, name, request):
            if self.id == registry_id and request["kind"] == "deployment_submission":
                original_proof = client.proofs[proof["run_id"]]
                return {
                    "reservation": {"root_admission": original_proof["admission"]["root"]},
                    "submission": {
                        "version": 1,
                        "request": original_proof["request"],
                        "manifest": runtime.manifest,
                        "activity_timeout": 2,
                        "task_queue": "original-queue",
                    },
                    "run_receipt": None,
                    "execution_epoch": original_proof["execution_epoch"],
                }
            if self.id == registry_id and request["kind"] == "deployment_configuration":
                return {
                    "version": 2,
                    "registry_id": registry_id,
                    "policy": POLICY.identity,
                    "namespace": client.registry.namespace,
                }
            if request["kind"] == "deployment_closure":
                return release.view(client.states[self.id])
            if request["kind"] == "deployment_start":
                original_proof = client.proofs[self.id]
                return {
                    "scope": original_proof["scope"],
                    "run_id": self.id,
                    "execution_epoch": original_proof["execution_epoch"],
                    "activity_timeout": 2,
                    "task_queue": "original-queue",
                    "request_digest": original_proof["request_digest"],
                    "manifest_digest": original_proof["manifest_digest"],
                }
            return await super().query(name, request)

        async def execute_update(self, name, request, **options):
            client.updates.append((self.id, self.epoch, name, copy.deepcopy(request)))
            if name == "deployment_call_started":
                result = release.begin_activity(client.states[self.id], request)
                if client.begin_failure:
                    client.begin_failure = False
                    raise RuntimeError("Original begin was accepted but its response was lost")
                return result
            if name == "deployment_call_ended":
                if client.end_failures:
                    client.end_failures -= 1
                    raise RuntimeError("Original durable ACK unavailable")
                return release.end_activity(client.states[self.id], request)
            if name == "deployment_seal":
                return release.seal(client.states[self.id], request)
            if name == "release_deployment_root":
                client.retirements.append(copy.deepcopy(request))
                return {"run_id": request["run_id"], "retired": True}
            return await super().execute_update(name, request, **options)

    client.get_workflow_handle = lambda workflow_id, **options: OwnedHandle(
        client, workflow_id, options.get("run_id")
    )
    runtime._deployment_execution_owner = runtime._deployment_execution_owner_pin = (
        ContextExecutionOwner(max_calls=8)
    )
    info.activity_id, info.activity_type, info.attempt = "business-call", "test.business", 1
    return runtime, client, state, proof, info


def test_sdk_release_helper_is_available():
    assert module()


def test_wrapped_real_async_handler_remains_owned_after_observer_cancel(monkeypatch):
    from temporalio import activity

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        started, finish = asyncio.Event(), asyncio.Event()
        actual = []

        @activity.defn(name="test.business")
        async def body(request: dict) -> dict:
            started.set()
            await finish.wait()
            actual.append(copy.deepcopy(request))
            return {"done": True}

        carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
        with module().activity_context(runtime, client, proof, carrier):
            observer = asyncio.create_task(
                module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                )
            )
        try:
            await asyncio.wait_for(started.wait(), 2)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert not next(iter(state.deployment_calls.values()))["stopped"]
            with pytest.raises(CloseIncomplete):
                await module().close_owner(runtime, wait_timeout=0)
            finish.set()
            assert await runtime._deployment_execution_owner.wait(wait_timeout=2)
            assert next(iter(state.deployment_calls.values()))["stopped"] is True
            assert actual == [{"input": "original"}]
        finally:
            finish.set()
            await runtime._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(run())


def test_failed_durable_end_ack_stays_owned_until_original_retry(monkeypatch):
    from temporalio import activity

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        client.end_failures = 10

        @activity.defn(name="test.business")
        async def body(request: dict) -> dict:
            return {"done": True}

        carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
        with module().activity_context(runtime, client, proof, carrier):
            assert await module().wrap_activity(runtime, client, body)(
                carrier["_deployment_activity_request"]
            ) == {"done": True}
        assert not await runtime._deployment_execution_owner.wait(wait_timeout=0)
        assert next(iter(state.deployment_calls.values()))["stopped"] is False
        client.end_failures = 0
        await module().close_owner(runtime, wait_timeout=2)
        assert next(iter(state.deployment_calls.values()))["stopped"] is True

    asyncio.run(run())


def test_handler_return_does_not_end_actual_tracked_sync_reader(monkeypatch):
    from temporalio import activity

    from ralf_agent import Scope
    from ralf_agent.recall import RecallQuery
    from tests.test_temporal_context_execution import blocked_reader, wait_started

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        reader, source, started, finish, stopped = blocked_reader()

        @activity.defn(name="test.business")
        async def body(request: dict) -> dict:
            task = asyncio.create_task(reader.read_page(Scope(), "s", RecallQuery()))
            await wait_started(started)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return {"observer": "cancelled"}

        carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
        try:
            with module().activity_context(runtime, client, proof, carrier):
                assert await module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                ) == {"observer": "cancelled"}
            assert not stopped.is_set()
            assert not await runtime._deployment_execution_owner.wait(wait_timeout=0)
            assert next(iter(state.deployment_calls.values()))["stopped"] is False
            finish.set()
            await module().close_owner(runtime, wait_timeout=2)
            assert stopped.is_set() and source.calls == 1
            assert next(iter(state.deployment_calls.values()))["stopped"] is True
        finally:
            finish.set()
            await runtime._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(run())


def test_release_reads_original_closure_and_seals_before_registry_retirement(monkeypatch):
    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        result = await module().execute(
            runtime,
            client,
            {
                "mode": "release",
                "scope": state.scope,
                "run_id": state.run_id,
                "execution_epoch": state.epoch,
            },
            info,
        )
        assert result == {"run_id": state.run_id, "retired": True}
        assert state.deployment_seal is not None
        assert client.retirements[0]["certificate"] == state.deployment_seal
        assert [item[2] for item in client.updates][-2:] == [
            "deployment_seal",
            "release_deployment_root",
        ]

    asyncio.run(run())


def test_registry_verification_rejects_forged_certificate_and_foreign_sdk_origin(monkeypatch):
    from ralf_agent.temporal_deployment_release_state import seal

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        certificate = seal(state, {"scope": state.scope, "children": []})
        root = certificate and proof["admission_receipt"]["root"]
        registry = client.registry.registry_id
        actual = SimpleNamespace(
            workflow_id=registry,
            workflow_run_id="registry-epoch",
            workflow_namespace=client.namespace,
        )
        value = {
            "mode": "verify",
            "scope": state.scope,
            "root": root,
            "certificate": certificate,
            "manifest": runtime.manifest,
            "registry_execution_epoch": "registry-epoch",
        }
        assert await module().execute(runtime, client, value, actual) == {
            "root": root,
            "certificate": certificate,
        }
        forged = copy.deepcopy(value)
        forged["certificate"]["closure_digest"] = "e" * 64
        forged["certificate"]["proof_digest"] = digest(
            {key: item for key, item in forged["certificate"].items() if key != "proof_digest"}
        )
        with pytest.raises(DefinitionMismatch):
            await module().execute(runtime, client, forged, actual)
        with pytest.raises(DefinitionMismatch):
            await module().execute(runtime, client, value, info)
        assert client.retirements == []

    asyncio.run(run())


def test_exact_release_registration_marker_and_owner_pin_are_required(monkeypatch):
    from temporalio import activity

    runtime, client, *_ = environment(monkeypatch)
    original = module().registered_activity(runtime, client)
    assert module().is_registered_activity(runtime, client, original)

    @activity.defn(name="ralf.temporal.deployment-release.v2")
    async def forged(request: dict) -> dict:
        return {"retired": True}

    assert not module().is_registered_activity(runtime, client, forged)
    runtime._deployment_execution_owner = ContextExecutionOwner(max_calls=8)
    with pytest.raises(DefinitionMismatch):
        module().check_owner(runtime)


def test_lost_begin_response_is_resolved_without_running_business(monkeypatch):
    from temporalio import activity

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        client.begin_failure = True
        called = []

        @activity.defn(name="test.business")
        async def body(request: dict) -> dict:
            called.append(True)
            return {"done": True}

        carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
        with module().activity_context(runtime, client, proof, carrier):
            with pytest.raises(RuntimeError):
                await module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                )
        await module().close_owner(runtime, wait_timeout=2)
        assert called == []
        assert next(iter(state.deployment_calls.values()))["stopped"] is True
        starts = [item for item in client.updates if item[2] == "deployment_call_started"]
        assert len(starts) == 2 and starts[0][3] == starts[1][3]

    asyncio.run(run())


async def child_environment(monkeypatch):
    from ralf_agent import temporal_deployment_execution as admission
    from ralf_agent import temporal_deployment_release_state as release
    from tests.test_temporal_deployment_execution import child_setup, sealed

    runtime, client, parent, proof, info = environment(monkeypatch)
    value, child_info, _ = child_setup(runtime, client, {"run_id": parent.run_id})
    client.descriptions[value["run_id"]].task_queue = "original-queue"
    receipt = await admission.admit(runtime, client, value, child_info)
    child_proof = client.proofs[value["run_id"]]
    client.proofs[value["run_id"]] = sealed({**child_proof, "admission_receipt": receipt})
    child = SimpleNamespace(
        manifest=runtime.manifest,
        scope=parent.scope,
        run_id=value["run_id"],
        epoch=value["execution_epoch"],
        state="succeeded",
        actions=[],
        reservations={},
        active_action=None,
        remote_uncertain=False,
    )
    release.initialize(child)
    client.states[child.run_id] = child
    parent.children = client.proofs[parent.run_id]["children"]
    parent.children[0].update(settled=True, started=True, state="succeeded")
    client.proofs[parent.run_id] = sealed(
        {**client.proofs[parent.run_id], "children": parent.children}
    )
    return runtime, client, parent, child, info


def test_bottom_up_child_seals_are_read_from_each_original_sdk_history(monkeypatch):
    async def run():
        runtime, client, parent, child, info = await child_environment(monkeypatch)
        await module().execute(
            runtime,
            client,
            {
                "mode": "release",
                "scope": parent.scope,
                "run_id": parent.run_id,
                "execution_epoch": parent.epoch,
            },
            info,
        )
        sealed_ids = [item[0] for item in client.updates if item[2] == "deployment_seal"]
        assert sealed_ids == [child.run_id, parent.run_id]
        assert (
            parent.deployment_seal["children"][0]["seal_digest"]
            == child.deployment_seal["proof_digest"]
        )
        assert len(client.retirements) == 1

    asyncio.run(run())


def test_wrong_actual_child_parent_prevents_every_tree_seal_and_retirement(monkeypatch):
    async def run():
        runtime, client, parent, child, info = await child_environment(monkeypatch)
        client.descriptions[child.run_id].parent_run_id = "replacement-parent-epoch"
        with pytest.raises(DefinitionMismatch):
            await module().execute(
                runtime,
                client,
                {
                    "mode": "release",
                    "scope": parent.scope,
                    "run_id": parent.run_id,
                    "execution_epoch": parent.epoch,
                },
                info,
            )
        assert child.deployment_seal is None and parent.deployment_seal is None
        assert client.retirements == []

    asyncio.run(run())


def test_whole_loop_cancellation_keeps_actual_thread_and_original_end_obligation(monkeypatch):
    from temporalio import activity

    from ralf_agent import Scope
    from ralf_agent.recall import RecallQuery
    from tests.test_temporal_context_execution import blocked_reader, wait_started

    runtime, client, state, proof, info = environment(monkeypatch)
    monkeypatch.setattr(activity, "info", lambda: info)
    reader, source, started, finish, stopped = blocked_reader()
    loop = asyncio.new_event_loop()

    @activity.defn(name="test.business")
    async def body(request: dict) -> dict:
        await reader.read_page(Scope(), "s", RecallQuery())
        return {"done": True}

    carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}

    async def begin():
        with module().activity_context(runtime, client, proof, carrier):
            asyncio.create_task(
                module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                )
            )
        await wait_started(started)

    try:
        loop.run_until_complete(begin())
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()
        assert not stopped.is_set()
        assert next(iter(state.deployment_calls.values()))["stopped"] is False
        assert runtime._deployment_execution_owner.active_count == 1
        finish.set()
        asyncio.run(module().close_owner(runtime, wait_timeout=2))
        assert stopped.is_set() and source.calls == 1
        assert next(iter(state.deployment_calls.values()))["stopped"] is True
    finally:
        finish.set()
        if not loop.is_closed():
            loop.close()
        asyncio.run(runtime._deployment_execution_owner.aclose(wait_timeout=2))
