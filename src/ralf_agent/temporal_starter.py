"""Explicit installed Temporal worker/client with offline RAG and managed children."""

TEMPORAL_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.env\n",
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\n\nmain()\n",
    "agent_app/runtime.py": r'''"""Explicit remote execution; defaults are offline and use no model credentials."""
import argparse
import asyncio
import json
import os
from dataclasses import asdict

from ralf_agent import (
    AgentSpec, DynamicWorkflowSpec, InMemoryKnowledgeStore, KnowledgeContext,
    LexicalRetriever, Document, ModelResponse, Scope, TeamSpec, ToolCall,
    ToolRegistry, ToolSpec, TemporalEngine, TemporalRuntime, build_temporal_worker,
)
from ralf_agent.errors import ValidationError


def scope():
    return Scope(os.environ.get("RALF_WORKSPACE","default"),os.environ.get("RALF_PRINCIPAL","local-owner"))


class OfflineProvider:
    identity={"kind":"temporal-starter-offline","version":"1"}

    async def complete(self,messages,tools):
        if messages[-1]["role"]=="tool":
            return ModelResponse(output={"reviewed":json.loads(messages[-1]["content"])})
        try:value=json.loads(messages[1]["content"])
        except ValueError:value=messages[1]["content"]
        request=value
        while isinstance(request,dict) and "task" in request:request=request["task"]
        if isinstance(request,dict) and request.get("ask_approval"):
            return ModelResponse(tool_calls=[ToolCall("review",{"input":request.get("input","hello")})])
        references=[m["content"] for m in messages if "Reference memory" in m.get("content","")]
        return ModelResponse(output={"echo":value,"knowledge":references})


async def review(arguments,context):
    return {"reviewed":arguments["input"]}


def create_runtime():
    tools=ToolRegistry()
    tools.register(ToolSpec("review","Review a diagnostic input; this read-only demonstration requires approval.",
        {"type":"object","additionalProperties":False,"required":["input"],"properties":{"input":{}}},
        requires_approval=True),review)
    store=InMemoryKnowledgeStore(backend_id="temporal-starter-docs-v1")
    store.put(scope(),"guide",Document("diagnosis","Database timeout: inspect connection pool and slow queries before a change.",source_uri="starter://diagnosis"),expected_version=0)
    knowledge=KnowledgeContext(LexicalRetriever(store),namespace="guide",max_chars=4000)
    return TemporalRuntime(providers={"default":OfflineProvider()},tools=tools,knowledge=knowledge)


def definition(kind):
    agent=AgentSpec("answer","Answer the provided input",("review",))
    if kind=="agent":return agent
    members={"first":agent,"second":AgentSpec("second","Review the first result")}
    if kind=="dag":return DynamicWorkflowSpec("dag",members,plan_mode="dag",child_budget=8)
    return TeamSpec("team",members,strategy="sequential",child_budget=8)


async def run(args):
    address=args.address or os.environ.get("RALF_TEMPORAL_ADDRESS")
    if not address:raise ValidationError("Set RALF_TEMPORAL_ADDRESS or --address explicitly")
    try:from temporalio.client import Client
    except ImportError:raise ValidationError("Install relf-agent[temporal]") from None
    runtime=create_runtime()
    client=await Client.connect(address)
    release=runtime.orchestration_release
    engine=TemporalEngine(client,task_queue=args.queue,release=release,scope=scope())
    try:
        if args.command=="worker":
            async with build_temporal_worker(client,task_queue=args.queue,runtime=runtime,release=release):
                print("Registered offline Temporal worker ready",flush=True)
                await asyncio.Event().wait()
        elif args.command=="run":
            value={"input":args.input,"ask_approval":True} if args.ask_approval else args.input
            handle=await engine.submit(definition(args.kind),value,command_id=args.command_id,budget=32)
            print(json.dumps({"handle":asdict(handle),"snapshot":asdict(await engine.drive(handle.run_id))},ensure_ascii=False))
        elif args.command=="status":
            print(json.dumps(asdict(await engine.diagnostics(args.run_id)),ensure_ascii=False))
        elif args.command=="resume":
            print(json.dumps(asdict(await engine.drive(args.run_id)),ensure_ascii=False))
        elif args.command=="approve":
            receipt=await engine.approve(args.run_id,args.action,args.digest,command_id=args.command_id)
            print(json.dumps(asdict(receipt),ensure_ascii=False))
        else:
            print(json.dumps(asdict(await engine.cancel(args.run_id,command_id=args.command_id)),ensure_ascii=False))
    finally:await engine.aclose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["worker","run","status","resume","approve","cancel"])
    parser.add_argument("--address");parser.add_argument("--queue",default="ralf-dev17-starter")
    parser.add_argument("--kind",choices=["agent","dag","team"],default="dag")
    parser.add_argument("--input",default="database timeout")
    parser.add_argument("--ask-approval",action="store_true")
    parser.add_argument("--command-id",default="first");parser.add_argument("--run-id")
    parser.add_argument("--action");parser.add_argument("--digest")
    args=parser.parse_args()
    if args.command in {"status","resume","approve","cancel"} and not args.run_id:parser.error("--run-id required")
    if args.command=="approve" and (not args.action or not args.digest):parser.error("--action/--digest required")
    try:asyncio.run(run(args))
    except ValidationError as exc:parser.error(str(exc))
''',
    "README.md": """# Explicit Temporal starter

Install relf-agent[temporal] and provide an actual Temporal Service.
Set RALF_TEMPORAL_ADDRESS locally, for example to your localhost development service.
No Service, model call, worker or storage connection starts on package import.
Run from this directory in separate terminals with the same workspace/principal:

```shell
python -m agent_app worker
python -m agent_app run --kind dag --input "database timeout" --command-id first
python -m agent_app run --kind team --input hello --command-id team-first
python -m agent_app run --kind agent --ask-approval --command-id review-first
```

The default Provider is offline Echo; RAG is a fixed in-memory lexical guide per
worker. This proves execution/evidence, not semantic AI quality or shared durable KB.
Replace the declared Provider and KnowledgeContext with your registered components;
PostgreSQL/Qdrant are documented shared defaults. Keep original releases/queues for
recovery and use a fresh queue for new deployments; do not mix old unsupported workers.

Status includes actual child Run/action/digest for approval and recursive budgets.
Acceptance and execution differ; poll status/resume for distributed observations.

```shell
python -m agent_app status --run-id ROOT_RUN_ID
python -m agent_app approve --run-id ACTUAL_LEAF_RUN_ID --action ACTION_ID --digest DIGEST --command-id approve-first
python -m agent_app resume --run-id ROOT_RUN_ID
```

The reviewed default tool is read-only. Business write tools need an EffectJournal
(default PostgreSQL) and downstream idempotency/receipt evidence. Hosts own and close
remote Provider/Knowledge/journal resources after stopping workers. Namespace service
authorization and enterprise identities remain deployment responsibilities.
""",
}
