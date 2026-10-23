"""Business fixture for profile selection across real CLI processes."""

import json
import sqlite3

from relf_agent import (
    ComponentRegistry,
    ModelResponse,
    ProfiledEngine,
    RuntimeBuilder,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    load_catalog,
)


class Provider:
    def __init__(self, label):
        self.label = label

    @property
    def identity(self):
        return {"kind": "configured-business-fixture", "version": "1", "label": self.label}

    async def complete(self, messages, tools):
        results = [message for message in messages if message["role"] == "tool"]
        if results:
            return ModelResponse(output=json.loads(results[-1]["content"]))
        return ModelResponse(tool_calls=(ToolCall("write", {"label": self.label}),))


def business_tools(config, context):
    path = context.db_path + ".effects.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS effects(effect_key TEXT PRIMARY KEY, result TEXT)"
        )

    def write(arguments, invocation):
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT result FROM effects WHERE effect_key=?", (invocation.effect_key,)
            ).fetchone()
            if row is not None:
                return json.loads(row[0])
            result = {"label": arguments["label"], "effect_key": invocation.effect_key}
            connection.execute(
                "INSERT INTO effects VALUES (?,?)", (invocation.effect_key, json.dumps(result))
            )
            return result

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "write",
            "Write a local fixture receipt",
            {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
                "additionalProperties": False,
            },
            version=config["version"],
            requires_approval=True,
            effect="idempotent_write",
            config={"business": path},
        ),
        write,
    )
    return registry


def create_engine(db_path):
    catalog = load_catalog(str(db_path) + ".runtime.json")
    registry = ComponentRegistry()
    registry.register("provider", "business", lambda config, context: Provider(config["label"]))
    registry.register("tools", "business", business_tools)
    return ProfiledEngine(
        catalog, db_path, builder=RuntimeBuilder(registry, base_dir=catalog.base_dir)
    )
