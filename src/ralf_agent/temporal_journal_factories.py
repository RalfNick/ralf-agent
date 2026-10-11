"""Explicit durable effect evidence; no execution Store or command authority."""

import asyncio

from .remote_factories import _env, _validate


def register_effect_journal(registry):
    def validate(config):
        _validate(
            config,
            {"dsn_env", "backend_id", "initialize", "timeout"},
            envs=["dsn_env"],
            identities=["backend_id"],
        )

    async def build(config, context):
        from .temporal_journal import PostgresEffectJournal

        async with asyncio.timeout(config.get("timeout", 10)):
            journal = context.own_async(
                await PostgresEffectJournal.connect(
                    _env(config, "dsn_env"), backend_id=config["backend_id"]
                )
            )
            if config.get("initialize", False):
                await journal.initialize()
            return journal

    registry.register_async("effect_journal", "postgres", build, validator=validate)
