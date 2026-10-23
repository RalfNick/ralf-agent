"""One ticket: Agent -> Session -> local RAG -> explicit Facts -> Workflow.

Download/copy this file beside your application; it imports only the installed
SDK and Python standard library. Offline output demonstrates wiring, not quality.
"""

import argparse
import asyncio
import json
from pathlib import Path

from relf_agent import (
    AgentSpec,
    DeepSeekChatProvider,
    LocalEngine,
    ModelResponse,
    OpenAIChatProvider,
    Runtime,
    Scope,
    SQLiteMemory,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.errors import RalfError, ValidationError
from relf_agent.memory import MemoryRecallPolicy
from relf_agent.retrieval import (
    Document,
    KnowledgeContext,
    KnowledgeVersionConflict,
    LexicalRetriever,
    SQLiteKnowledgeStore,
)


class OfflineSupportProvider:
    identity = {"kind": "offline-support-journey", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        observations = [m for m in messages if m.get("role") == "tool"]
        if not observations:
            return ModelResponse(tool_calls=[ToolCall("lookup_ticket", {"ticket_id": "INC-001"})])
        references = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content.startswith("Reference memory;"):
                references.extend(json.loads(content.partition("\n")[2]))
        return ModelResponse(
            output={
                "ticket": json.loads(observations[-1]["content"]),
                "advice": "Check cache health and connectivity; do not restart without approval.",
                "knowledge": [
                    {
                        "document_id": r["value"]["document_id"],
                        "version": r["version"],
                        "source_uri": r["value"]["source_uri"],
                    }
                    for r in references
                    if "_knowledge" in r
                ],
                "facts": {
                    r["key"]: r["value"]
                    for r in references
                    if "value" in r and "_knowledge" not in r
                },
                "session_records": sum(len(r.get("session", [])) for r in references),
            }
        )


def provider_for(args):
    if args.provider == "offline":
        return OfflineSupportProvider()
    if not args.model:
        raise ValidationError(
            "Live providers require an explicit --model and credential environment"
        )
    provider = DeepSeekChatProvider if args.provider == "deepseek-chat" else OpenAIChatProvider
    return provider(args.model, timeout=30, max_output_tokens=1024)


def tools_for():
    tools = ToolRegistry()

    @tools.tool(effect="read_only", description="Read the fixture support ticket")
    def lookup_ticket(ticket_id: str) -> dict:
        if ticket_id != "INC-001":
            raise ValidationError("This example contains only ticket INC-001")
        return {"ticket_id": ticket_id, "service": "cache", "status": "connection-error"}

    return tools


async def run(args, provider):
    directory = Path(args.data_dir)
    store = SQLiteStore(directory / (args.stage + ".sqlite"))
    scope = Scope()
    try:
        memory = SQLiteMemory(store)
        knowledge_store = (
            SQLiteKnowledgeStore(store) if args.stage in {"rag", "memory", "workflow"} else None
        )
        knowledge = (
            KnowledgeContext(LexicalRetriever(knowledge_store), namespace="runbooks")
            if knowledge_store is not None
            else None
        )
        engine = LocalEngine(
            store,
            providers={"default": provider},
            tools=tools_for(),
            scope=scope,
            session_store=memory,
            memory_store=memory,
            knowledge=knowledge,
            recall_policy=MemoryRecallPolicy(),
        )
    except BaseException:
        store.close()
        raise

    # Knowledge and memory borrow the same SQLite connection. Runtime owns Engine;
    # incomplete shutdown retains its original obligations rather than force-closing.
    async with Runtime(engine, owned=True) as runtime:
        if knowledge_store is not None:
            try:
                knowledge_store.put(
                    scope,
                    "runbooks",
                    Document(
                        "cache-recovery",
                        "Cache connection errors: check cache health and network connectivity. "
                        "Do not restart the service without approval.",
                        source_uri="local://runbooks/cache-recovery",
                    ),
                    expected_version=0,
                )
            except KnowledgeVersionConflict:
                pass  # Never overwrite existing revisions or revive deleted documents.
        if (
            args.stage in {"memory", "workflow"}
            and memory.inspect_fact(scope, "support", "response-style") is None
        ):
            memory.put_fact(scope, "support", "response-style", "concise", expected_version=0)

        instructions = (
            "Read ticket INC-001 with lookup_ticket. Use supplied evidence, cite runbooks, "
            "and respect response-style preferences. Do not modify or restart services."
        )
        definition = AgentSpec("support", instructions, ("lookup_ticket",))
        if args.stage == "workflow":
            definition = WorkflowSpec(
                "support-workflow",
                [
                    AgentSpec("triage", instructions, ("lookup_ticket",)),
                    definition,
                ],
            )
        agent = runtime.create_agent(definition)
        if args.stage != "agent":
            session = await agent.open_session("INC-001", command_id="open:INC-001")
            handle = await session.submit(args.input, command_id=args.command_id, budget=32)
        else:
            handle = await agent.submit(args.input, command_id=args.command_id, budget=32)
        observed = await handle.wait()
        return {
            "stage": args.stage,
            "run_id": handle.ref.run_id,
            "state": observed.snapshot.state,
            "result": observed.snapshot.result,
            "model_calls": provider.calls if args.provider == "offline" else None,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("agent", "session", "rag", "memory", "workflow"))
    parser.add_argument("--data-dir", default=".ralf/support-journey")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--input", default="Help resolve cache connection errors for INC-001.")
    parser.add_argument(
        "--provider", choices=("offline", "deepseek-chat", "chat-completions"), default="offline"
    )
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    try:
        provider = provider_for(args)  # Validate live configuration before creating data.
        args.data_dir = Path(args.data_dir).resolve()
        args.data_dir.mkdir(parents=True, exist_ok=True)
        result = asyncio.run(run(args, provider))
    except RalfError as error:
        print(json.dumps({"error": error.code}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
