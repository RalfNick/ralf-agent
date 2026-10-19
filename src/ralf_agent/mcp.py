"""MCP tool normalization; transport and execution authority are independent."""

import copy
from typing import Protocol

from jsonschema import Draft202012Validator

from .errors import ValidationError
from .ports import is_async_callable
from .tool_sources import ToolDescriptor, ToolSourceError, _identity
from .types import canonical


class MCPTransport(Protocol):
    identity: dict

    async def request(
        self, method: str, params: dict, *, expected_tool: dict | None = None
    ) -> dict: ...


def mcp_descriptor(value):
    if not isinstance(value, dict):
        raise ValidationError("MCP tool descriptor must be an object")
    try:
        return ToolDescriptor(
            value["name"],
            value.get("description", ""),
            value["inputSchema"],
            value.get("outputSchema"),
        )
    except KeyError as exc:
        raise ValidationError("MCP tool descriptor is incomplete") from exc


async def list_mcp_tools(transport):
    items, cursor, seen = [], None, set()
    for _ in range(32):
        result = await transport.request("tools/list", {} if cursor is None else {"cursor": cursor})
        canonical(result)
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise ValidationError("MCP tools/list returned an invalid page")
        items.extend(mcp_descriptor(value) for value in result["tools"])
        if len(items) > 256 or len({item.name for item in items}) != len(items):
            raise ValidationError("MCP discovery exceeded its limit or duplicated names")
        cursor = result.get("nextCursor")
        if cursor is None:
            return tuple(items)
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValidationError("MCP discovery returned an invalid/repeated cursor")
        seen.add(cursor)
    raise ValidationError("MCP discovery exceeded 32 pages")


class MCPToolSource:
    def __init__(self, transport):
        _identity(transport)
        if not is_async_callable(getattr(transport, "request", None)):
            raise ValidationError("MCP transport requires an async request method")
        self.transport = transport

    @property
    def identity(self):
        return {"kind": "mcp-tool-source", "version": "1", "transport": _identity(self.transport)}

    async def list_tools(self):
        return await list_mcp_tools(self.transport)

    async def call_tool(self, descriptor, arguments, context):
        if not isinstance(descriptor, ToolDescriptor) or not isinstance(arguments, dict):
            raise ValidationError("MCP call requires a pinned descriptor and JSON arguments")
        canonical(arguments)
        if not Draft202012Validator(descriptor.input_schema).is_valid(arguments):
            raise ValidationError("MCP arguments differ from the pinned Schema")
        result = await self.transport.request(
            "tools/call",
            {"name": descriptor.name, "arguments": copy.deepcopy(arguments)},
            expected_tool=descriptor.to_dict(),
        )
        canonical(result)
        if not isinstance(result, dict) or not isinstance(result.get("content"), list):
            raise ToolSourceError("MCP call returned an invalid content envelope")
        if type(result.get("isError", False)) is not bool or result.get("isError", False):
            raise ToolSourceError("MCP tool reported an error")
        for block in result["content"]:
            if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise ToolSourceError("MCP call returned an invalid content block")
            if block["type"] == "text" and not isinstance(block.get("text"), str):
                raise ToolSourceError("MCP text block is invalid")
        structured = result.get("structuredContent")
        if descriptor.output_schema is not None and (
            not isinstance(structured, dict)
            or not Draft202012Validator(descriptor.output_schema).is_valid(structured)
        ):
            raise ToolSourceError("MCP structured output differs from the pinned Schema")
        return copy.deepcopy(result)
