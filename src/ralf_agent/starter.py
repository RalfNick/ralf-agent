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
    template: str = "oncall"


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


_RAG_RUNTIME = r'''"""Offline retrieval with real local documents and explicit evidence citations.

Run from this project directory with the SDK installed:
    python -m agent_app --query '缓存连接失败怎么恢复'

The provider only copies retrieved evidence. It evaluates integration behavior,
not a real model's answer quality. No external model or embedding is called.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from ralf_agent.errors import RalfError
from ralf_agent.memory import MemoryRecallPolicy
from ralf_agent.retrieval import (
    Document,
    KnowledgeContext,
    KnowledgeVersionConflict,
    LexicalRetriever,
    SQLiteKnowledgeStore,
)


SEED_DOCUMENTS = (
    Document(
        "cache-recovery",
        "缓存连接失败恢复手册：首先检查缓存服务健康状态和网络连通性；"
        "确认连接地址与凭证；修复后重新验证缓存读写。没有审批时不要执行服务重启。",
        source_uri="local://runbooks/cache-recovery",
        metadata={"language": "zh", "kind": "runbook"},
    ),
    Document(
        "postgres-recovery",
        "Postgres connection refused recovery: confirm the database host and port, "
        "check the server's health and firewall rules, then verify a read-only connection. "
        "Do not restart the service without approval.",
        source_uri="local://runbooks/postgres-recovery",
        metadata={"language": "en", "kind": "runbook"},
    ),
    Document(
        "cafeteria-hours",
        "Office cafeteria: lunch starts at noon and vegetarian options are available.",
        source_uri="local://office/cafeteria-hours",
        metadata={"language": "en", "kind": "office"},
    ),
)


def seed_documents(store, scope):
    """Initial ingest uses CAS; starting the app never rewrites user revisions."""
    for document in SEED_DOCUMENTS:
        if store.get(scope, "runbooks", document.document_id) is not None:
            continue
        try:
            store.put(scope, "runbooks", document, expected_version=0)
        except KnowledgeVersionConflict:
            # Respect all prior versions, including retired/expired documents.
            # A concurrent initializer may also have won the create-only CAS.
            pass


class EvidenceProvider:
    identity = {"kind": "offline-evidence-copy", "version": "1"}

    async def complete(self, messages, tools):
        references = []
        for message in messages:
            content = message.get("content")
            if not isinstance(content, str) or not content.startswith("Reference memory;"):
                continue
            # This fixture reads the default ContextAssembler's JSON evidence.
            for reference in json.loads(content.partition("\n")[2]):
                if isinstance(reference, dict) and "_knowledge" in reference:
                    references.append(reference)
        citations = [
            {
                "document_id": reference["value"]["document_id"],
                "source_uri": reference["value"]["source_uri"],
                "version": reference["version"],
                "excerpt": reference["value"]["text"],
            }
            for reference in references
        ]
        return ModelResponse(
            output={
                "grounded": bool(citations),
                "answer": "\n\n".join(citation["excerpt"] for citation in citations)
                if citations
                else "No supporting evidence found / 没有找到相关证据，无法回答。",
                "citations": citations,
            },
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-evidence-copy"},
        )


def agent_spec():
    return AgentSpec(
        "knowledge-agent",
        "Use only the provided knowledge evidence. Cite document ID, version and source URI. "
        "If no evidence supports the question, say that no supporting evidence was found.",
        output_schema={
            "type": "object",
            "properties": {
                "grounded": {"type": "boolean"},
                "answer": {"type": "string", "minLength": 1},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document_id": {"type": "string", "minLength": 1},
                            "source_uri": {"type": "string", "minLength": 1},
                            "version": {"type": "integer", "minimum": 1},
                            "excerpt": {"type": "string", "minLength": 1},
                        },
                        "required": ["document_id", "source_uri", "version", "excerpt"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["grounded", "answer", "citations"],
            "additionalProperties": False,
            "allOf": [
                {
                    "if": {"properties": {"grounded": {"const": True}}},
                    "then": {"properties": {"citations": {"minItems": 1}}},
                    "else": {"properties": {"citations": {"maxItems": 0}}},
                }
            ],
        },
    )


class KnowledgeEngine(LocalEngine):
    """This application owns its injected knowledge connection."""

    def __init__(self, store, knowledge_store, **options):
        self.knowledge_store = knowledge_store
        super().__init__(store, **options)

    def close(self):
        # Refusing to close active operations also keeps their knowledge alive.
        super().close()
        self.knowledge_store.close()


def create_engine(db_path):
    store = SQLiteStore(db_path)
    knowledge_store = None
    try:
        # Anchor to the canonical execution path, not the current working directory.
        knowledge_store = SQLiteKnowledgeStore(store.path + ".knowledge.sqlite")
        scope = Scope()
        seed_documents(knowledge_store, scope)
        return KnowledgeEngine(
            store,
            knowledge_store,
            providers={"default": EvidenceProvider()},
            tools=ToolRegistry(),
            scope=scope,
            recall_policy=MemoryRecallPolicy(),
            knowledge=KnowledgeContext(LexicalRetriever(knowledge_store), namespace="runbooks"),
        )
    except BaseException:
        if knowledge_store is not None:
            knowledge_store.close()
        store.close()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--query", default="缓存连接失败怎么恢复")
    parser.add_argument("--command-id")
    parser.add_argument("--submit-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        with create_engine(args.db) as engine:
            handle = engine.submit(
                agent_spec(),
                {"query": args.query},
                command_id=args.command_id
                or "knowledge:" + hashlib.sha256(args.query.encode()).hexdigest()[:20],
            )
            snapshot = (
                engine.status(handle.run_id)
                if args.submit_only
                else asyncio.run(engine.drive(handle.run_id))
            )
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
    except RalfError as exc:
        print(json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

'''

_RAG_FILES = {
    **_FILES,
    "agent_app/runtime.py": _RAG_RUNTIME,
    "README.md": """# My knowledge Agent

This application uses the installed `ralf-agent` SDK, a local SQLite knowledge
database, and real lexical retrieval. Its offline Provider copies retrieved
evidence and cites document ID, version and source URI. It refuses to answer
without evidence. No model, embedding service, credentials or repository checkout
is needed.

Run from this directory:

```sh
python -m agent_app --query '缓存连接失败怎么恢复'
python -m agent_app --query 'postgres connection refused'
python -m agent_app --query 'quantum entanglement teleportation'
```

The first two questions retrieve the corresponding local runbooks; the last one
has no supporting document. `grounded=false` and an empty `citations` list make
that refusal explicit. This fixture verifies retrieval and citation plumbing;
it does not measure real AI answer quality. Source URIs such as
`local://runbooks/cache-recovery` identify the fixture documents stored in SQLite,
not files fetched from another service.

To submit and resume in separate processes:

```sh
python -m agent_app --query '缓存连接失败怎么恢复' --submit-only
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Use the printed `run_id` for `RUN_ID`. These tools only read knowledge and produce
a response; there is no business write requiring approval. Run factory commands
from this directory, where the explicitly selected local module is importable.
If you run from another directory, install your application as a package or
explicitly configure its import path, and use the same absolute database path.

The default execution database is `.ralf/runs.sqlite`. The knowledge database is
the canonical execution path plus `.knowledge.sqlite`, so passing an absolute
`--db` keeps it stable across working directories. The three fixture documents
are created once with create-only CAS; starting the factory does not overwrite
your revised documents or restore deleted/expired documents. Edit `SEED_DOCUMENTS`,
or explicitly ingest new document
versions through `SQLiteKnowledgeStore.put(..., expected_version=...)`.
Existing document IDs keep their stored versions until you update them yourself.

`MemoryRecallPolicy()` bounds memory candidate scans and returned context.
`LexicalRetriever` matches terms; it is not semantic retrieval. For vector
retrieval, inject an embedding provider and a `VectorRetriever` configured for
your corpus. The local vector implementation performs a local linear scan;
it is not a production vector search service.

Edit `agent_app/runtime.py` to replace the Provider, documents, retrieval policy
or Agent schema. A real `OpenAIChatProvider` can be supplied through the same
SDK interface; doing so may call a paid service. No real-model baseline or
embedding billing integration is supplied by this starter. Scope isolation here
trusts application code and is not enterprise authentication or ACL enforcement.
Changing runtime configuration may invalidate an existing Run's pinned release;
resume old Runs with their original factory and configuration.
""",
}


_CONFIG_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n",
    "agent_app/__init__.py": "",
    "agent_app/runtime.py": '''"""Stable factory; runtime declarations are in runtime.toml."""
from pathlib import Path
from ralf_agent import ProfiledEngine, load_catalog


def create_engine(db_path):
    catalog = load_catalog(Path(__file__).resolve().parents[1] / "runtime.toml")
    return ProfiledEngine(catalog, db_path)
''',
    "agent_app/__main__.py": '''"""Offline configuration example using the installed CLI."""
import argparse
from pathlib import Path
from ralf_agent.cli import main

parser = argparse.ArgumentParser()
parser.add_argument("--db", default=".ralf/runs.sqlite")
parser.add_argument("--input", default="hello")
parser.add_argument("--command-id", default="config-demo")
parser.add_argument("--submit-only", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
command = ["--db", args.db, "--config", str(root / "runtime.toml"), "run",
           "--spec", str(root / "agent.toml"), "--input", args.input, "--command-id", args.command_id]
if args.submit_only:
    command.append("--submit-only")
raise SystemExit(main(command))
''',
    "runtime.toml": """schema_version = 1
[default]
name = "assistant"
version = "1"

[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "config-v1"

[[profiles]]
name = "assistant"
version = "2"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "config-v2"
""",
    "agent.toml": """kind = "agent"
name = "configured-assistant"
instructions = "Answer the supplied task."
""",
    "README.md": """# Configured Agent

This editable project uses the installed SDK and an explicit offline echo
Provider. It tests configuration and recovery, without calling a model service.

```sh
python -m agent_app --input hello
ralf --config runtime.toml run --spec agent.toml --input question --command-id new
```

Edit `runtime.toml` to select version 2 under `[default]`. Keep both historical
profile entries. New submissions use the new default; queued version 1 Runs
continue with version 1. Do not edit an accepted profile version in place.

```sh
python -m agent_app --input pending --command-id pending --submit-only
ralf --config runtime.toml resume RUN_ID
```

Replace RUN_ID with the submitted ID. Cross-directory commands need the same
absolute --db and --config paths. JSON/TOML does not import plugins: register
custom factories explicitly in Python and return ProfiledEngine from that
trusted factory. Inline Chat Provider keys are rejected; `api_key_env` names an
environment variable. Installing this template does not prove real model quality.
""",
}


_MODEL_FILES = {
    **_CONFIG_FILES,
    "agent_app/__main__.py": _CONFIG_FILES["agent_app/__main__.py"]
    .replace("Offline configuration example", "Explicit model configuration example")
    .replace('default="config-demo"', 'default="model-demo"'),
    "runtime.toml": """schema_version = 1
[default]
name = "model-assistant"
version = "1"

[[profiles]]
name = "model-assistant"
version = "1"
[profiles.providers.default]
adapter = "chat-completions"
[profiles.providers.default.config]
model = "YOUR_MODEL"
base_url = "https://api.openai.com/v1"
api_key_env = "RALF_MODEL_API_KEY"
max_output_tokens = 1024
""",
    "README.md": """# Model Agent

Edit runtime.toml: replace YOUR_MODEL with a model available to your account,
select its protocol/base_url, and name its credential environment variable.
chat-completions uses max_completion_tokens by default; compatible services may
need token_parameter="max_tokens". deepseek-chat explicitly disables thinking.
anthropic-messages supports text/client function tools; gemini-content supports
text only and refuses tool declarations/history.

Supply the credential through your own environment or secret manager; never
put it in TOML. Invoking the configured service may incur fees.

```sh
python -m agent_app --input hello --command-id first-task
ralf --config runtime.toml resume RUN_ID
```

The generated application uses the installed SDK without repository imports.
It does not verify model quality or account availability. Before adopting a new
configuration, register a new profile version and keep the original declaration,
adapter code and data for accepted Runs. Use a new command ID for a new task.
""",
}


def create_starter(destination, *, template="oncall") -> StarterProject:
    """Create the application atomically in a new or empty directory.

    A file or nonempty destination is rejected, including hidden user files.
    Templates are contained in the installed package and need no source checkout.
    """
    if template not in ("oncall", "rag", "config", "model"):
        raise ValidationError("Starter template must be oncall, rag, config or model")
    files = {"oncall": _FILES, "rag": _RAG_FILES, "config": _CONFIG_FILES, "model": _MODEL_FILES}[
        template
    ]
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
            for name, source in files.items():
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
        str(directory), "agent_app", "agent_app.runtime:create_engine", tuple(files), template
    )
