"""Reproduced independent review findings at adapter/replay/locator boundaries."""

import asyncio
from contextlib import contextmanager

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider
from .test_agent_runtime import engine


@pytest.mark.parametrize(
    "method",
    [
        "prepare",
        "insert",
        "save",
        "insert_turn",
        "confirmed_result",
        "turns",
        "load",
        "legacy_owner",
    ],
)
def test_lazy_admission_results_refuse_before_durable_acceptance(method, tmp_path):
    async def scenario():
        class Adapter:
            def __init__(self, base, owner):
                self.base, self.owner = base, owner

            def __getattr__(self, name):
                original = getattr(self.base, name)
                if not callable(original) or name != method:
                    return original

                def deferred(*args, **kwargs):
                    if not self.owner.bad:
                        return original(*args, **kwargs)

                    @contextmanager
                    def lazy():
                        raise RuntimeError("must never enter lazy port result")
                        yield

                    return lazy()

                return deferred

        class Store(r.SQLiteStore):
            bad = False

            def create_session_admission(self):
                return Adapter(super().create_session_admission(), self)

        provider = ScriptedProvider(
            [r.ModelResponse(output="first"), r.ModelResponse(output="next")]
        )
        raw = r.LocalEngine(
            Store(tmp_path / "lazy.sqlite"), providers={"default": provider}, tools=r.ToolRegistry()
        )
        async with r.Runtime(raw, owned=True) as runtime:
            agent = runtime.create_agent(r.AgentSpec("a", "A"))
            if method in {"prepare", "insert"}:
                raw.store.bad = True
                with pytest.raises(ValidationError):
                    await agent.open_session("s", command_id="open")
                assert (
                    raw.store.conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    == "1"
                )
                assert raw.store.conn.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
                return
            session = await agent.open_session("s", command_id="open")
            if method == "confirmed_result":
                first = await session.submit("first", command_id="one")
                await first.wait(wait_timeout=1)
            raw.store.bad = True
            with pytest.raises(ValidationError):
                if method == "turns":
                    await session.turns()
                else:
                    await session.submit("next", command_id="next")
            raw.store.bad = False
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == (
                1 if method == "confirmed_result" else 0
            )
            assert len(await session.turns()) == (1 if method == "confirmed_result" else 0)
            next_run = await session.submit("next", command_id="next")
            await next_run.wait(wait_timeout=1)
            assert next_run.turn.turn_seq == (2 if method == "confirmed_result" else 1)

    asyncio.run(scenario())


def test_resolved_manifest_drift_rejects_durably_after_component_is_restored(tmp_path):
    async def scenario():
        class Changed(ScriptedProvider):
            identity = {"kind": "changed", "version": "2"}

        original = ScriptedProvider([r.ModelResponse(output="ok")])
        raw = engine(tmp_path / "drift.sqlite", original)
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "A")).open_session(
                "s", command_id="open"
            )
            raw.providers["default"] = Changed([])
            with pytest.raises(r.SessionBindingMismatch) as rejected:
                await session.submit("q", command_id="drift")
            receipt = rejected.value.receipt
            raw.providers["default"] = original
            with pytest.raises(r.SessionBindingMismatch) as replayed:
                await session.submit("q", command_id="drift")
            assert replayed.value.receipt == receipt
            assert raw.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            run = await session.submit("q", command_id="retry")
            await run.wait(wait_timeout=1)
            assert run.turn.turn_seq == 1

    asyncio.run(scenario())


def test_incompatible_locator_refuses_session_attach_and_open_without_losing_original(tmp_path):
    async def scenario():
        path = tmp_path / "locator.sqlite"
        spec = r.AgentSpec("a", "A")
        async with r.Runtime(
            engine(path, ScriptedProvider([r.ModelResponse(output="ok")])),
            owned=True,
            authority_locator="one",
        ) as runtime:
            session = await runtime.create_agent(spec).open_session("s", command_id="open")
            run = await session.submit("q", command_id="one")
            await run.wait(wait_timeout=1)
            session_ref, receipt = session.ref, run.receipt
        async with r.Runtime(
            engine(path, ScriptedProvider([])), owned=True, authority_locator="two"
        ) as runtime:
            with pytest.raises(DefinitionMismatch):
                runtime.attach_session(session_ref)
            with pytest.raises((DefinitionMismatch, r.SessionBindingMismatch)):
                await runtime.create_agent(spec).open_session("s", command_id="different-locator")
            with pytest.raises(DefinitionMismatch):
                await runtime.create_agent(spec).open_session("s", command_id="open")
        async with r.Runtime(
            engine(path, ScriptedProvider([])), owned=True, authority_locator="one"
        ) as runtime:
            session = runtime.attach_session(session_ref)
            assert (await session.submit("q", command_id="one")).receipt == receipt

    asyncio.run(scenario())
