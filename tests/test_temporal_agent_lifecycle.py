import asyncio
import time
from contextlib import contextmanager
from dataclasses import replace

import pytest

import relf_agent as r
from relf_agent.errors import CloseIncomplete, DefinitionMismatch, RuntimeClosed, ValidationError

from .temporal_agent_fixture import StateClient, engine


def test_remote_wait_bounds_blocked_query_with_true_prior_observation(monkeypatch):
    async def scenario():
        client = StateClient()
        client.hold_execution = True
        raw = engine(monkeypatch, client=client)
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            record = client.states[run.ref.run_id]
            before = record.diagnostics()
            cutoff = time.time()
            client.query_gate = asyncio.Event()
            result = await asyncio.wait_for(run.wait(wait_timeout=0.02), 0.5)
            assert result.wait_reason == "observation_timeout"
            assert result.snapshot.state == "queued" and result.observed_at <= cutoff
            assert result.snapshot.pending == ()
            assert record.diagnostics() == before

    asyncio.run(scenario())


def test_remote_zero_wait_and_returned_diagnostics_do_not_mutate_cached_snapshot(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A", ("lookup",))).submit(
                "q", command_id="s"
            )
            info = await run.diagnostics()
            info.snapshot.pending[0]["arguments"]["injected"] = True
            raw.client.query_gate = asyncio.Event()
            result = await asyncio.wait_for(run.wait(wait_timeout=0), 0.5)
            assert "injected" not in result.snapshot.pending[0]["arguments"]
            assert not raw.client.states[run.ref.run_id].actions[1]["arguments"]

    asyncio.run(scenario())


def test_cancelled_remote_observer_sends_no_business_commands(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.hold_execution = True
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            before = raw.client.states[run.ref.run_id].diagnostics()
            raw.client.query_gate = asyncio.Event()
            observer = asyncio.create_task(run.wait())
            await asyncio.sleep(0.01)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert raw.client.states[run.ref.run_id].diagnostics() == before
            raw.client.query_gate = None
            await run.resume()
            raw.client.hold_execution = False
            await raw.client.advance(run.ref.run_id)
            assert (await run.wait(wait_timeout=1)).snapshot.state == "succeeded"

    asyncio.run(scenario())


def test_cancelled_submit_and_close_timeout_retain_rpc_and_detached_input(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.start_gate.clear()
        runtime = r.Runtime.from_temporal(raw, owned=True)
        agent = runtime.create_agent(r.AgentSpec("a", "A", ("lookup",)))
        input = {"number": 1}
        caller = asyncio.create_task(agent.submit(input, command_id="s"))
        await raw.client.start_entered.wait()
        input["number"] = 9
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert runtime.hosting_status["running"] == 1
        with pytest.raises(CloseIncomplete):
            await runtime.aclose(close_timeout=0.01)
        assert not raw._closed
        raw.client.start_gate.set()
        report = await runtime.aclose(close_timeout=1)
        assert report.state == "closed" and raw._closed and not raw.client.closed
        assert len(raw.client.states) == 1
        record = next(iter(raw.client.states.values()))
        assert record.request["input"] == {"number": 1}
        assert record.state == "waiting_approval" and raw.client.tool_calls == 0
        reconnect = engine(monkeypatch, client=raw.client)
        async with r.Runtime.from_temporal(reconnect) as runtime:
            restored = await runtime.create_agent(r.AgentSpec("a", "A", ("lookup",))).submit(
                {"number": 1}, command_id="s"
            )
            action = (await restored.pending())[0]
            await restored.approve(action["action_id"], action["digest"], command_id="approve")
            assert (await restored.wait(wait_timeout=1)).snapshot.state == "succeeded"
            assert raw.client.tool_calls == 1

    asyncio.run(scenario())


def test_cancelled_close_wait_keeps_cleanup_owned_and_retryable(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.start_gate.clear()
        runtime = r.Runtime.from_temporal(raw, owned=True)
        submit = asyncio.create_task(
            runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
        )
        await raw.client.start_entered.wait()
        closer = asyncio.create_task(runtime.aclose())
        await asyncio.sleep(0.01)
        closer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert not raw._closed and runtime.hosting_status["running"] == 1
        raw.client.start_gate.set()
        run = await submit
        assert (await runtime.aclose(close_timeout=1)).state == "closed"
        assert raw.client.states[run.ref.run_id].state == "succeeded" and not raw.client.closed

    asyncio.run(scenario())


def test_owned_remote_close_failure_retry_and_primary_body_error(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        count = 0
        original = raw.aclose

        async def fail_once():
            nonlocal count
            count += 1
            if count == 1:
                raise OSError("close failed")
            await original()

        raw.aclose = fail_once
        runtime = r.Runtime.from_temporal(raw, owned=True)
        run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
        with pytest.raises(ValueError) as body:
            async with runtime:
                raise ValueError("business body")
        assert isinstance(body.value.__cause__, CloseIncomplete)
        with pytest.raises(RuntimeClosed):
            await run.status()
        assert (await runtime.aclose()).state == "closed" and count == 2

    asyncio.run(scenario())


def test_wrong_loop_does_not_poison_remote_owner_cleanup(monkeypatch):
    owner, other = asyncio.new_event_loop(), asyncio.new_event_loop()
    raw = engine(monkeypatch)

    async def create():
        return r.Runtime.from_temporal(raw, owned=True)

    runtime = owner.run_until_complete(create())
    try:
        with pytest.raises(ValidationError):
            other.run_until_complete(runtime.aclose())
        assert not raw._closed and runtime.state == "open"
        assert owner.run_until_complete(runtime.aclose()).state == "closed"
    finally:
        owner.close()
        other.close()


@pytest.mark.parametrize("policy", ["drain", "cancel", "handoff"])
def test_remote_client_policies_cannot_claim_server_shutdown(monkeypatch, policy):
    async def scenario():
        raw = engine(monkeypatch)
        with pytest.raises(ValidationError):
            r.Runtime.from_temporal(raw, close_policy=policy)
        assert not raw._closed and not raw.client.states

    asyncio.run(scenario())


def test_completed_remote_dispatch_keeps_no_task_or_run_history(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        async with r.Runtime.from_temporal(raw) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            for i in range(100):
                run = await agent.submit(i, command_id=f"s-{i}")
                assert (await run.status()).state == "succeeded"
            await asyncio.sleep(0)
            assert runtime.hosting_status["running"] == 0
            assert not runtime._supervisor.tasks and not runtime._supervisor.refs

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        r.RunHandle("x", r.CommandReceipt("s", "other", "submit")),
        r.RunHandle("x", r.CommandReceipt("other", "x", "submit")),
    ],
)
def test_malformed_async_submission_receipt_refuses_before_ref_query(monkeypatch, value):
    async def scenario():
        raw = engine(monkeypatch)

        async def malformed(*args, **kwargs):
            return value

        raw.submit = malformed
        async with r.Runtime.from_temporal(raw) as runtime:
            with pytest.raises(ValidationError):
                await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            assert not raw.client.states

    asyncio.run(scenario())


def test_resource_drift_after_query_does_not_return_original_reference(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            original = raw.diagnostics
            original_client = raw.client

            async def drift(run_id):
                info = await original(run_id)
                raw.client = StateClient("other:7233")
                return info

            raw.diagnostics = drift
            try:
                with pytest.raises(DefinitionMismatch):
                    await runtime.areference(run.ref.run_id)
            finally:
                raw.client = original_client
                raw.diagnostics = original

    asyncio.run(scenario())


def test_invalid_control_receipt_does_not_silently_confirm_wrong_target(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        raw.client.hold_execution = True
        async with r.Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            original = raw.cancel

            async def wrong(*args, **kwargs):
                return replace(await original(*args, **kwargs), run_id="other")

            raw.cancel = wrong
            with pytest.raises(ValidationError):
                await run.cancel(command_id="cancel")
            assert raw.client.states[run.ref.run_id].state == "cancelled"
            raw.cancel = original
            assert (await run.cancel(command_id="cancel")).run_id == run.ref.run_id

    asyncio.run(scenario())


def test_lazy_owned_close_does_not_confirm_resource_cleanup(monkeypatch):
    async def scenario():
        raw = engine(monkeypatch)
        original = raw.aclose

        @contextmanager
        def lazy():
            raise AssertionError("never enter lazy cleanup")
            yield

        async def invalid():
            return lazy()

        raw.aclose = invalid
        runtime = r.Runtime.from_temporal(raw, owned=True)
        with pytest.raises(CloseIncomplete):
            await runtime.aclose()
        assert runtime.state == "close_failed" and not raw._closed
        raw.aclose = original
        assert (await runtime.aclose()).state == "closed"

    asyncio.run(scenario())
