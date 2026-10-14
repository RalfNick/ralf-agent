"""Actual Temporal Worker/PG; deterministic native process peer, no real model."""

import asyncio
import os
from pathlib import Path

from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.postgres_runner_journal import PostgresRunnerJournal
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import ModelResponse, Scope, ToolCall


class Provider:
    identity = {"kind": "temporal-coding-process-peer", "version": "106"}

    async def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return ModelResponse(output="finished")
        return ModelResponse(
            tool_calls=(
                ToolCall(tools[0]["function"]["name"], {"task": "fixed task"}, "original-call"),
            )
        )


class FaultClient:
    """Fault occurs after the real SDK confirms an original History Update."""

    def __init__(self, client, fault):
        self.client, self.fault, self.triggered = client, fault, False

    def __getattr__(self, name):
        return getattr(self.client, name)

    def get_workflow_handle(self, *args, **kwargs):
        owner = self
        original = self.client.get_workflow_handle(*args, **kwargs)

        class Handle:
            def __getattr__(self, name):
                return getattr(original, name)

            async def execute_update(self, name, payload, **options):
                result = await original.execute_update(name, payload, **options)
                matches = {
                    "claim_crash": name == "admit_tool_dispatch",
                    "prepare_crash": name == "admit_coding_phase"
                    and payload.get("method") == "prepare",
                    "turn_grant_crash": name == "admit_coding_phase"
                    and payload.get("method") == "turn/start",
                    "candidate_loss": name == "coding_receipt"
                    and payload.get("kind") == "result_candidate",
                }
                if not owner.triggered and matches.get(owner.fault, False):
                    owner.triggered = True
                    print("FAULT_WINDOW_" + owner.fault, flush=True)
                    if owner.fault.endswith("crash"):
                        os._exit(71)
                    raise OSError("Original committed History response lost")
                return result

        return Handle()


async def runtime(*, request_timeout=5):
    import psycopg
    from psycopg import sql

    conn = await psycopg.AsyncConnection.connect(
        os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True
    )
    await conn.execute(
        sql.SQL("SET search_path TO {}").format(sql.Identifier(os.environ["RALF_CODING_SCHEMA"]))
    )
    effect = PostgresEffectJournal(conn, backend_id="coding-process-peer", owns_connection=True)
    await effect.initialize()
    journal = PostgresRunnerJournal(effect, identity={"deployment": "coding-process-peer-106"})
    await journal.initialize()
    root = Path(os.environ["RALF_CODING_ROOT"])
    native = CodexCodingRunner(
        root,
        journal=journal,
        docker_executable=os.environ["RALF_CODING_DOCKER"],
        docker_host=os.environ["RALF_CODING_HOST"],
        request_timeout=request_timeout,
    )
    tools = ToolRegistry()
    register_coding_tool(tools, native)
    from ralf_agent.binding_catalog import BindingCatalog

    catalog = BindingCatalog(scope=Scope("coding-service", os.environ["RALF_CODING_QUEUE"]))
    catalog.register("runner", "original", "1", native)
    return (
        TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            journal=effect,
            coding_execution=True,
            binding_catalog=catalog,
        ),
        native,
        journal,
    )


async def main():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    if os.getenv("RALF_CODING_FAULT"):
        client = FaultClient(client, os.environ["RALF_CODING_FAULT"])
    built, native, journal = await runtime()
    worker = build_temporal_worker(
        client, task_queue=os.environ["RALF_CODING_QUEUE"], runtime=built
    )
    async with worker:
        print("CODING_WORKER_READY", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
