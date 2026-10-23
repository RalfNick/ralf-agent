"""Actual Session4 handler/effect debt and original owned receiver retention."""

import asyncio
import json
import os
import traceback
import uuid
from dataclasses import asdict
from datetime import timedelta

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    DeploymentAdmissionPolicy,
    Runtime,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from relf_agent.errors import CloseIncomplete, SessionBusy
from relf_agent.temporal_deployment_admission import registry_id, root_run_id
from relf_agent.temporal_deployment_release import check_owner
from relf_agent.temporal_session_state import workflow_id
from relf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_deployment_public_service import (
    CommittedThreadWrite,
    PublicSystem,
    SDKFaultClient,
    SQLiteEffectEvidence,
    WriteProvider,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("obligation", ["effect-ack", "call-end-ack"])
def test_actual_session_unknown_handler_and_ack_debt_keep_root_and_close_receiver(
    tmp_path, obligation
):
    async def scenario():
        clients, namespace = await _clients()
        client = SDKFaultClient(clients[0])
        queue = "session-debt-" + uuid.uuid4().hex
        scope = Scope("deployment-public-service", queue)
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
        write = CommittedThreadWrite(tmp_path / "business.sqlite")
        journal = SQLiteEffectEvidence(tmp_path / "evidence.sqlite")

        class OwnedProvider(WriteProvider):
            def __init__(self):
                self.closed = 0

            async def aclose(self):
                self.closed += 1

        provider = OwnedProvider()
        components = ComponentRegistry()
        components.register("provider", "debt", lambda c, ctx: ctx.own_async(provider))
        components.register("tools", "debt", lambda c, ctx: write.tools())
        components.register("effect_journal", "debt", lambda c, ctx: ctx.own_async(journal))
        profile = TemporalProfile(
            queue,
            "1",
            {"default": {"adapter": "debt"}},
            {
                "tools": {"adapter": "debt"},
                "effect_journal": {"adapter": "debt"},
                "tool_execution": {
                    "adapter": "tracked",
                    "config": {"version": "session-service-thread-1"},
                },
            },
            execution={"enable_sessions": True, "deployment_sessions": True},
        )
        assembly = await TemporalRuntimeBuilder(components, base_dir=tmp_path).abuild(
            profile, scope=scope, admission_policy=policy
        )
        system = PublicSystem(
            tmp_path,
            client,
            namespace,
            queue,
            policy,
            assembly._runtime,
            provider,
            assembly=assembly,
        )
        # PublicSystem cleanup's probe is normally a gated read Provider. This
        # scenario owns its write gate and only releases it on the success path.
        system.unblock = lambda: None
        # Explicit three-second fault deadline: obtain an unknown outcome before
        # the original handler's 45-second bound without also forcing every
        # mechanical verification into one second. Separate from the default60 matrix.
        engine = assembly.create_engine(client, task_queue=queue, activity_timeout=3)
        facade = Runtime.from_temporal(engine)
        completed = False
        stages = []

        async def preserved(error):
            (tmp_path / "primary-traceback.txt").write_text(
                "".join(traceback.format_exception(type(error), error, error.__traceback__))
            )
            identities = sorted(system.targets | {registry_id(policy.deployment_id)})
            saved = []
            for index, identity in enumerate(identities):
                try:
                    history = await client.get_workflow_handle(identity).fetch_history(
                        rpc_timeout=timedelta(seconds=3)
                    )
                    (tmp_path / f"failure-history-{index}.json").write_text(history.to_json())
                    saved.append({"workflow_id": identity, "saved": True})
                except Exception as read_error:
                    saved.append({"workflow_id": identity, "error_type": type(read_error).__name__})
            (tmp_path / "failure-preserved.json").write_text(
                json.dumps(
                    {
                        "scope": asdict(scope),
                        "task_queue": queue,
                        "histories": saved,
                        "stages": stages,
                        "terminated": False,
                        "forced_release": False,
                        "obligation": obligation,
                    },
                    sort_keys=True,
                )
            )

        try:
            assert assembly.release["deployment_admission_protocol"]["version"] == 4
            await assembly.start_worker(client, task_queue=queue)
            system.workers.append(assembly._worker)
            session = await facade.open_session(
                AgentSpec("writer", "Write once", ("write",)), queue, command_id="open"
            )
            system.targets.add(workflow_id(session.ref.key))
            # Owned close marks its own Engine closed while the original receiver
            # remains live. Preserve an independent borrowed read facade.
            observer = Runtime.from_temporal(system.engine)
            observed_session = await observer.aattach_session(session.ref)
            for seq in (1, 2):
                write.started.clear()
                write.ended.clear()
                write.release.clear()
                journal.ack_attempted.clear()
                journal.block_ack = obligation == "effect-ack"
                client.end_attempted.clear()
                command = f"turn-{seq}"
                expected = root_run_id(
                    policy.deployment_id,
                    asdict(scope),
                    "ralf-session-run:" + digest([session.ref.key.to_dict(), command]),
                )
                system.targets.add(expected)
                turn = await session.submit({}, command_id=command, budget=64)
                assert turn.ref.run_id == expected and turn.turn.turn_seq == seq
                assert await asyncio.to_thread(write.started.wait, 20)
                genuine, calls = write.committed()[-1]
                assert calls == 1 and not write.ended.is_set()
                await system.engine.cancel(expected, command_id=f"cancel-{seq}")
                unknown = await _eventually(
                    lambda expected=expected: system.engine.diagnostics(expected),
                    lambda value: any(
                        a["kind"] == "tool" and a["status"] == "outcome_unknown"
                        for a in value.snapshot.actions
                    ),
                )
                action = next(a for a in unknown.snapshot.actions if a["kind"] == "tool")
                assert not write.ended.is_set()
                assert any(
                    r["amount"] == 0 and r["status"] == "unknown"
                    for r in unknown.budget["reservations"]
                )
                await system.engine.reconcile(
                    expected, action["id"], genuine, command_id=f"manual-evidence-{seq}"
                )
                assert not write.ended.is_set()
                await system.count(1)
                assert (await session.status()).busy
                with pytest.raises(SessionBusy):
                    await session.submit({}, command_id=f"blocked-physical-{seq}", budget=64)
                assert len(await session.turns()) == seq
                stages.append({"turn": seq, "stage": "physical-held", "held_root_runs": 1})
                client.block_end = obligation == "call-end-ack"
                write.release.set()
                assert await asyncio.to_thread(write.ended.wait, 10)
                if obligation == "effect-ack":
                    await asyncio.wait_for(journal.ack_attempted.wait(), 15)
                    await _eventually(
                        lambda expected=expected: system.engine.events(expected),
                        lambda events: any(e.kind == "effect_journal_ack_deferred" for e in events),
                    )
                    assert (await system.engine.diagnostics(expected)).workflow[
                        "deferred_evidence_acks"
                    ] == 1
                else:
                    await asyncio.wait_for(client.end_attempted.wait(), 15)
                await system.count(1)
                assert (await system.closure(expected))["seal"] is None
                assert (await session.status()).busy
                with pytest.raises(SessionBusy):
                    await session.submit({}, command_id=f"blocked-ack-{seq}", budget=64)
                stages.append({"turn": seq, "stage": "ack-held", "held_root_runs": 1})
                if seq == 2:
                    with pytest.raises(CloseIncomplete):
                        await assembly.aclose(wait_timeout=0.2)
                    assert assembly._worker.is_running and not assembly._worker.is_shutdown
                    assert provider.closed == 0 and (await observed_session.status()).busy
                    await system.count(1)
                    stages.append({"turn": seq, "stage": "close-incomplete-receiver-alive"})
                journal.block_ack = False
                client.block_end = False
                await system.engine.drive(expected, wait_seconds=0)
                assert await check_owner(system.runtime).wait(wait_timeout=15)
                await system.count(0)
                await _eventually(
                    observed_session.status, lambda status: not status.busy, seconds=60
                )
                assert await system.evidence(expected) == 1
                assert len(write.committed()) == seq
                assert all(count == 1 for _, count in write.committed())
                stages.append({"turn": seq, "stage": "retired-published", "held_root_runs": 0})
            close_attempts = 0

            async def finish_original_close():
                nonlocal close_attempts
                close_attempts += 1
                try:
                    await assembly.aclose(wait_timeout=10)
                except CloseIncomplete:
                    # A previous bounded close Task can finish with its original
                    # incomplete report before a later retry starts a fresh drain.
                    return False
                return True

            await _eventually(finish_original_close, bool, seconds=40)
            assert assembly._worker.is_shutdown and provider.closed == 1
            (tmp_path / "debt-acceptance.json").write_text(
                json.dumps(
                    {
                        "obligation": obligation,
                        "stages": stages,
                        "turns": 2,
                        "physical_calls": len(write.committed()),
                        "provider_closed": provider.closed,
                        "close_attempts_after_retirement": close_attempts,
                        "receiver_stopped_after_drain": assembly._worker.is_shutdown,
                        "held_root_runs": 0,
                    },
                    sort_keys=True,
                )
            )
            completed = True
        except BaseException as error:
            await preserved(error)
            raise
        finally:
            if completed:
                await observer.aclose()
                await facade.aclose()
                await system.cleanup()
            # Failure leaves original Histories and unknown/ACK obligations in
            # place. Do not terminate, release the handler, or synthesize ACKs.

    asyncio.run(asyncio.wait_for(scenario(), 240))
