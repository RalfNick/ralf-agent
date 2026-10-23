"""One real-SDK S1 acceptance; externally owned Service, offline structured Provider."""

import asyncio
import json
import os
import traceback
import uuid
from dataclasses import asdict
from datetime import timedelta
from urllib.parse import urlsplit

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    DeploymentAdmissionPolicy,
    ModelResponse,
    Runtime,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from relf_agent.temporal_deployment_admission import registry_id, root_run_id
from relf_agent.temporal_deployment_release import _binding
from relf_agent.temporal_session_state import workflow_id
from relf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires externally owned Temporal Service"
)


def test_actual_two_consecutive_session_agent_turns_retire_before_advance(tmp_path):
    async def scenario():
        address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
        assert urlsplit(address if "://" in address else "//" + address).hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }, "S1 acceptance requires the existing loopback Service"
        clients, namespace = await _clients()
        client = clients[0]
        unique = "session-deployment-" + uuid.uuid4().hex
        scope = Scope("session-deployment-service", unique)
        policy = DeploymentAdmissionPolicy(unique, max_active_root_runs=1)

        class Provider:
            identity = {"kind": "offline-session-deployment-service", "version": "1"}

            def __init__(self):
                self.calls, self.closed = [], 0

            async def complete(self, messages, tools):
                assert not tools
                self.calls.append(messages)
                assert len(self.calls) <= 2
                return ModelResponse(output="answer-" + str(len(self.calls)))

            async def aclose(self):
                self.closed += 1

        provider = Provider()
        components = ComponentRegistry()
        components.register(
            "provider", "offline-session", lambda config, context: context.own_async(provider)
        )
        profile = TemporalProfile(
            unique,
            "1",
            {"default": {"adapter": "offline-session"}},
            execution={"enable_sessions": True, "deployment_sessions": True},
        )
        assembly = await TemporalRuntimeBuilder(components, base_dir=tmp_path).abuild(
            profile,
            scope=scope,
            admission_policy=policy,
        )
        engine = assembly.create_engine(client, task_queue=unique, activity_timeout=10)
        facade = Runtime.from_temporal(engine)
        targets, evidence = [], []
        completed = False
        primary, close_failures, diagnostic_failures = None, [], []

        def record_identity():
            (tmp_path / "identity-summary.json").write_text(
                json.dumps(
                    {
                        "scope": asdict(scope),
                        "task_queue": unique,
                        "deployment_id": policy.deployment_id,
                        "registry_id": registry_id(policy.deployment_id),
                        "targets": targets,
                        "completed_business_assertions": completed,
                        "completed_turn_evidence": len(evidence),
                        "provider_calls": len(provider.calls),
                    },
                    sort_keys=True,
                )
            )

        async def record_failure(stage, error):
            # Preserve the original traceback before any cleanup RPC can fail.
            (tmp_path / (stage + "-traceback.txt")).write_text(
                "".join(traceback.format_exception(type(error), error, error.__traceback__))
            )
            record_identity()
            diagnostic_errors = []
            for index, identity in enumerate(
                dict.fromkeys([*targets, registry_id(policy.deployment_id)])
            ):
                try:
                    history = await client.get_workflow_handle(identity).fetch_history(
                        rpc_timeout=timedelta(seconds=3),
                    )
                    (tmp_path / f"{stage}-history-{index}.json").write_text(history.to_json())
                except Exception as diagnostic_error:
                    diagnostic_errors.append(
                        {"workflow_id": identity, "error_type": type(diagnostic_error).__name__}
                    )
            (tmp_path / (stage + "-diagnostics.json")).write_text(
                json.dumps(
                    {
                        "workflow_ids": list(
                            dict.fromkeys([*targets, registry_id(policy.deployment_id)])
                        ),
                        "history_read_errors": diagnostic_errors,
                    },
                    sort_keys=True,
                )
            )

        record_identity()
        try:
            assert assembly.release["deployment_admission_protocol"]["version"] == 4
            assert assembly.release["session_deployment_protocol"] == 1
            await assembly.start_worker(client, task_queue=unique)
            session = await facade.open_session(
                AgentSpec("ordinary", "Answer the question"),
                unique,
                command_id="open-" + unique,
            )
            coordinator_id = workflow_id(session.ref.key)
            targets.append(coordinator_id)
            record_identity()
            coordinator = client.get_workflow_handle(coordinator_id)
            original = await coordinator.describe()
            epoch = original.run_id
            assert original.raw_info.first_run_id == epoch
            first = None
            for seq, question in enumerate(("question-one", "question-two"), 1):
                command = f"turn-{seq}-" + unique
                expected_command = "ralf-session-run:" + digest(
                    [session.ref.key.to_dict(), command]
                )
                targets.append(root_run_id(policy.deployment_id, asdict(scope), expected_command))
                record_identity()
                run = await session.submit(question, command_id=command)
                if first is None:
                    first = run
                assert run.ref.run_id == root_run_id(
                    policy.deployment_id, asdict(scope), expected_command
                )
                assert run.turn.turn_seq == seq
                assert (
                    await run.wait(wait_timeout=45, terminal_only=True)
                ).snapshot.state == "succeeded"
                await _eventually(session.status, lambda status: not status.busy, seconds=45)
                counts = await engine.deployment_diagnostics()
                assert counts["counts"]["held_root_runs"] == 0
                selector = {
                    "scope": asdict(scope),
                    "namespace": namespace,
                    "coordinator_execution_epoch": epoch,
                    "session_command_id": command,
                    "turn_id": run.turn.turn_id,
                }
                intent = await coordinator.query(
                    "view", {"kind": "deployment_session_intent", **selector}
                )
                assert intent["run_id"] == run.ref.run_id
                assert intent["run_command_id"] == expected_command
                if seq == 2:
                    assert intent["submission"]["request"]["session_history"] == [
                        {"role": "user", "content": "question-one"},
                        {"role": "assistant", "content": "answer-1"},
                    ]
                started = await coordinator.query(
                    "view",
                    {
                        "kind": "deployment_session_start",
                        **selector,
                        "intent_digest": intent["intent_digest"],
                    },
                )
                assert started["phase"] == "started"
                actual = await client.get_workflow_handle(run.ref.run_id).describe()
                assert actual.run_id == started["execution_epoch"] == actual.raw_info.first_run_id
                assert (actual.parent_id, actual.parent_run_id) == (coordinator_id, epoch)
                history = await client.get_workflow_handle(
                    run.ref.run_id, run_id=actual.run_id
                ).fetch_history()
                start = history.events[0].workflow_execution_started_event_attributes
                assert (
                    start.original_execution_run_id == start.first_execution_run_id == actual.run_id
                )
                assert start.parent_workflow_namespace == namespace["name"]
                assert (
                    start.parent_workflow_execution.workflow_id,
                    start.parent_workflow_execution.run_id,
                ) == (coordinator_id, epoch)
                closure = await client.get_workflow_handle(
                    run.ref.run_id, run_id=actual.run_id
                ).query(
                    "view",
                    {"kind": "deployment_closure", "scope": asdict(scope)},
                )
                assert closure["ready"] is True and closure["seal"] is not None
                root = closure["deployment"]["admission_receipt"]["root"]
                retired = await client.get_workflow_handle(registry_id(policy.deployment_id)).query(
                    "view",
                    {
                        "kind": "deployment_retirement",
                        **_binding(root, policy.identity, closure["seal"]),
                    },
                )
                assert retired == {"root": root, "certificate": closure["seal"], "released": True}
                duplicate = await session.submit(question, command_id=command)
                assert duplicate.turn == run.turn and duplicate.ref == run.ref
                assert [turn.turn_seq for turn in await session.turns()] == list(range(1, seq + 1))
                assert len(provider.calls) == seq
                (tmp_path / f"turn-{seq}-history.json").write_text(history.to_json())
                evidence.append(
                    {
                        "turn": run.turn.to_dict(),
                        "start": started,
                        "retirement": retired,
                        "counts": counts,
                    }
                )
            assert first is not None
            duplicate = await session.submit("question-one", command_id="turn-1-" + unique)
            assert duplicate.turn == first.turn and len(await session.turns()) == 2
            assert len(provider.calls) == 2 and not (await session.status()).busy
            assert (await coordinator.describe()).run_id == epoch
            (tmp_path / "session-history.json").write_text(
                (await coordinator.fetch_history()).to_json()
            )
            (tmp_path / "acceptance.json").write_text(json.dumps(evidence, sort_keys=True))
            completed = True
            record_identity()
        except BaseException as error:
            primary = error
            try:
                await record_failure("primary", error)
            except BaseException as diagnostic_error:
                diagnostic_failures.append(diagnostic_error)
        finally:
            for stage, close in (
                ("facade-close", facade.aclose),
                ("assembly-close", lambda: assembly.aclose(wait_timeout=30)),
            ):
                try:
                    await close()
                except BaseException as error:
                    close_failures.append(error)
                    try:
                        await record_failure(stage, error)
                    except BaseException as diagnostic_error:
                        diagnostic_failures.append(diagnostic_error)
        if primary is not None:
            if close_failures or diagnostic_failures:
                raise BaseExceptionGroup(
                    "S1 primary failure and owned cleanup/diagnostic failures",
                    [primary, *close_failures, *diagnostic_failures],
                )
            raise primary.with_traceback(primary.__traceback__)
        if close_failures or diagnostic_failures:
            raise BaseExceptionGroup(
                "S1 owned cleanup/diagnostic failures", [*close_failures, *diagnostic_failures]
            )
        assert completed and provider.closed == 1
        assert assembly._worker.is_shutdown and not assembly._worker.is_running
        assert engine._closed
        # Test-owned terminal Histories are cleaned only after positive original
        # retirement and owned resource close; termination never proves retirement.
        from temporalio.client import WorkflowExecutionStatus

        targets.append(registry_id(policy.deployment_id))
        for identity in reversed(targets):
            handle = client.get_workflow_handle(identity)
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="completed S1 Session acceptance cleanup")
        (tmp_path / "cleanup.json").write_text(
            json.dumps(
                {
                    "provider_closed_once": provider.closed == 1,
                    "worker_shutdown": assembly._worker.is_shutdown,
                    "held_root_runs_before_cleanup": 0,
                    "terminated_test_owned_histories": targets,
                },
                sort_keys=True,
            )
        )

    asyncio.run(asyncio.wait_for(scenario(), timeout=180))


def test_actual_session_approval_worker_restart_and_lost_completed_replies(tmp_path):
    async def scenario():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        from relf_agent import ToolCall, ToolRegistry, ToolSpec
        from relf_agent.temporal import TemporalEngine, build_temporal_worker
        from relf_agent.temporal_activities import TemporalRuntime
        from tests.test_temporal_deployment_public_service import SDKFaultClient, SDKFaultHandle

        class StartReceiptLossHandle(SDKFaultHandle):
            async def execute_update(self, name, *args, **kwargs):
                result = await super().execute_update(name, *args, **kwargs)
                if name == "start_receipt" and self.client.lose == "session-start-receipt":
                    assert result["phase"] == "started"
                    self.client.lose = None
                    self.client.dropped.append(
                        {"kind": "session_start_receipt", "workflow_id": self.original.id}
                    )
                    raise self.client.unavailable("lost completed original Session start receipt")
                return result

        class Client(SDKFaultClient):
            def get_workflow_handle(self, *args, **kwargs):
                return StartReceiptLossHandle(
                    self, self.original.get_workflow_handle(*args, **kwargs)
                )

        class Provider:
            identity = {"kind": "offline-session-approval-recovery", "version": "1"}

            async def complete(self, messages, tools):
                if not any(message["role"] == "tool" for message in messages):
                    return ModelResponse(tool_calls=[ToolCall("lookup", {}, "original-lookup")])
                return ModelResponse(output="approved-answer")

        address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
        assert urlsplit(address if "://" in address else "//" + address).hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        clients, namespace = await _clients()
        client = Client(clients[0], lose="reserve")
        unique = "session-restart-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(unique, max_active_root_runs=1)
        scope = Scope("session-deployment-recovery", unique)
        calls, workers, targets = [], [], []

        async def lookup(arguments, context):
            calls.append(context.effect_key)
            return {"found": True}

        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "lookup", "lookup", {"type": "object"}, requires_approval=True, effect="read_only"
            ),
            lookup,
        )
        execution = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            enable_sessions=True,
            deployment_sessions=True,
            admission_policy=policy,
        )
        engine = TemporalEngine(
            client,
            task_queue=unique,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=10,
        )
        facade = Runtime.from_temporal(engine)
        accepted, primary, close_failures = None, None, []
        (tmp_path / "recovery-identity.json").write_text(
            json.dumps(
                {
                    "scope": asdict(scope),
                    "task_queue": unique,
                    "registry_id": registry_id(policy.deployment_id),
                },
                sort_keys=True,
            )
        )
        try:
            worker = build_temporal_worker(client, task_queue=unique, runtime=execution)
            workers.append(worker)
            async with worker:
                definition = AgentSpec("ordinary-approval", "Use lookup", ("lookup",))
                with pytest.raises(RPCError) as lost_reserve:
                    await facade.open_session(definition, unique, command_id="open-" + unique)
                assert lost_reserve.value.status == RPCStatusCode.UNAVAILABLE
                session = await facade.open_session(definition, unique, command_id="open-" + unique)
                original_ref, open_receipt = session.ref, session.receipt
                coordinator_id = workflow_id(session.ref.key)
                targets.append(coordinator_id)
                coordinator = client.get_workflow_handle(coordinator_id)
                epoch = (await coordinator.describe()).run_id
                command = "turn-" + unique
                turn_id = "ralf-turn-" + digest([session.ref.key.to_dict(), command])
                root_command = "ralf-session-run:" + digest([session.ref.key.to_dict(), command])
                run_id = root_run_id(policy.deployment_id, asdict(scope), root_command)
                targets.append(run_id)
                client.lose = "session-start-receipt"
                with pytest.raises(RPCError) as lost_start:
                    await session.submit("needs approval", command_id=command)
                assert lost_start.value.status == RPCStatusCode.UNAVAILABLE
                selector = {
                    "scope": asdict(scope),
                    "namespace": namespace,
                    "coordinator_execution_epoch": epoch,
                    "session_command_id": command,
                    "turn_id": turn_id,
                }
                intent = await coordinator.query(
                    "view", {"kind": "deployment_session_intent", **selector}
                )
                selector["intent_digest"] = intent["intent_digest"]
                accepted = await coordinator.query(
                    "view", {"kind": "deployment_session_command", **selector}
                )
                start = await coordinator.query(
                    "view", {"kind": "deployment_session_start", **selector}
                )
                assert start["phase"] == "started"
                original_run_epoch = start["execution_epoch"]
                await _eventually(
                    lambda: engine.status(run_id),
                    lambda value: value.state == "waiting_approval",
                    seconds=45,
                )
                assert (await engine.deployment_diagnostics())["counts"]["held_root_runs"] == 1
                assert (await session.status()).busy and calls == []
                (tmp_path / "before-restart.json").write_text(
                    json.dumps(
                        {"intent": intent, "command": accepted, "start": start}, sort_keys=True
                    )
                )
            assert worker.is_shutdown
            await facade.aclose()
            facade = Runtime.from_temporal(engine)
            resumed_worker = build_temporal_worker(client, task_queue=unique, runtime=execution)
            workers.append(resumed_worker)
            async with resumed_worker:
                resumed = await facade.aattach_session(original_ref)
                replay = await resumed.submit("needs approval", command_id=command)
                assert replay.receipt == type(replay.receipt)(**accepted["receipt"])
                assert replay.turn.turn_id == turn_id and replay.turn.turn_seq == 1
                assert replay.ref.run_id == run_id
                assert (await coordinator.describe()).run_id == epoch
                actual = await client.get_workflow_handle(run_id).describe()
                assert actual.run_id == original_run_epoch == actual.raw_info.first_run_id
                assert (actual.parent_id, actual.parent_run_id) == (coordinator_id, epoch)
                reopened = await facade.open_session(
                    definition, unique, command_id="open-" + unique
                )
                assert reopened.receipt == open_receipt and reopened.ref == original_ref
                pending = (await replay.pending())[0]
                from relf_agent import RunRef

                owner = await facade.aattach(RunRef.from_dict(pending["ref"]))
                approval = await owner.approve(
                    pending["action_id"], pending["digest"], command_id="approve-" + unique
                )
                assert (
                    await replay.wait(wait_timeout=45, terminal_only=True)
                ).snapshot.state == "succeeded"
                await _eventually(resumed.status, lambda value: not value.busy, seconds=45)
                assert (await engine.deployment_diagnostics())["counts"]["held_root_runs"] == 0
                assert len(calls) == 1 and len(await resumed.turns()) == 1
                assert (
                    await resumed.submit("needs approval", command_id=command)
                ).turn == replay.turn
                assert (
                    await owner.approve(
                        pending["action_id"], pending["digest"], command_id="approve-" + unique
                    )
                    == approval
                )
                assert [drop["kind"] for drop in client.dropped] == [
                    "reserve",
                    "session_start_receipt",
                ]
                (tmp_path / "recovery.json").write_text(
                    json.dumps(
                        {
                            "command": accepted,
                            "start": start,
                            "coordinator_epoch": epoch,
                            "run_epoch": actual.run_id,
                            "lost_completed_replies": client.dropped,
                            "held_root_runs_after_recovery": 0,
                            "tool_calls": calls,
                            "start_loss_boundary": "completed Session start_receipt Update reply; not child-start command transport",
                        },
                        sort_keys=True,
                    )
                )
                for index, identity in enumerate([*targets, registry_id(policy.deployment_id)]):
                    history = await client.get_workflow_handle(identity).fetch_history()
                    (tmp_path / f"recovered-history-{index}.json").write_text(history.to_json())
        except BaseException as error:
            primary = error
            (tmp_path / "recovery-primary-traceback.txt").write_text(
                "".join(traceback.format_exception(type(error), error, error.__traceback__))
            )
        finally:
            for stage, close in (
                ("facade", facade.aclose),
                ("engine", engine.aclose),
                ("execution", lambda: execution.close_deployment_execution(wait_timeout=30)),
            ):
                try:
                    await close()
                except BaseException as error:
                    close_failures.append(error)
                    (tmp_path / ("recovery-" + stage + "-close-traceback.txt")).write_text(
                        "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    )
        if primary is not None:
            if close_failures:
                raise BaseExceptionGroup(
                    "Session recovery primary and close failures", [primary, *close_failures]
                )
            raise primary.with_traceback(primary.__traceback__)
        if close_failures:
            raise BaseExceptionGroup("Session recovery close failures", close_failures)
        assert accepted is not None and all(worker.is_shutdown for worker in workers)
        for identity in [*targets, registry_id(policy.deployment_id)]:
            handle = client.get_workflow_handle(identity)
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="completed S1 Session approval recovery cleanup")

    asyncio.run(asyncio.wait_for(scenario(), timeout=180))
