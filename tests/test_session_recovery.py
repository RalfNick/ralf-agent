"""Paused and terminal effects keep durable Session occupancy through restart."""

import asyncio
import threading

import pytest

import relf_agent as r

from .helpers import ScriptedProvider
from .test_agent_runtime import engine
from .test_agent_sessions import api


def test_approval_busy_rejection_is_durable_and_replayed_after_restart(tmp_path):
    async def scenario():
        tools = r.ToolRegistry()
        writes = []
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: writes.append(c.effect_key) or {"applied": True},
        )
        path = tmp_path / "recover.sqlite"
        spec = r.AgentSpec("a", "A", ("change",))
        async with api()(
            engine(
                path,
                ScriptedProvider([r.ModelResponse(tool_calls=[r.ToolCall("change", {})])]),
                tools=tools,
            ),
            owned=True,
        ) as runtime:
            session = await runtime.create_agent(spec).open_session("s", command_id="open")
            run = await session.submit("q", command_id="first")
            waited = await run.wait(wait_timeout=1)
            assert waited.snapshot.state == "waiting_approval"
            action = waited.snapshot.pending[0]
            with pytest.raises(r.SessionBusy) as rejection:
                await session.submit("next", command_id="busy")
            busy = rejection.value.receipt
            ref = session.ref
            run_ref = run.ref
            assert rejection.value.run_ref == run_ref
        async with api()(
            engine(
                path,
                ScriptedProvider([r.ModelResponse(output="done"), r.ModelResponse(output="next")]),
                tools=tools,
            ),
            owned=True,
        ) as runtime:
            session = runtime.attach_session(r.SessionRef.from_dict(ref.to_dict()))
            assert (await session.status()).busy
            with pytest.raises(r.SessionBusy) as rejection:
                await session.submit("next", command_id="busy")
            assert rejection.value.receipt == busy
            original = runtime.attach(run_ref)
            await original.approve(action["action_id"], action["digest"], command_id="approve")
            assert (await original.wait(wait_timeout=1)).snapshot.state == "succeeded"
            with pytest.raises(r.SessionBusy) as rejection:
                await session.submit("next", command_id="busy")
            assert rejection.value.receipt == busy
            next_run = await session.submit("next", command_id="retry")
            await next_run.wait(wait_timeout=1)
            assert next_run.turn.turn_seq == 2 and len(writes) == 1
            assert runtime.engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2

    asyncio.run(scenario())


def test_cancelled_real_thread_and_unknown_write_hold_turn_until_reconciliation(tmp_path):
    async def scenario():
        started, release = threading.Event(), threading.Event()

        def handler(a, c):
            started.set()
            release.wait(3)
            raise RuntimeError("lost business receipt")

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, effect="idempotent_write"), handler
        )
        raw = engine(
            tmp_path / "thread.sqlite",
            ScriptedProvider(
                [
                    r.ModelResponse(tool_calls=[r.ToolCall("change", {})]),
                    r.ModelResponse(output="next"),
                ]
            ),
            tools=tools,
        )
        runtime = api()(raw, owned=True)
        try:
            session = await runtime.create_agent(r.AgentSpec("a", "A", ("change",))).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one")
            assert await asyncio.to_thread(started.wait, 1)
            await run.cancel(command_id="cancel")
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="active")
            release.set()
            await raw.wait_for_threads()
            await asyncio.sleep(0.02)
            assert (await run.status()).state == "cancelled"
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="unknown")
            action = next(a for a in (await run.status()).actions if a["kind"] == "tool")
            assert action["status"] == "outcome_unknown"
            await run.reconcile(action["id"], {"applied": True}, command_id="reconcile")
            next_run = await session.submit("next", command_id="after")
            await next_run.wait(wait_timeout=1)
            assert next_run.turn.turn_seq == 2
        finally:
            release.set()
            await runtime.aclose()

    asyncio.run(scenario())


def test_acceptance_failure_rolls_back_run_turn_and_sequence(tmp_path):
    async def scenario():
        class Store(r.SQLiteStore):
            fail = False

            def insert_run(self, data):
                super().insert_run(data)
                if self.fail:
                    raise RuntimeError("between Run and Turn")

        raw = r.LocalEngine(
            Store(tmp_path / "rollback.sqlite"),
            providers={"default": ScriptedProvider([r.ModelResponse(output="ok")])},
            tools=r.ToolRegistry(),
        )
        async with api()(raw, owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "s", command_id="open"
            )
            raw.store.fail = True
            with pytest.raises(RuntimeError):
                await session.submit("q", command_id="one")
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            assert (await session.status()).last_turn_seq == 0
            assert await session.turns() == []
            raw.store.fail = False
            run = await session.submit("q", command_id="one")
            await run.wait(wait_timeout=1)
            assert run.turn.turn_seq == 1

    asyncio.run(scenario())


def test_existing_legacy_approval_and_required_save_evidence_hold_lane(tmp_path):
    async def scenario():
        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
            lambda a, c: {"applied": True},
        )
        raw = engine(
            tmp_path / "legacy.sqlite",
            ScriptedProvider(
                [
                    r.ModelResponse(tool_calls=[r.ToolCall("change", {})]),
                    r.ModelResponse(output="ok"),
                ]
            ),
            tools=tools,
        )
        spec = r.AgentSpec("a", "A", ("change",))
        original = raw.submit(spec, "q", command_id="legacy", session_id="s")
        waiting = await raw.drive(original.run_id)
        async with api()(raw, owned=True) as runtime:
            session = await runtime.create_agent(spec).open_session("s", command_id="open")
            with pytest.raises(r.SessionBusy) as busy:
                await session.submit("new", command_id="busy")
            assert busy.value.run_ref.run_id == original.run_id
            action = waiting.pending[0]
            restored = runtime.attach(runtime.reference(original.run_id))
            await restored.approve(action["action_id"], action["digest"], command_id="approve")
            await restored.wait(wait_timeout=1)
            raw.providers["default"] = ScriptedProvider([r.ModelResponse(output="new")])
            turn = await session.submit("new", command_id="turn")
            await turn.wait(wait_timeout=1)
            # Required save confirmation is authority evidence, not terminal-state guessing.
            raw.store.conn.execute(
                "UPDATE memory_session_index_state SET dirty=1 WHERE session='s'"
            )
            with pytest.raises(r.SessionBusy):
                await session.submit("next", command_id="unconfirmed")
            raw.store.conn.execute(
                "UPDATE memory_session_index_state SET dirty=0 WHERE session='s'"
            )
            assert not (await session.status()).busy

    asyncio.run(scenario())
