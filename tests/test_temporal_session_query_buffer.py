"""Two facts on one original coordinator do not contend for its query slot."""

import asyncio

import pytest
from temporalio.service import RPCError, RPCStatusCode

from tests.test_temporal_session_coding_origin_readset import ReadHandle, environment


@pytest.mark.parametrize("composition", [False, True])
def test_single_slot_original_query_buffer_retains_both_fresh_facts(composition):
    async def run():
        _, client, validate = environment(composition=composition)
        client.gate.set()
        active = 0

        class SingleSlot(ReadHandle):
            async def query(self, name, selector):
                nonlocal active
                if active:
                    raise RPCError(
                        "consistent query buffer is full", RPCStatusCode.RESOURCE_EXHAUSTED, b""
                    )
                active += 1
                try:
                    await asyncio.sleep(0)
                    return await super().query(name, selector)
                finally:
                    active -= 1

        client.get_workflow_handle = lambda identity, run_id=None: SingleSlot(client, run_id)
        result = await asyncio.wait_for(validate(), 2)
        assert result["intent"] == client.intent
        assert client.completed == {
            "namespace",
            "describe",
            "deployment_session_intent",
            "deployment_session_command",
        }
        assert client.events.count("deployment_session_intent") == 1
        assert client.events.count("deployment_session_command") == 1
        assert client.events.count("history") == 1
        assert active == 0

    asyncio.run(run())


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("separate_clients", [False, True])
def test_independent_verifiers_share_one_original_coordinator_query_slot(
    composition, separate_clients
):
    async def run():
        _, first, validate_first = environment(composition=composition)
        if separate_clients:
            _, second, validate_second = environment(composition=composition)
        else:
            second, validate_second = first, validate_first
        first.gate.set()
        second.gate.set()
        active = 0
        maximum = 0

        class SingleSlot(ReadHandle):
            async def query(self, name, selector):
                nonlocal active, maximum
                if active:
                    raise RPCError(
                        "consistent query buffer is full", RPCStatusCode.RESOURCE_EXHAUSTED, b""
                    )
                active += 1
                maximum = max(maximum, active)
                try:
                    await asyncio.sleep(0)
                    return await super().query(name, selector)
                finally:
                    active -= 1

        first.get_workflow_handle = lambda identity, run_id=None: SingleSlot(first, run_id)
        if separate_clients:
            second.get_workflow_handle = lambda identity, run_id=None: SingleSlot(second, run_id)
        results = await asyncio.wait_for(asyncio.gather(validate_first(), validate_second()), 2)
        assert [value["intent"] for value in results] == [first.intent, second.intent]
        assert maximum == 1 and active == 0
        events = first.events + (second.events if separate_clients else [])
        assert events.count("deployment_session_intent") == 2
        assert events.count("deployment_session_command") == 2
        assert events.count("history") == 2

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "reader", "cancel"])
def test_queued_original_reader_drains_and_releases_transport_slot(fault):
    from relf_agent import temporal_session_deployment_verification as verification

    async def run():
        _, first, validate_first = environment(composition=True)
        _, second, validate_second = environment(composition=True)
        first.gate.set()
        second.gate.set()
        entered, release = asyncio.Event(), asyncio.Event()
        active = 0
        reads = []

        class SingleSlot(ReadHandle):
            async def query(self, name, selector):
                nonlocal active
                assert active == 0
                active += 1
                try:
                    reads.append((self.client is first, selector["kind"]))
                    if self.client is first and selector["kind"] == "deployment_session_intent":
                        entered.set()
                        await release.wait()
                    return await super().query(name, selector)
                finally:
                    active -= 1

        first.get_workflow_handle = lambda identity, run_id=None: SingleSlot(first, run_id)
        second.get_workflow_handle = lambda identity, run_id=None: SingleSlot(second, run_id)
        original = asyncio.create_task(validate_first())
        queued = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            queued = asyncio.create_task(validate_second())
            for _ in range(50):
                if second.completed == {"namespace", "describe"}:
                    break
                await asyncio.sleep(0)
            assert second.completed == {"namespace", "describe"}
            assert len(reads) == 1 and not queued.done()
            if fault == "reader":
                second.fail = "deployment_session_intent"
            elif fault == "cancel":
                queued.cancel()
                await asyncio.sleep(0)
                assert not queued.done()  # The started read set still owns its drain.
            release.set()
            assert (await original)["intent"] == first.intent
            if fault:
                with pytest.raises(RuntimeError if fault == "reader" else asyncio.CancelledError):
                    await queued
            else:
                assert (await queued)["intent"] == second.intent
            assert reads == [
                (True, "deployment_session_intent"),
                (True, "deployment_session_command"),
                (False, "deployment_session_intent"),
                (False, "deployment_session_command"),
            ]
            assert active == 0
            assert asyncio.get_running_loop() not in verification._COORDINATOR_QUERIES
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (original, queued) if task is not None), return_exceptions=True
            )

    asyncio.run(run())


def test_different_original_epochs_keep_independent_query_slots():
    import copy

    from relf_agent.temporal_session_deployment_verification import validate_session_origin
    from tests.test_temporal_session_deployment_dto import origin, seal

    async def run():
        _, first, validate_first = environment(composition=True)
        runtime, second, _ = environment(composition=True)
        other = copy.deepcopy(second.intent)
        other["coordinator_execution_epoch"] = "other-original-epoch"
        seal(other)
        second.intent = other
        second.epoch = second.first_epoch = second.original_epoch = other[
            "coordinator_execution_epoch"
        ]
        first.gate.set()
        second.gate.set()
        entered = {client.epoch: asyncio.Event() for client in (first, second)}
        release = asyncio.Event()
        active = set()

        class IndependentSlots(ReadHandle):
            async def query(self, name, selector):
                epoch = self.client.epoch
                assert epoch not in active
                active.add(epoch)
                try:
                    if selector["kind"] == "deployment_session_intent":
                        entered[epoch].set()
                        await release.wait()
                    return await super().query(name, selector)
                finally:
                    active.remove(epoch)

        first.get_workflow_handle = lambda identity, run_id=None: IndependentSlots(first, run_id)
        second.get_workflow_handle = lambda identity, run_id=None: IndependentSlots(second, run_id)
        tasks = [
            asyncio.create_task(validate_first()),
            asyncio.create_task(validate_session_origin(runtime, second, other, origin(other))),
        ]
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
            assert len(active) == 2
            release.set()
            results = await asyncio.gather(*tasks)
            assert [result["intent"] for result in results] == [first.intent, second.intent]
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not active

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["selector", "_check", "checker-code"])
def test_queued_reader_rechecks_original_pins_before_foreign_callbacks(changed, monkeypatch):
    from relf_agent import temporal_session_deployment_verification as verification
    from relf_agent.errors import DefinitionMismatch

    async def run():
        _, first, validate_first = environment(composition=True)
        _, second, validate_second = environment(composition=True)
        first.gate.set()
        second.gate.set()
        entered, release = asyncio.Event(), asyncio.Event()
        foreign_calls = []
        reads = []

        class HeldOriginal(ReadHandle):
            async def query(self, name, selector):
                reads.append((self.client is first, selector["kind"]))
                if self.client is first and selector["kind"] == "deployment_session_intent":
                    entered.set()
                    await release.wait()
                return await super().query(name, selector)

        first.get_workflow_handle = lambda identity, run_id=None: HeldOriginal(first, run_id)
        second.get_workflow_handle = lambda identity, run_id=None: HeldOriginal(second, run_id)
        original = asyncio.create_task(validate_first())
        queued = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            queued = asyncio.create_task(validate_second())
            for _ in range(50):
                if second.completed == {"namespace", "describe"}:
                    break
                await asyncio.sleep(0)
            assert second.completed == {"namespace", "describe"}
            assert len(reads) == 1 and not queued.done()

            def foreign(*args, **kwargs):
                foreign_calls.append(changed)
                return {"kind": "foreign"}

            if changed == "checker-code":
                first.foreign_calls = second.foreign_calls = foreign_calls

                def foreign_body(self, *, full=True):
                    self.client.foreign_calls.append("checker-code")

                monkeypatch.setattr(
                    verification.SessionControlValidation._check, "__code__", foreign_body.__code__
                )
            else:
                monkeypatch.setattr(verification.SessionControlValidation, changed, foreign)
            release.set()
            results = await asyncio.gather(original, queued, return_exceptions=True)
            assert all(isinstance(result, DefinitionMismatch) for result in results)
            assert foreign_calls == []
            assert reads == [(True, "deployment_session_intent")]
            assert asyncio.get_running_loop() not in verification._COORDINATOR_QUERIES
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (original, queued) if task is not None), return_exceptions=True
            )

    asyncio.run(run())
