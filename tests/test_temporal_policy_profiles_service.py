"""Declared policy, original real History and owned Worker resource retirement."""

import asyncio
import json
import os
import uuid
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalProfileCatalog,
    TemporalRuntimeBuilder,
)
from ralf_agent.errors import CloseIncomplete
from ralf_agent.governance import TemporalExecutionPolicy
from ralf_agent.temporal import replay_temporal_history

from .test_temporal_composite_service import fixture

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires real Temporal/PostgreSQL",
)


def selected_profile(policy, *, name="policy-service"):
    return TemporalProfile(
        name,
        "1",
        {"default": {"adapter": "policy-service"}},
        {
            "tools": {"adapter": "policy-service"},
            "effect_journal": {
                "adapter": "postgres",
                "config": {
                    "dsn_env": "RALF_TEST_POSTGRES_DSN",
                    "backend_id": name,
                    "initialize": True,
                },
            },
            "execution_policy": {"adapter": "bounded", "config": policy},
        },
    )


def through_catalog(tmp_path, profile, syntax):
    if syntax == "sdk":
        return profile
    path = tmp_path / ("policy." + syntax)
    if syntax == "json":
        path.write_text(
            json.dumps(
                {
                    "kind": "temporal-profiles",
                    "schema_version": 1,
                    "default": {"name": profile.name, "version": profile.version},
                    "profiles": [profile.to_dict()],
                }
            )
        )
    else:
        assert syntax == "toml"
        lines = [
            'kind = "temporal-profiles"',
            "schema_version = 1",
            "[default]",
            f"name = {json.dumps(profile.name)}",
            f"version = {json.dumps(profile.version)}",
            "[[profiles]]",
            f"name = {json.dumps(profile.name)}",
            f"version = {json.dumps(profile.version)}",
            "[profiles.providers.default]",
            'adapter = "policy-service"',
        ]
        for kind, declaration in profile.components.items():
            lines.extend(
                [f"[profiles.components.{kind}]", f"adapter = {json.dumps(declaration['adapter'])}"]
            )
            if declaration["config"]:
                lines.append(f"[profiles.components.{kind}.config]")
                for key, value in declaration["config"].items():
                    lines.append(f"{key} = {json.dumps(value)}")
        path.write_text("\n".join(lines) + "\n")
    result = TemporalProfileCatalog.from_file(path).default_profile
    assert result.identity == profile.identity
    return result


async def assembled(profile, scope, tmp_path, *, provider=None):
    factories = ComponentRegistry()
    factories.register(
        "provider", "policy-service", lambda c, ctx: provider or fixture.CompositeProvider()
    )
    factories.register("tools", "policy-service", lambda c, ctx: fixture.native.tools())
    result = await TemporalRuntimeBuilder(factories, base_dir=tmp_path).abuild(profile, scope=scope)
    try:
        await result._runtime.journal.connection.execute(
            "CREATE TABLE IF NOT EXISTS ralf_temporal_probe_effects "
            "(effect_key TEXT PRIMARY KEY, label TEXT NOT NULL, result TEXT NOT NULL, writes INTEGER NOT NULL)"
        )
    except BaseException as original:
        try:
            await result.aclose(wait_timeout=15)
        except BaseException as cleanup:
            original.add_note(f"Owned service assembly cleanup failed: {type(cleanup).__name__}")
            original.policy_service_assembly = result
        raise
    return result


class HeldProvider(fixture.CompositeProvider):
    def __init__(self, started, release):
        self.started, self.release = started, release

    async def complete(self, messages, tools):
        self.started.set()
        await self.release.wait()
        return ModelResponse(output={"slow": "complete"})


async def view(client, run_id, scope):
    return await client.get_workflow_handle(run_id).query(
        "view", {"scope": asdict(scope), "kind": "diagnostics"}
    )


async def eventually(operation, predicate, *, seconds=15):
    async with asyncio.timeout(seconds):
        while not predicate(value := await operation()):  # noqa: ASYNC110 -- actual History observation
            await asyncio.sleep(0.05)
        return value


@pytest.mark.parametrize("syntax", ["json", "toml"])
def test_actual_declared_approval_expiry_survives_worker_absence_and_rejects_late_approval(
    tmp_path, syntax
):
    async def run():
        from temporalio.client import Client

        queue = "policy-expiry-" + uuid.uuid4().hex
        scope = Scope("policy-profile", queue)
        profile = through_catalog(
            tmp_path,
            selected_profile({"approval_timeout_seconds": 3}, name=queue),
            syntax,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        current = await assembled(profile, scope, tmp_path)
        try:
            await current.start_worker(client, task_queue=queue)
            original_release = current.release
            assert (
                original_release["execution_policy"]
                == TemporalExecutionPolicy(approval_timeout_seconds=3).identity
            )
            engine = current.create_engine(
                client, task_queue=queue, activity_timeout=3, drive_timeout=15
            )
            handle = await engine.submit(
                AgentSpec("change", "Change", ("write",)),
                {"tool": True, "arguments": {"label": queue}},
                command_id="first",
            )
            pending = await engine.drive(handle.run_id)
            assert pending.state == "waiting_approval", pending
            action = pending.pending[0]
            events_before = await eventually(
                lambda: engine.events(handle.run_id),
                lambda events: any(event.kind == "approval_expiry_recorded" for event in events),
            )
            expiry_before = [
                event for event in events_before if event.kind == "approval_expiry_recorded"
            ]
            assert len(expiry_before) == 1
            assert expiry_before[0].data["action_id"] == action["action_id"]
            original_expires_at = expiry_before[0].data["expires_at"]
            history_before = await client.get_workflow_handle(handle.run_id).fetch_history()
            timers_before = [
                event.SerializeToString()
                for event in history_before.events
                if event.HasField("timer_started_event_attributes")
            ]
            # Drive can wake the wait condition, cancelling and recreating its
            # timer with the remaining original TTL before Worker retirement.
            assert timers_before
            original = await client.get_workflow_handle(handle.run_id).describe()
            await current.aclose(wait_timeout=15)
            assert current._closed and current._worker_start.done() and current._worker_stop.done()
            await asyncio.sleep(3.2)  # Server timer expires with no Worker available.
            current = await assembled(profile, scope, tmp_path)
            assert current.release == original_release
            await current.start_worker(client, task_queue=queue)
            engine = current.create_engine(
                client, task_queue=queue, activity_timeout=3, drive_timeout=15
            )
            expired = await eventually(
                lambda: engine.status(handle.run_id), lambda result: result.state == "failed"
            )
            assert expired.error["code"] == "approval_expired"
            assert not any(a["kind"] == "tool" and a["attempts"] for a in expired.actions)
            expired_action = next(a for a in expired.actions if a["id"] == action["action_id"])
            assert expired_action["approval_expires_at"] == original_expires_at
            events_after = await engine.events(handle.run_id)
            assert [
                event for event in events_after if event.kind == "approval_expiry_recorded"
            ] == expiry_before
            expiry_failure = [event for event in events_after if event.kind == "approval_expired"]
            assert len(expiry_failure) == 1
            assert expiry_failure[0].data["action_id"] == action["action_id"]
            assert expiry_before[0].seq < expiry_failure[0].seq
            history_after = await client.get_workflow_handle(handle.run_id).fetch_history()
            assert [
                event.SerializeToString()
                for event in history_after.events
                if event.HasField("timer_started_event_attributes")
            ] == timers_before  # No new wait timer while the original expired TTL is replayed.
            receipt = await engine.approve(
                handle.run_id, action["action_id"], action["digest"], command_id="late"
            )
            assert receipt.outcome["rejected"]
            assert (
                await engine.approve(
                    handle.run_id, action["action_id"], action["digest"], command_id="late"
                )
                == receipt
            )
            assert (
                await client.get_workflow_handle(handle.run_id).describe()
            ).run_id == original.run_id
            raw = await view(client, handle.run_id, scope)
            assert raw["manifest"]["runtime_profile"] == profile.identity
            cursor = await current._runtime.journal.connection.execute(
                "SELECT count(*) FROM ralf_temporal_probe_effects WHERE label=%s", (queue,)
            )
            assert (await cursor.fetchone())[0] == 0
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            await current.aclose(wait_timeout=15)
            assert current._closed and current._worker_start.done()

    asyncio.run(asyncio.wait_for(run(), 90))


def test_actual_declared_approval_before_expiry_survives_owned_restart(tmp_path):
    async def run():
        from temporalio.client import Client

        queue = "policy-approve-" + uuid.uuid4().hex
        scope = Scope("policy-profile", queue)
        profile = selected_profile({"approval_timeout_seconds": 15}, name=queue)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        current = await assembled(profile, scope, tmp_path)
        try:
            await current.start_worker(client, task_queue=queue)
            original_release = current.release
            engine = current.create_engine(
                client, task_queue=queue, activity_timeout=3, drive_timeout=15
            )
            handle = await engine.submit(
                AgentSpec("change", "Change", ("write",)),
                {"tool": True, "arguments": {"label": queue}},
                command_id="first",
            )
            pending = await engine.drive(handle.run_id)
            assert pending.state == "waiting_approval", pending
            action = pending.pending[0]
            original = await client.get_workflow_handle(handle.run_id).describe()
            await current.aclose(wait_timeout=15)
            assert current._closed and current._worker_start.done()
            current = await assembled(profile, scope, tmp_path)
            assert current.release == original_release
            await current.start_worker(client, task_queue=queue)
            engine = current.create_engine(
                client, task_queue=queue, activity_timeout=3, drive_timeout=15
            )
            receipt = await engine.approve(
                handle.run_id, action["action_id"], action["digest"], command_id="approve"
            )
            assert not receipt.outcome.get("rejected", False)
            assert (
                await engine.approve(
                    handle.run_id, action["action_id"], action["digest"], command_id="approve"
                )
                == receipt
            )
            assert (await engine.drive(handle.run_id)).state == "succeeded"
            assert (
                await client.get_workflow_handle(handle.run_id).describe()
            ).run_id == original.run_id
            cursor = await current._runtime.journal.connection.execute(
                "SELECT writes FROM ralf_temporal_probe_effects WHERE label=%s", (queue,)
            )
            assert await cursor.fetchall() == [(1,)]
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            await current.aclose(wait_timeout=15)
            assert current._closed and current._worker_start.done()

    asyncio.run(asyncio.wait_for(run(), 90))


def test_actual_declared_deadline_and_close_preserve_late_original_model_ack(tmp_path):
    async def run():
        from temporalio.client import Client

        queue = "policy-deadline-" + uuid.uuid4().hex
        scope = Scope("policy-profile", queue)
        profile = selected_profile({"run_timeout_seconds": 1}, name=queue)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        started, release = asyncio.Event(), asyncio.Event()
        current = await assembled(profile, scope, tmp_path, provider=HeldProvider(started, release))
        try:
            await current.start_worker(client, task_queue=queue)
            engine = current.create_engine(
                client, task_queue=queue, activity_timeout=3, drive_timeout=15
            )
            handle = await engine.submit(
                AgentSpec("slow", "Answer"), {"model_delay": 2.5}, command_id="first", budget=8
            )
            await asyncio.wait_for(started.wait(), 15)
            cancelled = await eventually(
                lambda: engine.status(handle.run_id), lambda result: result.state == "cancelled"
            )
            assert cancelled.error["code"] == "deadline_exceeded"
            raw = await view(client, handle.run_id, scope)
            assert raw["budget"]["reserved"] == 1 and not raw["workflow"]["quiescent"]
            with pytest.raises(CloseIncomplete):
                await current.aclose(wait_timeout=0)
            assert not current._closed and current._worker_stop is None
            release.set()
            raw = await eventually(
                lambda: view(client, handle.run_id, scope),
                lambda result: result["workflow"]["quiescent"],
            )
            assert raw["snapshot"]["state"] == "cancelled"
            assert raw["budget"]["reserved"] == 0 and raw["budget"]["spent"] == 1
            assert raw["manifest"]["runtime_profile"] == profile.identity
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            release.set()
            await current.aclose(wait_timeout=15)
            assert current._closed and current._worker_start.done() and current._worker_stop.done()

    asyncio.run(asyncio.wait_for(run(), 90))
