"""Real Worker process fixture; no credentials or model network access."""

import asyncio
import os
import sqlite3
from pathlib import Path

from ralf_agent import Scope, SQLiteArtifactStore
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from tests.test_composite_data_context import Provider, registry
from tests.test_managed_data_context import context


def runtime(root, queue):
    root = Path(root)
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")

    class Artifacts(SQLiteArtifactStore):
        block = False

        async def put(self, *args, **kwargs):
            return super().put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            result = super().get(*args, **kwargs)
            if self.block:
                self.block = False
                (root / "model-artifact-read-ready").write_text("ready")
                for _ in range(400):
                    if (root / "release-model-read").exists():
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise TimeoutError("Test controller did not release the artifact read")
            return result

    artifacts = Artifacts(root / "artifacts.sqlite")

    class RecordedProvider(Provider):
        async def complete(self, messages, tools):
            kind = (
                "summary" if messages[0]["content"].startswith("context-summary:") else "business"
            )
            with sqlite3.connect(root / "business.sqlite") as db:
                db.execute("INSERT INTO calls VALUES (?)", (kind,))
            return await super().complete(messages, tools)

    writes = []
    tools = registry(writes)
    target = tools.get("lookup")
    original = target.handler

    def record(arguments, invocation):
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO calls VALUES ('tool')")
        return original(arguments, invocation)

    # Use the same handler implementation on every Worker registration.
    tools = type(tools)()
    tools.register(target.spec, record)
    value = TemporalRuntime(
        providers={"default": RecordedProvider()},
        tools=tools,
        context_builder=context(
            artifacts, scope=Scope("h3-temporal", queue), mode="model", summary_max_chars=256
        ),
    )
    return value, artifacts


async def run():
    from temporalio.client import Client

    root, queue = Path(os.environ["RALF_H3_ROOT"]), os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    value, artifacts = runtime(root, queue)
    original = value.manage_context

    async def gated(request, *, dispatch_guard=None):
        if (
            os.environ.get("RALF_H3_MODE") == "crash"
            and request["phase"] == "finalize"
            and request.get("summary_response", {}).get("received_response")
        ):
            (root / "summary-finalize-ready").write_text("ready")
            await asyncio.Event().wait()
        try:
            value.validate_release(request["runtime_manifest"])
        except Exception as exc:
            print("H3_RELEASE_FAILURE", type(exc).__name__, str(exc), flush=True)
        response = await original(request, dispatch_guard=dispatch_guard)
        if not response.get("ok"):
            print("H3_PHASE_FAILURE", request["phase"], response, flush=True)
        return response

    value.manage_context = gated
    original_model = value.complete_model

    async def gated_model(request, *, dispatch_guard=None):
        if os.environ.get("RALF_H3_MODE") == "cancel-read" and request.get("context", {}).get(
            "context_identity", {}
        ).get("artifact_projection"):
            artifacts.block = True
        return await original_model(request, dispatch_guard=dispatch_guard)

    value.complete_model = gated_model
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=value, release=value.orchestration_release
        ):
            print("H3_TEMPORAL_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        artifacts.close()


if __name__ == "__main__":
    asyncio.run(run())
