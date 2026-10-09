import asyncio
import copy
from dataclasses import asdict, replace
from types import MethodType

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, NotFound, ValidationError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.types import digest

from .temporal_agent_fixture import StateClient, engine
from .temporal_composite_agent_fixture import CompositeClient, definitions


async def system(monkeypatch, kind="nested"):
    client = CompositeClient()
    raw = engine(monkeypatch, client=client, release=client.worker_runtime.orchestration_release)
    runtime = r.Runtime.from_temporal(raw)
    run = await runtime.create_agent(definitions()[kind]).submit("q", command_id="s", budget=64)
    return client, raw, runtime, run


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "plan", "nested"])
def test_pending_controls_use_actual_child_ref_and_never_root_aggregates(monkeypatch, kind):
    async def scenario():
        client, _, runtime, run = await system(monkeypatch, kind)
        async with runtime:
            before = {key: copy.deepcopy(s.receipts) for key, s in client.states.items()}
            pending = await run.pending()
            assert len(pending) == 1
            control = pending[0]
            ref = r.RunRef.from_dict(control["ref"])
            assert ref.run_id == (await run.status()).pending[0]["run_id"]
            assert ref != run.ref and control["kind"] == "approval"
            owner = await runtime.aattach(ref)
            assert ref.release_digest == (await owner.diagnostics()).release_digest
            assert {key: s.receipts for key, s in client.states.items()} == before
            approval = await owner.approve(control["action_id"], control["digest"], command_id="a")
            assert approval.run_id == ref.run_id
            assert (
                await owner.approve(control["action_id"], control["digest"], command_id="a")
                == approval
            )
            assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"
            assert await run.pending() == [] and client.tool_calls == 1

    asyncio.run(scenario())


def test_nested_unknown_tool_remains_discoverable_after_root_cancellation(monkeypatch):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch)
        async with runtime:
            item = (await run.status()).pending[0]
            client.hold_execution = True
            await raw.approve(item["run_id"], item["action_id"], item["digest"], command_id="a")
            child = client.states[item["run_id"]]
            action, _ = child.next_operation()
            child.operation_unknown(action["id"], "lost_receipt")
            client.hold_execution = False
            await client.pump()
            assert (await run.wait(wait_timeout=0.1)).snapshot.state == "outcome_unknown"
            await run.cancel(command_id="stop")
            assert (await run.status()).state == "cancelled"
            controls = await run.pending()
            assert len(controls) == 1 and controls[0]["kind"] == "reconciliation"
            owner = await runtime.aattach(r.RunRef.from_dict(controls[0]["ref"]))
            assert owner.ref.run_id == child.run_id and client.tool_calls == 0
            receipt = await owner.reconcile(action["id"], {"found": True}, command_id="evidence")
            assert (
                await owner.reconcile(action["id"], {"found": True}, command_id="evidence")
                == receipt
            )
            assert await run.pending() == []
            assert (await run.diagnostics()).budget["unknown"] == 24
            assert (await run.diagnostics()).workflow["unknown_remote_execution"] is True
            assert (await run.status()).state == "cancelled" and client.tool_calls == 0

    asyncio.run(scenario())


def test_cancelled_native_projection_drops_unusable_approval_without_changing_receipt(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        handle = await raw.submit(r.AgentSpec("a", "A", ("lookup",)), "q", command_id="s")
        assert len((await raw.status(handle.run_id)).pending) == 1
        receipt = await raw.cancel(handle.run_id, command_id="stop")
        assert await raw.cancel(handle.run_id, command_id="stop") == receipt
        assert (await raw.status(handle.run_id)).pending == ()
        state = raw.client.states[handle.run_id]
        assert any(a["status"] == "waiting_approval" for a in state.actions)
        assert state.quiescent and state.budget["reserved"] == state.budget["unknown"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "corruption",
    [
        "id",
        "command",
        "release",
        "manifest",
        "children",
        "oversized",
        "duplicate",
        "started",
        "settled",
    ],
)
def test_malformed_parent_or_child_evidence_cannot_hide_controls(monkeypatch, corruption):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch, "graph")
        async with runtime:
            child_id = client.states[run.ref.run_id].children[0]["run_id"]

            async def corrupt(view, run_id):
                info = await TemporalEngine.diagnostics(view, run_id)
                flow = copy.deepcopy(info.workflow)
                if run_id == run.ref.run_id:
                    call = flow["children"][0]
                    if corruption == "id":
                        call["run_id"] = run.ref.run_id
                    elif corruption == "command":
                        call["command_id"] = "other"
                    elif corruption == "children":
                        flow["children"] = {}
                    elif corruption == "oversized":
                        flow["children"] *= 4097
                    elif corruption == "duplicate":
                        flow["children"] *= 2
                    elif corruption in {"started", "settled"}:
                        call[corruption] = "yes"
                    return replace(info, workflow=flow)
                if run_id == child_id and corruption == "release":
                    return replace(info, release_digest="0" * 64)
                if run_id == child_id and corruption == "manifest":
                    return replace(info, manifest={**info.manifest, "policy": {"kind": "changed"}})
                return info

            raw.diagnostics = MethodType(corrupt, raw)
            before = copy.deepcopy(client.states[run.ref.run_id].receipts)
            with pytest.raises((DefinitionMismatch, ValidationError)):
                await run.pending()
            assert client.states[run.ref.run_id].receipts == before and client.tool_calls == 0

    asyncio.run(scenario())


def test_unstarted_intent_is_not_queried_but_missing_started_child_is_error(monkeypatch):
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
            call.update(state="queued", spent=0)
            call["started"] = False
            assert await run.pending() == []
            call["started"] = True
            with pytest.raises(NotFound):
                await run.pending()

    asyncio.run(scenario())


def test_nested_discovery_pins_original_dispatch_and_rejects_client_drift(monkeypatch):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch)
        async with runtime:
            entered, release = asyncio.Event(), asyncio.Event()
            original = raw.client

            async def blocked(view, run_id):
                if run_id != run.ref.run_id:
                    entered.set()
                    await release.wait()
                return await TemporalEngine.diagnostics(view, run_id)

            raw.diagnostics = MethodType(blocked, raw)
            discovering = asyncio.create_task(run.pending())
            try:
                await asyncio.wait_for(entered.wait(), 0.5)
                replacement = StateClient("other:7233")
                raw.client = replacement
                release.set()
                with pytest.raises(DefinitionMismatch):
                    await discovering
                assert not replacement.states and not replacement.registries
                assert client.tool_calls == 0
            finally:
                raw.client = original
                release.set()
                await asyncio.gather(discovering, return_exceptions=True)

    asyncio.run(scenario())


def test_parent_wait_and_pending_cancellation_remain_observation_only(monkeypatch):
    async def scenario():
        client, _, runtime, run = await system(monkeypatch)
        async with runtime:
            before = {key: copy.deepcopy(s.receipts) for key, s in client.states.items()}
            client.query_gate = asyncio.Event()
            waiting = asyncio.create_task(run.wait(wait_timeout=0.01, terminal_only=True))
            assert (await waiting).wait_reason == "observation_timeout"
            discovering = asyncio.create_task(run.pending())
            await asyncio.sleep(0)
            discovering.cancel()
            with pytest.raises(asyncio.CancelledError):
                await discovering
            assert {key: s.receipts for key, s in client.states.items()} == before
            client.query_gate.set()
            await run.cancel(command_id="stop")
            assert (await run.status()).state == "cancelled"
            assert await run.pending() == [] and client.tool_calls == 0

    asyncio.run(scenario())


def test_deep_wire_tree_is_bounded_before_unlimited_queries(monkeypatch):
    async def scenario():
        client, raw, runtime, run = await system(monkeypatch, "graph")
        async with runtime:
            template = await run.diagnostics()
            scope = asdict(raw.scope)
            responses = {}
            current = run.ref.run_id
            for _ in range(18):
                call = copy.deepcopy(template.workflow["children"][0])
                call["id"] = "0:a"
                call["command_id"] = "ralf-child:" + digest([scope, current, call["id"]])
                call["run_id"] = "ralf-temporal-" + digest([scope, call["command_id"]])
                call["request"]["definition"] = client.states[run.ref.run_id].definition
                call["settled"] = False
                flow = {**template.workflow, "children": [call]}
                responses[current] = replace(
                    template, snapshot=replace(template.snapshot, run_id=current), workflow=flow
                )
                current = call["run_id"]

            async def query(view, run_id):
                return responses[run_id]

            raw.diagnostics = MethodType(query, raw)
            with pytest.raises(DefinitionMismatch):
                await run.pending()
            assert client.tool_calls == 0

    asyncio.run(scenario())
