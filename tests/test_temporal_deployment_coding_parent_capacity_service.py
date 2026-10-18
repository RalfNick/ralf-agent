"""Original Coding graph closure at real Parent Update capacity, not model quality."""

import asyncio
import copy
import json
import re
import sys
from contextlib import contextmanager
from datetime import timedelta

import pytest

from ralf_agent.temporal import build_temporal_worker
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_service import (
    _eventually,
    coding_system,
    definition,
)
from tests.test_temporal_deployment_coding_service import (
    pytestmark as service_mark,
)

pytestmark = [
    service_mark,
    pytest.mark.skipif(
        not hasattr(sys, "monitoring"), reason="passive RPC proof requires Python 3.12 monitoring"
    ),
]


@contextmanager
def observe_original_parent_rpc(directory):
    """Observe host exceptions without replacing any pinned product code."""
    from temporalio.service import RPCError

    from ralf_agent.temporal_coding_composition_control import _adopt

    monitoring = sys.monitoring
    tool = next(i for i in reversed(range(6)) if monitoring.get_tool(i) is None)
    code = _adopt.__code__
    records = []

    def unwound(frame_code, offset, error):
        if frame_code is not code or not isinstance(error, RPCError) or len(records) >= 64:
            return
        frame = sys._getframe(1)
        while frame is not None and frame.f_code is not code:
            frame = frame.f_back
        if frame is None:
            return
        parent = frame.f_locals["parent"]
        marker = re.search(
            r"The limit on the total number of distinct updates in this workflow has been reached \(\d+\)\.",
            str(error),
        )
        record = {
            "run_id": parent["run_id"],
            "execution_epoch": parent["execution_epoch"],
            "operation": frame.f_locals["name"],
            "error_type": type(error).__name__,
            "status": error.status.name,
            "message_category": "distinct_update_limit" if marker else "other_rpc_error",
            "message": None if marker is None else marker.group(0),
        }
        records.append(record)
        path = directory / "parent-recovery-rpc-errors.jsonl"
        with path.open("a") as output:
            output.write(json.dumps(record) + "\n")
        path.chmod(0o600)

    monitoring.use_tool_id(tool, "ralf-parent-recovery-proof")
    try:
        monitoring.register_callback(tool, monitoring.events.PY_UNWIND, unwound)
        monitoring.set_events(tool, monitoring.events.PY_UNWIND)
        yield
    finally:
        monitoring.set_events(tool, 0)
        monitoring.register_callback(tool, monitoring.events.PY_UNWIND, None)
        monitoring.free_tool_id(tool)


@pytest.mark.parametrize("pressure", [False, True], ids=["normal", "2000-updates"])
def test_actual_original_coding_graph_stop_and_owned_close(tmp_path, monkeypatch, pressure):
    async def scenario():
        async with (
            coding_system(tmp_path, monkeypatch, kind="graph-sequential") as system,
            system.worker() as first_worker,
        ):
            await system.effect_ack_gate(True)
            gate = tmp_path / "hold-native-stop"
            gate.touch()
            original = await system.submit(*definition("graph-sequential")[:2])
            leaf, action_id = await system.approve(original.run_id)
            assert leaf != original.run_id
            await _eventually(
                lambda: asyncio.sleep(0, result=(tmp_path / "hold-native-stop.attempted").exists()),
                bool,
                seconds=80,
            )
            before = copy.deepcopy(system.lines("native-submissions.jsonl"))
            assert [r["method"] for r in before] == ["thread/start", "turn/start"]
            handle = system.client.get_workflow_handle(original.run_id)
            epoch = (await handle.describe()).run_id
            if pressure:
                # The scheduler pins the original child directly in History;
                # explicitly acknowledge that same existing execution once so
                # the pressure repeats an actually completed SDK receipt.
                parent = await system.view(original.run_id, "coding_composition_proof")
                child = await system.view(leaf, "coding_composition_proof")
                child_info = await system.client.get_workflow_handle(leaf).describe()
                assert (
                    child_info.run_id
                    == child_info.raw_info.first_run_id
                    == child["execution_epoch"]
                    == child["original_execution_epoch"]
                )
                assert child["namespace"] == parent["namespace"] == system.data["namespace"]
                request = {
                    **{
                        k: parent[k]
                        for k in (
                            "scope",
                            "run_id",
                            "execution_epoch",
                            "request_digest",
                            "release_digest",
                        )
                    },
                    "child_run_id": leaf,
                    "evidence": {
                        **{
                            k: child[k]
                            for k in (
                                "namespace",
                                "execution_epoch",
                                "original_execution_epoch",
                                "request_digest",
                            )
                        },
                        "parent_run_id": original.run_id,
                        "parent_execution_epoch": epoch,
                    },
                }
                assert len(json.dumps(request).encode()) < 4096
                assert await handle.execute_update("coding_composition_child_epoch", request) == {
                    "run_id": leaf,
                    "recorded": True,
                }
                started = asyncio.get_running_loop().time()
                history = await handle.fetch_history()
                epochs = [
                    event.workflow_execution_update_accepted_event_attributes.accepted_request
                    for event in history.events
                    if event.HasField("workflow_execution_update_accepted_event_attributes")
                    and event.workflow_execution_update_accepted_event_attributes.accepted_request.input.name
                    == "coding_composition_child_epoch"
                ]
                assert len(epochs) == 1
                (request,) = await system.client.data_converter.decode(
                    epochs[0].input.args.payloads
                )
                assert request["child_run_id"] == leaf
                accepted = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in history.events
                )
                assert 1 <= accepted < 2000
                for start in range(accepted, 2000, 8):
                    replies = await asyncio.gather(
                        *[
                            handle.execute_update("coding_composition_child_epoch", request)
                            for _ in range(start, min(start + 8, 2000))
                        ]
                    )
                    assert all(reply == {"run_id": leaf, "recorded": True} for reply in replies)
                history = await handle.fetch_history()
                accepted = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in history.events
                )
                completed = sum(
                    e.HasField("workflow_execution_update_completed_event_attributes")
                    for e in history.events
                )
                elapsed = asyncio.get_running_loop().time() - started
                assert accepted == completed == 2000 and elapsed < 30 and gate.exists()
                assert (await handle.describe()).run_id == epoch
                (tmp_path / "parent-pressure-history.json").write_text(history.to_json())
                (tmp_path / "parent-pressure.json").write_text(
                    json.dumps(
                        {
                            "run_id": original.run_id,
                            "leaf_run_id": leaf,
                            "original_execution_epoch": epoch,
                            "accepted_updates": accepted,
                            "completed_updates": completed,
                            "original_child_epoch_repeated": True,
                            "explicit_existing_child_ack": True,
                            "fill_payload_bytes": len(json.dumps(request).encode()),
                            "hold_gate_seconds_unchanged": 30,
                            "pressure_seconds": elapsed,
                        }
                    )
                )
            cancel = await system.engine.cancel(original.run_id, command_id="stop-original-graph")
            assert (
                await system.engine.cancel(original.run_id, command_id="stop-original-graph")
                == cancel
            )
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            gate.unlink()
            await _eventually(
                lambda: system.engine.events(leaf),
                lambda events: any(e.kind == "effect_journal_ack_deferred" for e in events),
                seconds=80,
            )
            await system.count(1)
            assert (await system.view(original.run_id, "deployment_closure"))["seal"] is None
            await system.effect_ack_gate(False)
            # The child History owns its deferred effect ACK. Waking only its
            # parent does not retry that independently retained obligation.
            await system.engine.drive(leaf, wait_seconds=0)
            details = await _eventually(
                lambda: system.view(leaf),
                lambda d: any(
                    a["id"] == action_id and a["status"] in {"completed", "outcome_unknown"}
                    for a in d["snapshot"]["actions"]
                ),
                seconds=80,
            )
            action = next(a for a in details["snapshot"]["actions"] if a["id"] == action_id)
            if action["status"] == "outcome_unknown":
                candidate = action["delegated_execution"].get("result_candidate")
                assert type(candidate) is dict
                captured = await system.capture()
                assert any(
                    item.get("kind") == "result_candidate" and item["result"] == candidate
                    for row in captured["ralf_temporal_runner_effects"]
                    for item in json.loads(row["record"])["observations"]
                )
                await system.engine.reconcile(
                    leaf, action_id, query=True, command_id="recover-original-graph-candidate"
                )
            # The original child notification advances its parent. An extra
            # parent drive can race that parent's irreversible seal; it is not
            # needed to recover the child's independently retained effect ACK.
            await system.count(0)
            closure = await system.evidence(original.run_id)
            assert closure["deployment"]["execution_epoch"] == epoch
            assert (await system.engine.status(original.run_id)).state == "cancelled"
            leaf_view = await system.view(leaf)
            action = next(a for a in leaf_view["snapshot"]["actions"] if a["id"] == action_id)
            assert action["status"] == "completed"
            assert system.lines("native-submissions.jsonl") == before
            captured = await system.capture()
            effects = captured["ralf_temporal_effects"]
            assert len(effects) == 1 and effects[0]["state"] == "adopted"
            assert effects[0]["adopted_result_digest"] == digest(action["result"])
            assert len(captured["ralf_temporal_effect_evidence"]) == 1
            await first_worker.shutdown()
            assert first_worker.is_shutdown and not first_worker.is_running
            restarted = build_temporal_worker(
                first_worker.config()["client"],
                task_queue=system.queue,
                runtime=system.runtime,
                release=system.release,
                graceful_shutdown_timeout=timedelta(seconds=1),
            )
            system.workers.append(restarted)
            async with restarted:
                assert (
                    await system.engine.cancel(original.run_id, command_id="stop-original-graph")
                    == cancel
                )
                await system.count(0)
                await system.evidence(original.run_id)
                assert system.lines("native-submissions.jsonl") == before
                try:
                    with observe_original_parent_rpc(tmp_path):
                        await system.assembly.aclose(wait_timeout=60)
                except Exception as error:
                    (tmp_path / "first-owned-close-error.json").write_text(
                        json.dumps(
                            {
                                "type": type(error).__name__,
                                "code": getattr(error, "code", None),
                                "report": getattr(error, "report", None),
                            }
                        )
                    )
                    raise
            (tmp_path / "parent-recovery.json").write_text(
                json.dumps(
                    {
                        "original_epoch": epoch,
                        "held_roots": 0,
                        "single_original_child": True,
                        "effect_adopted": True,
                        "physical_stopped": True,
                        "original_submissions_unchanged": True,
                        "worker_restarted": True,
                        "histories_replayed": True,
                        "owned_assembly_closed": True,
                        "model_api_calls": 0,
                        "structural_native_peer": True,
                    }
                )
            )

    asyncio.run(asyncio.wait_for(scenario(), 240))
