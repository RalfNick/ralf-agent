"""Actual Worker loss/recovery/replay using committed fixture receipts."""

import asyncio
import copy
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import RunRef, Runtime, Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from ralf_agent.types import digest
from tests.temporal_parent_completion_worker import SESSION_WINDOWS, runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "kind,window",
    [
        ("team-pure", "approval"),
        ("plan", "receipt"),
        ("dag", "proposal"),
        ("team-reject", "proposal"),
        ("team", "cancel-receipt"),
        ("team", "final-session"),
        ("team", "lost-session-ack"),
    ],
)
def test_parent_verdict_child_receipts_and_session_survive_real_worker_loss(tmp_path, kind, window):
    asyncio.run(asyncio.wait_for(recover(tmp_path, kind, window), 150))


async def recover(root, kind, window):
    from temporalio.client import Client

    import ralf_agent

    address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
    queue = "parent-completion-" + uuid.uuid4().hex
    client = await Client.connect(address)
    execution, definition, clients, backend = runtime(root, kind, window=window)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-parent-completion", queue),
        activity_timeout=10 if window == "lost-session-ack" else 3,
    )
    host, processes, session = Runtime.from_temporal(engine), [], None
    lost_write_request, lost_write_before = None, None
    (root / "host-manifest.json").write_text(
        json.dumps(execution.orchestration_release, indent=2) + "\n"
    )

    def lifecycle(row):
        value = {"address": address, "queue": queue, "kind": kind, "window": window, **row}
        with (root / "parent-worker-lifecycle.jsonl").open("a") as output:
            output.write(json.dumps(value) + "\n")
        target = os.environ.get("RALF_DEV92_TEMPORAL_LIFECYCLE_FILE")
        if target:
            with Path(target).open("a") as output:
                output.write(json.dumps(value) + "\n")

    async def start(mode):
        log = root / ("parent-worker-" + mode + ".log")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_PARENT_COMPLETION_ROOT": str(root),
            "RALF_PARENT_COMPLETION_KIND": kind,
            "RALF_PARENT_COMPLETION_WINDOW": window,
            "RALF_PARENT_COMPLETION_MODE": mode,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_parent_completion_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        lifecycle({"phase": "worker-started", "mode": mode, "pid": process.pid})
        async with asyncio.timeout(25):
            while "TEMPORAL_PARENT_COMPLETION_READY" not in log.read_text():  # noqa: ASYNC110 -- actual Worker readiness
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
        return process

    async def diagnostics(run_id):
        return await client.get_workflow_handle(run_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )

    def audit():
        return [json.loads(line) for line in (root / "parent-audit.jsonl").read_text().splitlines()]

    try:
        original = await start("original")
        if window in SESSION_WINDOWS:
            session = await host.open_session(definition, "checked", command_id="open")
            run = await session.submit({"quantity": 3}, command_id="turn", budget=20)
        else:
            run = await host.submit(
                definition, {"quantity": 3}, command_id="submit-" + queue, budget=20
            )
        async with asyncio.timeout(35):
            while True:
                pending = await run.pending()
                if pending and window != "approval":
                    item = pending[0]
                    leaf = await host.aattach(RunRef.from_dict(item["ref"]))
                    receipt = await leaf.approve(
                        item["action_id"], item["digest"], command_id="approval"
                    )
                    assert (
                        await leaf.approve(item["action_id"], item["digest"], command_id="approval")
                        == receipt
                    )
                if window == "approval" and pending:
                    checkpoint_id = run.ref.run_id
                    break
                if (
                    window == "lost-session-ack"
                    and lost_write_before is None
                    and (root / "session-ack-lost").exists()
                ):
                    original_write = json.loads(
                        (root / "session-lost-ack-write-request.json").read_text()
                    )
                    current = await diagnostics(run.ref.run_id)
                    write = next(
                        (
                            a
                            for a in current["snapshot"]["actions"]
                            if a["id"] == original_write["action_id"]
                        ),
                        None,
                    )
                    if write is not None and write["status"] == "outcome_unknown":
                        proof = json.loads((root / "session-lost-ack-end-proof.json").read_text())
                        assert proof == {
                            "scope": asdict(engine.scope),
                            "action_id": write["id"],
                            "request_digest": digest(original_write),
                            "release_digest": current["release_digest"],
                        }
                        assert write["request_digest"] == proof["request_digest"]
                        assert write["execution_end_proof"] == proof
                        assert write["dispatch_grant"]["allowed"] is True
                        assert write["response"] == {
                            "ok": False,
                            "code": "activity_outcome_unknown",
                            "dispatched": True,
                            "execution_stopped": False,
                        }
                        assert "revision" not in write["response"]
                        assert current["snapshot"]["state"] == "waiting_reconciliation"
                        assert (
                            current["budget"]["unknown"] == 1 and current["budget"]["reserved"] == 0
                        )
                        assert original_write["phase"] == "session-write"
                        assert original_write["session_lineage"]["root_run_id"] == run.ref.run_id
                        intent = original_write["intent"]
                        committed = backend.inspect_message(
                            engine.scope, intent["address"], intent["message_id"]
                        )
                        assert committed["receipt"] == {
                            "revision": intent["expected_revision"] + 1,
                            "message": intent["message"],
                        }
                        actual_result = json.loads(
                            (root / "session-lost-ack-write-result.json").read_text()
                        )
                        assert actual_result == {
                            "ok": True,
                            "revision": committed["receipt"]["revision"],
                            "dispatched": True,
                            "execution_stopped": True,
                        }
                        lost_write_request, lost_write_before = original_write, copy.deepcopy(write)
                        (root / "lost-session-ack-before-recovery.json").write_text(
                            json.dumps(
                                {
                                    "diagnostics": current,
                                    "original_write_request": original_write,
                                    "actual_receipt": committed,
                                    "actual_end_proof": proof,
                                    "discarded_activity_result": actual_result,
                                },
                                indent=2,
                            )
                            + "\n"
                        )
                        lifecycle(
                            {
                                "phase": "session-ack-lost-confirmed",
                                "root_run_id": run.ref.run_id,
                                "action_id": write["id"],
                                "request_digest": write["request_digest"],
                            }
                        )
                        # Original SDK control asks History to retry_blocked.
                        # It inspects the committed receipt, never replays append.
                        await engine.drive(run.ref.run_id, wait_seconds=0)
                if (root / "checkpoint").exists():
                    checkpoint_id = (root / "checkpoint").read_text()
                    break
                assert (await run.status()).state not in {"failed", "succeeded"}, (
                    await run.diagnostics()
                )
                assert original.poll() is None, (root / "parent-worker-original.log").read_text()
                await asyncio.sleep(0.05)
        parent_before = await diagnostics(run.ref.run_id)
        checkpoint = await diagnostics(checkpoint_id)
        (root / "parent-checkpoint-diagnostics.json").write_text(
            json.dumps(parent_before, indent=2) + "\n"
        )
        (root / "node-checkpoint-diagnostics.json").write_text(
            json.dumps(checkpoint, indent=2) + "\n"
        )
        stage = parent_before.get("parent_completion_stages", {}).get("r0")
        expected = {
            "receipt": "child_pending",
            "cancel-receipt": "child_pending",
            "proposal": "proposal_received",
            "final-session": "adopted",
            "lost-session-ack": "adopted",
        }
        if window in expected:
            assert stage["status"] == expected[window], parent_before
            assert len(stage["source"]["receipts"]) == 1
            tool = stage["source"]["receipts"][0]
            assert tool["arguments"] == {"quantity": 3, "price": 2} and tool["result"] == {
                "amount": 6
            }
            assert tool["consumed_by"] and stage["source"]["children"][0]["input_consumed"] is True
            assert stage["child_key"] == "r0.verifier.verdict"
        if window in {"receipt", "cancel-receipt"}:
            model = next(a for a in checkpoint["snapshot"]["actions"] if a["kind"] == "model")
            assert (
                model["status"] == "received"
                and model["received_response"]["continuation"]["protocol"]
                == "openai-responses-reasoning-v1"
            )
            assert checkpoint["budget"]["spent"] == 1 and checkpoint["budget"]["unknown"] == 0
        if window in SESSION_WINDOWS:
            request = json.loads((root / "session-checkpoint-request.json").read_text())
            assert checkpoint_id == request["run_id"] == run.ref.run_id
            assert request["phase"] == "adopt"
            assert request["session_lineage"]["root_run_id"] == run.ref.run_id
            assert parent_before["snapshot"]["state"] == (
                "waiting_reconciliation" if window == "lost-session-ack" else "running"
            )
            assert stage["adopted_verdict"]["status"] == "accept"
            operations = [
                a for a in parent_before["snapshot"]["actions"] if a["kind"] == "managed_session"
            ]
            assert [a["phase"] for a in operations] == [
                "inspect",
                "session-write",
                "verify",
                "adopt",
            ]
            assert all(
                a["status"] == "completed"
                for a in operations[:-1]
                if window != "lost-session-ack" or a["phase"] != "session-write"
            )
            assert operations[-1]["status"] == "executing"
            assert operations[-1]["id"] == request["action_id"]
            assert operations[-1]["request_digest"] == digest(request)
            intent, inspection = request["intent"], request["received_inspection"]
            assert intent["source_kind"] == "parent-aggregate" and intent["node"] == "root"
            assert intent["run_id"] == run.ref.run_id
            assert inspection == operations[-2]["response"]["inspection"]
            assert inspection["message_id"] == intent["message_id"]
            assert (
                inspection["receipt"]["message"]
                == intent["message"]
                == {
                    "role": "assistant",
                    "task": {"quantity": 3},
                    "content": {"amount": 6},
                }
            )
            assert inspection["receipt"]["revision"] == intent["expected_revision"] + 1
            if window == "lost-session-ack":
                assert lost_write_request is not None and lost_write_before is not None
                assert operations[1] == lost_write_before
                assert operations[1]["status"] == "outcome_unknown"
                assert operations[1]["response"]["ok"] is False
                assert "revision" not in operations[1]["response"]
                assert operations[1]["execution_end_proof"]["request_digest"] == digest(
                    lost_write_request
                )
                assert request["intent"] == lost_write_request["intent"]
                assert parent_before["budget"]["unknown"] == 1
            else:
                assert operations[1]["response"]["execution_stopped"] is True
                assert operations[1]["response"]["revision"] == inspection["receipt"]["revision"]
            assert (await session.status()).busy
        lifecycle(
            {
                "phase": "checkpoint",
                "root_run_id": run.ref.run_id,
                "node_run_id": checkpoint_id,
                "stage": None if stage is None else stage["status"],
            }
        )
        if window == "cancel-receipt":
            await run.cancel(command_id="cancel")
            assert (await run.status()).state == "cancelled"
        original.kill()
        await asyncio.to_thread(original.wait, timeout=5)
        lifecycle(
            {
                "phase": "worker-killed",
                "mode": "original",
                "pid": original.pid,
                "returncode": original.returncode,
            }
        )
        await host.aclose()
        host = Runtime.from_temporal(engine)
        recovered = await start("recover")
        assert recovered.pid != original.pid
        run = await host.aattach(run.ref)
        if window == "approval":
            pending = await run.pending()
            item = pending[0]
            leaf = await host.aattach(RunRef.from_dict(item["ref"]))
            receipt = await leaf.approve(item["action_id"], item["digest"], command_id="approval")
            assert (
                await leaf.approve(item["action_id"], item["digest"], command_id="approval")
                == receipt
            )
        expected_state = (
            "cancelled"
            if window == "cancel-receipt"
            else "failed"
            if kind == "team-reject"
            else "succeeded"
        )
        async with asyncio.timeout(55):
            while True:
                final = await diagnostics(run.ref.run_id)
                if final["snapshot"]["state"] == expected_state and final["workflow"]["quiescent"]:
                    break
                assert final["snapshot"]["state"] in {
                    "running",
                    "queued",
                    "waiting_approval",
                    *({"waiting_reconciliation"} if window == "lost-session-ack" else set()),
                    expected_state,
                }, final
                await asyncio.sleep(0.1)
        assert final["budget"]["reserved"] == final["budget"]["unknown"] == 0
        assert len(final["workflow"]["children"]) == (
            1 if kind == "team-pure" else 3 if kind == "plan" else 2
        )
        if expected_state == "succeeded":
            assert final["snapshot"]["result"] == {"amount": 6}
        stages = final["parent_completion_stages"]
        if window != "cancel-receipt":
            assert stages["r0"]["status"] == "adopted"
        if stage is not None:
            for name in (
                "source",
                "source_digest",
                "prepared_input",
                "child_key",
                "child_run_id",
                "child_release_digest",
            ):
                assert stages["r0"][name] == stage[name]
        rows = audit()
        assert len([r for r in rows if r["kind"] == "model" and r["provider"] == "business"]) == 2
        assert len(
            [r for r in rows if r["kind"] == "model" and r["provider"] == "verifier"]
        ) == int(kind != "team-pure")
        assert len([r for r in rows if r["kind"] == "tool"]) == 1
        assert len([r for r in rows if r["kind"] == "model" and r["provider"] == "planner"]) == int(
            kind == "plan"
        )
        assert final["budget"]["spent"] == 3 + int(kind != "team-pure") + int(
            window in SESSION_WINDOWS
        ) * 2 + int(kind == "plan")
        run_ids = {run.ref.run_id, *(c["run_id"] for c in final["workflow"]["children"])}
        if session is not None:
            session = await host.aattach_session(session.ref)
            async with asyncio.timeout(20):
                while (await session.status()).busy:  # noqa: ASYNC110 -- original Session publication
                    await asyncio.sleep(0.1)
            from ralf_agent.temporal_session_state import workflow_id

            run_ids.add(workflow_id(session.ref.key))
            if window == "lost-session-ack":
                intent = lost_write_request["intent"]
                writes = [
                    a for a in final["snapshot"]["actions"] if a.get("phase") == "session-write"
                ]
                assert len(writes) == 1 and writes[0]["id"] == lost_write_before["id"]
                assert writes[0]["status"] == "completed"
                assert writes[0]["response"] == lost_write_before["response"]
                assert writes[0]["execution_end_proof"] == lost_write_before["execution_end_proof"]
                assert "revision" not in writes[0]["response"]
                actual_receipt = backend.inspect_message(
                    engine.scope, intent["address"], intent["message_id"]
                )
                assert actual_receipt["receipt"] == inspection["receipt"]
                revision, records = backend.read(engine.scope, session.ref.key.storage_key)
                assert revision == 1 and records == [intent["message"]]
                appends = [
                    row
                    for row in rows
                    if row["kind"] == "session-append-attempt"
                    and row["message_id"] == intent["message_id"]
                ]
                commits = [
                    row
                    for row in rows
                    if row["kind"] == "session-append-committed"
                    and row["message_id"] == intent["message_id"]
                ]
                assert len(appends) == len(commits) == 1
                assert appends[0]["address"] == commits[0]["address"] == intent["address"]
                assert appends[0]["message"] == commits[0]["message"] == intent["message"]
                assert commits[0]["revision"] == intent["expected_revision"] + 1
                (root / "lost-session-ack-final-proof.json").write_text(
                    json.dumps(
                        {
                            "original_write_action": lost_write_before,
                            "final_write_action": writes[0],
                            "receipt": actual_receipt,
                            "session_revision": revision,
                            "records": records,
                            "append_attempts": appends,
                            "append_commits": commits,
                        },
                        indent=2,
                    )
                    + "\n"
                )
        assert len(run_ids) == (
            2 if kind == "team-pure" else 4 if kind == "plan" or session is not None else 3
        )
        before_replay = copy.deepcopy(audit())
        for run_id in run_ids:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
            lifecycle({"phase": "history-replayed", "run_id": run_id})
        assert audit() == before_replay
        recovered.terminate()
        await asyncio.to_thread(recovered.wait, timeout=12)
        assert recovered.returncode == 0, (root / "parent-worker-recover.log").read_text()
        assert (root / "worker-closed-recover").read_text() == "closed"
        lifecycle(
            {
                "phase": "worker-stopped",
                "mode": "recover",
                "pid": recovered.pid,
                "returncode": recovered.returncode,
            }
        )
    finally:
        await host.aclose()
        for process in processes:
            if process.poll() is None:
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            lifecycle(
                {"phase": "worker-reaped", "pid": process.pid, "returncode": process.returncode}
            )
        await execution.close_context_execution(wait_timeout=5)
        await execution.close_session_execution(wait_timeout=5)
        for provider_client in clients:
            await provider_client.aclose()
        if backend is not None:
            backend.store.close()
        await engine.aclose()
