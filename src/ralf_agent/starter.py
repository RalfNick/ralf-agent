"""Generate an editable standalone application using the installed SDK."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .errors import ValidationError


@dataclass(frozen=True)
class StarterProject:
    directory: str
    module: str
    factory: str
    files: tuple[str, ...]


_RUNTIME = '''"""Editable offline Agent: read, approve a write, then verify its receipt."""

import argparse
import asyncio
import hashlib
import inspect
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)


class ChangeService:
    """A local fixture. A production service must also deduplicate effect_key."""

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS effects "
                "(effect_key TEXT PRIMARY KEY, ticket TEXT NOT NULL, result TEXT NOT NULL)"
            )

    def apply(self, arguments, effect_key):
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
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
            connection.execute(
                "INSERT INTO effects VALUES (?,?,?)",
                (effect_key, arguments["ticket"], json.dumps(result)),
            )
            return result

    def lookup(self, effect_key):
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT result FROM effects WHERE effect_key=?", (effect_key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def verify(self, ticket):
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT result FROM effects WHERE ticket=? ORDER BY rowid DESC LIMIT 1",
                (ticket,),
            ).fetchone()
            return {
                "stage": "verification",
                "ticket": ticket,
                "verified": row is not None,
                "change_id": json.loads(row[0])["change_id"] if row else None,
            }


class OfflineProvider:
    # Replace this class with an async ModelProvider for real model decisions.
    # Update the declared version when changing this decision behavior.
    identity = {"kind": "starter-offline", "version": "1"}

    async def complete(self, messages, tools):
        ticket = json.loads(messages[1]["content"])["ticket"]
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        usage = {"input_tokens": 0, "output_tokens": 0, "source": "offline-scripted"}
        if not results:
            call = ToolCall("read_ticket", {"ticket": ticket})
        elif results[-1]["stage"] == "ticket":
            call = ToolCall("apply_change", {"ticket": ticket, "plan": "restart test cache"})
        elif results[-1]["stage"] == "change":
            call = ToolCall("verify_change", {"ticket": ticket})
        else:
            verified = results[-1]
            return ModelResponse(
                output={
                    "ticket": ticket,
                    "verified": verified["verified"],
                    "change_id": verified["change_id"],
                },
                usage=usage,
            )
        return ModelResponse(tool_calls=(call,), usage=usage)


def agent_spec():
    return AgentSpec(
        "my-oncall-agent",
        "Read the test ticket, propose a change, wait for approval, then verify its receipt.",
        ("read_ticket", "apply_change", "verify_change"),
        output_schema={
            "type": "object",
            "properties": {
                "ticket": {"type": "string"},
                "verified": {"const": True},
                "change_id": {"type": "string"},
            },
            "required": ["ticket", "verified", "change_id"],
            "additionalProperties": False,
        },
    )


def create_engine(db_path):
    """SDK and CLI reconstruct the same providers, tools and downstream identity."""
    store = SQLiteStore(db_path)
    try:
        service = ChangeService(store.path + ".business.sqlite")
        registry = ToolRegistry()
        ticket_schema = {
            "type": "object",
            "properties": {"ticket": {"type": "string", "minLength": 1}},
            "required": ["ticket"],
            "additionalProperties": False,
        }
        write_schema = {
            **ticket_schema,
            "properties": {
                **ticket_schema["properties"],
                "plan": {"type": "string", "minLength": 1},
            },
            "required": ["ticket", "plan"],
        }
        config = {
            "service": service.path,
            "service_code": hashlib.sha256(inspect.getsource(ChangeService).encode()).hexdigest(),
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

        registry.register(
            ToolSpec("read_ticket", "Read a test ticket", ticket_schema, config=config),
            read_ticket,
        )
        registry.register(
            ToolSpec(
                "apply_change",
                "Apply the explicitly approved test change",
                write_schema,
                effect="queryable_write",
                requires_approval=True,
                config=config,
            ),
            apply_change,
            reconciler=reconcile_change,
        )
        registry.register(
            ToolSpec("verify_change", "Verify the change receipt", ticket_schema, config=config),
            verify_change,
        )
        return LocalEngine(store, providers={"default": OfflineProvider()}, tools=registry)
    except BaseException:
        store.close()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--ticket", default="INC-001")
    parser.add_argument("--command-id")
    args = parser.parse_args(argv)
    with create_engine(args.db) as engine:
        handle = engine.submit(
            agent_spec(),
            {"ticket": args.ticket},
            command_id=args.command_id or f"starter:{args.ticket}",
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        print(
            json.dumps(
                {
                    "run_id": snapshot.run_id,
                    "state": snapshot.state,
                    "pending": snapshot.pending,
                    "result": snapshot.result,
                    "submission": asdict(handle.receipt),
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    return 0
'''

_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.venv/\n",
    "agent_app/__init__.py": '"""My editable Agent application."""\n',
    "agent_app/__main__.py": (
        'from .runtime import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
    ),
    "agent_app/runtime.py": _RUNTIME,
    "README.md": """# My Agent application

This starter runs offline with the installed `ralf-agent` SDK. It reads a test
ticket, waits for explicit approval, applies one local SQLite change, and verifies
the receipt. No external model or credentials are needed.

Run from this directory:

```sh
python -m agent_app --ticket INC-001
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
```

Replace `RUN_ID` with the first command's `run_id`. `inspect` shows the proposed
write arguments, pending approval, execution credits, and commands ready to copy.
Review the arguments, then choose its explicit approval or rejection command.
After approval, execute the displayed `resume` command to apply and verify the
change. You may stop and restart these processes between commands.

Run the factory commands from this directory. The CLI imports your explicitly
selected local `agent_app.runtime:create_engine` factory for approval and resume;
no repository checkout or `PYTHONPATH` setting is needed. Inspection reads saved
execution facts and uses the supplied factory name to generate command hints.

The default database is `.ralf/runs.sqlite`; both the SDK entry and CLI accept an
explicit `--db`. The default submission key is `starter:<ticket>`; rerunning the
same command returns its original Run. Use `--command-id` for a new submission.

Edit `agent_app/runtime.py` to change the Agent, Provider, tools, or business
service. Keep imports through `agent_app.runtime` so SDK and CLI share a stable
tool identity. The write service must enforce uniqueness of `effect_key` and be
able to look up its committed result. Its reconciler recovers an effect whose
confirmation was lost; it does not grant permission for a fresh write.

Changing providers, tool code, business configuration, or runtime version may
invalidate a Run's pinned release. Finish old Runs with their original code and
configuration; use a new submission key for the revised application. The SDK's
execution credits are a local budget, not a model billing estimate.
""",
}


def create_starter(destination) -> StarterProject:
    """Create the application atomically in a new or empty directory.

    A file or nonempty destination is rejected, including hidden user files.
    Templates are contained in the installed package and need no source checkout.
    """
    try:
        directory = Path(destination).expanduser().resolve()
        if directory == Path.cwd().resolve():
            raise ValidationError(
                "Starter cannot replace the current directory; run init from its parent directory"
            )
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise ValidationError("Starter destination must be a new or empty directory")
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".ralf-starter-", dir=directory.parent) as temporary:
            staging = Path(temporary)
            for name, source in _FILES.items():
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
            # Directory rename cannot replace a destination that has gained files.
            # It also publishes the complete project without partial templates.
            staging.rename(directory)
    except ValidationError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise ValidationError("Cannot create starter in the requested directory") from exc
    return StarterProject(
        str(directory), "agent_app", "agent_app.runtime:create_engine", tuple(_FILES)
    )
