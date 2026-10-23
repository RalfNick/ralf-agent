"""Lost remote acknowledgement and terminal recovery preserve business execution."""

import asyncio
import copy
import sqlite3

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch, ValidationError

from .test_remote_session_turns import definition, setup


async def settled(runtime):
    async def observe():
        while runtime.hosting_status["running"]:  # noqa: ASYNC110 -- public observation has no event
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observe(), 1)


@pytest.mark.parametrize("namespace", [None, "red"])
def test_lost_ack_restart_reuses_output_and_does_not_append_twice(tmp_path, namespace):
    async def scenario():
        path, data = tmp_path / "run.sqlite", tmp_path / "data.sqlite"
        runtime, backend, provider = setup(path, data, [r.ModelResponse(output="ok")], namespace)
        backend.fail_after_append = 1
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                assert (await one.wait(wait_timeout=1)).snapshot.state == "waiting_reconciliation"
                assert (
                    (await session.status()).busy
                    and backend.append_calls == 1
                    and provider.calls == 1
                )
                saved_ref, session_ref = one.ref, session.ref
        finally:
            backend.close()
        runtime, backend, provider = setup(path, data, [], namespace)
        try:
            async with runtime:
                session = runtime.attach_session(session_ref)
                resumed = await runtime.resume(saved_ref)
                done = await resumed.wait(wait_timeout=1, terminal_only=True)
                assert done.snapshot.state == "succeeded" and done.snapshot.result == "ok"
                assert backend.append_calls == provider.calls == 0
                assert backend.memory.read(r.Scope(), session_ref.key.storage_key)[0] == 1
                # Run.wait observes the terminal receipt; Session also requires owner exit.
                await settled(runtime)
                assert not (await session.status()).busy
        finally:
            backend.close()

    asyncio.run(scenario())


def test_append_ack_without_matching_receipt_cannot_confirm_success(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        backend.receipt_override = lambda value: {**value, "receipt": None}
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                assert (await one.wait(wait_timeout=1)).snapshot.state == "waiting_reconciliation"
                assert (await session.status()).busy
                backend.receipt_override = None
                await runtime.resume(one.ref)
                assert (
                    await one.wait(wait_timeout=1, terminal_only=True)
                ).snapshot.state == "succeeded"
                assert backend.append_calls == provider.calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", ["binding", "run", "both"])
def test_independent_remote_admission_evidence_cannot_downgrade(tmp_path, missing):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        backend.fail_after_append = 1
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=1)
                await settled(runtime)
                store = runtime.engine.store
                with store.transaction():
                    if missing in {"binding", "both"}:
                        port = store.create_session_admission()
                        state = port.load(r.Scope(), session.ref.key.key_id)
                        original_state = copy.deepcopy(state)
                        del state["bindings"]["1"]["remote_session"]
                        port.save(state, expected_revision=state["revision"])
                    if missing in {"run", "both"}:
                        run = store.run(one.ref.run_id)
                        original_run = copy.deepcopy(run)
                        del run["remote_session_binding"]
                        store.save_run(run)
                with pytest.raises(DefinitionMismatch):
                    await runtime.engine.drive(one.ref.run_id)
                with store.transaction():
                    if missing in {"binding", "both"}:
                        port.save(original_state, expected_revision=state["revision"])
                    if missing in {"run", "both"}:
                        original_run["revision"] = store.run(one.ref.run_id)["revision"]
                        store.save_run(original_run)
                assert backend.append_calls == provider.calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())


def test_cancelled_unknown_remote_write_holds_turn_until_query_only_recovery(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        backend.fail_after_append = 1
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=1)
                await settled(runtime)
                backend.receipt_override = lambda value: {**value, "receipt": None}
                await one.cancel(command_id="cancel")
                await settled(runtime)
                assert (await one.status()).state == "cancelled"
                assert (await session.status()).busy
                before = backend.append_calls, provider.calls
                backend.receipt_override = None
                await runtime.resume(one.ref)
                await settled(runtime)
                assert (await one.status()).state == "cancelled"
                assert not (await session.status()).busy
                assert before == (backend.append_calls, provider.calls)
        finally:
            backend.close()

    asyncio.run(scenario())


def test_cancelled_live_append_retains_runtime_until_real_completion(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        backend.pause()
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await asyncio.wait_for(backend.started.wait(), 1)
                await one.cancel(command_id="cancel")
                assert (await session.status()).busy
                with pytest.raises(ValidationError):
                    runtime.engine.close()
                backend.release.set()
                await one.wait(wait_timeout=1)
                await settled(runtime)
                await runtime.resume(one.ref)
                await settled(runtime)
                assert (await one.status()).state == "cancelled"
                assert not (await session.status()).busy
                assert backend.append_calls == provider.calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())


def test_persisted_receipt_must_still_match_adopted_model_message(tmp_path):
    async def scenario():
        runtime, backend, _ = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=1)
                await settled(runtime)
                with runtime.engine.store.transaction():
                    run = runtime.engine.store.run(one.ref.run_id)
                    intent = run["remote_session_saves"]["0"]
                    intent["message"]["content"] = "injected"
                    intent["receipt"]["receipt"]["message"] = copy.deepcopy(intent["message"])
                    runtime.engine.store.save_run(run)
                with pytest.raises(DefinitionMismatch):
                    await session.status()
                with runtime.engine.store.transaction():
                    intent["message"]["content"] = "ok"
                    intent["receipt"]["receipt"]["message"] = copy.deepcopy(intent["message"])
                    runtime.engine.store.save_run(run)
                assert backend.append_calls == 1
        finally:
            backend.close()

    asyncio.run(scenario())


def test_lazy_remote_activation_rolls_back_schema_route_and_command(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(tmp_path / "run.sqlite", tmp_path / "data.sqlite", [])
        store = runtime.engine.store
        original_factory = store.create_session_admission

        def factory():
            port = original_factory()

            def lazy():
                port._prepare(5)
                return iter(())

            port.prepare_remote_sessions = lazy
            return port

        store.create_session_admission = factory
        try:
            async with runtime:
                with pytest.raises(ValidationError):
                    await runtime.create_agent(definition()).open_session("s", command_id="open")
                assert (
                    store.conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    == "1"
                )
                assert store.conn.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
                assert provider.calls == backend.append_calls == 0
        finally:
            backend.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["wrong_key", "list"])
def test_malformed_save_journal_refuses_observation(tmp_path, damage):
    async def scenario():
        runtime, backend, _ = setup(
            tmp_path / "run.sqlite", tmp_path / "data.sqlite", [r.ModelResponse(output="ok")]
        )
        try:
            async with runtime:
                session = await runtime.create_agent(definition()).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await one.wait(wait_timeout=1)
                await settled(runtime)
                with runtime.engine.store.transaction():
                    run = runtime.engine.store.run(one.ref.run_id)
                    original = copy.deepcopy(run["remote_session_saves"])
                    run["remote_session_saves"] = [] if damage == "list" else {"bad": original["0"]}
                    runtime.engine.store.save_run(run)
                try:
                    with pytest.raises(DefinitionMismatch):
                        await session.status()
                    with pytest.raises(DefinitionMismatch):
                        await one.pending()
                finally:
                    with runtime.engine.store.transaction():
                        run["remote_session_saves"] = original
                        runtime.engine.store.save_run(run)
        finally:
            backend.close()

    asyncio.run(scenario())


def test_lost_save_ack_does_not_reexecute_real_business_write(tmp_path):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite",
            tmp_path / "data.sqlite",
            [
                r.ModelResponse(tool_calls=[r.ToolCall("change", {})]),
                r.ModelResponse(output="applied"),
            ],
        )
        business = r.SQLiteStore(tmp_path / "business.sqlite")
        business.conn.execute("CREATE TABLE effects (action_id TEXT PRIMARY KEY)")

        def handler(args, context):
            with sqlite3.connect(business.path) as conn:
                conn.execute("INSERT INTO effects VALUES (?)", (context.action_id,))
            return {"applied": True}

        runtime.engine.tools.register(
            r.ToolSpec("change", "Change", {"type": "object"}, effect="idempotent_write"), handler
        )
        backend.fail_after_append = 1
        bound = r.AgentDefinition(r.AgentSpec("a", "Answer", ("change",)), definition().bindings)
        try:
            async with runtime:
                session = await runtime.create_agent(bound).open_session("s", command_id="open")
                one = await session.submit("q", command_id="one")
                assert (await one.wait(wait_timeout=1)).snapshot.state == "waiting_reconciliation"
                assert business.conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
                await runtime.resume(one.ref)
                assert (
                    await one.wait(wait_timeout=1, terminal_only=True)
                ).snapshot.state == "succeeded"
                assert business.conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
                assert provider.calls == 2 and backend.append_calls == 1
        finally:
            backend.close()
            business.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
@pytest.mark.parametrize("damage", ["missing", "empty", "entry"])
def test_terminal_unknown_save_journal_loss_cannot_release_turn(tmp_path, outcome, damage):
    async def scenario():
        runtime, backend, provider = setup(
            tmp_path / "run.sqlite",
            tmp_path / "data.sqlite",
            [r.ModelResponse(output="one"), r.ModelResponse(output="two")],
        )
        backend.fail_after_append = 1
        try:
            async with runtime:
                session = await runtime.create_agent(definition("sequence")).open_session(
                    "s", command_id="open"
                )
                one = await session.submit("q", command_id="one")
                await settled(runtime)
                backend.fail_after_append = 1
                await runtime.resume(one.ref)
                await settled(runtime)
                assert (await one.status()).state == "waiting_reconciliation"
                assert backend.append_calls == provider.calls == 2
                if outcome == "cancelled":
                    backend.receipt_override = lambda value: {**value, "receipt": None}
                    await one.cancel(command_id="cancel")
                    await settled(runtime)
                else:

                    def conflict(value):
                        if value["receipt"]:
                            value["receipt"]["message"]["content"] = "wrong"
                        return value

                    backend.receipt_override = conflict
                    await runtime.engine.drive(one.ref.run_id)
                assert (await one.status()).state == outcome
                assert (await session.status()).busy
                assert any(item.get("source") == "remote_session" for item in await one.pending())
                store = runtime.engine.store
                with store.transaction():
                    run = store.run(one.ref.run_id)
                    original = copy.deepcopy(run["remote_session_saves"])
                    if damage == "missing":
                        del run["remote_session_saves"]
                    elif damage == "empty":
                        run["remote_session_saves"] = {}
                    else:
                        del run["remote_session_saves"]["1"]
                    store.save_run(run)
                try:
                    with pytest.raises(DefinitionMismatch):
                        await session.status()
                    with pytest.raises(DefinitionMismatch):
                        await one.pending()
                    with pytest.raises(DefinitionMismatch):
                        await runtime.engine.drive(one.ref.run_id)
                    assert backend.append_calls == provider.calls == 2
                finally:
                    with store.transaction():
                        run["remote_session_saves"] = original
                        store.save_run(run)
        finally:
            backend.close()

    asyncio.run(scenario())
