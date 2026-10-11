"""Temporal-only journal declarations reuse the existing durable evidence port."""

import asyncio

import pytest

from ralf_agent import RuntimeProfile, TemporalProfile, TemporalRuntimeBuilder
from ralf_agent.errors import ValidationError


def selected(config):
    return TemporalProfile(
        "journal",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"effect_journal": {"adapter": "postgres", "config": config}},
    )


def test_temporal_only_journal_is_not_a_local_execution_store():
    declaration = {
        "effect_journal": {
            "adapter": "postgres",
            "config": {"dsn_env": "RALF_JOURNAL_DSN", "backend_id": "effects"},
        }
    }
    assert selected(declaration["effect_journal"]["config"]).components == declaration
    with pytest.raises(ValidationError):
        RuntimeProfile("local", "1", {"default": {"adapter": "offline-echo"}}, declaration)


def test_journal_config_and_environment_preflight_before_factory(tmp_path):
    async def run():
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
                selected({"dsn_env": "ABSENT_RALF_JOURNAL_FIXTURE", "backend_id": "effects"})
            )
        assert not any(tmp_path.iterdir())

    asyncio.run(run())


def test_declared_journal_connect_initialize_and_owned_close(tmp_path, monkeypatch):
    from ralf_agent.temporal_journal import PostgresEffectJournal

    async def run():
        events = []

        class Journal:
            identity = {"kind": "fixture-journal", "version": "1"}

            async def initialize(self):
                events.append("initialize")

            async def begin(self, envelope):
                return {"execute": True}

            async def received(self, envelope, observation):
                pass

            async def observation(self, envelope):
                return None

            async def acknowledge(self, envelope, observation):
                pass

            async def aclose(self):
                events.append("close")

        async def connect(dsn, *, backend_id):
            assert dsn == "fixture-dsn" and backend_id == "effects"
            events.append("connect")
            return Journal()

        monkeypatch.setenv("RALF_JOURNAL_DSN", "fixture-dsn")
        monkeypatch.setattr(PostgresEffectJournal, "connect", connect)
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            selected({"dsn_env": "RALF_JOURNAL_DSN", "backend_id": "effects", "initialize": True})
        )
        assert assembly.release["effect_journal"] == Journal.identity
        await assembly.aclose()
        assert events == ["connect", "initialize", "close"]

    asyncio.run(run())
