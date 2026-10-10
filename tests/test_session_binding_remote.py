"""Run the same Session binding path on real Redis and configured PostgreSQL."""

import asyncio

import pytest

from ralf_agent import (
    BindingCatalog,
    BindingSelection,
    LocalEngine,
    Scope,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import ValidationError

from .test_binding_execution import RecordingProvider
from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_session_binding_execution import session_agent
from .test_session_binding_resources import resource_type


async def scenario(backend, tmp_path, scope=None):
    scope = Scope() if scope is None else scope
    catalog = BindingCatalog(scope=scope)
    resource = resource_type()(backend, namespaces=("red", "blue"), default_namespace="red")
    catalog.register("session", "history", "1", resource)
    catalog.register("session", "alias", "1", resource)
    path = tmp_path / "run.sqlite"

    def runtime():
        return LocalEngine(
            SQLiteStore(path),
            providers={"default": RecordingProvider("offline")},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            scope=scope,
        )

    with runtime() as e:
        h = e.submit(session_agent(namespace="red"), "q", session_id="shared", command_id="first")
    with runtime() as e:
        with pytest.raises(ValidationError):
            e.submit(session_agent("alias", "red"), "q", session_id="shared", command_id="busy")
        assert (await e.drive(h.run_id)).state == "succeeded"
        red, _ = catalog.resolve("session", BindingSelection.ref("history", "1"), scope)
        blue, _ = catalog.resolve(
            "session", BindingSelection.ref("history", "1", selector={"namespace": "blue"}), scope
        )
        assert (await red.read(scope, "shared"))[0] == 1
        assert await blue.read(scope, "shared") == (0, [])


def test_real_redis_session_binding_restart_and_namespace_isolation(redis_service, tmp_path):
    async def run():
        async with memory_at(redis_service, "session-bindings") as (backend, client):
            await scenario(backend, tmp_path)

    asyncio.run(run())


def test_real_postgres_session_binding_restart_and_namespace_isolation(postgres_dsn, tmp_path):
    async def run():
        async with stores(postgres_dsn) as (backend, knowledge, scope):
            await scenario(backend, tmp_path, scope)

    asyncio.run(run())
