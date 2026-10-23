"""Offline process fixture for committed response/receipt recovery windows."""

import argparse
import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)


class ReceiptEvidence:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS calls (kind TEXT PRIMARY KEY, count INTEGER);"
                "CREATE TABLE IF NOT EXISTS effects "
                "(effect_key TEXT PRIMARY KEY, result TEXT NOT NULL);"
            )

    @staticmethod
    def count_call(connection, kind):
        connection.execute(
            "INSERT INTO calls VALUES (?, 1) ON CONFLICT(kind) DO UPDATE SET count=count+1",
            (kind,),
        )

    def model_call(self):
        with sqlite3.connect(self.path) as connection:
            self.count_call(connection, "model")

    def write(self, arguments, context):
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.count_call(connection, "handler")
            row = connection.execute(
                "SELECT result FROM effects WHERE effect_key=?", (context.effect_key,)
            ).fetchone()
            if row:
                return json.loads(row[0])
            result = {"written": arguments["value"], "receipt_id": context.effect_key}
            connection.execute(
                "INSERT INTO effects VALUES (?, ?)",
                (context.effect_key, json.dumps(result)),
            )
            return result

    def reconcile(self, arguments, context):
        with sqlite3.connect(self.path) as connection:
            self.count_call(connection, "reconciler")
            row = connection.execute(
                "SELECT result FROM effects WHERE effect_key=?", (context.effect_key,)
            ).fetchone()
            return json.loads(row[0]) if row else None


class ReceiptProvider:
    def __init__(self, evidence, scenario):
        self.evidence, self.scenario = evidence, scenario

    @property
    def identity(self):
        return {"kind": "receipt-window-fixture", "version": "1", "scenario": self.scenario}

    async def complete(self, messages, tools):
        self.evidence.model_call()
        usage = {"input_tokens": 11, "output_tokens": 3, "source": "offline-fixture"}
        if self.scenario == "final":
            return ModelResponse(
                output={"completed": True, "answer": "recorded model response"}, usage=usage
            )
        results = [
            json.loads(message["content"]) for message in messages if message["role"] == "tool"
        ]
        if results:
            return ModelResponse(output={"completed": True, **results[-1]}, usage=usage)
        return ModelResponse(
            tool_calls=(ToolCall("write", {"value": 7}, "fixture-call"),), usage=usage
        )


class ReceiptWindowStore(SQLiteStore):
    """The hook runs only after the outermost transaction commits successfully."""

    def __init__(self, path, *, trigger_event=None, trigger_mode="crash"):
        super().__init__(path)
        self.trigger_event, self.trigger_mode = trigger_event, trigger_mode
        self.after_record = None

    @contextmanager
    def transaction(self):
        outermost = not self.conn.in_transaction
        with super().transaction():
            yield
        if outermost and self.trigger_event:
            row = self.conn.execute(
                "SELECT run_id FROM events WHERE kind=? ORDER BY rowid DESC LIMIT 1",
                (self.trigger_event,),
            ).fetchone()
            if row:
                self.trigger_event = None
                if self.trigger_mode == "crash":
                    os._exit(77)
                self.after_record(row["run_id"])


def spec(scenario):
    return AgentSpec(
        f"receipt-{scenario}",
        "Complete the local fixture and return its verified result.",
        () if scenario == "final" else ("write",),
        model_credits=2,
        output_schema={
            "type": "object",
            "properties": {"completed": {"const": True}},
            "required": ["completed"],
        },
    )


def create_engine(path, scenario, *, trigger_event=None, trigger_mode="crash"):
    store = ReceiptWindowStore(path, trigger_event=trigger_event, trigger_mode=trigger_mode)
    try:
        evidence = ReceiptEvidence(str(store.path) + ".evidence.sqlite")
        tools = ToolRegistry()
        if scenario != "final":
            tools.register(
                ToolSpec(
                    "write",
                    "Record one isolated fixture effect",
                    {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                    effect=scenario,
                    cost=3,
                    config={"evidence": evidence.path},
                ),
                evidence.write,
                reconciler=evidence.reconcile if scenario == "queryable_write" else None,
            )
        engine = LocalEngine(
            store, providers={"default": ReceiptProvider(evidence, scenario)}, tools=tools
        )
        store.after_record = lambda run_id: engine.cancel(run_id, command_id="cancel-recorded")
        return engine
    except BaseException:
        store.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("scenario", choices=("final", "queryable_write", "unqueryable_write"))
    parser.add_argument("--trigger-event")
    parser.add_argument("--trigger-mode", choices=("crash", "cancel"), default="crash")
    parser.add_argument("--run-id")
    parser.add_argument("--cancel-before-resume", action="store_true")
    arguments = parser.parse_args()
    with create_engine(
        arguments.database,
        arguments.scenario,
        trigger_event=arguments.trigger_event,
        trigger_mode=arguments.trigger_mode,
    ) as engine:
        run_id = arguments.run_id
        if run_id is None:
            handle = engine.submit(
                spec(arguments.scenario), "fixture", command_id="start", budget=12
            )
            run_id = handle.run_id
        if arguments.trigger_event and arguments.trigger_mode == "crash":
            print(json.dumps({"run_id": run_id}), flush=True)
        if arguments.cancel_before_resume:
            engine.cancel(run_id, command_id="cancel-before-resume")
        snapshot = asyncio.run(engine.drive(run_id))
        print(json.dumps(asdict(snapshot), allow_nan=False))
    return 0


if __name__ == "__main__":
    # Worker and parent reconstruct the same importable tool implementation.
    from tests.receipt_runtime import main as run_fixture

    raise SystemExit(run_fixture())
