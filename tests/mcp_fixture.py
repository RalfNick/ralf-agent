"""Real, offline MCP stdio peer. All effects stay in a test-owned directory."""

import json
import os
import sys
import time
from pathlib import Path

mode, directory = sys.argv[1:]
root = Path(directory)
root.mkdir(exist_ok=True)
(root / "pid").write_text(str(os.getpid()))
initialized = False
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        initialized = True
        continue
    if method == "initialize":
        if mode == "ping":
            print(json.dumps({"jsonrpc": "2.0", "id": "peer-ping", "method": "ping"}), flush=True)
            assert json.loads(sys.stdin.readline()) == {
                "jsonrpc": "2.0",
                "id": "peer-ping",
                "result": {},
            }
        if mode == "flood":
            for index in range(101):
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/progress",
                            "params": {"progress": index},
                        }
                    ),
                    flush=True,
                )
        if mode == "malformed":
            print("NOT JSON", flush=True)
            continue
        if mode == "oversized":
            print("x" * 1048577, flush=True)
            continue
        result = {
            "protocolVersion": "invalid" if mode == "version" else "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "offline", "version": "1"},
        }
    elif method == "tools/list":
        assert initialized
        schema = {
            "type": "object",
            "properties": {"value": {"type": "string" if mode == "drift" else "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        tool = {
            "name": "read",
            "description": "Read fixture",
            "inputSchema": schema,
            "outputSchema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            "annotations": {"readOnlyHint": True},
        }
        if mode == "manypages":
            page = int(message["params"].get("cursor", "0"))
            tool["name"] = "page-" + str(page)
            result = {"tools": [tool], "nextCursor": str(page + 1)}
        elif mode == "too_many_tools":
            result = {"tools": [{**tool, "name": "tool-" + str(index)} for index in range(257)]}
        elif mode == "pagination":
            if message["params"].get("cursor") == "next":
                tool["name"] = "second"
                result = {"tools": [tool]}
            else:
                result = {"tools": [tool], "nextCursor": "next"}
        elif mode == "cursor":
            result = {"tools": [tool], "nextCursor": "next"}
        else:
            result = {"tools": [tool]}
    elif method == "tools/call":
        assert initialized
        (root / "calls").write_text(
            str(int((root / "calls").read_text()) + 1) if (root / "calls").exists() else "1"
        )
        (root / "arguments.json").write_text(json.dumps(message["params"]))
        if mode == "hang":
            (root / "started").touch()
            time.sleep(20)
        if mode == "rpc_error":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": "private error"},
                    }
                ),
                flush=True,
            )
            continue
        value = message["params"]["arguments"]["value"]
        if mode == "bad_output":
            value = "wrong-type"
        result = {
            "content": [{"type": "text", "text": "result"}],
            "structuredContent": {"value": value},
            "isError": mode == "tool_error",
        }
        if mode == "environment":
            result["structuredContent"]["inherited_secret"] = "RALF_TEST_MCP_SECRET" in os.environ
            result["structuredContent"]["explicit"] = os.environ.get("EXPLICIT") == "fixture-only"
    else:
        raise AssertionError(method)
    print(
        json.dumps(
            {"jsonrpc": "2.0", "id": True if mode == "wrongid" else request_id, "result": result}
        ),
        flush=True,
    )
