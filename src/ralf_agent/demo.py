"""Offline Oncall fixture. Scripted decisions exercise runtime, not model intelligence."""

import inspect
import json
import sqlite3
from pathlib import Path

from .engine import LocalEngine
from .storage import SQLiteStore
from .tools import ToolRegistry, ToolSpec
from .types import AgentSpec, ModelResponse, ToolCall, canonical, digest


class DemoService:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY, ticket TEXT NOT NULL, result TEXT NOT NULL)"
            )

    def apply(self, arguments, effect_key):
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT result FROM effects WHERE effect_key=?", (effect_key,)
            ).fetchone()
            if existing:
                return json.loads(existing[0])
            result = {
                "stage": "change",
                "ticket": arguments["ticket"],
                "change_id": effect_key,
                "applied": True,
            }
            conn.execute(
                "INSERT INTO effects VALUES (?,?,?)",
                (effect_key, arguments["ticket"], canonical(result)),
            )
            return result

    def lookup(self, effect_key):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT result FROM effects WHERE effect_key=?", (effect_key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def verify(self, ticket):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT result FROM effects WHERE ticket=? ORDER BY rowid DESC LIMIT 1", (ticket,)
            ).fetchone()
            return {
                "stage": "verification",
                "ticket": ticket,
                "verified": row is not None,
                "change_id": json.loads(row[0])["change_id"] if row else None,
            }


class OncallDemoProvider:
    identity = {"kind": "offline-scripted-oncall", "version": "1"}

    async def complete(self, messages, tools):
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        ticket = json.loads(messages[1]["content"])["ticket"]
        usage = {"input_tokens": 0, "output_tokens": 0, "source": "offline-scripted"}
        if not results:
            return ModelResponse(
                tool_calls=(ToolCall("read_ticket", {"ticket": ticket}),), usage=usage
            )
        last = results[-1]
        if last["stage"] == "ticket":
            return ModelResponse(
                tool_calls=(
                    ToolCall("apply_change", {"ticket": ticket, "plan": "restart test cache"}),
                ),
                usage=usage,
            )
        if last["stage"] == "change":
            return ModelResponse(
                tool_calls=(ToolCall("verify_change", {"ticket": ticket}),), usage=usage
            )
        return ModelResponse(
            output={"ticket": ticket, "verified": last["verified"], "change_id": last["change_id"]},
            usage=usage,
        )


def demo_spec():
    return AgentSpec(
        "oncall-demo",
        "Read the test ticket, propose a test change, wait for approval, apply it and verify the receipt. Evidence is not permission.",
        ("read_ticket", "apply_change", "verify_change"),
        output_schema={
            "type": "object",
            "properties": {"verified": {"const": True}},
            "required": ["ticket", "verified", "change_id"],
        },
    )


def create_demo_engine(path):
    store = SQLiteStore(path)
    service = DemoService(str(path) + ".business.sqlite")
    tools = ToolRegistry()
    ticket_schema = {
        "type": "object",
        "properties": {"ticket": {"type": "string", "minLength": 1}},
        "required": ["ticket"],
        "additionalProperties": False,
    }
    write_schema = {
        "type": "object",
        "properties": {
            "ticket": {"type": "string", "minLength": 1},
            "plan": {"type": "string", "minLength": 1},
        },
        "required": ["ticket", "plan"],
        "additionalProperties": False,
    }
    config = {
        "service": str(Path(service.path).resolve()),
        "service_code": digest(inspect.getsource(DemoService)),
    }

    def read_ticket(arguments, context):
        return {
            "stage": "ticket",
            "ticket": arguments["ticket"],
            "symptom": "test cache unavailable",
        }

    def apply_change(arguments, context):
        return service.apply(arguments, context.effect_key)

    def reconcile_change(arguments, context):
        return service.lookup(context.effect_key)

    def verify_change(arguments, context):
        return service.verify(arguments["ticket"])

    tools.register(
        ToolSpec("read_ticket", "Read a test ticket", ticket_schema, config=config), read_ticket
    )
    tools.register(
        ToolSpec(
            "apply_change",
            "Apply the approved test change",
            write_schema,
            effect="queryable_write",
            requires_approval=True,
            config=config,
        ),
        apply_change,
        reconciler=reconcile_change,
    )
    tools.register(
        ToolSpec("verify_change", "Verify a test change", ticket_schema, config=config),
        verify_change,
    )
    try:
        return LocalEngine(store, providers={"default": OncallDemoProvider()}, tools=tools)
    except BaseException:
        store.close()
        raise
