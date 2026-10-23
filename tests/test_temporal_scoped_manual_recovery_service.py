"""Actual unowned thread end remains independent of manual effect adoption."""

import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope
from relf_agent.errors import NotFound, RalfError, ValidationError
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from relf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_scoped_capacity_service import discover_owned_descendants

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_full_scoped_manual_preserves_original_action_and_end_debt(tmp_path):
    _exercise(tmp_path, pressure_updates=False)


def test_actual_scoped_manual_after_registry_2000_updates(tmp_path):
    _exercise(tmp_path, pressure_updates=True)


@pytest.mark.skipif(
    not os.getenv("RALF_TEST_MANUAL_LEGACY_PYTHON"), reason="requires immutable old manual Worker"
)
def test_actual_old_manual_worker_uses_original_update_without_manual_signal(tmp_path):
    _exercise(tmp_path, pressure_updates=False, legacy_worker=True)


def _exercise(tmp_path, *, pressure_updates, legacy_worker=False):
    async def run():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        clients, namespace = await _clients()
        client, queue = (clients[0], "scoped-manual-" + uuid.uuid4().hex)
        scope = Scope("unowned-end", queue)
        python = os.environ["RALF_TEST_MANUAL_LEGACY_PYTHON"] if legacy_worker else sys.executable
        environment = {
            k: os.environ[k]
            for k in ("PATH", "HOME", "TMPDIR", "RALF_TEST_TEMPORAL_ADDRESS")
            if k in os.environ
        }
        environment["RALF_TEST_TEMPORAL_NAMESPACE"] = namespace["name"]
        processes, engine, owned, failure = ([], None, set(), None)

        async def start(generation):
            with (tmp_path / f"worker-{generation}.log").open("w") as out:
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
            processes.append((generation, process))
            async with asyncio.timeout(15):
                while not (tmp_path / f"ready-{generation}.json").exists():
                    assert process.returncode is None, "owned Worker exited before readiness"
                    await asyncio.sleep(0.02)
            ready = json.loads((tmp_path / f"ready-{generation}.json").read_text())
            assert Path(ready["package_file"]).is_relative_to(Path(python).parent.parent)
            return (process, ready["release"])

        async def stop(generation, process):
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()
                pytest.fail("owned Worker could not drain")
            assert process.returncode == 0
            assert json.loads((tmp_path / f"closed-{generation}.json").read_text())[
                "worker_shutdown"
            ]

        try:
            process, release = await start("first")
            engine = TemporalEngine(
                client, task_queue=queue, release=release, scope=scope, activity_timeout=1
            )
            assert "tool_execution_protocol" not in release
            owned.update(
                {engine.command_registry_id, "ralf-temporal-" + digest([asdict(scope), "root"])}
            )
            definition = GraphWorkflowSpec(
                "g",
                [
                    GraphNode(
                        "a",
                        agent=AgentSpec("reader", "Read", tools=("slow", "fast"), max_decisions=2),
                    )
                ],
            )
            root = await engine.submit(definition, "task", command_id="root", budget=32)
            original = await _eventually(
                lambda: engine.diagnostics(root.run_id), lambda d: bool(d.workflow["children"])
            )
            child = original.workflow["children"][0]["run_id"]
            owned.add(child)
            (tmp_path / "original-identities.json").write_text(
                json.dumps({"scope": asdict(scope), "queue": queue, "owned": sorted(owned)})
            )

            async def child_status():
                try:
                    return await engine.status(child)
                except NotFound:
                    return None

            unknown = await _eventually(
                child_status, lambda s: s is not None and s.state == "waiting_reconciliation"
            )
            first = next(a for a in unknown.actions if a["kind"] == "tool" and a["tool"] == "slow")
            assert (tmp_path / "slow-started").exists() and (not (tmp_path / "slow-ended").exists())
            registry = client.get_workflow_handle(engine.command_registry_id)
            before = await registry.query("view", {"scope": asdict(scope)})
            for fill_start in range(
                before["accepted_commands"], 4096 if not legacy_worker else 0, 48
            ):
                await asyncio.gather(
                    *[
                        engine._guard(
                            "drive",
                            f"fill:{i}",
                            root.run_id,
                            {"scope": asdict(scope), "kind": "drive"},
                        )
                        for i in range(fill_start, min(fill_start + 48, 4096))
                    ]
                )
                (tmp_path / "progress.json").write_text(
                    json.dumps({"accepted": min(fill_start + 48, 4096)})
                )
            if not legacy_worker:
                assert (await registry.query("view", {"scope": asdict(scope)}))[
                    "accepted_commands"
                ] == 4096
                with pytest.raises(ValidationError):
                    await engine.submit(AgentSpec("new", "new"), "new", command_id="refused")
            else:
                # Directly exercise the existing strong-admission helper against
                # its genuine old CONTROL verifier; no full-capacity claim here.
                from relf_agent.temporal_scoped_manual_recovery import reserve_manual

                payload = {
                    "kind": "reconcile",
                    "scope": asdict(scope),
                    "action_id": first["id"],
                    "query": False,
                    "result": "operator confirms slow effect",
                }
                await reserve_manual(
                    engine,
                    registry,
                    {
                        "scope": asdict(scope),
                        "command_id": "confirm",
                        "kind": "reconcile",
                        "target": child,
                        "payload_digest": digest(payload),
                    },
                    payload,
                )
            if pressure_updates:
                repeat = {
                    "scope": asdict(scope),
                    "command_id": f"fill:{before['accepted_commands']}",
                    "kind": "drive",
                    "target": root.run_id,
                    "payload_digest": digest({"scope": asdict(scope), "kind": "drive"}),
                }
                for update_start in range(0, 2000, 8):
                    await asyncio.gather(
                        *[registry.execute_update("reserve", repeat) for _ in range(8)]
                    )
                    (tmp_path / "update-progress.json").write_text(
                        json.dumps({"distinct_updates": update_start + 8})
                    )
                assert (await registry.query("view", {"scope": asdict(scope)}))[
                    "accepted_commands"
                ] == 4096
            receipt = await engine.reconcile(
                child, first["id"], "operator confirms slow effect", command_id="confirm"
            )
            assert (await registry.query("view", {"scope": asdict(scope)}))[
                "accepted_commands"
            ] == (before["accepted_commands"] + 1 if legacy_worker else 4097)
            if legacy_worker:
                # This compatibility case has free ordinary slots. Existing
                # late evidence is allowed, but cannot replace the first result
                # or clear its independent physical-end obligation.
                late = await engine.reconcile(
                    child, first["id"], "changed", command_id="another-confirm"
                )
                assert late.apply_state == "applied"
                same = next(
                    a for a in (await engine.status(child)).actions if a["id"] == first["id"]
                )
                assert same["result"] == "operator confirms slow effect"
                assert same["execution_unconfirmed"] is True
            else:
                with pytest.raises(RalfError):
                    await engine.reconcile(
                        child, first["id"], "changed", command_id="another-confirm"
                    )
            finished = await _eventually(
                lambda: engine.diagnostics(child),
                lambda d: (
                    d.snapshot.state == "succeeded" and (not d.workflow["evidence_ack_pending"])
                ),
            )
            assert (tmp_path / "fast-returned").exists() and (
                not (tmp_path / "slow-ended").exists()
            )
            assert finished.budget["unknown"] == finished.budget["reserved"] == 0
            assert finished.workflow["quiescent"] is False
            observed = await _eventually(
                lambda: engine.diagnostics(root.run_id),
                lambda d: d.workflow["children"][0].get("uncertain") is True,
            )
            assert not observed.workflow["quiescent"] and (
                not observed.workflow["children"][0].get("settled", False)
            )
            assert observed.budget["reserved"] + observed.budget["unknown"] > 0
            assert next(a for a in finished.snapshot.actions if a["id"] == first["id"])[
                "execution_unconfirmed"
            ]
            (tmp_path / "while-live.json").write_text(
                json.dumps(
                    {
                        "legacy": False,
                        "original_thread_live": True,
                        "second_tool_completed": True,
                        "effect_credits_unknown": finished.budget["unknown"],
                        "child_quiescent": finished.workflow["quiescent"],
                        "parent_quiescent": observed.workflow["quiescent"],
                        "child_settled": observed.workflow["children"][0].get("settled", False),
                    }
                )
            )
            (tmp_path / "release-slow").touch()
            async with asyncio.timeout(5):
                while not (tmp_path / "slow-ended").exists():  # noqa: ASYNC110 -- peer process evidence
                    await asyncio.sleep(0.02)
            await stop("first", process)
            _, replacement = await start("replacement")
            assert replacement == release
            restored = await engine.diagnostics(child)
            assert restored.workflow["quiescent"] is False
            assert (
                await engine.reconcile(
                    child, first["id"], "operator confirms slow effect", command_id="confirm"
                )
                == receipt
            )
            for index, target in enumerate(sorted(owned)):
                history = await client.get_workflow_handle(target).fetch_history()
                await replay_temporal_history(history, namespace=namespace["name"])
                (tmp_path / f"history-{index}.json").write_text(history.to_json())
                if target == engine.command_registry_id:
                    manual_signals = sum(
                        e.HasField("workflow_execution_signaled_event_attributes")
                        and e.workflow_execution_signaled_event_attributes.signal_name
                        == "reserve_scoped_manual"
                        for e in history.events
                    )
                    assert (manual_signals == 0) is legacy_worker
                if target == child:
                    marked = any(
                        b"ralf-unowned-tool-end-evidence-v1" in p.data
                        for e in history.events
                        if e.HasField("marker_recorded_event_attributes")
                        for v in e.marker_recorded_event_attributes.details.values()
                        for p in v.payloads
                    )
                    assert marked is True
            (tmp_path / "result.json").write_text(
                json.dumps(
                    {
                        "normal_capacity": None if legacy_worker else 4096,
                        "registry_distinct_updates_before_manual": 2000 if pressure_updates else 0,
                        "accepted_after_manual": before["accepted_commands"] + 1
                        if legacy_worker
                        else 4097,
                        "legacy_manual_transport_compatibility": legacy_worker,
                        "manual_proof_signals": manual_signals,
                        "legacy_baseline": False,
                        "protected": True,
                        "thread_started_and_ended": True,
                        "worker_restart_preserves_evidence": True,
                        "original_receipt_repeated": True,
                        "all_histories_replayed": True,
                        "external_model_calls": 0,
                    },
                    indent=2,
                )
            )
        except BaseException as exc:
            failure = exc
        finally:
            failures = [failure] if failure is not None else []
            (tmp_path / "release-slow").touch()
            if (tmp_path / "slow-started").exists():
                try:
                    async with asyncio.timeout(5):
                        while not (tmp_path / "slow-ended").exists():  # noqa: ASYNC110 -- peer process evidence
                            await asyncio.sleep(0.02)
                except BaseException as exc:
                    failures.append(exc)
            try:
                await discover_owned_descendants(client, owned)
            except BaseException as exc:
                failures.append(exc)
            for target in sorted(owned):
                try:
                    handle = client.get_workflow_handle(target)
                    if failure is not None:
                        (tmp_path / f"failed-history-{target}.json").write_text(
                            (await handle.fetch_history()).to_json()
                        )
                    if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await handle.terminate(reason="owned unowned-tool acceptance cleanup")
                    assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
            for generation, process in processes:
                try:
                    await stop(generation, process)
                except BaseException as exc:
                    failures.append(exc)
            if engine is not None:
                await engine.aclose()
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_histories_closed": len(owned),
                        "workers_closed": len(processes),
                        "original_thread_ended": (tmp_path / "slow-ended").exists(),
                        "body_failed": failure is not None,
                        "cleanup_failed": len(failures) > int(failure is not None),
                    }
                )
            )
            if failures:
                raise BaseExceptionGroup("unowned Tool end acceptance and cleanup", failures)

    asyncio.run(asyncio.wait_for(run(), 180))
