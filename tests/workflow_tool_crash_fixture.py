import asyncio
import json
import os
import sys
from pathlib import Path

from relf_agent import (
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    ValueRef,
)

root, mode = Path(sys.argv[1]), sys.argv[2]


def handler(arguments, context):
    path = root / "business-count"
    path.write_text(str(int(path.read_text()) + 1) if path.exists() else "1")
    return arguments


class CrashEngine(LocalEngine):
    def _record_tool_observation(self, *args):
        result = super()._record_tool_observation(*args)
        if mode == "crash":
            os._exit(77)
        return result


registry = ToolRegistry()
registry.register(
    ToolSpec("business", "Write", {"type": "object"}, effect="unqueryable_write"), handler
)
with CrashEngine(SQLiteStore(root / "run.sqlite"), providers={}, tools=registry) as engine:
    spec = GraphWorkflowSpec(
        "tool", [GraphNode("write", tool="business")], output=ValueRef("write")
    )
    handle = engine.submit(spec, {"value": 3}, command_id="same")
    result = asyncio.run(engine.drive(handle.run_id))
    print(
        json.dumps(
            {
                "state": result.state,
                "result": result.result,
                "calls": int((root / "business-count").read_text()),
            }
        )
    )
