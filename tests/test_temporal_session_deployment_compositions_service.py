"""The existing nine ordinary compositions through two original Session Turns."""

import asyncio
import json
import os
import traceback
from dataclasses import asdict
from datetime import timedelta

import pytest

from relf_agent import Runtime
from relf_agent.temporal import TemporalEngine
from relf_agent.temporal_deployment_admission import registry_id, root_run_id
from relf_agent.temporal_deployment_release import _binding
from relf_agent.temporal_session_state import workflow_id
from relf_agent.types import digest
from tests.test_temporal_deployment_dispatch_service import _case, _eventually
from tests.test_temporal_deployment_public_service import CASES, public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires externally owned Temporal Service"
)


@pytest.mark.parametrize("case", CASES)
def test_actual_session_two_consecutive_existing_ordinary_compositions(tmp_path, case):
    _exercise_two_turns(tmp_path, case, legacy_three_second_deadline=False)


def test_actual_agent_original_three_second_observer_deadline_recovery(tmp_path):
    # Preserve the original failed Agent configuration as an explicit regression.
    _exercise_two_turns(tmp_path, "agent", legacy_three_second_deadline=True)


def _exercise_two_turns(tmp_path, case, *, legacy_three_second_deadline):
    async def scenario():
        async with public_system(
            tmp_path, options={"enable_sessions": True, "deployment_sessions": True}
        ) as system:
            original_cleanup = system.cleanup
            passed, primary = False, None
            if legacy_three_second_deadline:
                engine = system.engine  # Existing PublicSystem facade deliberately fixes 3 seconds.
            else:
                # Exercise the public Engine default; the reusable fixture's
                # legacy 3-second deadline is a separate regression below.
                engine = TemporalEngine(
                    system.client,
                    task_queue=system.queue,
                    release=system.runtime.orchestration_release,
                    scope=system.scope,
                )
                system.engines.append(engine)
            facade = Runtime.from_temporal(engine)

            async def cleanup():
                if passed:
                    await original_cleanup()
                    return
                # The reusable fixture normally terminates its test Histories.
                # A failed Session case may have unknown debt: preserve all of
                # those Histories instead, with bounded local diagnostics.
                reads = []
                for index, identity in enumerate(
                    sorted(system.targets | {registry_id(system.policy.deployment_id)})
                ):
                    try:
                        history = await system.client.get_workflow_handle(identity).fetch_history(
                            rpc_timeout=timedelta(seconds=3),
                        )
                        (tmp_path / f"failure-history-{index}.json").write_text(history.to_json())
                        reads.append({"workflow_id": identity, "saved": True})
                    except Exception as error:
                        reads.append(
                            {
                                "workflow_id": identity,
                                "saved": False,
                                "error_type": type(error).__name__,
                            }
                        )
                (tmp_path / "failure-preserved.json").write_text(
                    json.dumps(
                        {
                            "histories": reads,
                            "terminated": False,
                            "case": case,
                            "configuration": "legacy-three-seconds"
                            if legacy_three_second_deadline
                            else "public-engine-default",
                            "session_activity_timeout": engine.activity_timeout,
                            "scope": asdict(system.scope),
                            "task_queue": system.queue,
                        },
                        sort_keys=True,
                    )
                )
                for borrowed_engine in system.engines:
                    await borrowed_engine.aclose()

            system.cleanup = cleanup
            try:
                async with system.worker():
                    try:
                        spec, reads, descendants, value = _case(case)
                        session = await facade.open_session(spec, case, command_id="open")
                        coordinator_id = workflow_id(session.ref.key)
                        system.targets.add(coordinator_id)
                        coordinator_epoch = (
                            await system.client.get_workflow_handle(coordinator_id).describe()
                        ).run_id
                        first = None
                        for seq in (1, 2):
                            command = f"turn-{seq}"
                            run_command = "ralf-session-run:" + digest(
                                [session.ref.key.to_dict(), command]
                            )
                            expected = root_run_id(
                                system.policy.deployment_id, asdict(system.scope), run_command
                            )
                            system.targets.add(expected)
                            run = await session.submit(value, command_id=command, budget=64)
                            first = run if first is None else first
                            assert run.ref.run_id == expected and run.turn.turn_seq == seq
                            result = await run.wait(wait_timeout=60, terminal_only=True)
                            assert result.snapshot.state == "succeeded", result
                            await _eventually(
                                session.status, lambda status: not status.busy, seconds=60
                            )
                            await system.count(0)
                            assert await system.evidence(run.ref.run_id) == descendants + 1
                            closure = await system.closure(run.ref.run_id)
                            root = closure["deployment"]["admission_receipt"]["root"]
                            retired = await system.client.get_workflow_handle(
                                registry_id(system.policy.deployment_id)
                            ).query(
                                "view",
                                {
                                    "kind": "deployment_retirement",
                                    **_binding(root, system.policy.identity, closure["seal"]),
                                },
                            )
                            assert retired == {
                                "root": root,
                                "certificate": closure["seal"],
                                "released": True,
                            }
                            actual = await system.client.get_workflow_handle(
                                run.ref.run_id
                            ).describe()
                            assert (actual.parent_id, actual.parent_run_id) == (
                                coordinator_id,
                                coordinator_epoch,
                            )
                            assert len(system.probe.reads) == seq * reads
                            before = (len(system.probe.models), len(system.probe.reads))
                            duplicate = await session.submit(value, command_id=command, budget=64)
                            assert duplicate.turn == run.turn and duplicate.receipt == run.receipt
                            assert (len(system.probe.models), len(system.probe.reads)) == before
                            assert [turn.turn_seq for turn in await session.turns()] == list(
                                range(1, seq + 1)
                            )
                        assert len(system.probe.reads) == 2 * reads
                        assert (
                            await session.submit(value, command_id="turn-1", budget=64)
                        ).turn == first.turn
                        assert len(await session.turns()) == 2 and not (await session.status()).busy
                        await system.count(0)
                        (tmp_path / "session-history.json").write_text(
                            (
                                await system.client.get_workflow_handle(
                                    coordinator_id
                                ).fetch_history()
                            ).to_json()
                        )
                        (tmp_path / "session-composition.json").write_text(
                            json.dumps(
                                {
                                    "case": case,
                                    "configuration": "legacy-three-seconds"
                                    if legacy_three_second_deadline
                                    else "public-engine-default",
                                    "session_activity_timeout": engine.activity_timeout,
                                    "turns": [turn.to_dict() for turn in await session.turns()],
                                    "reads": len(system.probe.reads),
                                    "expected_reads": 2 * reads,
                                    "held_root_runs": 0,
                                    "coordinator_execution_epoch": coordinator_epoch,
                                },
                                sort_keys=True,
                            )
                        )
                    except BaseException as error:
                        primary = error
                        (tmp_path / "primary-traceback.txt").write_text(
                            "".join(
                                traceback.format_exception(type(error), error, error.__traceback__)
                            )
                        )
                        raise
            except BaseException as error:
                if primary is not None and error is not primary:
                    raise BaseExceptionGroup(
                        "Session composition primary and Worker cleanup failures", [primary, error]
                    ) from None
                raise
            finally:
                await facade.aclose()
            passed = True

    asyncio.run(asyncio.wait_for(scenario(), timeout=240))
