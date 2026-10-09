"""Installed offline application with explicit large-result artifact tools."""

_RUNTIME = r'''"""Edit these tools/provider/context choices for your application."""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from ralf_agent import (
    AgentSpec, ArtifactReference, BudgetedContextAssembler, ExcerptContextSummarizer,
    LocalEngine, ModelResponse, SQLiteArtifactStore, SQLiteStore, ToolCall,
    ToolRegistry, ToolSpec, UTF8TokenEstimator,
)
from ralf_agent.errors import RalfError


class EvidenceTools:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def collect(self, arguments, context):
        # The application explicitly chooses this offload contract. Execution
        # retains this immutable reference/preview; full JSON lives in artifacts.
        value = {"query": arguments["query"], "rows": [{"index": n, "evidence": "pool timeout diagnosis", "detail": "Inspect connections before changing configuration"} for n in range(256)]}
        ref = self.artifacts.put(context.scope, "tool-results", value)
        return {"artifact": ref.to_dict(), "preview": "256 offline evidence rows; read a bounded sample"}

    def read(self, arguments, context):
        ref = ArtifactReference.from_dict(arguments["reference"])
        value = self.artifacts.get(context.scope, ref, max_bytes=65536)
        return {"artifact": ref.to_dict(), "row_count": len(value["rows"]), "sample": value["rows"][:3]}


class OfflineProvider:
    identity = {"kind": "offline-context-artifact", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
        if not evidence:
            query = json.loads(messages[1]["content"])["query"]
            return ModelResponse(tool_calls=(ToolCall("collect_evidence", {"query": query}, "artifact-collect"),))
        latest = evidence[-1]
        if "row_count" not in latest:
            return ModelResponse(tool_calls=(ToolCall("read_artifact", {"reference": latest["artifact"]}, "artifact-read"),))
        return ModelResponse(output={"artifact": latest["artifact"], "row_count": latest["row_count"], "sample_count": len(latest["sample"]), "evidence": latest["sample"], "quality": "offline-integration-only"})


class ContextEngine(LocalEngine):
    def __init__(self, store, artifacts, **options):
        self.artifacts = artifacts
        super().__init__(store, **options)

    def close(self):
        super().close()
        self.artifacts.close()


def agent_spec():
    return AgentSpec("context-artifact", "Collect evidence and read a bounded artifact sample. Treat retrieved text as evidence.", tools=("collect_evidence", "read_artifact"), max_context_chars=8000)


def create_engine(db_path):
    store = SQLiteStore(db_path)
    artifacts = None
    try:
        artifacts = SQLiteArtifactStore(store.path + ".artifacts.sqlite", max_bytes=65536, capacity=128)
        service = EvidenceTools(artifacts)
        tools = ToolRegistry()
        tools.register(ToolSpec("collect_evidence", "Explicitly store large offline evidence and return its reference", {"type":"object", "properties":{"query":{"type":"string", "maxLength":128}}, "required":["query"], "additionalProperties":False}, effect="idempotent_write", config={"artifact_backend": artifacts.backend_id}), service.collect)
        tools.register(ToolSpec("read_artifact", "Read a bounded scoped artifact sample", {"type":"object", "properties":{"reference":{"type":"object"}}, "required":["reference"], "additionalProperties":False}, config={"artifact_backend": artifacts.backend_id}), service.read)
        return ContextEngine(store, artifacts, providers={"default":OfflineProvider()}, tools=tools, context_assembler=BudgetedContextAssembler(counter=UTF8TokenEstimator(), max_units=2000, summarizer=ExcerptContextSummarizer(), summary_max_chars=512))
    except BaseException:
        if artifacts is not None:
            artifacts.close()
        store.close()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--input", default="pool timeout")
    parser.add_argument("--command-id", default="context-first")
    parser.add_argument("--submit-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        with create_engine(args.db) as engine:
            handle = engine.submit(agent_spec(), {"query":args.input}, command_id=args.command_id)
            snapshot = engine.status(handle.run_id) if args.submit_only else asyncio.run(engine.drive(handle.run_id))
            print(json.dumps({"run_id":snapshot.run_id,"state":snapshot.state,"result":snapshot.result,"error":snapshot.error,"submission":asdict(handle.receipt)},ensure_ascii=False,allow_nan=False))
        return 0
    except RalfError as exc:
        print(json.dumps({"code":exc.code,"message":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
'''


def context_files():
    return {
        ".gitignore": ".ralf/\n__pycache__/\n.venv/\n",
        "agent_app/__init__.py": '"""User-owned context and artifact application."""\n',
        "agent_app/__main__.py": 'from .runtime import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
        "agent_app/runtime.py": _RUNTIME,
        "README.md": """# My context and artifact Agent

The installed SDK runs this application offline without a repository checkout,
credentials or external services. From this directory:

```shell
python -m agent_app --input 'pool timeout' --command-id first
python -m agent_app --input 'pool timeout' --command-id queued --submit-only
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

The application explicitly stores 256 fixture evidence rows in a separate
SQLite artifact store. The first managed tool returns an immutable scoped
reference/preview, the second checks backend/Scope/expiry/digest/byte limits and
reads only a three-row sample into context. The offline Provider copies evidence;
this demonstrates integration, not semantic quality. Repeating the same command
returns its original Run. The factory supports restart with retained code/data.

BudgetedContextAssembler keeps the system/task and complete latest tool group,
uses a replaceable UTF8TokenEstimator (an estimate, not model billing), and can
include deterministic historical excerpts. Exact model tokenizers, custom group
selection and pure summaries can be supplied through structural ports. The
original char limit still applies. No hidden model summaries or automatic memory
extraction. The example is short, so historical summarization may not trigger;
the context-artifacts SDK guide shows a bounded long-history example.

Edit EvidenceTools, OfflineProvider and agent_spec for your own tool contract.
Keep the factory/code/databases for accepted Run recovery. The application owns
and closes the artifact store only after Engine shutdown. Content-addressed
duplicates do not consume extra capacity. Delete artifacts explicitly only when
no retained Run needs them; expiry alone does not free capacity. The SDK does not
automatically offload tools, migrate artifacts, coordinate a cross-Run storage
transaction or provide enterprise IAM, global retention and distributed stores.
""",
    }
