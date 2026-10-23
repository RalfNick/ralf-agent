"""Real process boundaries preserve the original tool and verification model calls."""

import argparse
import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.parent_completion import ParentCompletionPolicy
from relf_agent.parent_completion_rules import ReceiptParentCompletionGate
from relf_agent.parent_verification_stage import ModelParentVerificationStage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--window")
    parser.add_argument("--run-id")
    parser.add_argument("--kind", default="team")
    args = parser.parse_args()
    marker = Path(args.database).with_suffix(".markers.sqlite")

    def counted(kind, identity=None):
        with sqlite3.connect(marker) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS calls(kind TEXT, identity TEXT)")
            conn.execute("INSERT INTO calls VALUES (?,?)", (kind, identity))

    class Provider:
        identity = {"kind": "durable-parent-completion-fixture", "version": "1"}

        async def complete(self, messages, tools):
            if messages[0]["content"] == "judge":
                counted("verifier-model")
                return ModelResponse({"status": "accept", "feedback": None, "evidence_ids": []})
            counted("worker-model")
            if not any(m["role"] == "tool" for m in messages):
                return ModelResponse(tool_calls=(ToolCall("measure", {"value": 7}, "call"),))
            return ModelResponse({"value": 7})

    class Store(SQLiteStore):
        @contextmanager
        def transaction(self):
            with super().transaction():
                yield
            if not args.window or self.conn.in_transaction:
                return
            rows = self.conn.execute(
                "SELECT run_id FROM events WHERE kind=?", (args.window,)
            ).fetchall()
            for row in rows:
                run = self.run(row[0])
                judge = run["definition"].get("steps", [{}])[0].get("instructions") == "judge"
                parent = run["definition"]["kind"] in {"team", "dynamic"}
                if (args.window in {"model_response_recorded", "decision_adopted"} and judge) or (
                    args.window not in {"model_response_recorded", "decision_adopted"} and parent
                ):
                    os._exit(77)

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "measure",
            "Read measurement",
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            effect="read_only",
        ),
        lambda arguments, context: counted("effect", context.effect_key) or arguments,
    )
    gate = ReceiptParentCompletionGate(
        [
            {
                "id": "value",
                "member_path": ["worker"],
                "tool": "measure",
                "output_bindings": {"/value": {"source": "candidate", "pointer": "/value"}},
            }
        ]
    )
    policy = ParentCompletionPolicy(
        gate, model_stage=ModelParentVerificationStage(instructions="judge")
    )
    with LocalEngine(
        Store(args.database),
        providers={"default": Provider()},
        tools=tools,
        parent_completion_policies={"business": policy},
    ) as engine:
        run_id = args.run_id
        if run_id is None:
            members = {"worker": AgentSpec("worker", "worker", tools=("measure",))}
            definition = (
                TeamSpec("parent", members, completion_policy="business", child_budget=3)
                if args.kind == "team"
                else DynamicWorkflowSpec(
                    "parent",
                    members,
                    completion_policy="business",
                    child_budget=3,
                    plan_mode=args.kind,
                )
            )
            run_id = engine.submit(definition, {"value": 7}, command_id="submit", budget=10).run_id
        print(json.dumps({"run_id": run_id}), flush=True)
        print(json.dumps(asdict(awaitable_result(engine, run_id))), flush=True)


def awaitable_result(engine, run_id):
    return asyncio.run(engine.drive(run_id))


if __name__ == "__main__":
    main()
