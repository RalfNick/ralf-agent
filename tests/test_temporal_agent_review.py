"""Permanent reproductions from the single independent dev33 review."""

import asyncio
from dataclasses import replace

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, ValidationError

from .temporal_agent_fixture import StateClient, engine


@pytest.mark.parametrize("operation", ["cancel", "resume", "submit"])
def test_managed_dispatch_never_follows_changed_client_after_internal_await(monkeypatch, operation):
    async def scenario():
        a, b = StateClient("a:7233"), StateClient("b:7233")
        a.hold_execution = b.hold_execution = True
        raw, other = engine(monkeypatch, client=a), engine(monkeypatch, client=b)
        spec = r.AgentSpec("a", "A")
        entered, release = asyncio.Event(), asyncio.Event()
        async with r.Runtime.from_temporal(raw) as runtime:
            if operation == "submit":
                original = raw._guard

                async def paused_guard(*args, **kwargs):
                    await original(*args, **kwargs)
                    entered.set()
                    await release.wait()

                raw._guard = paused_guard
                caller = asyncio.create_task(runtime.create_agent(spec).submit("q", command_id="s"))
            else:
                run = await runtime.create_agent(spec).submit("q", command_id="s")
                await other.submit(spec, "q", command_id="s")
                original = raw._view

                async def paused_view(run_id, kind, **values):
                    value = await original(run_id, kind, **values)
                    if kind == "status":
                        entered.set()
                        await release.wait()
                    return value

                raw._view = paused_view
                caller = asyncio.create_task(
                    run.cancel(command_id="cancel") if operation == "cancel" else run.resume()
                )
            await asyncio.wait_for(entered.wait(), 1)
            raw.client = b
            release.set()
            try:
                with pytest.raises(DefinitionMismatch):
                    await caller
                if operation == "submit":
                    assert len(a.states) == 1 and not b.states
                else:
                    record = next(iter(b.states.values()))
                    assert record.state == "queued"
                    assert set(record.command_digests) == {"s"}
            finally:
                raw.client = a
                release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("wait_timeout", [None, 10])
def test_query_timeout_error_propagates_instead_of_becoming_observation_timeout(
    monkeypatch, wait_timeout
):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.hold_execution = True
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")

            async def failed_query(run_id):
                raise TimeoutError("transport timed out")

            raw.diagnostics = failed_query
            with pytest.raises(TimeoutError, match="transport timed out"):
                await run.wait(wait_timeout=wait_timeout)
            assert set(raw.client.states[run.ref.run_id].command_digests) == {"s"}

    asyncio.run(scenario())


@pytest.mark.parametrize("response", ["none", "coroutine", "other_target"])
def test_resume_refuses_invalid_completed_drive_response_without_claiming_dispatch(
    monkeypatch, response
):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.hold_execution = True
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")

            async def nested():
                raise AssertionError("never execute nested drive coroutine")

            async def invalid(*args, **kwargs):
                if response == "coroutine":
                    return nested()
                if response == "other_target":
                    return replace(await raw.status(run.ref.run_id), run_id="other")
                return None

            raw.drive = invalid
            with pytest.raises(ValidationError):
                await run.resume()
            assert set(raw.client.states[run.ref.run_id].command_digests) == {"s"}

    asyncio.run(scenario())
