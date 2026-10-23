"""Remote native ACK, cancellation and root eligibility through public Runtime."""

import asyncio
import copy
import threading

import pytest

import relf_agent as r
from relf_agent.errors import CoordinatorBusy, ValidationError
from tests.test_local_native_history_remote_save import ReceiptMemory
from tests.test_local_session_history_compositions import MemberProvider, definition
from tests.test_local_session_model_history import options, spec, tools


async def idle(session):
    async with asyncio.timeout(3):
        while (await session.status()).busy:  # noqa: ASYNC110 -- observe original handler completion
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("cancelled", [False, True])
def test_native_ack_loss_reconnect_and_terminal_unknown_hold_original_turn(tmp_path, cancelled):
    async def scenario():
        backend, requests, queries = ReceiptMemory(), [], []
        backend.lose_ack = True

        def make():
            return r.Runtime(
                r.LocalEngine(
                    r.SQLiteStore(tmp_path / "runs.sqlite"),
                    session_store=backend,
                    **options(requests, queries),
                ),
                owned=True,
            )

        async with make() as runtime:
            session = await runtime.create_agent(spec()).open_session("same", command_id="open")
            first = await session.submit("first-task", command_id="first")
            assert (await first.wait(wait_timeout=5)).snapshot.state == "waiting_reconciliation"
            assert len(requests) == 2 and backend.writes == 1
            assert (await session.status()).busy
            run_ref, session_ref = first.ref, session.ref
            if cancelled:
                backend.inspect_unknown = True
                await first.cancel(command_id="cancel-first")
                async with asyncio.timeout(3):
                    while (await first.status()).state != "cancelled":  # noqa: ASYNC110 -- observe original control adoption
                        await asyncio.sleep(0.01)
                assert (await session.status()).busy

        async with make() as runtime:
            session = runtime.attach_session(session_ref)
            if cancelled:
                assert (await session.status()).busy
            backend.inspect_unknown = False
            resumed = await runtime.resume(run_ref)
            snapshot = (await resumed.wait(wait_timeout=5, terminal_only=True)).snapshot
            assert snapshot.state == ("cancelled" if cancelled else "succeeded")
            await idle(session)
            assert backend.writes == (1 if cancelled else 2)
            assert len(requests) == 2
            original = copy.deepcopy(runtime.engine.store.run(run_ref.run_id))
            await (await runtime.resume(run_ref)).wait(wait_timeout=5)
            await idle(session)
            assert (
                original["native_model_history"]
                == runtime.engine.store.run(run_ref.run_id)["native_model_history"]
            )
            second = await session.submit("second-task", command_id="second")
            done = (await second.wait(wait_timeout=5)).snapshot
            assert done.state == "succeeded", runtime.engine.store.run(second.ref.run_id).get(
                "error"
            )
            await idle(session)
            roles = [m["role"] for m in requests[2][:6]]
            assert roles == (
                ["system", "user"]
                if cancelled
                else ["system", "user", "assistant", "tool", "assistant", "user"]
            )
            assert len(requests) == 4

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["sequence", "parallel", "team", "dynamic-dag", "nested"])
def test_remote_candidates_from_failed_root_are_excluded_from_next_turn(tmp_path, kind):
    async def scenario():
        written, requests = asyncio.Event(), []
        backend = ReceiptMemory()
        backend.after_write = written.set

        class FailsOnce(MemberProvider):
            failed = False

            async def complete(self, messages, descriptions):
                if messages[0]["content"] == "member-b" and not self.failed:
                    await written.wait()
                    self.failed = True
                    self.requests.append(copy.deepcopy(messages))
                    return r.ModelResponse(output="")
                return await super().complete(messages, descriptions)

        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": FailsOnce(requests)},
            tools=tools(),
            session_store=backend,
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        ) as engine:
            first = engine.submit(
                definition(kind), "first-task", session_id="same", command_id="first", budget=64
            )
            assert (await engine.drive(first.run_id)).state == "failed"
            assert backend.writes >= 1
            assert (
                engine.store.conn.execute(
                    "SELECT count(*) FROM native_history_publications"
                ).fetchone()[0]
                == 0
            )
            before = len(requests)
            second = engine.submit(
                definition(kind), "second-task", session_id="same", command_id="second", budget=64
            )
            done = await engine.drive(second.run_id)
            assert done.state == "succeeded", engine.store.run(second.run_id).get("error")
            assert not any(
                m.get("model_continuation", {})
                .get("data", {})
                .get("signature", "")
                .startswith("final-")
                for messages in requests[before:]
                for m in messages
                if m["role"] == "assistant" and not m.get("tool_calls")
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_task", [False, True])
def test_real_native_save_thread_retains_coordinator_and_turn_until_actual_end(
    tmp_path, cancel_task
):
    class BlockingMemory(r.InMemoryMemory):
        def __init__(self):
            super().__init__(backend_id="native-blocking-source")
            self.started, self.release = threading.Event(), threading.Event()
            self.writes = 0

        def append(self, scope, address, message, *, expected_revision, message_id):
            self.writes += 1
            result = super().append(
                scope, address, message, expected_revision=expected_revision, message_id=message_id
            )
            if address.startswith("ralf-native-model-history-v1:") and not self.started.is_set():
                self.started.set()
                if not self.release.wait(10):
                    raise RuntimeError("test-owned handler was not released")
            return result

    async def scenario():
        backend, requests, queries = BlockingMemory(), [], []
        path = tmp_path / "runs.sqlite"
        engine = r.LocalEngine(
            r.SQLiteStore(path),
            session_store=r.ThreadedMemoryAdapter(backend),
            **options(requests, queries),
        )
        runtime = r.Runtime(engine, owned=True)
        try:
            session = await runtime.create_agent(spec()).open_session("same", command_id="open")
            first = await session.submit("first-task", command_id="first")
            async with asyncio.timeout(3):
                while not backend.started.is_set():  # noqa: ASYNC110 -- actual owned sync handler
                    await asyncio.sleep(0.01)
            if cancel_task:
                engine._inflight[first.ref.run_id].cancel()
                await asyncio.sleep(0.02)
            else:
                await first.cancel(command_id="cancel")
            assert engine._threads.has_active_for(first.ref.run_id)
            assert (await session.status()).busy
            with pytest.raises(ValidationError):
                engine.close()
            competing_store = r.SQLiteStore(path)
            try:
                with pytest.raises(CoordinatorBusy):
                    r.LocalEngine(
                        competing_store, providers={"default": MemberProvider([])}, tools=tools()
                    )
            finally:
                competing_store.close()
            backend.release.set()
            await engine.wait_for_threads()
            async with asyncio.timeout(3):
                while runtime.hosting_status["running"]:  # noqa: ASYNC110 -- original hosting completion
                    await asyncio.sleep(0.01)
            resumed = await runtime.resume(first.ref)
            assert (
                await resumed.wait(wait_timeout=5, terminal_only=True)
            ).snapshot.state == "cancelled"
            await idle(session)
            assert backend.writes == 1 and len(requests) == 2
        finally:
            backend.release.set()
            await engine.wait_for_threads()
            await runtime.aclose()

    asyncio.run(scenario())
