"""Original Local response windows with a truly independent source implementation."""

import argparse
import asyncio
import json
import os
from contextlib import contextmanager
from dataclasses import asdict

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    Runtime,
    RuntimeBuilder,
    Scope,
    SQLiteStore,
    recommended_profile,
)
from relf_agent.adapter_contract_reference import (
    ReferenceKnowledgeSource,
    register_reference_components,
)


class WindowStore(SQLiteStore):
    def __init__(self, path, *, trigger=None):
        super().__init__(path)
        self.trigger = trigger

    @contextmanager
    def transaction(self):
        outermost = not self.conn.in_transaction
        with super().transaction():
            yield
        if outermost and self.trigger:
            row = self.conn.execute(
                "SELECT run_id FROM events WHERE kind=? ORDER BY rowid DESC LIMIT 1",
                (self.trigger,),
            ).fetchone()
            if row is not None:
                print(json.dumps({"run_id": row["run_id"]}), flush=True)
                os._exit(77)


def create_runtime(database, trigger=None):
    source = ReferenceKnowledgeSource(str(database) + ".external.sqlite")
    registry = ComponentRegistry()
    register_reference_components(registry, source, owned=True)
    profile = recommended_profile(
        "semantic-knowledge",
        version="2",
        provider={"adapter": "external-reference-reader"},
        components={
            "knowledge": {"adapter": "external-reference", "config": {"namespace": "manuals"}}
        },
    )
    builder = RuntimeBuilder(
        registry, store_factory=lambda path: WindowStore(path, trigger=trigger)
    )
    try:
        return builder.build(profile, database), source
    except BaseException:
        source.close()
        raise


async def execute(arguments):
    instance, source = create_runtime(arguments.database, arguments.trigger)
    async with Runtime(instance, owned=True) as runtime:
        if arguments.run_id is None:
            # Explicit initial seed only. Recovery never replaces deleted sources.
            source.put(
                Scope(),
                "manuals",
                "cache",
                "cache timeout inspect connection pool",
                source_uri="reference://manuals/cache",
                metadata={"category": "runbook"},
            )
            session = await runtime.create_agent(
                AgentSpec("reader", "Use original references", model_credits=2)
            ).open_session("knowledge-session", command_id="open")
            run = await session.submit("cache", command_id="start", budget=32)
            result = (await run.wait(wait_timeout=10)).snapshot
        else:
            if arguments.delete_source:
                source.delete(Scope(), "manuals", "cache")
            result = await instance.drive(arguments.run_id)
        return asdict(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--trigger", choices=("model_dispatched", "model_response_recorded"))
    parser.add_argument("--run-id")
    parser.add_argument("--delete-source", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(execute(arguments)), allow_nan=False))


if __name__ == "__main__":
    from tests.adapter_contract_reference_worker import main as canonical_main

    canonical_main()
