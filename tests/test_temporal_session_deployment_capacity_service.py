"""One actual SDK gate for Session4 shared capacity and original queue recovery."""

import asyncio
import copy
import json
import os
import traceback
from dataclasses import asdict
from datetime import timedelta

import pytest

from relf_agent import ComponentRegistry, Runtime, Scope, TemporalProfile, TemporalRuntimeBuilder
from relf_agent.errors import (
    AuthorizationDenied,
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
)
from relf_agent.temporal import TemporalEngine
from relf_agent.temporal_deployment_admission import registry_id, root_run_id
from relf_agent.temporal_session_state import workflow_id
from relf_agent.types import digest
from tests.test_temporal_deployment_dispatch_service import BusinessProbe, _agent, _eventually
from tests.test_temporal_deployment_public_service import PublicSystem, public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires externally owned Temporal Service"
)


def test_actual_session_profiles_share_capacity_and_retry_original_deferred_intent(tmp_path):
    async def scenario():
        async def assembly(label, queue, policy, probe, scope):
            components = ComponentRegistry()
            components.register("provider", "capacity-probe", lambda config, context: probe)
            components.register("tools", "capacity-probe", lambda config, context: probe.tools())
            return await TemporalRuntimeBuilder(components, base_dir=tmp_path / label).abuild(
                TemporalProfile(
                    "session-capacity-" + label,
                    "1",
                    {"default": {"adapter": "capacity-probe"}},
                    {"tools": {"adapter": "capacity-probe"}},
                    execution={"enable_sessions": True, "deployment_sessions": True},
                ),
                scope=scope,
                admission_policy=policy,
            )

        async def first_profile(queue, policy, probe):
            return await assembly(
                "a", queue, policy, probe, Scope("deployment-public-service", queue)
            )

        async with public_system(tmp_path, hold=True, profile=first_profile) as first:
            second_scope = Scope(first.scope.workspace, first.scope.principal + "-other")
            second_queue = first.queue + "-profile-b"
            second_probe = BusinessProbe()
            second_probe.identity = {**second_probe.identity, "version": "profile-b"}
            second_assembly = await assembly(
                "b", second_queue, first.policy, second_probe, second_scope
            )
            second = PublicSystem(
                tmp_path,
                first.client,
                first.namespace,
                second_queue,
                first.policy,
                second_assembly._runtime,
                second_probe,
                assembly=second_assembly,
            )
            second.scope = second_scope
            engines, facades = [], []
            passed, primary = False, None
            original_cleanup = first.cleanup
            targets = first.targets
            identities = {
                "registry_id": registry_id(first.policy.deployment_id),
                "queues": [first.queue, second_queue],
                "scopes": [asdict(first.scope), asdict(second_scope)],
                "profile_identities": [
                    first.assembly.profile.identity,
                    second_assembly.profile.identity,
                ],
                "public_activity_timeout": 60,
            }

            async def save(stage):
                (tmp_path / "identities.json").write_text(json.dumps(identities, sort_keys=True))
                results = []
                for index, target in enumerate(sorted(targets | {identities["registry_id"]})):
                    try:
                        history = await first.client.get_workflow_handle(target).fetch_history(
                            rpc_timeout=timedelta(seconds=3)
                        )
                        (tmp_path / f"{stage}-history-{index}.json").write_text(history.to_json())
                        results.append({"workflow_id": target, "saved": True})
                    except Exception as error:
                        results.append({"workflow_id": target, "error_type": type(error).__name__})
                (tmp_path / f"{stage}-histories.json").write_text(
                    json.dumps(results, sort_keys=True)
                )

            async def cleanup():
                if passed:
                    await original_cleanup()
                else:
                    await save("failure")
                    for engine in first.engines:
                        await engine.aclose()

            first.cleanup = cleanup
            try:
                async with first.worker(), second.worker():
                    try:
                        for system, scope in ((first, first.scope), (second, second_scope)):
                            engine = TemporalEngine(
                                system.client,
                                task_queue=system.queue,
                                release=system.runtime.orchestration_release,
                                scope=scope,
                            )
                            engines.append(engine)
                            facades.append(Runtime.from_temporal(engine))
                        owner, contender = facades
                        spec, value = _agent("capacity"), {"capacity": "same-original-input"}
                        a = await owner.open_session(spec, "owner", command_id="open")
                        b = await contender.open_session(spec, "contender", command_id="open")
                        targets.update({workflow_id(a.ref.key), workflow_id(b.ref.key)})
                        registry = first.client.get_workflow_handle(identities["registry_id"])
                        registry_epoch = (await registry.describe()).run_id
                        assert (await registry.describe()).task_queue == first.queue
                        assert (await engines[0].deployment_diagnostics())["counts"][
                            "held_root_runs"
                        ] == 0
                        initial = await a.submit(value, command_id="turn", budget=64)
                        targets.add(initial.ref.run_id)
                        await asyncio.wait_for(first.probe.started.wait(), 30)
                        await first.count(1)
                        with pytest.raises(CapacityExceeded) as deferred:
                            await b.submit(value, command_id="turn", budget=64)
                        start = copy.deepcopy(deferred.value.start)
                        intent = start["intent"]
                        targets.add(intent["run_id"])
                        assert start["phase"] == "capacity-deferred"
                        assert start["reservation"] is None and start["execution_epoch"] is None
                        assert intent["submission"]["task_queue"] == second_queue
                        assert intent["submission"]["manifest"] == json.loads(
                            json.dumps(engines[1].release)
                        )
                        assert second_probe.models == second_probe.reads == []
                        assert (await b.status()).busy
                        assert [turn.turn_seq for turn in await b.turns()] == [1]
                        foreign = await engines[1].deployment_diagnostics()
                        assert foreign["counts"]["held_root_runs"] == 1
                        assert foreign["counts"]["held_root_runs_for_scope"] == 0
                        assert foreign["held_roots"] == [] and initial.ref.run_id not in json.dumps(
                            foreign
                        )
                        with pytest.raises(IdempotencyConflict):
                            await b.submit({"changed": True}, command_id="turn", budget=64)
                        with pytest.raises(IdempotencyConflict):
                            await contender.open_session(spec, "other", command_id="turn")
                        with pytest.raises(IdempotencyConflict):
                            await engines[1].submit(spec, value, command_id="turn", budget=64)
                        with pytest.raises(DefinitionMismatch):
                            await contender.aattach_session(a.ref)
                        with pytest.raises(AuthorizationDenied):
                            await engines[1].status(initial.ref.run_id)
                        assert second_probe.models == second_probe.reads == []
                        assert (await registry.describe()).run_id == registry_epoch
                        await first.count(1)
                        (tmp_path / "deferred.json").write_text(json.dumps(start, sort_keys=True))
                        first.probe.release.set()
                        assert (
                            await initial.wait(wait_timeout=60, terminal_only=True)
                        ).snapshot.state == "succeeded"
                        await _eventually(a.status, lambda status: not status.busy, seconds=60)
                        await first.count(0)
                        await first.evidence(initial.ref.run_id)
                        # The retry facade changes queue and publication. The already
                        # accepted Session command must use its first complete binding.
                        retry_engine = TemporalEngine(
                            first.client,
                            task_queue=second_queue + "-unserved",
                            release=engines[0].release,
                            scope=second_scope,
                        )
                        engines.append(retry_engine)
                        retry = Runtime.from_temporal(retry_engine)
                        facades.append(retry)
                        recovered = await retry.aattach_session(b.ref)
                        run = await recovered.submit(value, command_id="turn", budget=64)
                        assert run.receipt == deferred.value.receipt and run.turn.turn_seq == 1
                        assert (
                            run.ref.run_id
                            == intent["run_id"]
                            == root_run_id(
                                first.policy.deployment_id,
                                asdict(second_scope),
                                intent["run_command_id"],
                            )
                        )
                        assert intent["run_command_id"] == "ralf-session-run:" + digest(
                            [b.ref.key.to_dict(), "turn"]
                        )
                        assert (
                            await run.wait(wait_timeout=60, terminal_only=True)
                        ).snapshot.state == "succeeded"
                        await _eventually(
                            recovered.status, lambda status: not status.busy, seconds=60
                        )
                        await first.count(0)
                        actual = await first.client.get_workflow_handle(run.ref.run_id).describe()
                        coordinator = await first.client.get_workflow_handle(
                            workflow_id(b.ref.key)
                        ).describe()
                        assert actual.task_queue == coordinator.task_queue == second_queue
                        assert (actual.parent_id, actual.parent_run_id) == (
                            coordinator.id,
                            coordinator.run_id,
                        )
                        selector = {
                            "scope": asdict(second_scope),
                            "namespace": first.namespace,
                            "coordinator_execution_epoch": coordinator.run_id,
                            "session_command_id": "turn",
                            "turn_id": intent["turn_id"],
                        }
                        assert (
                            await first.client.get_workflow_handle(coordinator.id).query(
                                "view", {"kind": "deployment_session_intent", **selector}
                            )
                            == intent
                        )
                        assert [turn.turn_seq for turn in await recovered.turns()] == [1]
                        before = (len(second_probe.models), len(second_probe.reads))
                        assert (
                            await recovered.submit(value, command_id="turn", budget=64)
                        ).turn == run.turn
                        assert (len(second_probe.models), len(second_probe.reads)) == before
                        assert len(first.probe.reads) == len(second_probe.reads) == 1
                        assert (await registry.describe()).run_id == registry_epoch
                        assert (await registry.describe()).task_queue == first.queue
                        # evidence() reads through a scoped facade; keep B's real Scope.
                        second.engine = engines[1]
                        await second.evidence(run.ref.run_id)
                        identities.update(
                            {
                                "registry_execution_epoch": registry_epoch,
                                "recovered_intent_digest": intent["intent_digest"],
                                "original_run_id": run.ref.run_id,
                                "original_run_epoch": actual.run_id,
                                "coordinator_epoch": coordinator.run_id,
                                "held_root_runs": 0,
                                "turn_sequences": [1],
                                "business_reads": [len(first.probe.reads), len(second_probe.reads)],
                            }
                        )
                        await save("success")
                    except BaseException as error:
                        primary = error
                        (tmp_path / "primary-traceback.txt").write_text(
                            "".join(traceback.format_exception(error))
                        )
                        await save("failure")
                        raise
            except BaseException as error:
                if primary is not None and error is not primary:
                    raise BaseExceptionGroup(
                        "Capacity scenario and Worker cleanup failures", [primary, error]
                    ) from None
                raise
            finally:
                for facade in facades:
                    await facade.aclose()
                for engine in [*engines, *second.engines]:
                    await engine.aclose()
            await second_assembly.aclose(wait_timeout=30)
            passed = True

    asyncio.run(asyncio.wait_for(scenario(), timeout=300))
