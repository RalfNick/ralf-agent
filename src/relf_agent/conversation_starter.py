"""An installed, offline reference application for configured Session Turns."""

_MAIN = """import argparse
import asyncio
import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from relf_agent import Runtime, RunRef, TurnAdmission, load_catalog, load_spec
from relf_agent.errors import DefinitionMismatch, RalfError, ValidationError
from relf_agent.runtime_config import read_declaration
from relf_agent.runtime_router import SQLiteRunReader
from relf_agent.types import canonical, digest


def save_reference(db, turn, profile):
    payload = {"turn": turn.to_dict(), "profile": profile}
    directory = db.parent / (db.name + ".refs")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest(turn.run.run_id) + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".reference-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(payload))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if read_declaration(path) != payload:
                raise DefinitionMismatch("Reference file conflicts with original admission")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(path)


def reference(path):
    payload = read_declaration(path)
    if not isinstance(payload, dict) or set(payload) != {"turn", "profile"}:
        raise DefinitionMismatch("Reference requires original Turn and Profile")
    return TurnAdmission.from_dict(payload["turn"]), payload["profile"]


async def execute(args):
    db = Path(args.db).resolve()
    if args.command == "status":
        # Observation has no need for model/configuration/runtime construction.
        return asdict(SQLiteRunReader(db).status(args.run_id))
    if not math.isfinite(args.wait_timeout) or args.wait_timeout < 0:
        raise ValidationError("Wait timeout must be finite nonnegative seconds")
    catalog = load_catalog(args.config)
    if args.command == "resume":
        turn, identity = reference(args.reference)
        original_identity = SQLiteRunReader(db).profile_identity(turn.run.run_id)
        if identity != original_identity:
            raise DefinitionMismatch("Reference Profile differs from original Run")
        selected = catalog.resolve(original_identity)
        async with Runtime.from_profile(selected, db) as runtime:
            session = runtime.attach_session(turn.session)
            original = await session.turns(after=turn.turn_seq - 1, limit=1)
            if original != [turn]:
                raise DefinitionMismatch("Reference differs from original Turn")
            run = await runtime.resume(turn.run)
            done = await run.wait(wait_timeout=args.wait_timeout)
            return {"state": done.snapshot.state, "result": done.snapshot.result,
                    "reference": str(Path(args.reference).resolve())}
    selected = catalog.default
    definition = load_spec(args.spec)
    async with Runtime.from_profile(selected, db) as runtime:
        agent = runtime.create_agent(definition)
        session = await agent.open_session(
            args.session_id, namespace=args.namespace,
            command_id="session-open:" + digest([args.namespace, args.session_id]),
        )
        run = await session.submit(args.input, command_id=args.command_id, budget=args.budget)
        identity = runtime.engine.diagnostics(run.ref.run_id).manifest["runtime_profile"]
        path = save_reference(db, run.turn, identity)
        done = await run.wait(wait_timeout=args.wait_timeout)
        return {"state": done.snapshot.state, "result": done.snapshot.result, "reference": path}


def main():
    parser = argparse.ArgumentParser(description="Offline durable Session example")
    parser.add_argument("--db", default=".ralf/sessions.sqlite")
    parser.add_argument("--config", default="runtime.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Submit a new or duplicate Turn")
    run.add_argument("--input", required=True)
    run.add_argument("--command-id", required=True)
    run.add_argument("--session-id", default="customer")
    run.add_argument("--namespace", default="support")
    run.add_argument("--spec", default="agent.json")
    run.add_argument("--budget", type=int, default=32)
    run.add_argument("--wait-timeout", type=float, default=10)
    resume = commands.add_parser("resume", help="Reconnect using the original reference")
    resume.add_argument("--reference", required=True)
    resume.add_argument("--wait-timeout", type=float, default=10)
    status = commands.add_parser("status", help="Observe without constructing a model")
    status.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args))
    except RalfError as error:
        print(json.dumps({"error": error.code}))
        raise SystemExit(2)
    except OSError:
        print(json.dumps({"error": "validation_error"}))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
"""

SESSIONS_FILES = {
    "session_app/__init__.py": "",
    "session_app/__main__.py": _MAIN,
    "runtime.toml": """schema_version = 1
[default]
name = "sessions"
version = "1"

[[profiles]]
name = "sessions"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "sessions-v1"
[profiles.components.conversation_resource]
adapter = "colocated-session"
[profiles.components.conversation_resource.config]
namespaces = ["support", "sales"]
default_namespace = "support"

[[profiles]]
name = "sessions"
version = "2"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "sessions-v2"
[profiles.components.conversation_resource]
adapter = "colocated-session"
[profiles.components.conversation_resource.config]
namespaces = ["support", "sales"]
default_namespace = "sales"
""",
    "agent.json": """{
  "kind": "graph", "name": "session-answer",
  "nodes": [{"id": "answer", "agent": {
    "name": "assistant", "instructions": "Answer the request"
  }}],
  "output": {"kind": "ref", "source": "answer"}
}
""",
    "README.md": """# Durable Session starter

Install `relf-agent` and run from this directory. The default Provider is offline
echo; the app makes no network/model calls and has no business write tool.

```sh
python -m session_app run --input "My order is 123" --command-id turn-1
python -m session_app run --input "Second request" --command-id turn-2
python -m session_app run --namespace sales --input "Sales request" --command-id sales-1
```

Each result includes a `reference` path. Use that exact path to reconnect:

```sh
python -m session_app resume --reference PATH_FROM_RESULT
python -m session_app status --run-id ORIGINAL_RUN_ID
```

Run IDs are in the reference JSON. `status` is read-only and works without a valid
runtime.toml; resume resolves the original Profile and validates the original Turn,
Scope and Run release. It never submits another Turn. Keep the database, reference,
original Profile and adapter code. Replaying identical input/command returns the
original result/reference; changed input with that command is rejected.

`--db`/`--config` are global flags before the command. Use absolute paths when
changing directories. References live beside the database in its `.refs` directory;
conflicting files are never overwritten. A reference is reconnect data, not the
execution journal. If it is lost, the original Run still exists in the database.

Profiles1/2 demonstrate version retention. Moving only `[default].version` to2
affects new Sessions; resume still uses1. Existing Sessions never silently upgrade:
restore their original Profile or use SDK idle CAS rebind on the same address.

Edit agent.json for your graph and register trusted custom Provider/tool factories
through RuntimeBuilder for your application. Tools, context and member Session
bindings remain independent from the root conversation namespace. The starter
records whole-turn results; offline echo does not demonstrate intelligent recall.
Remote conversation stores, Temporal Session binding and queues remain unsupported.
""",
    ".gitignore": ".ralf/\n__pycache__/\n*.sqlite*\n*.refs/\n.env\n",
}
