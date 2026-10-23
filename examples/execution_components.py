"""Offline custom Harness and ToolExecutor, with durable approval and recovery.

Run from the repository root with the SDK installed:
    python -m examples.execution_components --db .ralf/components.sqlite

Use `relf --db DB --factory examples.execution_components:create_engine
--format text inspect RUN_ID` to review the proposed write and copy the explicit
approval/resume commands. Add `--workflow` for a two-step sequential workflow.
This fixture uses local SQLite, not a remote service or a live model.
"""

import argparse
import asyncio
import copy
import inspect
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from relf_agent.errors import RalfError, ValidationError
from relf_agent.executors import DispatchEnvelope, EffectObservation
from relf_agent.harness import DecisionProposal, ModelRequest
from relf_agent.tools import current_thread_tracker
from relf_agent.types import canonical, digest


class ReviewHarness:
    identity = {"kind": "example-review-harness", "version": "1"}

    def prepare(self, spec, messages, tools):
        prepared = copy.deepcopy(messages)
        prepared[0]["content"] += (
            f"\nExample policy for {spec.name}: use verified business evidence; "
            "tool proposals remain subject to the engine's approval policy."
        )
        return ModelRequest(prepared, tools)

    def propose(self, spec, response):
        if response.tool_calls:
            calls = []
            for call in response.tool_calls:
                arguments = copy.deepcopy(call.arguments)
                if call.name == "apply_change":
                    arguments["plan"] = f"policy/{spec.name}: {arguments['plan']}"
                calls.append(ToolCall(call.name, arguments, call.call_id))
            return DecisionProposal(tool_calls=tuple(calls))
        return DecisionProposal(output={**response.output, "policy": spec.name})


class OfflineProvider:
    identity = {"kind": "example-component-script", "version": "1"}

    async def complete(self, messages, tools):
        task = json.loads(messages[1]["content"])
        usage = {"input_tokens": 0, "output_tokens": 0, "source": "offline-scripted"}
        if not tools:
            return ModelResponse(
                output={**task, "summary": "One approved fixture change was verified."},
                usage=usage,
            )
        receipts = [
            json.loads(message["content"]) for message in messages if message["role"] == "tool"
        ]
        if not receipts:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        "apply_change",
                        {"ticket": task["ticket"], "plan": "restart fixture cache"},
                    ),
                ),
                usage=usage,
            )
        return ModelResponse(output=receipts[-1], usage=usage)


class BusinessService:
    """SQLite stand-in for an external effect-key-aware business API."""

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS effects "
                "(effect_key TEXT PRIMARY KEY, operation_digest TEXT NOT NULL, "
                "arguments TEXT NOT NULL, result TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS dispatches "
                "(effect_key TEXT NOT NULL, action_id TEXT NOT NULL, "
                "operation_digest TEXT NOT NULL, arguments TEXT NOT NULL)"
            )

    @staticmethod
    def _receipt(row, envelope):
        if row is None:
            return None
        operation_digest, arguments, result = row
        if operation_digest != envelope.operation_digest or arguments != canonical(
            envelope.arguments
        ):
            raise ValidationError("Business effect key was reused for a different operation")
        return json.loads(result)

    def apply(self, envelope):
        arguments = envelope.arguments
        effect_key = envelope.context.effect_key
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO dispatches VALUES (?,?,?,?)",
                (
                    effect_key,
                    envelope.context.action_id,
                    envelope.operation_digest,
                    canonical(arguments),
                ),
            )
            existing = connection.execute(
                "SELECT operation_digest, arguments, result FROM effects WHERE effect_key=?",
                (effect_key,),
            ).fetchone()
            receipt = self._receipt(existing, envelope)
            if receipt is not None:
                return receipt
            receipt = {
                "ticket": arguments["ticket"],
                "plan": arguments["plan"],
                "change_id": effect_key,
                "verified": True,
            }
            connection.execute(
                "INSERT INTO effects VALUES (?,?,?,?)",
                (effect_key, envelope.operation_digest, canonical(arguments), canonical(receipt)),
            )
            return receipt

    def lookup(self, envelope):
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT operation_digest, arguments, result FROM effects WHERE effect_key=?",
                (envelope.context.effect_key,),
            ).fetchone()
            return self._receipt(row, envelope)


class BusinessExecutor:
    def __init__(self, service):
        self.service = service

    @property
    def identity(self):
        return {
            "kind": "example-business-executor",
            "version": "1",
            "database": self.service.path,
            "service_code": digest(inspect.getsource(BusinessService)),
        }

    async def _call(self, function, envelope):
        if envelope.tool_name != "apply_change":
            raise ValidationError("Example executor only supports apply_change")
        tracker = current_thread_tracker.get()
        if tracker is None:
            return await asyncio.to_thread(function, envelope)
        return await tracker.run(function, envelope, group=envelope.context.run_id)

    async def execute(self, envelope: DispatchEnvelope):
        result = await self._call(self.service.apply, envelope)
        return EffectObservation(result, source="example-business-executor")

    async def reconcile(self, envelope: DispatchEnvelope):
        result = await self._call(self.service.lookup, envelope)
        return (
            None
            if result is None
            else EffectObservation(result, source="example-business-reconciler")
        )


def descriptor_only(arguments, context):
    raise AssertionError("The custom executor handles this tool; the descriptor is not executable")


def create_engine(db_path):
    store = SQLiteStore(db_path)
    try:
        service = BusinessService(store.path + ".business.sqlite")
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "apply_change",
                "Apply one explicitly approved offline business change",
                {
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string", "minLength": 1},
                        "plan": {"type": "string", "minLength": 1},
                    },
                    "required": ["ticket", "plan"],
                    "additionalProperties": False,
                },
                effect="queryable_write",
                requires_approval=True,
                config={"operation": "fixture-change:v1"},
            ),
            descriptor_only,
            # There is no Python reconciler. BusinessExecutor owns receipt queries.
        )
        return LocalEngine(
            store,
            providers={"default": OfflineProvider()},
            tools=registry,
            harness=ReviewHarness(),
            tool_executor=BusinessExecutor(service),
        )
    except BaseException:
        store.close()
        raise


def definition(workflow=False):
    schema = {
        "type": "object",
        "properties": {
            "ticket": {"type": "string"},
            "plan": {"type": "string"},
            "change_id": {"type": "string"},
            "verified": {"const": True},
            "policy": {"type": "string"},
        },
        "required": ["ticket", "plan", "change_id", "verified", "policy"],
        "additionalProperties": False,
    }
    agent = AgentSpec(
        "component-change",
        "Propose one fixture change, wait for explicit approval, then return the committed receipt.",
        ("apply_change",),
        output_schema=schema,
    )
    if not workflow:
        return agent
    summary = AgentSpec(
        "component-summary",
        "Summarize the verified fixture receipt from the preceding step.",
        output_schema={
            **schema,
            "properties": {**schema["properties"], "summary": {"type": "string"}},
            "required": [*schema["required"], "summary"],
        },
    )
    return WorkflowSpec("component-flow", (agent, summary))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/components.sqlite")
    parser.add_argument("--ticket", default="INC-COMPONENTS")
    parser.add_argument("--command-id")
    parser.add_argument("--workflow", action="store_true")
    args = parser.parse_args(argv)
    try:
        with create_engine(args.db) as engine:
            mode = "flow" if args.workflow else "agent"
            handle = engine.submit(
                definition(args.workflow),
                {"ticket": args.ticket},
                command_id=args.command_id or f"components:{mode}:{args.ticket}",
            )
            result = asyncio.run(engine.drive(handle.run_id))
            print(
                json.dumps(
                    {
                        "run_id": result.run_id,
                        "state": result.state,
                        "pending": result.pending,
                        "result": result.result,
                        "submission": asdict(handle.receipt),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        return 0
    except RalfError as exc:
        print(json.dumps({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Use the same source identity as the recovery factory imported by the CLI.
    from examples.execution_components import main as canonical_main

    raise SystemExit(canonical_main())
