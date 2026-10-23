"""Importable custom runtime profile for CLI conformance tests."""

from relf_agent import LocalEngine, ModelResponse, SQLiteStore, ToolCall, ToolRegistry, ToolSpec


class CustomProvider:
    identity = {"kind": "custom-cli-profile", "version": "1"}

    async def complete(self, messages, tools):
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output={"custom": True})
        return ModelResponse(tool_calls=(ToolCall("custom_change", {"value": 7}),))


def custom_change(arguments, context):
    return {"updated": arguments["value"]}


def create_engine(db):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "custom_change",
            "Apply a custom test change",
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            effect="idempotent_write",
            requires_approval=True,
        ),
        custom_change,
    )
    return LocalEngine(SQLiteStore(db), providers={"default": CustomProvider()}, tools=tools)


def broken_factory(db):
    raise RuntimeError("fixture-private-configuration")


def wrong_factory(db):
    return object()


not_callable = "a profile must be callable"
