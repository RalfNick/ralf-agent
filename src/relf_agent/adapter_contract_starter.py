"""Generate an editable external adapter, not a package-reference import."""

import inspect
import json

from . import adapter_contract_reference
from .recommended import recommended_profile

_RUNTIME = '''"""Application-owned component registration and explicit source seeding."""
import json
from pathlib import Path
from weakref import WeakKeyDictionary

from relf_agent import (
    AgentSpec, ComponentRegistry, DynamicWorkflowSpec, ProfiledEngine,
    KnowledgeContext, Runtime, RuntimeBuilder, Scope, TeamSpec, load_catalog,
)
from relf_agent.errors import ValidationError
from .adapter import (
    ReferenceKnowledgeSource, ReferenceReader, ReferenceSQLiteRetriever,
    register_reference_components,
)


def source_path():
    return Path(".ralf/knowledge.sqlite").resolve()


def seed():
    source = ReferenceKnowledgeSource(source_path())
    try:
        if source.read(Scope(), "manuals"):
            return {"seeded": 0}
        source.put(Scope(), "manuals", "cache", "cache timeout inspect connection pool",
                   source_uri="reference://manuals/cache", metadata={"category": "runbook"})
        return {"seeded": 1}
    finally:
        # Source management is separate from runtime ownership observations.
        source.close()


def components(*, asynchronous=False, owned=True):
    source = ReferenceKnowledgeSource(source_path())
    try:
        registry = ComponentRegistry()
        register_reference_components(registry, source, asynchronous=asynchronous, owned=owned)
        return source, registry
    except BaseException:
        source.close()
        raise


def create_engine(db_path):
    # ProfiledEngine observations need no knowledge client. Creation happens
    # only during original BuildContext assembly, with explicit ownership.
    sources = WeakKeyDictionary()
    registry = ComponentRegistry()

    def owned_source(context):
        if context not in sources:
            source = ReferenceKnowledgeSource(source_path())
            try:
                sources[context] = context.own(source)
            except BaseException:
                source.close()
                raise
        return sources[context]

    def provider_config(config):
        if config:
            raise ValidationError("Reference reader accepts no config")

    def knowledge_config(config):
        namespace = config.get("namespace", "manuals")
        if set(config) - {"namespace"} or not isinstance(namespace, str) or not namespace.strip():
            raise ValidationError("Reference knowledge requires only namespace")

    registry.register("provider", "external-reference-reader",
        lambda config, context: ReferenceReader(owned_source(context)), validator=provider_config)
    registry.register("knowledge", "external-reference",
        lambda config, context: KnowledgeContext(ReferenceSQLiteRetriever(owned_source(context)),
            namespace=config.get("namespace", "manuals")), validator=knowledge_config)
    return ProfiledEngine(load_catalog("runtime.toml"), db_path,
        builder=RuntimeBuilder(registry, base_dir=Path.cwd()))


def definition(kind):
    agent = AgentSpec("reader", "Answer using original source references and include their identities")
    if kind == "rag":
        return AgentSpec("rag-reader", "Retrieve runbooks, answer from them and cite original sources")
    if kind == "plan":
        return DynamicWorkflowSpec("reference-plan", {"research": agent, "review": agent}, child_budget=4)
    if kind == "team":
        return TeamSpec("reference-team", {"research": agent, "review": agent}, child_budget=4)
    return agent


async def run(kind, *, format="toml", asynchronous=False, owned=True, command_id="reference-first"):
    source, registry = components(asynchronous=asynchronous, owned=owned)
    try:
        before = source.audit()
        catalog = load_catalog("runtime." + format)
        builder = RuntimeBuilder(registry, base_dir=Path.cwd())
        instance = await builder.abuild(catalog.default, ".ralf/runs.sqlite") if asynchronous else builder.build(catalog.default, ".ralf/runs.sqlite")
        async with Runtime(instance, owned=True) as runtime:
            handle = await runtime.submit(definition(kind), "cache", command_id=command_id, budget=32)
            done = await handle.wait(wait_timeout=10)
            disclosed = 0
            # Read the committed original model request, not candidate retrieval.
            for row in instance.store.conn.execute("SELECT data FROM runs"):
                record = json.loads(row[0])
                for action in record["actions"]:
                    if action["kind"] != "model":
                        continue
                    for message in action["snapshot"]:
                        content = message.get("content")
                        if isinstance(content, str) and content.startswith("Reference memory;"):
                            disclosed += sum("_knowledge" in item for item in json.loads(content.partition("\\n")[2]))
            snapshot = done.snapshot
        after = source.audit()
        return {
            "run_id": handle.ref.run_id, "state": snapshot.state, "result": snapshot.result,
            "error": snapshot.error, "references_disclosed": disclosed,
            "audit": {key: after[key] - before[key] for key in after},
            "adapter_module": "agent_app.adapter", "execution_authority": "local",
            "model_quality": None, "semantic_quality": None,
        }
    finally:
        # The host owns borrowed resources; Runtime closes only declared owned ones.
        source.close()
'''

_MAIN = """import argparse
import asyncio
import json

from .adapter import offline_knowledge_fixture
from .runtime import run, seed


async def check(evidence_dir):
    from relf_agent import AdapterContractSuite
    suite = AdapterContractSuite(role="knowledge-retriever")
    try:
        return await suite.run(offline_knowledge_fixture(), evidence_dir=evidence_dir)
    finally:
        # Retain and retry the original owner on the same creation loop.
        await suite.aclose()


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("--evidence-dir")
    execute = commands.add_parser("run")
    execute.add_argument("--kind", choices=("agent", "rag", "plan", "team"), default="agent")
    execute.add_argument("--format", choices=("json", "toml"), default="toml")
    execute.add_argument("--async", dest="asynchronous", action="store_true")
    execute.add_argument("--borrowed", action="store_true")
    execute.add_argument("--command-id", default="reference-first")
    args = parser.parse_args()
    if args.command == "seed":
        result = seed()
    elif args.command == "check":
        from relf_agent.errors import CloseIncomplete, ValidationError
        try:
            result = asyncio.run(check(args.evidence_dir)).to_dict()
        except CloseIncomplete as exc:
            result = {"status": "failed", "reason": "cleanup_incomplete",
                      "contract_report": exc.report.get("contract_report")}
        except ValidationError:
            result = {"status": "invalid", "reason": "invalid_contract_configuration"}
    else:
        result = asyncio.run(run(args.kind, format=args.format,
            asynchronous=args.asynchronous, owned=not args.borrowed, command_id=args.command_id))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if args.command == "check":
        return 0 if result["status"] in {"passed", "not_run"} else 1
    return 0 if args.command == "seed" or result["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


def adapter_contract_files():
    """Return complete external source files, editable with installed SDK only."""
    source = inspect.getsource(adapter_contract_reference)
    # Preserve the actual independent implementation, moving only SDK imports.
    for name in ("errors", "retrieval", "types", "providers", "knowledge_adapter_contract"):
        source = source.replace("from ." + name + " import", "from relf_agent." + name + " import")
    profile = recommended_profile(
        "semantic-knowledge",
        version="2",
        name="external-knowledge",
        provider={"adapter": "external-reference-reader"},
        components={
            "knowledge": {"adapter": "external-reference", "config": {"namespace": "manuals"}}
        },
    )
    catalog = {
        "schema_version": 1,
        "default": {"name": profile.name, "version": profile.version},
        "profiles": [
            {
                "name": profile.name,
                "version": profile.version,
                "providers": profile.providers,
                "components": profile.components,
            }
        ],
    }
    toml = [
        "schema_version = 1",
        "[default]",
        'name = "external-knowledge"',
        'version = "2"',
        "[[profiles]]",
        'name = "external-knowledge"',
        'version = "2"',
        "[profiles.providers.default]",
        'adapter = "external-reference-reader"',
    ]
    for role, declaration in profile.components.items():
        toml.extend(
            [
                "[profiles.components." + role + "]",
                "adapter = " + json.dumps(declaration["adapter"]),
            ]
        )
        if declaration.get("config"):
            toml.append("[profiles.components." + role + ".config]")
            toml.extend(
                key + " = " + json.dumps(value) for key, value in declaration["config"].items()
            )
    return {
        "agent_app/__init__.py": "",
        "agent_app/__main__.py": _MAIN,
        "agent_app/adapter.py": source,
        "agent_app/runtime.py": _RUNTIME,
        "runtime.json": json.dumps(catalog, indent=2) + "\n",
        "runtime.toml": "\n".join(toml) + "\n",
        ".gitignore": ".ralf/\n__pycache__/\n",
        "README.md": """# Independent adapter contract application

Install relf-agent, then run from this directory. No service, model or embedding
credentials are used. `agent_app/adapter.py` contains a genuinely independent,
editable SQLite source and structural Retriever; it does not wrap an SDK
KnowledgeStore or Retriever. Its lexical ranking is a wiring example.

```shell
python -m agent_app check
python -m agent_app seed
python -m agent_app run --kind agent --command-id agent-first
python -m agent_app run --kind rag --command-id rag-first
python -m agent_app run --kind plan --format json --async --command-id plan-first
python -m agent_app run --kind team --format toml --borrowed --command-id team-first
```

The contract runner invokes frozen cases; source/fault/audit hooks do not supply
verdicts. Missing hooks remain not_verified. A pass proves only the declared
offline contract subset, not semantic/model quality or Temporal/remote-service
certification. Use --evidence-dir with a fresh private directory to retain evidence.
The check command exits nonzero for failed/incomplete checks. Its async helper
retains the original suite and retries owned cleanup on the same event loop;
a cleanup failure never becomes a passed case when its resource later closes.

JSON and TOML select the same semantic-knowledge version2 complete replacement;
the factory is explicitly registered by application code. No unused HTTP
Embedding is required. `--async` uses register_async/abuild and owned aclose.
Default clients are owned; --borrowed keeps client ownership with the host,
which closes it after observing Runtime shutdown. Seeding is an explicit command
and is never performed during execution or recovery.

The RAG application is an Agent using the selected knowledge context. Plan and
Team use the same source and original managed child Runs, each with bounded
credits. Observations inspect original persisted model snapshots, rather than
counting candidates as disclosed references. The offline Provider copies actual
references and reports source identity; neither quality field is certified.

Keep original code/config/databases for recovery. Read a committed Run with
`relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID`.
Use the same factory to resume the original Run. A consumed model response
is adopted from original evidence; a deleted source is never automatically
reseeded. Genuine process/window evidence is reported separately from suite passes.
""",
    }
