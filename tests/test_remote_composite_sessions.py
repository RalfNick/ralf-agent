"""Remote final root conversations retain original Local composite authority."""

import asyncio

import pytest

import ralf_agent as r

from .composite_session_fixture import definitions, engine
from .remote_session_fixture import RemoteMemory
from .test_remote_session_recovery import settled


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
@pytest.mark.parametrize("namespace", [None, "red"])
def test_remote_root_turns_all_compositions(tmp_path, kind, namespace):
    async def scenario():
        backend = RemoteMemory(tmp_path / "data.sqlite")
        try:
            raw = engine(
                tmp_path / "run.sqlite",
                conversation_resource=r.SessionBindingResource(
                    backend, namespaces=(namespace,), default_namespace=namespace
                ),
            )
            async with r.Runtime(raw, owned=True) as runtime:
                session = await runtime.create_agent(definitions()[kind]).open_session(
                    "s", command_id="open"
                )
                assert (
                    raw.store.conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    == "6"
                )
                for seq in (1, 2):
                    one = await session.submit(
                        "q" + str(seq), command_id="turn" + str(seq), budget=128
                    )
                    done = (await one.wait(wait_timeout=2)).snapshot
                    assert done.state == "succeeded", done
                    await settled(runtime)
                    assert not (await session.status()).busy
                    receipt = await backend.inspect_message(
                        r.Scope(), session.ref.key.storage_key, one.ref.run_id + ":turn:result"
                    )
                    assert receipt["receipt"]["message"] == {
                        "role": "assistant",
                        "content": done.result,
                        "agent": definitions()[kind].name,
                        "task": "q" + str(seq),
                    }
                    assert receipt["revision"] == seq
                assert len(await session.turns()) == 2 and backend.append_calls == 2
                before = backend.inspect_calls, backend.append_calls, backend.read_calls
                await session.status()
                await session.turns()
                assert before == (backend.inspect_calls, backend.append_calls, backend.read_calls)
        finally:
            backend.close()

    asyncio.run(scenario())
