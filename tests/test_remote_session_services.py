"""Native/sequence durable Turns on actual Redis and configured PostgreSQL data."""

import asyncio

import pytest

import relf_agent as r
from relf_agent.binding_catalog import BindingCatalog
from relf_agent.errors import MemoryBackendError

from .helpers import ScriptedProvider
from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_remote_session_turns import definition


async def scenario(backend, path, scope, kind):
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "session",
        "remote",
        "1",
        r.SessionBindingResource(backend, namespaces=("red",), default_namespace="red"),
    )
    provider = ScriptedProvider([r.ModelResponse(output="one"), r.ModelResponse(output="two")])

    def make():
        return r.Runtime(
            r.LocalEngine(
                r.SQLiteStore(path),
                providers={"default": provider},
                tools=r.ToolRegistry(),
                scope=scope,
                binding_catalog=catalog,
            ),
            owned=True,
        )

    append = backend.append
    writes = 0

    async def lost(*args, **kwargs):
        nonlocal writes
        writes += 1
        result = await append(*args, **kwargs)
        if writes == 1:
            raise MemoryBackendError("Lost real service response")
        return result

    backend.append = lost
    async with make() as runtime:
        session = await runtime.create_agent(definition(kind)).open_session("s", command_id="open")
        one = await session.submit("q", command_id="one")
        assert (await one.wait(wait_timeout=2)).snapshot.state == "waiting_reconciliation"
        run_ref, session_ref = one.ref, session.ref
    async with make() as runtime:
        session = runtime.attach_session(session_ref)
        resumed = await runtime.resume(run_ref)
        assert (
            await resumed.wait(wait_timeout=2, terminal_only=True)
        ).snapshot.state == "succeeded"
        expected = 1 if kind == "agent" else 2
        assert writes == provider.calls == expected
        assert not (await session.status()).busy
        receipt = await backend.inspect_message(
            scope, session_ref.key.storage_key, f"{run_ref.run_id}:{expected - 1}:result"
        )
        assert receipt["receipt"]["message"]["content"] == ("one" if kind == "agent" else "two")
        assert receipt["revision"] == expected


@pytest.mark.parametrize("kind", ["agent", "sequence"])
def test_real_redis_durable_turn_lost_response_restart(redis_service, tmp_path, kind):
    async def run():
        async with memory_at(redis_service, "durable-" + kind) as (backend, _):
            await scenario(backend, tmp_path / "run.sqlite", r.Scope(), kind)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["agent", "sequence"])
def test_real_postgres_durable_turn_lost_response_restart(postgres_dsn, tmp_path, kind):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await scenario(backend, tmp_path / "run.sqlite", scope, kind)

    asyncio.run(run())
