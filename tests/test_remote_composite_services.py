"""Actual remote root data, lost responses and original Local authority restart."""

import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import MemoryBackendError

from .composite_session_fixture import definitions
from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_remote_composite_recovery import raw_at
from .test_remote_session_recovery import settled


async def scenario(backend, path, scope, kind):
    append = backend.append
    writes = 0

    async def lost(*args, **kwargs):
        nonlocal writes
        writes += 1
        result = await append(*args, **kwargs)
        if writes == 1:
            raise MemoryBackendError("Lost real remote root response")
        return result

    backend.append = lost
    async with r.Runtime(raw_at(path, backend, "red", scope=scope), owned=True) as runtime:
        session = await runtime.create_agent(definitions()[kind]).open_session(
            "s", command_id="open"
        )
        one = await session.submit("q", command_id="one", budget=128)
        assert (await one.wait(wait_timeout=2)).snapshot.state == "waiting_reconciliation"
        await settled(runtime)
        ref, sref = one.ref, session.ref
    async with r.Runtime(raw_at(path, backend, "red", scope=scope), owned=True) as runtime:
        session = runtime.attach_session(sref)
        one = await runtime.resume(ref)
        assert (await one.wait(wait_timeout=2, terminal_only=True)).snapshot.state == "succeeded"
        await settled(runtime)
        assert not (await session.status()).busy
        assert writes == 1 and runtime.engine.providers["default"].calls == 0
        receipt = await backend.inspect_message(
            scope, sref.key.storage_key, ref.run_id + ":turn:result"
        )
        assert (
            receipt["revision"] == 1
            and receipt["receipt"]["message"]["content"] == (await one.status()).result
        )


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_actual_redis_root_unknown_save_restart(redis_service, tmp_path, kind):
    async def run():
        async with memory_at(redis_service, "root-" + kind) as (backend, _):
            await scenario(backend, tmp_path / "run.sqlite", r.Scope(), kind)

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["graph", "parallel", "team", "plan", "dag", "nested", "transform"]
)
def test_actual_postgres_root_unknown_save_restart(postgres_dsn, tmp_path, kind):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await scenario(backend, tmp_path / "run.sqlite", scope, kind)

    asyncio.run(run())
