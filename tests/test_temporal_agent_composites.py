import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch

from .temporal_agent_fixture import engine, worker_runtime
from .temporal_composite_agent_fixture import CompositeClient, definitions


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "plan", "nested"])
def test_composite_agent_original_refs_receipts_and_child_execution(monkeypatch, kind):
    async def scenario():
        client = CompositeClient()
        raw = engine(
            monkeypatch, client=client, release=client.worker_runtime.orchestration_release
        )
        async with r.Runtime.from_temporal(raw) as runtime:
            agent = runtime.create_agent(definitions()[kind])
            run = await agent.submit("q", command_id="submit", budget=64)
            assert (await run.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
            assert (await run.diagnostics()).workflow["backend"] == "temporal-parent"
            assert await runtime.areference(run.ref.run_id) == run.ref
            attached = await runtime.aattach(r.RunRef.from_dict(run.ref.to_dict()))
            before = await run.events()
            assert (await attached.status()).state == "waiting_approval"
            assert await run.events() == before
            # Current aliases may move; already accepted History fixes the release.
            raw._release = {
                **raw.release,
                "providers": {"moved": {"kind": "other", "version": "2"}},
            }
            raw.task_queue = "unavailable"
            replay = await agent.submit("q", command_id="submit", budget=64)
            assert replay.ref == run.ref and replay.receipt == run.receipt
            pending = (await run.status()).pending
            assert len(pending) == 1 and pending[0]["run_id"] != run.ref.run_id
            owner = await runtime.aattach(await runtime.areference(pending[0]["run_id"]))
            approval = await owner.approve(
                pending[0]["action_id"], pending[0]["digest"], command_id="approve"
            )
            assert (
                await owner.approve(
                    pending[0]["action_id"], pending[0]["digest"], command_id="approve"
                )
                == approval
            )
            expected = {"a": "done"} if kind in {"graph", "nested"} else "done"
            assert (await attached.wait(wait_timeout=1)).snapshot.result == expected
            assert client.tool_calls == 1
            info = await attached.diagnostics()
            assert info.budget["reserved"] == info.budget["unknown"] == 0
            assert info.budget["spent"] == 3
            with pytest.raises(DefinitionMismatch):
                await runtime.aattach(
                    r.RunRef.from_dict({**run.ref.to_dict(), "release_digest": "0" * 64})
                )

    asyncio.run(scenario())


def test_composite_capabilities_require_explicit_registered_release(monkeypatch):
    async def scenario():
        async with r.Runtime.from_temporal(engine(monkeypatch)) as native:
            assert native.capabilities["supported_definition_kinds"] == ["agent", "sequence"]
        raw = engine(monkeypatch, release=worker_runtime().orchestration_release)
        async with r.Runtime.from_temporal(raw) as extended:
            assert extended.capabilities["supported_definition_kinds"] == [
                "agent",
                "sequence",
                "graph",
                "team",
                "dynamic",
            ]

    asyncio.run(scenario())
