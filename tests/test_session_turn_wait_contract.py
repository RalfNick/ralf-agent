"""The ordered-Turn fixture must observe idle, independently of Run success."""

import asyncio

import ralf_agent as r
from ralf_agent.agent_session import AgentSession

from .test_agent_sessions import (
    test_ordered_turns_keep_history_and_original_receipts as ordered_turns,
)


def test_ordered_turns_observe_idle_with_terminal_host_cleanup_pending(monkeypatch, tmp_path):
    release, held = asyncio.Event(), asyncio.Event()
    drive = r.LocalEngine.drive
    status = AgentSession.status
    close = r.Runtime.aclose

    async def hold_terminal_host(self, run_id):
        result = await drive(self, run_id)
        if result.state == "succeeded" and not held.is_set():
            held.set()
            await release.wait()
        return result

    async def observe_then_release(self):
        result = await status(self)
        if result.busy:
            release.set()
        return result

    async def close_after_release(self):
        release.set()
        return await close(self)

    monkeypatch.setattr(r.LocalEngine, "drive", hold_terminal_host)
    monkeypatch.setattr(AgentSession, "status", observe_then_release)
    monkeypatch.setattr(r.Runtime, "aclose", close_after_release)
    ordered_turns("bound", tmp_path)
    assert held.is_set()
