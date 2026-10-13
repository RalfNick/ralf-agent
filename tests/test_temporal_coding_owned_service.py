"""Owned builder shutdown against real History/PG and a deterministic native peer."""

import asyncio
import json
import os
import socket
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, Scope, TemporalProfile, TemporalRuntimeBuilder
from ralf_agent.errors import CloseIncomplete, ValidationError
from ralf_agent.temporal import replay_temporal_history
from tests.temporal_coding_worker_fixture import Provider
from tests.test_codex_runner import native_fixture
from tests.test_temporal_coding_service import wait_until

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="Requires actual Temporal and PostgreSQL",
)


class OwnedPeer(Provider):
    identity = {"kind": "owned-coding-shutdown-peer", "version": "106"}

    def __init__(self):
        self.calls = 0
        self.closed = False
        self.on_close = None

    async def complete(self, messages, tools):
        self.calls += 1
        return await super().complete(messages, tools)

    async def aclose(self):
        if self.on_close is not None:
            await self.on_close()
        self.closed = True


async def completed_updates(history):
    """Read the real accepted request and matching completed Update receipts."""
    from temporalio.converter import DataConverter

    accepted, completed = {}, {}
    converter = DataConverter.default
    for event in history.events:
        if event.HasField("workflow_execution_update_accepted_event_attributes"):
            request = event.workflow_execution_update_accepted_event_attributes.accepted_request
            values = await converter.decode(request.input.args.payloads)
            accepted[request.meta.update_id] = (request.input.name, values[0])
        if event.HasField("workflow_execution_update_completed_event_attributes"):
            attributes = event.workflow_execution_update_completed_event_attributes
            if attributes.outcome.HasField("success"):
                values = await converter.decode(attributes.outcome.success.payloads)
                assert len(values) == 1
                completed[attributes.meta.update_id] = values[0]
    return [(*accepted[key], completed[key]) for key in completed if key in accepted]


def test_owned_coding_close_retains_original_receivers_and_ledger_then_retries(
    tmp_path, monkeypatch
):
    async def run():
        import psycopg
        from psycopg import sql
        from temporalio.client import Client

        schema = "coding_owned_106_" + uuid.uuid4().hex
        admin = await psycopg.AsyncConnection.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
        )
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = psycopg.conninfo.make_conninfo(
            os.environ["RALF_TEST_POSTGRES_DSN"], options="-c search_path=" + schema
        )
        monkeypatch.setenv("RALF_OWNED_CODING_DSN", scoped_dsn)
        root = tmp_path / "owned-native"
        root.mkdir(mode=0o700)
        cli = native_fixture(tmp_path, "hang_turn")
        sock = socket.socket(socket.AF_UNIX)
        sock_path = Path("/private/tmp") / ("ralf-owned-" + uuid.uuid4().hex[:12] + ".sock")
        sock.bind(str(sock_path))
        cli.write_text(
            cli.read_text().replace("unix:///fixture/docker.sock", "unix://" + str(sock_path))
        )
        queue = "coding-owned-106-" + uuid.uuid4().hex
        scope = Scope("coding-owned-service", queue)
        peer = OwnedPeer()
        registry = ComponentRegistry()
        registry.register("provider", "owned-coding-peer", lambda c, ctx: ctx.own_async(peer))
        profile = TemporalProfile(
            "owned-coding",
            "106",
            {"default": {"adapter": "owned-coding-peer"}},
            {
                "effect_journal": {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_OWNED_CODING_DSN",
                        "backend_id": queue,
                        "initialize": True,
                    },
                },
                "tools": {
                    "adapter": "codex-coding-postgres",
                    "config": {
                        "name": "coding",
                        "description": "Finite original Coding task",
                        "cost": 1,
                        "runner_root": str(root),
                        "fixed_dependencies": {"deployment": queue},
                        "docker_executable": str(cli),
                        "docker_host": "unix://" + str(sock_path),
                        "request_timeout": 30,
                    },
                },
            },
            execution={"coding_execution": True},
        )
        assembly = None
        fail_kill = tmp_path / "fail-kill"
        try:
            assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile, scope=scope
            )
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            await assembly.start_worker(client, task_queue=queue)
            engine = assembly.create_engine(
                client, task_queue=queue, activity_timeout=40, drive_timeout=40
            )
            runtime = assembly._runtime
            native = runtime.tools.get("coding").handler.runner
            journal, effect = native._journal, runtime.journal
            assert journal._effect is effect
            ledger = assembly._context._resources
            original_ledger = tuple(item.resource for item in ledger)
            assert (
                peer in original_ledger and native in original_ledger and effect in original_ledger
            )
            handle = await engine.submit(
                AgentSpec("code", "Perform approved Coding", tools=("coding",)),
                "fixed task",
                command_id="submit",
            )
            waiting = await wait_until(
                lambda: engine.status(handle.run_id),
                lambda value: value.state == "waiting_approval",
            )
            pending = waiting.pending[0]
            await engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            sdk = client.get_workflow_handle(handle.run_id)

            async def diagnostics():
                return await sdk.query("view", {"scope": asdict(scope), "kind": "diagnostics"})

            raw = await wait_until(
                diagnostics,
                lambda value: any(
                    action.get("delegated_execution", {}).get("turn")
                    for action in value["snapshot"]["actions"]
                ),
            )
            action = next(item for item in raw["snapshot"]["actions"] if item["kind"] == "tool")
            original_native = action["delegated_execution"]
            original_execution = raw["workflow"]["tool_executions"][0]
            original_cid = original_native["prepared"]["container_id"]
            assert original_native["pending_stop"] is True and original_native["fenced"] is False
            counter = tmp_path / "native-submissions.jsonl"
            assert len(counter.read_text().splitlines()) == 2 and peer.calls == 1
            assert native.active_operations == 1
            assert len(await journal.pending_resources(scope)) == 1
            receipts = []

            async def verify_final_release():
                assert assembly._worker_stop.done() and assembly._worker_start.done()
                assert native.active_operations == 0 and effect.connection.closed
                cursor = await admin.execute(
                    sql.SQL("SELECT record FROM {}.ralf_temporal_coding_resources").format(
                        sql.Identifier(schema)
                    )
                )
                saved = json.loads((await cursor.fetchone())[0])
                assert saved["pending_stop"] is False
                assert saved["stop"]["container_id"] == original_cid
                assert saved["stop"]["fenced"] is True and saved["stop"]["transport_closed"] is True
                history = await sdk.fetch_history()
                updates = await completed_updates(history)
                expected_ack = {"action_id": action["id"], "recorded": True}
                expected_proof = {
                    "scope": asdict(scope),
                    "action_id": action["id"],
                    "release_digest": raw["release_digest"],
                    "request_digest": original_execution["request_digest"],
                    "execution_epoch": original_execution["execution_epoch"],
                }
                assert any(
                    name == "coding_receipt"
                    and payload.get("kind") == "stop"
                    and payload["evidence"] == saved["stop"]
                    and acknowledgement == expected_ack
                    and all(payload[key] == value for key, value in expected_proof.items())
                    for name, payload, acknowledgement in updates
                )
                assert any(
                    name == "tool_execution_ended"
                    and payload.get("invocation_id") == original_execution["invocation_id"]
                    and acknowledgement == expected_ack
                    and all(payload[key] == value for key, value in expected_proof.items())
                    for name, payload, acknowledgement in updates
                )
                receipts.append(history)

            peer.on_close = verify_final_release
            fail_kill.touch()
            with pytest.raises(CloseIncomplete):
                await assembly.aclose(wait_timeout=10)
            assert assembly._closing and not assembly._closed
            assert assembly._worker_stop is None and not assembly._worker_start.done()
            assert assembly._client is client
            assert assembly._context._resources is ledger
            assert tuple(item.resource for item in ledger) == original_ledger
            assert not peer.closed and not journal._closed and not effect.connection.closed
            assert len(await journal.pending_resources(scope)) == 1
            assert len(counter.read_text().splitlines()) == 2 and peer.calls == 1
            retained = await diagnostics()
            retained_action = next(
                item for item in retained["snapshot"]["actions"] if item["id"] == action["id"]
            )
            assert len(retained_action["attempts"]) == 1
            assert retained_action["delegated_execution"]["pending_stop"] is True
            with pytest.raises(ValidationError):
                assembly.create_engine(client, task_queue=queue)
            fail_kill.unlink()
            await assembly.aclose(wait_timeout=20)
            assert assembly._closed and peer.closed and receipts
            assert assembly._context._resources is ledger and ledger == []
            assert journal._closed and effect.connection.closed
            assert len(counter.read_text().splitlines()) == 2 and peer.calls == 1
            cursor = await admin.execute(
                sql.SQL("SELECT state FROM {}.ralf_temporal_effects").format(sql.Identifier(schema))
            )
            assert (await cursor.fetchone())[0] != "adopted"
            docker = json.loads((tmp_path / "docker.json").read_text())
            assert docker["containers"] == {} and docker["removed"] == [original_cid]
            await replay_temporal_history(receipts[0])
        finally:
            fail_kill.unlink(missing_ok=True)
            if assembly is not None:
                await assembly.aclose(wait_timeout=20)
            sock.close()
            sock_path.unlink(missing_ok=True)
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await admin.close()

    asyncio.run(asyncio.wait_for(run(), 90))
