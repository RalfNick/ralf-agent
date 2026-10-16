"""A current end client positively recognizes an immutable old original Worker."""

import asyncio
import copy
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from ralf_agent.temporal_execution_end_transport import execute
from ralf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("public", [False, True], ids=["end", "public-lifecycle"])
def test_actual_end_client_reuses_original_legacy_end_id_without_signals(tmp_path, public):
    variable = "RALF_TEST_LIFECYCLE_LEGACY_PYTHON" if public else "RALF_TEST_END_LEGACY_PYTHON"
    python = os.getenv(variable)
    if not python:
        pytest.skip("requires immutable original end-ACK Worker Python")
    assert Path(python).is_file()

    async def run():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        clients, namespace = await _clients()
        client, queue = clients[0], "end-legacy-" + uuid.uuid4().hex
        scope = Scope("execution-end-legacy", queue)
        generation = "legacy-owner"
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "RALF_TEST_TEMPORAL_ADDRESS")
            if key in os.environ
        }
        environment.update(RALF_TEST_TEMPORAL_NAMESPACE=namespace["name"], RALF_TEST_END_OWNER="1")
        if public:
            environment["RALF_TEST_END_PUBLIC"] = "1"
        process, engine, failure = None, None, None
        owned, closed, absent, facts = set(), [], [], None

        async def stop():
            if process is None:
                return
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise AssertionError("Legacy owned Worker did not drain") from None
            assert process.returncode == 0
            receipt = json.loads((tmp_path / f"closed-{generation}.json").read_text())
            assert receipt["worker_shutdown"] is True
            assert receipt["tool_owner_drained"] is receipt["tool_owner_closed"] is True
            if public:
                assert receipt["public_owner_closed"] is True
            assert Path(receipt["package_file"]).is_relative_to(Path(python).parent.parent)

        try:
            with (tmp_path / "worker.log").open("w") as out:
                process = await asyncio.create_subprocess_exec(
                    python,
                    "-I",
                    str(Path(__file__).with_name("unowned_tool_end_worker.py")),
                    queue,
                    str(tmp_path),
                    generation,
                    env=environment,
                    stdout=out,
                    stderr=out,
                )
            async with asyncio.timeout(15):
                while not (tmp_path / f"ready-{generation}.json").exists():
                    assert process.returncode is None, "Legacy Worker exited before readiness"
                    await asyncio.sleep(0.02)
            ready = json.loads((tmp_path / f"ready-{generation}.json").read_text())
            assert Path(ready["package_file"]).is_relative_to(Path(python).parent.parent)
            assert ready["end_transport_available"] is public
            if public:
                assert ready["lifecycle_transport_available"] is False
            release = ready["release"]
            assert release["tool_execution_protocol"]["owner"]["behavior_version"] == "end-compat-1"
            if public:
                # Old selected publications require their matching SDK and
                # Worker. Only the new mechanical helper runs in this process.
                target, registry_id = ready["run_id"], ready["registry_id"]
            else:
                engine = TemporalEngine(
                    client, task_queue=queue, release=release, scope=scope, activity_timeout=30
                )
                target = "ralf-temporal-" + digest([asdict(scope), "original"])
                registry_id = engine.command_registry_id
            owned.update({target, registry_id})
            identities = {
                "scope": asdict(scope),
                "namespace": namespace,
                "run_id": target,
                "registry_id": registry_id,
                "worker_python": python,
            }
            (tmp_path / "original-identities.json").write_text(json.dumps(identities))
            if not public:
                receipt = await engine.submit(
                    AgentSpec("reader", "Read", tools=("slow", "fast"), max_decisions=2),
                    "task",
                    command_id="original",
                    budget=32,
                )
                assert receipt.run_id == target
            async with asyncio.timeout(10):
                while not (tmp_path / "slow-started").exists():  # noqa: ASYNC110 -- peer process receipt
                    assert process.returncode is None
                    await asyncio.sleep(0.02)
            assert not (tmp_path / "slow-ended").exists()
            (tmp_path / "release-slow").touch()
            if public:
                async with asyncio.timeout(25):
                    while not (tmp_path / "public-original-evidence.json").exists():
                        assert process.returncode is None
                        assert not (tmp_path / "public-task-error.json").exists()
                        await asyncio.sleep(0.02)
                evidence = json.loads((tmp_path / "public-original-evidence.json").read_text())
                assert evidence["run_id"] == target and evidence["registry_id"] == registry_id
                assert evidence["state"] == "succeeded" and evidence["quiescent"] is True
                assert evidence["registry"]["counts"]["held_root_runs"] == 0
                assert evidence["matching_old_worker_replayed_run_and_registry"] is True
                assert Path(evidence["package_file"]).is_relative_to(Path(python).parent.parent)
                records, actions = evidence["tool_executions"], evidence["actions"]
                closure = evidence["closure"]
                assert closure["seal"] is not None and all(
                    record["stopped"] for record in closure["calls"].values()
                )
            else:
                finished = await _eventually(
                    lambda: engine.diagnostics(target),
                    lambda value: (
                        value.snapshot.state == "succeeded" and value.workflow["quiescent"]
                    ),
                    seconds=15,
                )
                records, actions = finished.workflow["tool_executions"], finished.snapshot.actions
            assert len(records) == 2 and all(
                value["execution_stopped"] is True for value in records
            )
            actions = [action for action in actions if action["kind"] == "tool"]
            assert len(actions) == 2 and {action["tool"] for action in actions} == {"slow", "fast"}
            slow = next(action for action in actions if action["tool"] == "slow")
            proof = next(
                value["end_proof"] for value in records if value["action_id"] == slow["id"]
            )
            original_proof = copy.deepcopy(proof)
            epoch = proof["execution_epoch"]
            handle = client.get_workflow_handle(target, run_id=epoch)
            description = await handle.describe()
            assert description.run_id == description.raw_info.first_run_id == epoch
            identities["execution_epoch"] = epoch
            identities["slow_end_proof_digest"] = digest(proof)
            (tmp_path / "original-identities.json").write_text(json.dumps(identities))
            if public:
                from ralf_agent.temporal_deployment_lifecycle_transport import execute as lifecycle

                before = await handle.fetch_history()
                accepted_before = [
                    event.workflow_execution_update_accepted_event_attributes.accepted_request.meta.update_id
                    for event in before.events
                    if event.HasField("workflow_execution_update_accepted_event_attributes")
                ]
                actual = next(
                    record["identity"]
                    for record in closure["calls"].values()
                    if record["identity"]["activity_id"] == slow["attempts"][0]["id"]
                )
                assert actual["run_id"] == target and actual["execution_epoch"] == epoch
                payload = {"scope": asdict(scope), "children": closure["seal"]["children"]}
                begin_id = "ralf-deployment-call:" + digest(actual)
                seal_id = "ralf-deployment-seal:" + digest(payload)
                assert accepted_before.count(begin_id) == accepted_before.count(seal_id) == 1
                for _ in range(2):
                    assert await lifecycle(
                        client,
                        target,
                        "deployment_call_started",
                        actual,
                        execution_epoch=epoch,
                        legacy_update_id=begin_id,
                    ) == {
                        key: actual[key] for key in ("activity_id", "attempt", "invocation_id")
                    } | {"allowed": True}
                    assert (
                        await lifecycle(
                            client,
                            target,
                            "deployment_seal",
                            payload,
                            execution_epoch=epoch,
                            legacy_update_id=seal_id,
                        )
                        == closure["seal"]
                    )
                after = await handle.fetch_history()
                accepted_after = [
                    event.workflow_execution_update_accepted_event_attributes.accepted_request.meta.update_id
                    for event in after.events
                    if event.HasField("workflow_execution_update_accepted_event_attributes")
                ]
                assert accepted_after == accepted_before
                assert not any(
                    event.HasField("workflow_execution_signaled_event_attributes")
                    and event.workflow_execution_signaled_event_attributes.signal_name
                    == "deployment_lifecycle"
                    for event in after.events
                )
                (tmp_path / "lifecycle-after-history.json").write_text(after.to_json())
                (tmp_path / "lifecycle-compatibility.json").write_text(
                    json.dumps(
                        {
                            "begin_update_id": begin_id,
                            "seal_update_id": seal_id,
                            "accepted_before": len(accepted_before),
                            "accepted_after": len(accepted_after),
                            "current_sdk_accepts_old_selected": False,
                            "old_worker_replay": True,
                        }
                    )
                )
            else:
                for _ in range(2):
                    assert await execute(
                        client,
                        target,
                        "tool_execution_ended",
                        proof,
                        execution_epoch=epoch,
                        legacy_update_id="ralf-tool-ended:" + digest(proof),
                    ) == {"action_id": slow["id"], "recorded": True}
            assert proof == original_proof
            if not public:
                final = await engine.diagnostics(target)
                assert final.snapshot.state == "succeeded" and final.workflow["quiescent"]
                assert final.workflow["tool_executions"] == records
            history = await handle.fetch_history()
            end_updates = [
                event.workflow_execution_update_accepted_event_attributes.accepted_request
                for event in history.events
                if event.HasField("workflow_execution_update_accepted_event_attributes")
                and event.workflow_execution_update_accepted_event_attributes.accepted_request.input.name
                == "tool_execution_ended"
            ]
            if not public:
                assert len(end_updates) == 2
                assert (
                    sum(
                        request.meta.update_id == "ralf-tool-ended:" + digest(proof)
                        for request in end_updates
                    )
                    == 1
                )
                assert not any(
                    event.HasField("workflow_execution_signaled_event_attributes")
                    and event.workflow_execution_signaled_event_attributes.signal_name
                    == "execution_ended"
                    for event in history.events
                )
            calls = [
                json.loads(line)
                for line in (tmp_path / "tool-calls.jsonl").read_text().splitlines()
            ]
            assert sorted(calls, key=lambda value: value["tool"]) == [
                {"tool": "fast"},
                {"tool": "slow"},
            ]
            assert (tmp_path / "slow-ended").exists() and (tmp_path / "fast-returned").exists()
            (tmp_path / "original-run-history.json").write_text(history.to_json())
            if not public:
                await replay_temporal_history(history, namespace=namespace["name"])
            facts = {
                "original_epoch": epoch,
                "original_end_updates": len(end_updates),
                "original_end_facts": len(records),
                "current_client_retries": 4 if public else 2,
                "compatibility": "public-lifecycle-helper" if public else "original-end-fallback",
                "execution_end_signals": sum(
                    event.HasField("workflow_execution_signaled_event_attributes")
                    and event.workflow_execution_signaled_event_attributes.signal_name
                    == "execution_ended"
                    for event in history.events
                ),
                "deployment_lifecycle_signals": 0,
                "business_tool_calls": 2,
                "original_proof_unchanged": True,
                "succeeded_and_quiescent": True,
                "original_run_replayed": True,
                "external_model_calls": 0,
                "capacity_gate_tested": False,
            }
        except BaseException as exc:
            failure = exc
        finally:
            failures = [failure] if failure is not None else []
            (tmp_path / "release-slow").touch()
            if (tmp_path / "slow-started").exists():
                try:
                    async with asyncio.timeout(5):
                        while not (tmp_path / "slow-ended").exists():  # noqa: ASYNC110 -- peer process receipt
                            await asyncio.sleep(0.02)
                except BaseException as exc:
                    failures.append(exc)
            try:
                await stop()
            except BaseException as exc:
                failures.append(exc)
            for index, target in enumerate(sorted(owned)):
                handle = client.get_workflow_handle(target)
                try:
                    history = await handle.fetch_history()
                    (tmp_path / f"retained-history-{index}.json").write_text(history.to_json())
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
                try:
                    if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await handle.terminate(
                            reason="owned execution end legacy compatibility cleanup"
                        )
                    assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                    closed.append(target)
                except RPCError as exc:
                    if exc.status == RPCStatusCode.NOT_FOUND:
                        absent.append(target)
                    else:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
            if engine is not None:
                try:
                    await engine.aclose()
                except BaseException as exc:
                    failures.append(exc)
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "owned": sorted(owned),
                        "closed": closed,
                        "not_found": absent,
                        "worker_shutdown": process is not None and process.returncode == 0,
                        "original_thread_ended": (tmp_path / "slow-ended").exists(),
                        "body_failed": failure is not None,
                        "cleanup_failed": len(failures) > int(failure is not None),
                    }
                )
            )
            if failures:
                raise BaseExceptionGroup("Original legacy end and owned cleanup", failures)
            assert facts is not None and set(closed) == owned and not absent
            (tmp_path / "result.json").write_text(json.dumps(facts, indent=2))

    asyncio.run(asyncio.wait_for(run(), 60))
