"""Real handlers, original controls and retryable resource ownership."""

import asyncio
import threading

import pytest

import relf_agent as r
from relf_agent.errors import CoordinatorBusy
from relf_agent.types import ToolCall

from .helpers import ScriptedProvider
from .test_agent_runtime import api, engine


def test_owned_approval_parks_and_recovers_original_receipt_after_restart(tmp_path):
    async def scenario():
        path, writes = tmp_path / "approval.sqlite", []
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: writes.append(c.effect_key) or {"applied": True},
        )
        async with api()(
            engine(
                path,
                ScriptedProvider([r.ModelResponse(tool_calls=[ToolCall("change", {})])]),
                tools=tools,
            ),
            owned=True,
        ) as runtime:
            run = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).submit(
                "q", command_id="s"
            )
            waiting = await run.wait(wait_timeout=1)
            assert waiting.snapshot.state == "waiting_approval"
            ref, pending = run.ref, waiting.snapshot.pending[0]
        async with api()(
            engine(path, ScriptedProvider([r.ModelResponse(output="ok")]), tools=tools), owned=True
        ) as runtime:
            restored = runtime.attach(r.RunRef.from_dict(ref.to_dict()))
            receipt = await restored.approve(
                pending["action_id"], pending["digest"], command_id="a"
            )
            assert (
                await restored.approve(pending["action_id"], pending["digest"], command_id="a")
                == receipt
            )
            assert (await restored.wait(wait_timeout=1)).snapshot.state == "succeeded"
            assert len(writes) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_wait", [False, True])
def test_close_wait_never_releases_actual_thread_or_cancels_business(cancel_wait, tmp_path):
    async def scenario():
        started, release = threading.Event(), threading.Event()
        writes = []

        def handler(a, ctx):
            started.set()
            release.wait(3)
            writes.append(ctx.effect_key)
            return {"seen": True}

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("block", "Block", {"type": "object"}, effect="read_only"), handler
        )
        path = tmp_path / "thread.sqlite"
        raw = engine(
            path,
            ScriptedProvider(
                [r.ModelResponse(tool_calls=[ToolCall("block", {})]), r.ModelResponse(output="ok")]
            ),
            tools=tools,
        )
        runtime = api()(raw, owned=True, close_timeout=0.02)
        run = await runtime.create_agent(r.AgentSpec("a", "A", ("block",))).submit(
            "q", command_id="s"
        )
        assert await asyncio.to_thread(started.wait, 1)
        try:
            if cancel_wait:
                closer = asyncio.create_task(runtime.aclose(close_timeout=1))
                await asyncio.sleep(0.01)
                closer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await closer
            else:
                with pytest.raises(r.CloseIncomplete):
                    await runtime.aclose()
            assert raw.status(run.ref.run_id).state == "running"
            with pytest.raises(CoordinatorBusy):
                with engine(path, ScriptedProvider([])):
                    pass
        finally:
            release.set()
            await runtime.aclose(close_timeout=2)
        assert len(writes) == 1

    asyncio.run(scenario())


def test_borrowed_runtime_drain_keeps_external_engine_open(tmp_path):
    async def scenario():
        with engine(
            tmp_path / "borrow.sqlite", ScriptedProvider([r.ModelResponse(output="ok")])
        ) as raw:
            runtime = api()(raw)
            await runtime.create_agent(r.AgentSpec("a", "A")).run(
                "q", command_id="s", wait_timeout=1
            )
            await runtime.aclose()
            assert raw.submit(r.AgentSpec("a", "A"), "q", command_id="next")

    asyncio.run(scenario())


def test_close_failure_keeps_retry_and_original_context_exception(tmp_path):
    async def scenario():
        class Store(r.SQLiteStore):
            failed = False

            def close(self):
                if not self.failed:
                    self.failed = True
                    raise ValueError("fixture close failure")
                super().close()

        raw = r.LocalEngine(
            Store(tmp_path / "close.sqlite"),
            providers={"default": ScriptedProvider([])},
            tools=r.ToolRegistry(),
        )
        runtime = api()(raw, owned=True)
        with pytest.raises(KeyError):
            async with runtime:
                raise KeyError("body")
        assert runtime.state == "close_failed"
        await runtime.aclose()
        assert runtime.state == "closed"

    asyncio.run(scenario())


def test_terminal_unknown_write_stays_in_close_report_and_reconciliation(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def uncertain(a, ctx):
            started.set()
            await release.wait()
            raise RuntimeError("lost receipt after remote acceptance")

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, effect="idempotent_write"), uncertain
        )
        path = tmp_path / "unknown.sqlite"
        runtime = api()(
            engine(
                path,
                ScriptedProvider([r.ModelResponse(tool_calls=[ToolCall("change", {})])]),
                tools=tools,
            ),
            owned=True,
        )
        run = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).submit(
            "q", command_id="s"
        )
        await started.wait()
        await run.cancel(command_id="cancel")
        release.set()
        await run.wait(wait_timeout=1)
        report = await runtime.aclose()
        assert report.parked == (run.ref,)
        async with api()(engine(path, ScriptedProvider([]), tools=tools), owned=True) as restored:
            attached = restored.attach(run.ref)
            snapshot = await attached.status()
            tool = next(action for action in snapshot.actions if action["kind"] == "tool")
            assert tool["status"] == "outcome_unknown"
            await attached.reconcile(tool["id"], {"applied": True}, command_id="reconcile")
            assert (await attached.status()).state == "cancelled"

    asyncio.run(scenario())


def test_close_cancel_policy_cancels_only_explicitly_managed_runs(tmp_path):
    async def scenario():
        provider = ScriptedProvider([r.ModelResponse(tool_calls=[ToolCall("change", {})])])
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, ctx: {"applied": True},
        )
        raw = engine(tmp_path / "close-cancel.sqlite", provider, tools=tools)
        unrelated = raw.submit(r.AgentSpec("other", "Other"), "q", command_id="other")
        runtime = api()(raw, close_policy="cancel")
        run = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).submit(
            "q", command_id="s"
        )
        assert (await run.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
        await runtime.aclose()
        assert raw.status(run.ref.run_id).state == "cancelled"
        assert raw.status(unrelated.run_id).state == "queued"
        raw.close()

    asyncio.run(scenario())


def test_parked_close_failure_retries_resource_closing_without_reading_closed_engine(tmp_path):
    async def scenario():
        class Store(r.SQLiteStore):
            failed = False

            def close(self):
                if not self.failed:
                    self.failed = True
                    raise ValueError("close failure")
                super().close()

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, ctx: {"applied": True},
        )
        raw = r.LocalEngine(
            Store(tmp_path / "parked-close.sqlite"),
            providers={
                "default": ScriptedProvider([r.ModelResponse(tool_calls=[ToolCall("change", {})])])
            },
            tools=tools,
        )
        runtime = api()(raw, owned=True)
        run = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).submit(
            "q", command_id="s"
        )
        assert (await run.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
        with pytest.raises(r.CloseIncomplete):
            await runtime.aclose()
        with pytest.raises(r.RuntimeClosed):
            await run.status()
        report = await runtime.aclose()
        assert report.parked == (run.ref,) and runtime.state == "closed"

    asyncio.run(scenario())
