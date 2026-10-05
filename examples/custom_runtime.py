"""Own importable Agent profile; offline fixture, no external model or writes."""

import argparse
import json

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)


class OfflineLookupProvider:
    identity = {"kind": "example-offline-lookup", "version": "1"}

    async def complete(self, messages, tools):
        results = [m for m in messages if m["role"] == "tool"]
        if results:
            return ModelResponse(output=json.loads(results[-1]["content"]))
        return ModelResponse(
            tool_calls=(ToolCall("lookup_record", {"record": messages[1]["content"]}),)
        )


class LookupRecord:
    def __call__(self, arguments, context):
        return {"record": arguments["record"], "status": "open", "source": "offline-fixture"}


def create_engine(db_path):
    """The CLI and SDK both construct the same fixed configuration."""
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "lookup_record",
            "Read an offline sample record",
            {
                "type": "object",
                "properties": {"record": {"type": "string"}},
                "required": ["record"],
                "additionalProperties": False,
            },
            effect="read_only",
            config={"dataset": "offline-example:v1"},
        ),
        LookupRecord(),
    )
    return LocalEngine(
        SQLiteStore(db_path), providers={"default": OfflineLookupProvider()}, tools=tools
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/custom.sqlite")
    parser.add_argument("--record", default="INC-CUSTOM")
    args = parser.parse_args()
    with create_engine(args.db) as engine:
        handle = engine.submit(
            AgentSpec(
                "custom_lookup",
                "Read the sample record and return its verified JSON.",
                ("lookup_record",),
            ),
            args.record,
            command_id=f"example:{args.record}",
        )
        print(json.dumps(handle.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    # SDK entry and CLI import the same module identity for tool release pins.
    from examples.custom_runtime import main as run_profile

    run_profile()
