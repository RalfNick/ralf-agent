"""Borrowed original PG records include already fenced closure obligations."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.postgres_runner_journal import PostgresRunnerJournal
from ralf_agent.types import Scope


def test_composition_resources_requires_scope_before_pg_io():
    async def run():
        assert hasattr(PostgresRunnerJournal, "composition_resources"), (
            "Missing all-resource closure query"
        )
        with pytest.raises(ValidationError):
            await PostgresRunnerJournal.composition_resources(object(), {"workspace": "foreign"})

    asyncio.run(run())


def test_composition_resources_includes_fenced_rows_and_validates_same_effect(monkeypatch):
    from ralf_agent import postgres_runner_journal as module

    seen = []

    @asynccontextmanager
    async def transaction():
        yield

    async def execute(query, params, **kwargs):
        assert params == ("original", "owner", 3)
        return [("live", "live-record"), ("fenced", "fenced-record")]

    async def check():
        pass

    async def integrity(key, resource):
        seen.append((key, resource["pending_stop"]))

    owner = SimpleNamespace(
        _capacity=2,
        _ready=lambda: None,
        _check=check,
        _effect=SimpleNamespace(_transaction=transaction, _execute=execute),
        _validate_resource_effect=integrity,
    )
    monkeypatch.setattr(
        module, "validate_resource", lambda encoded, key: {"pending_stop": key[-1] == "live"}
    )

    async def run():
        assert hasattr(PostgresRunnerJournal, "composition_resources"), (
            "Missing all-resource closure query"
        )
        result = await PostgresRunnerJournal.composition_resources(
            owner, Scope("original", "owner")
        )
        assert result == ({"pending_stop": True}, {"pending_stop": False})
        assert seen == [
            (("original", "owner", "live"), True),
            (("original", "owner", "fenced"), False),
        ]

    asyncio.run(run())
