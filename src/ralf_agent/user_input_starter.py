"""Standalone offline application exercising original durable input controls."""

USER_INPUT_FILES = {
    "agent_app/__init__.py": "",
    "agent_app/runtime.py": '''"""Replace the fixture Provider while retaining fixed input policy and release."""

import json

from ralf_agent import (
    AgentSpec, ComponentRegistry, ModelResponse, RuntimeBuilder, RuntimeProfile, ToolCall,
)

SPEC = AgentSpec("assistant", "Ask which environment, then report the supplied answer.",
                 tools=("request_input",), output_schema={
                     "type": "object", "required": ["environment"],
                     "additionalProperties": False,
                     "properties": {"environment": {"type": "string"}},
                 })


class InputFixture:
    identity = {"kind": "offline-user-input-starter", "version": "1"}

    async def complete(self, messages, tools):
        replies = [item for item in messages if item["role"] == "tool"]
        if replies:
            return ModelResponse(output={"environment": json.loads(replies[-1]["content"])})
        return ModelResponse(tool_calls=(ToolCall(
            "request_input", {"prompt": "Which environment should I use?"}, call_id="environment",
        ),))


def create_engine(db_path=".ralf/runs.sqlite"):
    registry = ComponentRegistry()
    registry.register("provider", "input-fixture", lambda config, context: InputFixture())
    profile = RuntimeProfile("user-input-starter", "1", {
        "default": {"adapter": "input-fixture"},
    }, {"user_input_policies": {"adapter": "configured", "config": {
        "policies": {"environment": {}},
        "tools": {"request_input": {"policy": "environment"}},
    }}})
    return RuntimeBuilder(registry).build(profile, db_path)
''',
    "agent_app/__main__.py": '''"""Explicit submit, reply and resume; every invocation can be a new process."""

import argparse
import asyncio
import json
from dataclasses import asdict

from ralf_agent.errors import RalfError
from .runtime import SPEC, create_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--command-id", required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    reply = commands.add_parser("reply")
    reply.add_argument("run_id")
    reply.add_argument("pending_id")
    reply.add_argument("--digest", required=True)
    reply.add_argument("--value-json", required=True)
    reply.add_argument("--command-id", required=True)
    args = parser.parse_args()
    try:
        with create_engine(args.db) as engine:
            if args.command == "run":
                handle = engine.submit(SPEC, "Choose an environment", command_id=args.command_id)
                result = asyncio.run(engine.drive(handle.run_id))
            elif args.command == "reply":
                result = engine.send_input(args.run_id, args.pending_id, args.digest,
                                           json.loads(args.value_json), command_id=args.command_id)
            else:
                result = asyncio.run(engine.drive(args.run_id))
            print(json.dumps(asdict(result), ensure_ascii=False, allow_nan=False))
    except (RalfError, ValueError) as error:
        parser.exit(2, str(error) + "\\n")


main()
''',
    "README.md": """# Durable user input

The offline Provider requests an environment through the intrinsic input tool.
No model credential or network service is required. Run each command separately:

```sh
python -m agent_app run --command-id first-question
python -m agent_app reply RUN_ID PENDING_ID --digest TARGET_DIGEST --value-json '"production"' --command-id environment-answer
python -m agent_app resume RUN_ID
```

Copy the Run ID, pending ID and target digest from the first result. Repeating
the same submission returns the same question. Repeating the same answer command
returns its original receipt, including after completion. A reply changes no
Session Turn or execution budget. The submission and reply commands are durable;
the final resume advances the original Run.

The standard installed CLI also works from this directory:

```sh
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine send-input RUN_ID PENDING_ID --digest TARGET_DIGEST --value-json '"production"' --command-id environment-answer
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Replace InputFixture with a configured Provider and retain the fixed input tool
allowlist/policy. Configure a JSON reply Schema for structured input. Ordinary
business JSON with status=needs_input remains an ordinary result. This fixture
proves durable protocol execution; it is not evidence of real model quality.
""",
}
