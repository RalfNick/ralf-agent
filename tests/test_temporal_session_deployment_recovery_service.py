"""Cold original Session recovery across a sealed claim and a lost retirement reply."""

import asyncio
import copy
import json
import os
import traceback
import uuid
from dataclasses import asdict
from datetime import timedelta
from urllib.parse import urlsplit

import pytest

from ralf_agent import (
    AgentSpec,
    DeploymentAdmissionPolicy,
    ModelResponse,
    Runtime,
    Scope,
    ToolRegistry,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_deployment_admission import registry_id, root_run_id
from ralf_agent.temporal_deployment_release import _binding
from ralf_agent.temporal_session_state import workflow_id
from ralf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_deployment_public_service import SDKFaultClient

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires externally owned Temporal Service"
)


def test_actual_cold_session_sealed_claim_and_lost_retirement_reply(tmp_path):
    async def scenario():
        from temporalio.client import WorkflowExecutionStatus

        address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
        assert urlsplit(address if "://" in address else "//" + address).hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        clients, namespace = await _clients()
        original_client = clients[0]
        first_client = SDKFaultClient(original_client, block_release=True)
        unique = "session-cold-retire-" + uuid.uuid4().hex
        scope = Scope("session-cold-retirement", unique)
        policy = DeploymentAdmissionPolicy(unique, max_active_root_runs=1)
        targets, workers, executions, facades = [], [], [], []

        class Provider:
            identity = {"kind": "offline-session-cold-retirement", "version": "1"}

            def __init__(self, cold=False):
                self.cold, self.calls = cold, []

            async def complete(self, messages, tools):
                assert not tools
                questions = [
                    message["content"]
                    for message in messages
                    if message["role"] == "user"
                    and message["content"] in {"first-question", "next-question"}
                ]
                assert len(questions) == 1
                question = questions[0]
                self.calls.append(copy.deepcopy(messages))
                if question == "first-question":
                    assert not self.cold, "Cold recovery must never repeat original business"
                    return ModelResponse(output="first-answer")
                assert question == "next-question" and self.cold
                return ModelResponse(output="next-answer")

        def execution(provider):
            value = TemporalRuntime(
                providers={"default": provider},
                tools=ToolRegistry(),
                enable_sessions=True,
                deployment_sessions=True,
                admission_policy=policy,
            )
            executions.append(value)
            return value

        def facade(client, value, queue=unique):
            engine = TemporalEngine(
                client,
                task_queue=queue,
                release=value.orchestration_release,
                scope=scope,
                activity_timeout=60,
            )
            result = Runtime.from_temporal(engine)
            facades.append(result)
            return engine, result

        async def query(client, target, kind, **fields):
            return await client.get_workflow_handle(target).query(
                "view",
                {"scope": asdict(scope), "kind": kind, **fields},
                rpc_timeout=timedelta(seconds=10),
            )

        async def inventory(client):
            return await query(
                client,
                registry_id(unique),
                "deployment_admission",
                admission_policy=policy.identity,
                namespace=namespace,
            )

        async def save_histories(client, stage):
            failures = []
            for index, identity in enumerate(dict.fromkeys([*targets, registry_id(unique)])):
                try:
                    history = await client.get_workflow_handle(identity).fetch_history(
                        rpc_timeout=timedelta(seconds=5)
                    )
                    (tmp_path / f"{stage}-history-{index}.json").write_text(history.to_json())
                except Exception as error:
                    failures.append({"workflow_id": identity, "type": type(error).__name__})
            (tmp_path / f"{stage}-history-read-errors.json").write_text(json.dumps(failures))

        initial_provider = Provider()
        first_execution = execution(initial_provider)
        first_engine, first_facade = facade(first_client, first_execution)
        definition = AgentSpec("cold-retirement", "Answer the question")
        command, open_command = "turn-" + unique, "open-" + unique
        latest_client = original_client
        primary, cleanup_errors, complete = None, [], False
        try:
            worker = build_temporal_worker(
                first_client,
                task_queue=unique,
                runtime=first_execution,
                graceful_shutdown_timeout=timedelta(seconds=1),
            )
            workers.append(worker)
            async with worker:
                session = await first_facade.open_session(
                    definition, unique, command_id=open_command
                )
                original_ref, open_receipt = session.ref, session.receipt
                coordinator_id = workflow_id(original_ref.key)
                root_command = "ralf-session-run:" + digest([original_ref.key.to_dict(), command])
                run_id = root_run_id(unique, asdict(scope), root_command)
                targets.extend([coordinator_id, run_id])
                coordinator_epoch = (
                    await original_client.get_workflow_handle(coordinator_id).describe()
                ).run_id
                run = await session.submit("first-question", command_id=command)
                assert (
                    await run.wait(wait_timeout=45, terminal_only=True)
                ).snapshot.state == "succeeded"
                await asyncio.wait_for(first_client.release_attempted.wait(), 20)
                await _eventually(
                    lambda: first_engine.events(run_id),
                    lambda events: (
                        sum(event.kind == "deployment_retirement_deferred" for event in events) >= 2
                    ),
                    seconds=40,
                )
                closure = await query(original_client, run_id, "deployment_closure")
                assert closure["ready"] is True and closure["seal"] is not None
                seal = copy.deepcopy(closure["seal"])
                assert (await inventory(original_client))["counts"]["held_root_runs"] == 1
                assert (await session.status()).busy and len(initial_provider.calls) == 1
                selector = {
                    "namespace": namespace,
                    "coordinator_execution_epoch": coordinator_epoch,
                    "session_command_id": command,
                    "turn_id": run.turn.turn_id,
                }
                intent = await query(
                    original_client, coordinator_id, "deployment_session_intent", **selector
                )
                original_start = await query(
                    original_client,
                    coordinator_id,
                    "deployment_session_start",
                    **selector,
                    intent_digest=intent["intent_digest"],
                )
                accepted = await query(
                    original_client,
                    registry_id(unique),
                    "deployment_session_root",
                    admission_policy=policy.identity,
                    namespace=namespace,
                    command_id=root_command,
                    payload_digest=digest(intent["submission"]["request"]),
                )
                assert accepted["intent"] == intent and original_start["phase"] == "started"
                assert accepted["submission"] == intent["submission"]
                await save_histories(original_client, "sealed-held-before-cold")
                (tmp_path / "sealed-held-identity.json").write_text(
                    json.dumps(
                        {
                            "session_ref": original_ref.to_dict(),
                            "turn": run.turn.to_dict(),
                            "intent": intent,
                            "start": original_start,
                            "accepted": accepted,
                            "seal": seal,
                            "coordinator_epoch": coordinator_epoch,
                            "counts": (await inventory(original_client))["counts"],
                        },
                        sort_keys=True,
                    )
                )
            assert worker.is_shutdown
            await first_facade.aclose()

            # No original Runtime, Worker, facade or Client is reused for recovery.
            cold_clients, cold_namespace = await _clients()
            cold_client = SDKFaultClient(cold_clients[0], lose="release")
            latest_client = cold_clients[0]
            cold_provider = Provider(cold=True)
            cold_execution = execution(cold_provider)
            assert (
                cold_execution is not first_execution
                and cold_client.original is not original_client
            )
            assert cold_namespace == namespace
            assert cold_execution.orchestration_release == first_execution.orchestration_release
            cold_engine, cold_facade = facade(cold_client, cold_execution)
            assert cold_engine is not first_engine and cold_facade is not first_facade
            restarted = build_temporal_worker(
                cold_client,
                task_queue=unique,
                runtime=cold_execution,
                graceful_shutdown_timeout=timedelta(seconds=1),
            )
            workers.append(restarted)
            async with restarted:
                restored = await cold_facade.aattach_session(original_ref)
                assert (await restored.status()).busy
                assert (await inventory(cold_client))["counts"]["held_root_runs"] == 1
                assert (await cold_engine.drive(run_id, wait_seconds=0)).state == "succeeded"
                await _eventually(
                    lambda: asyncio.sleep(0, result=cold_client.dropped), bool, seconds=30
                )
                assert cold_client.dropped == [
                    {"kind": "release", "workflow_id": registry_id(unique)}
                ]
                await _eventually(
                    lambda: inventory(cold_client),
                    lambda value: value["counts"]["held_root_runs"] == 0,
                    seconds=30,
                )
                root = closure["deployment"]["admission_receipt"]["root"]
                retirement = await query(
                    cold_client,
                    registry_id(unique),
                    "deployment_retirement",
                    **{
                        key: value
                        for key, value in _binding(root, policy.identity, seal).items()
                        if key != "scope"
                    },
                )
                assert retirement == {"root": root, "certificate": seal, "released": True}
                replay = await restored.submit("first-question", command_id=command)
                assert (
                    replay.ref == run.ref
                    and replay.turn == run.turn
                    and replay.receipt == run.receipt
                )
                await _eventually(restored.status, lambda status: not status.busy, seconds=45)
                assert cold_provider.calls == [] and len(initial_provider.calls) == 1
                assert (
                    await cold_client.get_workflow_handle(coordinator_id).describe()
                ).run_id == coordinator_epoch
                actual = await cold_client.get_workflow_handle(run_id).describe()
                assert (
                    actual.run_id
                    == original_start["execution_epoch"]
                    == actual.raw_info.first_run_id
                )
                assert (actual.parent_id, actual.parent_run_id) == (
                    coordinator_id,
                    coordinator_epoch,
                )
                after = await query(
                    cold_client,
                    registry_id(unique),
                    "deployment_session_root",
                    admission_policy=policy.identity,
                    namespace=namespace,
                    command_id=root_command,
                    payload_digest=digest(intent["submission"]["request"]),
                )
                assert (
                    after == accepted
                    and (await query(cold_client, run_id, "deployment_closure"))["seal"] == seal
                )
                assert (
                    await cold_facade.open_session(definition, unique, command_id=open_command)
                ).receipt == open_receipt
                assert len(await restored.turns()) == 1

                # The following Turn exposes exactly one adopted conversation pair.
                second = await restored.submit("next-question", command_id="next-" + unique)
                targets.append(second.ref.run_id)
                next_intent = await query(
                    cold_client,
                    coordinator_id,
                    "deployment_session_intent",
                    namespace=namespace,
                    coordinator_execution_epoch=coordinator_epoch,
                    session_command_id="next-" + unique,
                    turn_id=second.turn.turn_id,
                )
                assert next_intent["submission"]["request"]["session_history"] == [
                    {"role": "user", "content": "first-question"},
                    {"role": "assistant", "content": "first-answer"},
                ]
                assert (
                    await second.wait(wait_timeout=45, terminal_only=True)
                ).snapshot.state == "succeeded"
                await _eventually(restored.status, lambda status: not status.busy, seconds=45)
                assert len(cold_provider.calls) == 1 and len(initial_provider.calls) == 1
                assert len(await restored.turns()) == 2
                assert (await inventory(cold_client))["counts"]["held_root_runs"] == 0
                await save_histories(cold_client, "cold-recovered")
                (tmp_path / "cold-recovery-result.json").write_text(
                    json.dumps(
                        {
                            "cold_runtime": True,
                            "cold_client": True,
                            "same_original_identity": True,
                            "original_intent": intent,
                            "accepted": accepted,
                            "retirement": retirement,
                            "lost_completed_replies": cold_client.dropped,
                            "next_history": next_intent["submission"]["request"]["session_history"],
                            "provider_calls": [
                                len(initial_provider.calls),
                                len(cold_provider.calls),
                            ],
                            "held_root_runs": 0,
                        },
                        sort_keys=True,
                    )
                )
                complete = True
        except BaseException as error:
            primary = error
            (tmp_path / "primary-traceback.txt").write_text(
                "".join(traceback.format_exception(error))
            )
            await save_histories(latest_client, "failure-retained")
        finally:
            for value in facades:
                try:
                    await value.aclose()
                except BaseException as error:
                    cleanup_errors.append(error)
            for value in executions:
                try:
                    await value.close_deployment_execution(wait_timeout=15)
                except BaseException as error:
                    cleanup_errors.append(error)
        if primary is not None:
            if cleanup_errors:
                raise BaseExceptionGroup(
                    "Cold recovery primary and owned close errors", [primary, *cleanup_errors]
                )
            raise primary.with_traceback(primary.__traceback__)
        if cleanup_errors:
            raise BaseExceptionGroup("Cold recovery owned close errors", cleanup_errors)
        assert complete and all(worker.is_shutdown for worker in workers)
        # Only successful, positively retired test-owned Histories are terminated.
        for identity in [*targets, registry_id(unique)]:
            handle = latest_client.get_workflow_handle(identity)
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(
                    reason="completed cold Session retirement recovery acceptance"
                )

    asyncio.run(asyncio.wait_for(scenario(), timeout=210))
