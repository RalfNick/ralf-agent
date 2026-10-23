import asyncio
from dataclasses import replace

import httpx
import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from relf_agent.a2a import A2AApplication
from relf_agent.handoff import SQLiteInbox
from relf_agent.task_controls import TaskControlBridge


@pytest.mark.parametrize("failed", [False, True])
def test_cancel_bridge_preserves_terminal_authority_rejection_and_replay(tmp_path, failed):
    class Provider:
        identity = {"kind": "terminal-cancel", "version": "1"}

        async def complete(self, messages, tools):
            if failed:
                return ModelResponse()
            return ModelResponse(output="done")

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
            snapshot = await engine.drive(handle.run_id)
            assert snapshot.state == ("failed" if failed else "succeeded")
            original = engine.cancel(handle.run_id, command_id="late")
            assert original.apply_state == "rejected"
            assert original.outcome == {"reason": "too_late"}
            bridge = TaskControlBridge(engine, engine.scope)
            assert await bridge.cancel(handle.run_id, command_id="late") == original
            assert await bridge.cancel(handle.run_id, command_id="late") == original
            assert engine.status(handle.run_id) == snapshot

    asyncio.run(run())


@pytest.mark.parametrize("legacy_receipt", [False, True])
def test_a2a_cancel_completion_race_reports_not_cancelable(tmp_path, legacy_receipt):
    async def run():
        started, release, sampled, finished = (asyncio.Event() for _ in range(4))

        class Provider:
            identity = {"kind": "cancel-race", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return ModelResponse(output="done")

        with (
            LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": Provider()},
                tools=ToolRegistry(),
            ) as engine,
            SQLiteInbox(tmp_path / "inbox.sqlite") as inbox,
        ):
            handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
            drive = asyncio.create_task(engine.drive(handle.run_id))
            await started.wait()

            class AsyncControls:
                scope = engine.scope
                delayed = False

                async def submit(self, *args, **kwargs):
                    return engine.submit(*args, **kwargs)

                async def status(self, run_id):
                    snapshot = engine.status(run_id)
                    if not self.delayed:
                        self.delayed = True
                        sampled.set()
                        await finished.wait()
                    return snapshot

                async def cancel(self, *args, **kwargs):
                    receipt = engine.cancel(*args, **kwargs)
                    if legacy_receipt and receipt.apply_state == "rejected":
                        # Temporal's existing representation remains a supported receipt.
                        return replace(
                            receipt,
                            apply_state="applied",
                            outcome={"rejected": True, **receipt.outcome},
                        )
                    return receipt

            controls = AsyncControls()

            async def authenticate(headers):
                return Scope()

            async def complete_between_status_and_cancel():
                await sampled.wait()
                release.set()
                await drive
                finished.set()

            completion = asyncio.create_task(complete_between_status_and_cancel())
            app = A2AApplication(
                engine_for_scope=lambda scope: controls,
                spec=AgentSpec("a", "Answer"),
                inbox=inbox,
                authenticate=authenticate,
                url="http://test/rpc",
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
                for request_id in ("first", "replay"):
                    response = await client.post(
                        "http://test/rpc",
                        json={
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "tasks/cancel",
                            "params": {"id": handle.run_id, "metadata": {"ralfCommandId": "late"}},
                        },
                    )
                    assert response.json()["error"]["code"] == -32002
            await completion
            assert engine.status(handle.run_id).state == "succeeded"
            original = engine.cancel(handle.run_id, command_id="late")
            assert original.apply_state == "rejected"
            assert original.outcome == {"reason": "too_late"}

    asyncio.run(run())
