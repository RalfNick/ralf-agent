"""Generate one installed-SDK editable ModelProvider business application."""

import inspect
import json

from . import model_adapter_contract_reference

_RUNTIME = '''"""Explicit seed, provider-only replacements and original Local recovery."""
import json
from pathlib import Path

from relf_agent import (
    AgentSpec, ComponentRegistry, DynamicWorkflowSpec, ProfiledEngine, Runtime,
    RuntimeBuilder, RuntimeProfile, TeamSpec, load_catalog,
)
from .adapter import ReferenceModelSource, register_model_reference_components


class ApplicationCleanup:
    """Retain the original runtime, instance and supplier on their owning loop."""

    def __init__(self, *, owned):
        self.owned = owned
        self.runtime = self.instance = self.source = None

    def retain(self, error):
        error.application_cleanup = self
        error.add_note("Retain application_cleanup and retry its aclose on the original loop")

    async def aclose(self, *, close_timeout=None):
        try:
            if self.runtime is not None:
                await self.runtime.aclose(close_timeout=close_timeout)
            elif self.instance is not None:
                await self.instance.aclose()
            if not self.owned and self.source is not None:
                self.source.close()
        except BaseException as error:
            self.retain(error)
            raise


def source_path():
    return Path(".ralf/business.sqlite").resolve()


def seed():
    source = ReferenceModelSource(source_path())
    try:
        return {"seeded": source.seed()}
    finally:
        source.close()


def components(*, source=None, asynchronous=False, owned=True):
    registry = ComponentRegistry()
    register_model_reference_components(registry, source, asynchronous=asynchronous, owned=owned)
    return registry


def sdk_profile(kind="agent", provider="primary"):
    # These same explicit SDK declarations are also serialized in JSON and TOML.
    business = {"path": ".ralf/business.sqlite"}
    declared = {
        "tools": {"adapter": "incident-tools", "config": business},
        "context_assembler": {"adapter": "default"},
        "verifier": {"adapter": "incident-receipts"},
        "planners": {"adapter": "incident-rule"},
        "plan_verifiers": {"adapter": "complete"},
        "team_strategies": {"adapter": "defaults"},
        "parent_completion_policies": {"adapter": "incident-members"},
    }
    if kind != "agent":
        declared["knowledge"] = {"adapter": "incident-current-source", "config": business}
    adapter = "external-sqlite-model" + ("-alternate" if provider == "alternate" else "")
    return RuntimeProfile("external-model-" + kind + "-" + provider, "1",
        {"default": {"adapter": adapter, "config": business}}, declared)


def create_engine(db_path):
    # ProfiledEngine read/inspect never assembles or opens the business supplier.
    return ProfiledEngine(load_catalog("runtime.toml"), db_path,
        builder=RuntimeBuilder(components(), base_dir=Path.cwd()))


def definition(kind="agent", *, plan_mode="dag"):
    reader = AgentSpec("incident-reader", "Use actual lookup receipts and disclosed runbook sources",
        tools=("lookup_incident",), max_decisions=4)
    reviewer = AgentSpec("incident-reviewer", "Read current incident and review original supplied member results",
        tools=("lookup_incident",), max_decisions=4)
    if kind == "plan":
        return DynamicWorkflowSpec("incident-plan", {"research": reader, "review": reviewer},
            child_budget=8, max_steps=2, max_revisions=1, plan_mode=plan_mode,
            completion_policy="business")
    if kind == "team":
        return TeamSpec("incident-team", {"research": reader, "supervisor": reviewer},
            strategy="supervisor", strategy_config={"supervisor": "supervisor"},
            child_budget=8, completion_policy="business")
    return reader


def evidence(instance, run_id):
    # Follow original owned child links, not cumulative supplier audit or candidates.
    pending, records = [run_id], []
    while pending:
        record = instance.store.run(pending.pop())
        records.append(record)
        pending.extend(child["run_id"] for child in record.get("orchestration", {}).get("children", []))
    disclosed = tools = 0
    for record in records:
        for action in record["actions"]:
            if action["kind"] == "tool" and action.get("receipt"):
                tools += 1
            if action["kind"] == "model":
                for message in action.get("snapshot", []):
                    content = message.get("content")
                    if isinstance(content, str) and content.startswith("Reference memory;"):
                        disclosed += sum("_knowledge" in item for item in json.loads(content.partition("\\n")[2]))
    stages = [stage for record in records for stage in record.get("parent_completion_stages", {}).values()]
    return {"references_disclosed": disclosed, "tool_receipts": tools,
        "member_receipts": len(records) - 1,
        "parent_verdicts": [stage["adopted_verdict"] for stage in stages]}


async def run(kind="agent", *, format="toml", provider="primary", asynchronous=False,
              owned=True, command_id="model-first", plan_mode="dag"):
    source = None
    cleanup = ApplicationCleanup(owned=owned)
    try:
        if not owned:
            source = ReferenceModelSource(source_path())
            cleanup.source = source
        registry = components(source=source, asynchronous=asynchronous, owned=owned)
        if format == "sdk":
            profile = sdk_profile(kind, provider)
        else:
            catalog = load_catalog("runtime." + format)
            catalog.set_default("external-model-" + kind + "-" + provider, "1")
            profile = catalog.default
        builder = RuntimeBuilder(registry, base_dir=Path.cwd())
        instance = await builder.abuild(profile, ".ralf/runs.sqlite") if asynchronous else builder.build(profile, ".ralf/runs.sqlite")
        cleanup.instance = instance
        source = instance.providers["default"].source
        cleanup.source = source
        before = source.audit()
        runtime = Runtime(instance, owned=True)
        cleanup.runtime = runtime
        async with runtime:
            handle = await runtime.submit(definition(kind, plan_mode=plan_mode),
                {"incident": "cache", "task": "Investigate cache timeout"},
                command_id=command_id, budget=40)
            done = await handle.wait(wait_timeout=10, terminal_only=True)
            snapshot = done.snapshot
            actual = evidence(instance, handle.ref.run_id)
        after = source.audit()
        return {"run_id": handle.ref.run_id, "state": snapshot.state,
            "result": snapshot.result, "error": snapshot.error, **actual,
            "audit": {key: after[key] - before[key] for key in after},
            "provider": provider, "profile": profile.identity,
            "adapter_module": "agent_app.adapter", "execution_authority": "local",
            "model_quality": None, "semantic_quality": None}
    except BaseException as error:
        cleanup.retain(error)
        raise
    finally:
        # Active/incomplete shutdown retains the actual source and original owner.
        # Owned suppliers close only through the original RuntimeInstance.
        if cleanup.runtime is None or cleanup.runtime.state == "closed":
            await cleanup.aclose()
'''

_MAIN = """import argparse
import asyncio
import json

from .adapter import offline_model_fixture
from .runtime import run, seed


async def check(evidence_dir, profile):
    from relf_agent import AdapterContractSuite
    from relf_agent.errors import CloseIncomplete

    suite = AdapterContractSuite(role="model-provider", contract_version="1", profile=profile)
    try:
        return await suite.run(offline_model_fixture(), evidence_dir=evidence_dir)
    finally:
        try:
            await suite.aclose()
        except CloseIncomplete:
            await suite.aclose()
            raise


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    checks = commands.add_parser("check")
    checks.add_argument("--profile", choices=("core", "tools"), default="core")
    checks.add_argument("--evidence-dir")
    execute = commands.add_parser("run")
    execute.add_argument("--kind", choices=("agent", "rag", "plan", "team"), default="agent")
    execute.add_argument("--format", choices=("sdk", "json", "toml"), default="toml")
    execute.add_argument("--provider", choices=("primary", "alternate"), default="primary")
    execute.add_argument("--plan-mode", choices=("flat", "dag"), default="dag")
    execute.add_argument("--async", dest="asynchronous", action="store_true")
    execute.add_argument("--borrowed", action="store_true")
    execute.add_argument("--command-id", default="model-first")
    args = parser.parse_args()
    if args.command == "seed":
        result = seed()
    elif args.command == "check":
        from relf_agent.errors import CloseIncomplete, ValidationError
        try:
            result = asyncio.run(check(args.evidence_dir, args.profile)).to_dict()
        except CloseIncomplete as exc:
            result = {"status": "failed", "reason": "cleanup_incomplete",
                "contract_report": exc.report.get("contract_report")}
        except ValidationError:
            result = {"status": "invalid", "reason": "invalid_contract_configuration"}
    else:
        result = asyncio.run(run(args.kind, format=args.format, provider=args.provider,
            asynchronous=args.asynchronous, owned=not args.borrowed,
            command_id=args.command_id, plan_mode=args.plan_mode))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if args.command == "check":
        return 0 if result["status"] in {"passed", "not_run"} else 1
    return 0 if args.command == "seed" or result["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""

_README = """# Independent ModelProvider business application

Install the SDK and run these commands from this directory. The complete editable
`agent_app/adapter.py` implements an independent async ModelProvider and SQLite
supplier, current runbook Retriever, business tools and bounded receipt verifiers.
The offline supplier consumes real messages/descriptors. Its request/response audit
never deduplicates model calls or dispatches, adopts or settles original Runs.

```shell
python -m agent_app check
python -m agent_app check --profile tools
python -m agent_app seed
python -m agent_app run --kind agent --format sdk --command-id agent-first
python -m agent_app run --kind rag --format json --provider alternate --command-id rag-first
python -m agent_app run --kind plan --format toml --async --command-id dag-first
python -m agent_app run --kind plan --plan-mode flat --command-id rule-first
python -m agent_app run --kind team --borrowed --provider alternate --command-id team-first
```

All modes use the same business source and original Run database. Seed is explicit
and idempotent; execution and recovery never seed. Unseeded execution fails because
no actual incident record exists. RAG uses current-source retrieval and discloses
references in actual model snapshots. Agent completion checks the actual committed
lookup receipt. Plan uses existing RulePlanner/RuleDAGPlanner orchestration; it does
not demonstrate intelligent planning. Supervisor Team and Plan additionally verify
original member results and receipts consumed by each final member model Action.

`--provider alternate` replaces only the provider declaration for the same mode,
preserving business components/data. SDK, JSON and TOML declare the same profiles.
Factories validate before allocation and open owned suppliers inside BuildContext.
`--async` uses register_async/abuild/own_async. `--borrowed` leaves cleanup with the
host after original Runtime shutdown. SQLite pins its durable UUID and physical
file identity. Raw supplier debug data stays private; public checks contain only
the fixed bounded counts, booleans and digests.

Incomplete shutdown or cancellation preserves the original error and attaches
`application_cleanup`, retaining the actual runtime, instance and source. Keep
that owner on the original loop and retry its `aclose(close_timeout=30)` after the
supplier can finish. Owned resources close through the original RuntimeInstance;
borrowed suppliers stay open until that original runtime drains. Source-close
errors remain observable and retain the same retry owner.

Keep original application code, profiles and databases for recovery:

```shell
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Factory construction and read-only inspection never open or seed business data.
A committed received model response is adopted without another provider call.
A lost supplier response stays unknown with its original held reservation on
inspection. An explicit resume is a new original model Attempt with another call
and reservation; it preserves the prior unknown evidence and hold. Equal prompts
or supplier audit records cannot establish safe exactly-once redispatch. Approved
business effects use actual effect receipts, independent of supplier observations.

These offline wiring/replacement checks leave model/task quality, remote services,
Temporal History, routing, streaming/native continuation, full R25/H3/M1/R26 and
independent adoption unverified. No credentials are discovered or model/service
calls made. Use a fresh private evidence directory. Failed cleanup retains the
original suite owner and retries on its original loop; failure remains reported.
"""


def _declaration(kind, provider):
    business = {"path": ".ralf/business.sqlite"}
    components = {
        "tools": {"adapter": "incident-tools", "config": business},
        "context_assembler": {"adapter": "default"},
        "verifier": {"adapter": "incident-receipts"},
        "planners": {"adapter": "incident-rule"},
        "plan_verifiers": {"adapter": "complete"},
        "team_strategies": {"adapter": "defaults"},
        "parent_completion_policies": {"adapter": "incident-members"},
    }
    if kind != "agent":
        components["knowledge"] = {"adapter": "incident-current-source", "config": business}
    adapter = "external-sqlite-model" + ("-alternate" if provider == "alternate" else "")
    return {
        "name": "external-model-" + kind + "-" + provider,
        "version": "1",
        "providers": {"default": {"adapter": adapter, "config": business}},
        "components": components,
    }


def model_contract_files():
    """Return full independent application source; no data or service allocation."""
    source = inspect.getsource(model_adapter_contract_reference)
    for name in (
        "errors",
        "types",
        "model_adapter_contract",
        "completion",
        "parent_completion",
        "retrieval",
        "tools",
        "dag_planning",
        "planning",
    ):
        source = source.replace("from ." + name + " import", "from relf_agent." + name + " import")
    profiles = [
        _declaration(kind, provider)
        for kind in ("agent", "rag", "plan", "team")
        for provider in ("primary", "alternate")
    ]
    catalog = {
        "schema_version": 1,
        "default": {"name": "external-model-agent-primary", "version": "1"},
        "profiles": profiles,
    }
    toml = [
        "schema_version = 1",
        "[default]",
        'name = "external-model-agent-primary"',
        'version = "1"',
    ]
    for profile in profiles:
        toml.extend(["[[profiles]]", "name = " + json.dumps(profile["name"]), 'version = "1"'])
        for section in ("providers", "components"):
            for role, declaration in profile[section].items():
                toml.extend(
                    [
                        "[profiles." + section + "." + role + "]",
                        "adapter = " + json.dumps(declaration["adapter"]),
                    ]
                )
                if declaration.get("config"):
                    toml.append("[profiles." + section + "." + role + ".config]")
                    toml.extend(
                        key + " = " + json.dumps(value)
                        for key, value in declaration["config"].items()
                    )
    return {
        "agent_app/__init__.py": "",
        "agent_app/adapter.py": source,
        "agent_app/runtime.py": _RUNTIME,
        "agent_app/__main__.py": _MAIN,
        "runtime.json": json.dumps(catalog, indent=2) + "\n",
        "runtime.toml": "\n".join(toml) + "\n",
        ".gitignore": ".ralf/\n__pycache__/\n",
        "README.md": _README,
    }
