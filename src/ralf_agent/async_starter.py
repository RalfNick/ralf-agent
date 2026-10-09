"""Installed async resource example; the HTTP transport stays entirely offline."""

ASYNC_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.env\n",
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\n\nmain()\n",
    "agent_app/runtime.py": '''"""Replace the offline HTTP transport/factory with your own async adapter."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

import httpx

from ralf_agent import (
    AgentSpec, ComponentRegistry, OpenAIChatProvider, RunHandle,
    RuntimeBuilder, SQLiteRunReader, load_catalog,
)
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import submission_request


def validate(config):
    if set(config) - {"label"} or not isinstance(config.get("label", "async"), str):
        raise ValidationError("Async demo accepts a string label")


async def provider_factory(config, context):
    label = config.get("label", "async")

    def respond(request):
        messages = json.loads(request.content)["messages"]
        question = next(message["content"] for message in messages if message["role"] == "user")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": label + ": " + question}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        })

    # MockTransport performs no network request; the client/pool lifetime is real.
    client = context.own_async(httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False))
    return OpenAIChatProvider(
        model="offline-" + label, api_key="offline-fixture",
        base_url="https://offline.invalid/v1", client=client,
    )


async def create_runtime(db_path, *, run_id=None):
    root = Path(__file__).resolve().parent.parent
    catalog = load_catalog(root / "runtime.toml")
    registry = ComponentRegistry()
    registry.register_async("provider", "async-demo", provider_factory, validator=validate)
    selected = catalog.default
    if run_id is not None:
        identity = SQLiteRunReader(db_path).profile_identity(run_id)
        if identity is None:
            raise DefinitionMismatch("Run has no original async runtime profile")
        selected = catalog.resolve(identity)
    return await RuntimeBuilder(registry, base_dir=root).abuild(selected, db_path)


async def execute(args):
    spec = AgentSpec("async-assistant", "Answer the user's request")
    prior = None
    if args.resume is None:
        prior = SQLiteRunReader(args.db).submit_receipt(
            args.command_id, submission_request(spec, args.input),
        )
        if prior is not None and args.submit_only:
            return asdict(RunHandle(prior.run_id, prior))
    run_id = args.resume or (None if prior is None else prior.run_id)
    async with await create_runtime(args.db, run_id=run_id) as runtime:
        if args.resume is not None:
            return asdict(await runtime.drive(args.resume))
        handle = runtime.submit(spec, args.input, command_id=args.command_id)
        return asdict(handle if args.submit_only else await runtime.drive(handle.run_id))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--input", default="hello")
    parser.add_argument("--command-id", default="first-run")
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    if args.resume is not None and args.submit_only:
        parser.error("Resume cannot be submit-only")
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, allow_nan=False))
''',
    "runtime.toml": """schema_version = 1
[default]
name = "async-assistant"
version = "1"

[[profiles]]
name = "async-assistant"
version = "1"
[profiles.providers.default]
adapter = "async-demo"
[profiles.providers.default.config]
label = "async"
""",
    "README.md": """# Async Agent starter

Run `python -m agent_app --input hello --command-id first`.
Submit without dispatch using `--submit-only`; continue with `--resume RUN_ID`.
New inputs need new command IDs. Repeated identical commands retain the original
receipt and profile; keep original declarations and adapter code for recovery.

The example uses an owned httpx.AsyncClient and an offline MockTransport. There
are no network requests or model charges; it is not an AI quality benchmark.
Replace provider_factory with your async model/client factory, keep its identity
versioned, and explicitly configure your service/credentials. Use the same loop
for creation, drive and aclose. Shutdown finishes execution before cleaning
clients; async with closes them, and failed aclose can be retried.

`create_runtime` is an async Python entry. The synchronous `ralf --factory` and
`--config` runtime route cannot construct it; use `python -m agent_app` to run or
resume. Read-only inspection still works with
`ralf --db .ralf/runs.sqlite --format text inspect RUN_ID`.
""",
}
