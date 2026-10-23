"""The new default receipt SPI uses existing Local admission/save authorities."""

import asyncio

import pytest

import relf_agent as r

from .composite_session_fixture import definitions, engine
from .test_remote_session_recovery import settled


@pytest.mark.parametrize("adapter", ["memory", "sqlite"])
@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_default_external_root_data_uses_original_composite_authority(tmp_path, adapter, kind):
    async def run():
        backend = (
            r.InMemoryMemory(backend_id="data")
            if adapter == "memory"
            else r.SQLiteMemory(tmp_path / "data.sqlite")
        )
        try:
            raw = engine(
                tmp_path / "run.sqlite",
                conversation_resource=r.SessionBindingResource(
                    backend, namespaces=("red",), default_namespace="red"
                ),
            )
            async with r.Runtime(raw, owned=True) as runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                for seq in (1, 2):
                    handle = await session.submit(
                        "q" + str(seq), command_id="turn" + str(seq), budget=128
                    )
                    done = (await handle.wait(wait_timeout=3)).snapshot
                    assert done.state == "succeeded", done
                    await settled(runtime)
                    assert not (await session.status()).busy
                    receipt = backend.inspect_message(
                        r.Scope(), session.ref.key.storage_key, handle.ref.run_id + ":turn:result"
                    )
                    assert receipt["revision"] == seq
                    assert receipt["receipt"]["message"] == {
                        "role": "assistant",
                        "content": done.result,
                        "task": "q" + str(seq),
                        "agent": definitions()[kind].name,
                    }
                    assert (
                        await session.submit(
                            "q" + str(seq), command_id="turn" + str(seq), budget=128
                        )
                    ).receipt == handle.receipt
                assert len(await session.turns()) == 2
            # Closing an owned Runtime must not close its borrowed data resource.
            assert backend.read(r.Scope(), session.ref.key.storage_key)[0] == 2
        finally:
            close = getattr(backend, "close", None)
            if close is not None:
                close()

    asyncio.run(run())


def test_default_colocated_sqlite_keeps_original_local_route(tmp_path):
    async def run():
        raw = engine(tmp_path / "run.sqlite")
        async with r.Runtime(raw, owned=True) as runtime:
            session = await runtime.create_agent(r.AgentSpec("a", "Answer")).open_session(
                "s", command_id="open"
            )
            handle = await session.submit("q", command_id="one")
            assert (await handle.wait(wait_timeout=2)).snapshot.state == "succeeded"
            run_data = raw.store.run(handle.ref.run_id)
            assert "remote_session_binding" not in run_data
            assert "remote_session_saves" not in run_data
            assert (
                raw.sessions.inspect_message(r.Scope(), "s", handle.ref.run_id + ":0:result")[
                    "receipt"
                ]
                is not None
            )
            assert (
                raw.store.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "2"
            )

    asyncio.run(run())
