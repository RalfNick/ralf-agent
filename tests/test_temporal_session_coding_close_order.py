"""Session acceptance closes even while original Coding retirement is pending."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent import Scope, TemporalProfile
from ralf_agent.errors import CloseIncomplete
from ralf_agent.runtime_lifecycle import BuildContext
from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly


@pytest.mark.parametrize("cancel_caller", [False, True])
def test_pending_coding_stop_does_not_leave_session_acceptance_open(
    tmp_path, monkeypatch, cancel_caller
):
    from ralf_agent import temporal_deployment_coding_bridge as coding
    from ralf_agent import temporal_session_deployment_close as sessions

    async def run():
        events = []
        coding_started, session_fenced, coding_stopped = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        release_coding, release_session = asyncio.Event(), asyncio.Event()

        async def close_coding(runtime, *, client, scope, task_queue):
            events.append("coding-start")
            coding_started.set()
            await release_coding.wait()
            coding_stopped.set()
            events.append("coding-stopped")

        async def close_sessions(runtime, *, client, scope, task_queue, wait_timeout):
            assert client.namespace == "original" and task_queue == "original-queue"
            events.append("session-fenced")
            session_fenced.set()
            await release_session.wait()
            assert coding_stopped.is_set()
            events.append("session-closed")

        async def close_owner(**options):
            assert coding_stopped.is_set() and "session-closed" in events
            events.append("owner-closed")

        scope = Scope()
        runtime = SimpleNamespace(
            orchestration_release={
                "binding_protocol": 23,
                "session_deployment_protocol": 1,
                "coding_execution_protocol": {},
                "deployment_admission_protocol": {"version": 4},
            },
            coding_execution=True,
            _deployment_public_execution=True,
            close_deployment_execution=close_owner,
            close_context_execution=close_owner,
            close_session_execution=close_owner,
        )
        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        assembly = TemporalRuntimeAssembly(
            runtime,
            context,
            TemporalProfile("original", "1", {"default": {"adapter": "echo"}}),
            scope,
        )
        assembly._bind_client(SimpleNamespace(namespace="original"), "original-queue")
        monkeypatch.setattr(coding, "close", close_coding)
        monkeypatch.setattr(sessions, "close", close_sessions)
        pending = asyncio.create_task(assembly.aclose(wait_timeout=0.1))
        try:
            await asyncio.wait_for(coding_started.wait(), 1)
            # A pending Coding drain must not defer the independent Session fence.
            for _ in range(30):
                if session_fenced.is_set():
                    break
                await asyncio.sleep(0)
            assert session_fenced.is_set()
            session_task = assembly._session_stop_task
            coding_task = assembly._coding_stop_task
            if cancel_caller:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                with pytest.raises(CloseIncomplete):
                    await pending
            assert not session_task.done() and not coding_task.done()
            assert not assembly._closed and "owner-closed" not in events
            release_coding.set()
            await coding_task
            release_session.set()
            await session_task
            await assembly.aclose(wait_timeout=1)
            assert assembly._closed and events.count("coding-start") == 1
            assert events.count("session-fenced") == 1
            assert events.index("coding-stopped") < events.index("owner-closed")
            assert events.index("session-closed") < events.index("owner-closed")
        finally:
            release_coding.set()
            release_session.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            for name in ("_coding_stop_task", "_session_stop_task"):
                task = getattr(assembly, name, None)
                if task is not None:
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
