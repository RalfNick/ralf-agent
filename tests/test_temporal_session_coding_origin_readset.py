"""Coding Session freshness reads overlap only within one drained SDK read set."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_deployment_verification import (
    SessionControlValidation,
    validate_session_origin,
)
from tests.test_temporal_deployment_session_registry import POLICY, deployment_intent
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_control import Client, Handle
from tests.test_temporal_session_deployment_control import fixture as ordinary
from tests.test_temporal_session_deployment_dto import origin
from tests.test_temporal_session_validation_readset import CountedRuntime

EARLY = {"namespace", "describe", "deployment_session_intent", "deployment_session_command"}


class ReadClient(Client):
    def __init__(self, wire):
        super().__init__(wire)
        self.gate, self.overlap = asyncio.Event(), asyncio.Event()
        self.started, self.completed, self.counts = set(), set(), {}
        self.fail = None
        self.fail_gate = None

    async def before(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1
        first = name in EARLY and self.counts[name] == 1
        if first:
            self.started.add(name)
            if self.started == EARLY:
                self.overlap.set()
            gate = (
                self.fail_gate
                if name == "deployment_session_intent" and self.fail_gate is not None
                else self.gate
            )
            await gate.wait()
        return first

    async def describe_namespace(self, request):
        first = await self.before("namespace")
        try:
            return await super().describe_namespace(request)
        finally:
            if first:
                self.completed.add("namespace")

    def get_workflow_handle(self, identity, *, run_id=None):
        assert identity == self.intent["coordinator_id"]
        return ReadHandle(self, run_id)


class ReadHandle(Handle):
    async def describe(self):
        first = await self.client.before("describe")
        try:
            return await super().describe()
        finally:
            if first:
                self.client.completed.add("describe")

    async def query(self, name, selector):
        kind = selector["kind"]
        first = await self.client.before(kind)
        try:
            if kind == self.client.fail:
                raise RuntimeError("original SDK reader failed")
            if self.client.fail == "cancel" and kind == "deployment_session_intent":
                raise asyncio.CancelledError("original SDK reader cancelled")
            return await super().query(name, selector)
        finally:
            if first:
                self.client.completed.add(kind)


def environment(*, composition=False, coordinator=False, coding=True):
    if coding:
        intent, _ = coding_intent_request(registry_state(), composition=composition)
    else:
        intent = deployment_intent()
    deployment = POLICY.deployment_id
    _, wire, info = ordinary()
    wire = {
        **wire,
        "intent": intent,
        **{
            key: intent[key]
            for key in ("scope", "namespace", "coordinator_id", "coordinator_execution_epoch")
        },
    }
    info = SimpleNamespace(**vars(info))
    info.workflow_id, info.workflow_run_id = (
        intent["coordinator_id"],
        intent["coordinator_execution_epoch"],
    )
    info.workflow_namespace, info.task_queue = (
        intent["namespace"]["name"],
        intent["binding"]["task_queue"],
    )
    client = ReadClient(wire)
    runtime = CountedRuntime(copy.deepcopy(intent["binding"]["manifest"]))

    async def validate():
        if coordinator:
            proof = SessionControlValidation(runtime, client, wire, info, deployment_id=deployment)
            return await proof.validate()
        return await validate_session_origin(runtime, client, intent, origin(intent))

    return runtime, client, validate


async def wait_for_overlap(client):
    # Old sequential reads stop at namespace; this assertion is the RED barrier.
    for _ in range(50):
        if client.overlap.is_set():
            break
        await asyncio.sleep(0)
    assert client.started == EARLY


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("coordinator", [False, True])
def test_four_independent_original_reads_overlap_before_start_and_final_freshness(
    composition, coordinator
):
    async def run():
        runtime, client, validate = environment(composition=composition, coordinator=coordinator)
        task = asyncio.create_task(validate())
        try:
            await wait_for_overlap(client)
        finally:
            client.gate.set()
            result = await task
        assert result["intent"] == client.intent
        assert client.completed == EARLY
        assert client.events == [
            "namespace",
            "describe",
            "deployment_session_intent",
            "deployment_session_command",
            "history",
            "describe",
            "namespace",
        ]
        assert runtime.validations == 3  # Constructor plus public entry/exit.

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["reset", "namespace", "callback", "resource", "reader", "child-cancel"]
)
def test_failed_original_readset_drains_all_readers_and_never_adopts(fault, monkeypatch):
    async def run():
        runtime, client, validate = environment()
        adopted = []
        if fault in {"reader", "child-cancel"}:
            client.fail_gate = asyncio.Event()

        async def operation():
            result = await validate()
            adopted.append(result)

        task = asyncio.create_task(operation())
        try:
            await wait_for_overlap(client)
            if fault == "reset":
                client.epoch = "replacement"
            elif fault == "namespace":
                client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
            elif fault == "callback":
                monkeypatch.setattr(client, "get_workflow_handle", lambda *args, **kwargs: None)
            elif fault == "resource":
                runtime.manifest = {"changed_resource": True}
            else:
                client.fail = "cancel" if fault == "child-cancel" else "deployment_session_intent"
                client.fail_gate.set()
                for _ in range(5):
                    await asyncio.sleep(0)
                assert client.completed == {"deployment_session_intent"}
                assert not task.done()
            client.gate.set()
            with pytest.raises((DefinitionMismatch, RuntimeError, asyncio.CancelledError)):
                await task
            assert client.completed == EARLY and not adopted
            if fault != "resource":
                assert "history" not in client.events
        finally:
            client.gate.set()
            if client.fail_gate is not None:
                client.fail_gate.set()
            if not task.done():
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_caller_cancellation_waits_for_every_original_reader_to_stop():
    async def run():
        _, client, validate = environment()
        task = asyncio.create_task(validate())
        try:
            await wait_for_overlap(client)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and client.completed == set()
            client.gate.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert client.completed == EARLY
            assert "history" not in client.events
        finally:
            client.gate.set()
            if not task.done():
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("coordinator", [False, True])
def test_ordinary_session_reads_keep_original_sequential_order(coordinator):
    async def run():
        _, client, validate = environment(coordinator=coordinator, coding=False)
        client.gate.set()
        await validate()
        assert client.events == [
            "namespace",
            "describe",
            "history",
            "deployment_session_intent",
            "deployment_session_command",
            "describe",
            "namespace",
        ]

    asyncio.run(run())
