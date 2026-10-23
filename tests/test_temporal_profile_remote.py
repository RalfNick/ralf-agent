"""Actual remote factories and selected Agent Sessions from Profile declarations."""

import asyncio
import os
import uuid

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    BindingSelection,
    BoundDefinition,
    Runtime,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
)
from relf_agent.temporal import replay_temporal_history

from .test_temporal_context_read_composition import definition


@pytest.mark.parametrize("backend", ["redis", "postgres"])
def test_profile_remote_root_and_selected_private_sessions(monkeypatch, backend):
    if not os.getenv("RALF_TEST_TEMPORAL_ADDRESS") or not os.getenv(
        "RALF_TEST_REDIS_URL" if backend == "redis" else "RALF_TEST_POSTGRES_DSN"
    ):
        pytest.skip("requires actual Temporal and selected remote service")

    async def run():
        from temporalio.client import Client

        identity = "profile-remote-" + uuid.uuid4().hex
        schema = None
        admin = None
        if backend == "redis":

            def declaration(label):
                return {
                    "adapter": "redis",
                    "config": {
                        "url_env": "RALF_TEST_REDIS_URL",
                        "backend_id": identity + label,
                        "prefix": identity + label,
                    },
                }
        else:
            import psycopg
            from psycopg import sql

            schema = "profile_" + uuid.uuid4().hex
            admin = await psycopg.AsyncConnection.connect(
                os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
            )
            await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            dsn = psycopg.conninfo.make_conninfo(
                os.environ["RALF_TEST_POSTGRES_DSN"], options="-c search_path=" + schema
            )
            monkeypatch.setenv("RALF_PROFILE_TEST_DSN", dsn)

            def declaration(label):
                return {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_PROFILE_TEST_DSN",
                        "backend_id": identity + label,
                        "initialize": True,
                    },
                }

        selected = TemporalProfile(
            "remote",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {
                "session_store": declaration("root"),
                "context_assembler": {"adapter": "managed-summary"},
            },
            binding_components=[
                {
                    "role": "session",
                    "component_id": "private",
                    "version": "1",
                    "component": {
                        "adapter": "session-resource",
                        "config": {
                            "backend": declaration("private"),
                            "namespaces": ["private-a", "private-b"],
                            "default_namespace": "private-a",
                        },
                    },
                }
            ],
            execution={
                "enable_sessions": True,
                "session_writes": True,
                "composite_sessions": True,
                "context_reads": True,
            },
        )
        assembled = None
        host = None
        try:
            assembled = await TemporalRuntimeBuilder().abuild(
                selected, scope=Scope("profile-remote", identity)
            )
            client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
            await assembled.start_worker(client, task_queue=identity)
            engine = assembled.create_engine(
                client, task_queue=identity, activity_timeout=3, drive_timeout=25
            )
            host = Runtime.from_temporal(engine)
            bound = BoundDefinition(
                definition("graph"),
                {
                    "graph/nodes/writer": AgentBindingDescriptor(
                        session=BindingSelection.ref(
                            "private", "1", selector={"namespace": "private-b"}
                        )
                    )
                },
            )
            entry = await host.open_session(bound, "chat", command_id="open")
            for index in (1, 2):
                turn = await entry.submit("question", command_id=f"turn-{index}", budget=32)
                done = await engine.drive(turn.turn.run.run_id)
                assert done.state == "succeeded", done
                async with asyncio.timeout(15):
                    while (await entry.status()).busy:  # noqa: ASYNC110 -- actual remote Turn evidence
                        await asyncio.sleep(0.05)
                root = await engine._view(done.run_id, "diagnostics")
                child_id = root["workflow"]["children"][0]["run_id"]
                raw = await engine._view(child_id, "diagnostics")
                saves = raw["session_stages"]
                assert saves[0]["status"] == "completed"
                assert saves[0]["execution_stopped"] is True
                assert all(read["execution_end_proof"] for read in raw["context_reads"])
                assert raw["manifest"]["runtime_profile"] == selected.identity
                for run_id in (done.run_id, child_id):
                    await replay_temporal_history(
                        await client.get_workflow_handle(run_id).fetch_history()
                    )
        finally:
            if host is not None:
                await host.aclose()
            if assembled is not None:
                await assembled.aclose(wait_timeout=20)
            if admin is not None:
                try:
                    await admin.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
                finally:
                    await admin.close()

    asyncio.run(asyncio.wait_for(run(), 150))
