import asyncio
import copy
from dataclasses import replace
from types import MethodType

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal import TemporalEngine

from .test_temporal_agent_controls import system


@pytest.mark.parametrize("flag", ["settled", "started"])
def test_pruning_flags_cannot_hide_recorded_unknown_child_effect(monkeypatch, flag):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch, "graph")
        async with runtime:
            item = (await run.status()).pending[0]
            client.hold_execution = True
            await raw.approve(item["run_id"], item["action_id"], item["digest"], command_id="a")
            child = client.states[item["run_id"]]
            action, _ = child.next_operation()
            child.operation_unknown(action["id"], "lost_receipt")
            client.hold_execution = False
            await client.pump()
            assert (await run.pending())[0]["kind"] == "reconciliation"

            async def contradictory(view, run_id):
                info = await TemporalEngine.diagnostics(view, run_id)
                if run_id == run.ref.run_id:
                    flow = copy.deepcopy(info.workflow)
                    flow["children"][0][flag] = flag == "settled"
                    return replace(info, workflow=flow)
                return info

            raw.diagnostics = MethodType(contradictory, raw)
            with pytest.raises(DefinitionMismatch):
                await run.pending()
            assert child.actions[-1]["status"] == "outcome_unknown" and client.tool_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["snapshot", "uncertain", "flow", "state", "spent"])
def test_settled_child_pruning_requires_consistent_retained_evidence(monkeypatch, field):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch, "graph")
        async with runtime:
            item = (await run.pending())[0]
            await raw.approve(
                item["ref"]["run_id"], item["action_id"], item["digest"], command_id="a"
            )
            assert (await run.status()).state == "succeeded"

            async def contradictory(view, run_id):
                info = await TemporalEngine.diagnostics(view, run_id)
                flow = copy.deepcopy(info.workflow)
                call = flow["children"][0]
                if field == "snapshot":
                    call.pop("snapshot")
                elif field == "uncertain":
                    call["uncertain"] = True
                elif field == "flow":
                    call["observed_flow"]["quiescent"] = False
                elif field == "state":
                    call["state"] = "running"
                elif field == "spent":
                    call["spent"] = call["cap"] + 1
                return replace(info, workflow=flow)

            raw.diagnostics = MethodType(contradictory, raw)
            with pytest.raises(DefinitionMismatch):
                await run.pending()
            assert client.tool_calls == 1

    asyncio.run(scenario())


def test_legitimate_undispatched_cancelled_settled_intent_needs_no_child_query(monkeypatch):
    async def scenario():
        client, _, runtime, run = await system(monkeypatch, "graph")
        async with runtime:
            parent = client.states[run.ref.run_id]
            call = parent.children[0]
            del client.states[call["run_id"]]
            for field in (
                "snapshot",
                "observed_flow",
                "observed_revision",
                "observation_digest",
                "uncertain",
            ):
                call.pop(field, None)
            call.update(started=False, settled=True, state="cancelled", spent=0)
            parent.command("stop", {"kind": "cancel", "scope": parent.scope})
            assert await run.pending() == [] and client.tool_calls == 0

    asyncio.run(scenario())
