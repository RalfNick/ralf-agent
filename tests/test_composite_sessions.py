import asyncio
import sqlite3

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError

from .composite_session_fixture import Provider, definitions, engine, root_messages


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_composite_turns_atomically_save_whole_result_and_remain_ordered(tmp_path, kind):
    async def scenario():
        provider = Provider()
        raw = engine(tmp_path / "turns.sqlite", provider=provider)
        async with r.Runtime(raw, owned=True) as runtime:
            definition = definitions()[kind]
            agent = runtime.create_agent(definition)
            session = await agent.open_session("customer", command_id="open")
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "3"
            )
            expected_kind = (
                "dynamic"
                if kind in {"plan", "dag"}
                else "graph"
                if kind in {"graph", "parallel", "transform"}
                else "team"
            )
            assert expected_kind in runtime.capabilities["session_definitions"]
            for seq, task in enumerate(("first", "second"), 1):
                run = await session.submit(task, command_id="s" + str(seq), budget=64)
                observed = await run.wait(wait_timeout=2)
                assert observed.snapshot.state == "succeeded"
                expected = (
                    {"copy": task}
                    if kind == "transform"
                    else (
                        {"a": "done", "b": "done"}
                        if kind == "parallel"
                        else ({"a": "done"} if kind in {"graph", "nested"} else "done")
                    )
                )
                assert observed.snapshot.result == expected
                assert run.turn.turn_seq == seq
                assert root_messages(raw, run.ref.run_id) == [
                    {
                        "role": "assistant",
                        "content": expected,
                        "agent": definition.name,
                        "task": task,
                    }
                ]
                deadline = asyncio.get_running_loop().time() + 2
                while (await session.status()).busy:
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0.01)
                replay = await session.submit(task, command_id="s" + str(seq), budget=64)
                assert (
                    replay.ref == run.ref
                    and replay.receipt == run.receipt
                    and replay.turn == run.turn
                )
                await replay.wait(wait_timeout=2)
                assert len(root_messages(raw, run.ref.run_id)) == 1
                events = await run.events()
                save = next(e.seq for e in events if e.kind == "session_turn_result_committed")
                assert save < next(e.seq for e in events if e.kind == "run_succeeded")
            assert [t.turn_seq for t in await session.turns()] == [1, 2]

    asyncio.run(scenario())


def test_failed_rollback_preserves_original_error_and_disables_store(tmp_path, monkeypatch):
    connect = sqlite3.connect

    class FailedRollback(sqlite3.Connection):
        def rollback(self):
            raise sqlite3.OperationalError("rollback unavailable")

    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=FailedRollback)
    )
    store = r.SQLiteStore(tmp_path / "rollback.sqlite")
    original = ValueError("original transaction failure")
    try:
        with pytest.raises(ValueError) as error, store.transaction():
            store.conn.execute("INSERT INTO metadata VALUES ('uncommitted','value')")
            raise original
        assert error.value is original
        with pytest.raises(ValidationError, match="rollback"):
            with store.transaction():
                pass
        with pytest.raises(ValidationError, match="rollback"):
            store.conn.execute("SELECT 1")
    finally:
        store.close()
    with connect(store.path) as observer:
        assert (
            observer.execute("SELECT value FROM metadata WHERE key='uncommitted'").fetchone()
            is None
        )


def test_real_sqlite_commit_failure_rolls_back_root_success_and_releases_transaction(tmp_path):
    async def scenario():
        raw = engine(tmp_path / "real-commit.sqlite")
        raw.store.conn.execute("PRAGMA foreign_keys=ON")
        raw.store.conn.execute("CREATE TABLE commit_parent (id INTEGER PRIMARY KEY)")
        raw.store.conn.execute(
            "CREATE TABLE commit_child (parent INTEGER REFERENCES commit_parent(id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
        raw.store.conn.execute(
            "CREATE TRIGGER refuse_root_save AFTER INSERT ON memory_session_items "
            "WHEN NEW.message_id LIKE '%:turn:result' BEGIN "
            "INSERT INTO commit_child VALUES (99); END"
        )
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", command_id="open"
            )
            run = await session.submit("q", command_id="one", budget=64)
            observed = await run.wait(wait_timeout=2)
            assert observed.snapshot.state == "failed"
            assert not raw.store.conn.in_transaction
            assert root_messages(raw, run.ref.run_id) == []
            assert raw.store.conn.execute("SELECT count(*) FROM commit_child").fetchone()[0] == 0
            child = raw.store.run(run.ref.run_id)["orchestration"]["children"][0]["run_id"]
            assert raw.status(child).state == "succeeded"
            assert not any(
                event.kind in {"run_succeeded", "session_turn_result_committed"}
                for event in await run.events()
            )
            assert not (await session.status()).busy

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["raise", "lazy", "unsaved", "commit"])
def test_final_conversation_failure_cannot_publish_composite_success(tmp_path, failure):
    async def scenario():
        raw = engine(tmp_path / "failure.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(definitions()["team"]).open_session(
                "s", command_id="open"
            )
            append, commit = raw.sessions.append, raw._commit

            async def deferred():
                raise AssertionError("never await deferred atomic append")

            def failing(scope, session_id, message, *, expected_revision, message_id):
                if message_id.endswith(":turn:result"):
                    if failure == "raise":
                        raise ValidationError("final save failed")
                    if failure == "lazy":
                        return deferred()
                    if failure == "unsaved":
                        return expected_revision + 1
                return append(
                    scope,
                    session_id,
                    message,
                    expected_revision=expected_revision,
                    message_id=message_id,
                )

            def failed_commit(run, kind, data=None):
                if kind == "run_succeeded" and "session_turn" in run and failure == "commit":
                    raise ValidationError("outer success commit failed")
                return commit(run, kind, data)

            raw.sessions.append, raw._commit = failing, failed_commit
            run = await session.submit("q", command_id="s", budget=64)
            observed = await run.wait(wait_timeout=2)
            assert observed.snapshot.state == "failed"
            assert root_messages(raw, run.ref.run_id) == []
            events = await run.events()
            assert not any(
                e.kind in {"run_succeeded", "session_turn_result_committed"} for e in events
            )
            child_id = (await run.diagnostics()).workflow["children"][0]["run_id"]
            assert raw.status(child_id).state == "succeeded"
            raw.sessions.append, raw._commit = append, commit
            await run.resume()
            assert (await run.wait(wait_timeout=2)).snapshot.state == "failed"
            assert root_messages(raw, run.ref.run_id) == []

    asyncio.run(scenario())
