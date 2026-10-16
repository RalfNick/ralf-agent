"""New Signal ports retain the selected Coding observer's original source pins."""

import asyncio

import pytest

pytest.importorskip("temporalio")

from ralf_agent import temporal_deployment_coding_bridge as bridge
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_deployment_coding_validation import CodingValidation
from tests.test_temporal_coding_aggregate_readset import environment


@pytest.mark.parametrize("when", ["before", "during-sdk-read"])
def test_selected_coding_rejects_replaced_readonly_signal_port(monkeypatch, when):
    async def run():
        runtime, client, _, request, info = environment(monkeypatch)
        validator = CodingValidation(runtime, client, request, info)
        await validator.validate()
        client.calls.clear()
        changed, writes = [], []

        async def forwarding(handle, *args, **kwargs):
            writes.append(True)
            return await handle.handle.signal(*args, **kwargs)

        async def replace(identity=None):
            if not changed:
                changed.append(identity)
                monkeypatch.setattr(bridge._ReadOnlyHandle, "signal", forwarding)

        if when == "before":
            await replace()
        else:
            client.read_hook = replace
        with pytest.raises(DefinitionMismatch):
            await validator.validate()
        assert changed and not writes
        if when == "before":
            assert not client.calls

    asyncio.run(run())


def test_original_readonly_signal_port_refuses_without_sdk_delivery(monkeypatch):
    async def run():
        _, client, _, request, _ = environment(monkeypatch)
        with pytest.raises(DefinitionMismatch):
            await (
                bridge._ReadOnlyClient(client)
                .get_workflow_handle(request["run_id"], run_id=request["execution_epoch"])
                .signal("execution_ended", {})
            )
        assert not client.calls

    asyncio.run(run())
