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
