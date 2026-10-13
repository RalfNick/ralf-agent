"""A runnable, offline inventory reference using the original Local runtime.

The pure receipt gate is always selected. Optional model verification uses a
separate provider alias and an original, budgeted verifier child Run. Default
providers are protocol fixtures, so even a successful run makes no model-quality
claim. Runtime credits are abstract accounting units, not US dollars.

Borrowed providers are never closed by this module; their caller owns clients.
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from .engine import LocalEngine
from .errors import ValidationError
from .orchestration_types import DynamicWorkflowSpec, TeamSpec
from .parent_completion import ParentCompletionPolicy
from .parent_completion_rules import InventoryParentCompletionGate
from .parent_verification_stage import ModelParentVerificationStage
from .storage import SQLiteStore
from .tools import ToolRegistry, ToolSpec
from .types import AgentSpec, ModelResponse, ToolCall, canonical

_DATASET_JSON = '{"id":"warehouse-a","inventory":[{"sku":"wire","units_available":40,"unit_price_cents":425},{"sku":"bolts","units_available":80,"unit_price_cents":120}]}'
_REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dataset_id", "target", "quantity"],
    "properties": {
        "dataset_id": {"type": "string", "minLength": 1},
        "target": {"type": ["string", "null"], "minLength": 1},
        "quantity": {"type": ["integer", "null"], "minimum": 1, "maximum": 100000},
    },
}
_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "total"],
    "properties": {
        "status": {"enum": ["completed", "needs_input", "not_found"]},
        "total": {"type": ["integer", "null"], "minimum": 0},
    },
}
_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["request", "lookup"],
    "properties": {"request": _REQUEST_SCHEMA, "lookup": {"type": ["object", "null"]}},
}


class OfflineInventoryProvider:
    """Protocol fixture reads only the input and actual returned tool messages."""

    identity = {"kind": "offline-inventory-reference", "version": "1"}

    async def complete(self, messages, tools):
        incoming = json.loads(messages[1]["content"])
        names = {tool["function"]["name"] for tool in tools}
        receipts = [
            json.loads(message["content"]) for message in messages if message["role"] == "tool"
        ]
        if names == {"inventory_lookup"}:
            request = incoming["task"] if "task" in incoming else incoming
            if request["target"] is None or request["quantity"] is None:
                response = ModelResponse({"request": request, "lookup": None})
            elif not receipts:
                response = ModelResponse(
                    tool_calls=(
                        ToolCall(
                            "inventory_lookup",
                            {"dataset_id": request["dataset_id"], "target": request["target"]},
                        ),
                    )
                )
            else:
                response = ModelResponse({"request": request, "lookup": receipts[-1]})
        elif names == {"calculator"}:
            evidence = incoming["results"]["researcher"] if "results" in incoming else incoming
            request, lookup = evidence["request"], evidence["lookup"]
            if (
                lookup is None
                or lookup["found"]
                and request["quantity"] > lookup["item"]["units_available"]
            ):
                response = ModelResponse({"status": "needs_input", "total": None})
            elif not lookup["found"]:
                response = ModelResponse({"status": "not_found", "total": None})
            elif not receipts:
                response = ModelResponse(
                    tool_calls=(
                        ToolCall(
                            "calculator",
                            {
                                "quantity": request["quantity"],
                                "unit_price_cents": lookup["item"]["unit_price_cents"],
                            },
                        ),
                    )
                )
            else:
                response = ModelResponse({"status": "completed", "total": receipts[-1]["total"]})
        else:
            raise ValidationError("Offline inventory provider requires its declared business tools")
        return ModelResponse(
            response.output,
            response.tool_calls,
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-fixture"},
        )


class OfflineParentReviewer:
    """An explicit independent stage fixture; this is not a model-quality score."""

    identity = {"kind": "offline-parent-reviewer-reference", "version": "1"}

    async def complete(self, messages, tools):
        if tools:
            raise ValidationError("Parent reviewer is tool-free")
        source = json.loads(messages[1]["content"])
        ids = [item["id"] for item in [*source["children"], *source["receipts"]]]
        return ModelResponse(
            {"status": "accept", "feedback": None, "evidence_ids": ids},
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-fixture"},
        )


def _tools(dataset):
    registry = ToolRegistry()

    def lookup(arguments, context):
        item = (
            next(
                (item for item in dataset["inventory"] if item["sku"] == arguments["target"]), None
            )
            if arguments["dataset_id"] == dataset["id"]
            else None
        )
        return {
            "found": item is not None,
            "dataset_id": arguments["dataset_id"],
            "target": arguments["target"],
            "item": item,
        }

    registry.register(
        ToolSpec(
            "inventory_lookup",
            "Read a fixed inventory item; unknown SKUs return found=false.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["dataset_id", "target"],
                "properties": {
                    "dataset_id": {"type": "string", "minLength": 1},
                    "target": {"type": "string", "minLength": 1},
                },
            },
            effect="read_only",
        ),
        lookup,
    )
    registry.register(
        ToolSpec(
            "calculator",
            "Multiply quantity by the actual inventory price in integer cents.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["quantity", "unit_price_cents"],
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 100000},
                    "unit_price_cents": {"type": "integer", "minimum": 0, "maximum": 100000000},
                },
            },
            effect="read_only",
        ),
        lambda arguments, context: {"total": arguments["quantity"] * arguments["unit_price_cents"]},
    )
    return registry


def _definition(kind):
    members = {
        "researcher": AgentSpec(
            "researcher",
            "Read the structured dataset_id,target,quantity request (for Team: task). If target or quantity is null, return {request,lookup:null} without tools. Otherwise use inventory_lookup with the exact dataset_id and target. Consume the actual tool result and return {request,lookup}; never invent facts or calculate.",
            tools=("inventory_lookup",),
            max_decisions=2,
            output_schema=_EVIDENCE_SCHEMA,
        ),
        "writer": AgentSpec(
            "writer",
            "Consume researcher evidence (for Team: results.researcher). Missing input or insufficient stock requires needs_input,total:null; a negative lookup requires not_found,total:null. Otherwise call calculator with the exact original quantity and lookup unit_price_cents. Consume its receipt and return completed with its integer total. Stop on missing input, unknown SKU or insufficient stock; do not call calculator then.",
            tools=("calculator",),
            max_decisions=2,
            output_schema=_OUTPUT_SCHEMA,
        ),
    }
    if kind == "team":
        return TeamSpec(
            "inventory-reference-team",
            members,
            strategy="supervisor",
            strategy_config={"supervisor": "writer"},
            completion_policy="inventory",
            child_budget=4,
            max_concurrency=1,
        )
    return DynamicWorkflowSpec(
        "inventory-reference-plan",
        members,
        plan_mode="dag",
        completion_policy="inventory",
        child_budget=4,
        max_concurrency=1,
        max_revisions=1,
        max_steps=4,
    )


def _report(engine, handle, snapshot, *, business_offline, verification_offline):
    parent = engine.store.run(handle.run_id)
    journal = parent.get("parent_completion_stages", {}).get("r0", {})
    children = []
    for call in parent["orchestration"]["children"]:
        run = engine.store.run(call["run_id"])
        children.append(
            {
                "key": call["id"],
                "role": call.get("role", "worker"),
                "member": call["member"],
                "run_id": call["run_id"],
                "state": run["state"],
                "provider": run["definition"]["steps"][0]["provider"],
            }
        )
    report = {
        "state": snapshot.state,
        "result": snapshot.result,
        "parent_id": handle.run_id,
        "receipts": journal.get("source", {}).get("receipts", []),
        "gate_verdict": journal.get("gate_verdict"),
        "adopted_verdict": journal.get("adopted_verdict"),
        "source_digest": journal.get("source_digest"),
        "children": children,
        "budget": {"unit": "credits", "is_usd": False, **engine.diagnostics(handle.run_id).budget},
        "model_quality": None,
        "offline": {
            "business": business_offline,
            "verification": verification_offline,
            "all": business_offline and verification_offline,
        },
    }
    # Projection is fully detached before its owned database/directory closes.
    return json.loads(canonical(report))


def _temporary_directory():
    # An explicit directory avoids tempfile's first-use TMPDIR/TEMP env lookup.
    temporary_root = tempfile.tempdir or ("/tmp" if Path("/tmp").is_dir() else Path.cwd())
    return tempfile.TemporaryDirectory(prefix="ralf-parent-completion-", dir=temporary_root)


async def run_reference(
    kind="plan",
    *,
    task=None,
    model_verification=False,
    db_path=None,
    business_provider=None,
    verification_provider=None,
):
    """Run one receipt-gated inventory task, borrowing optional provider clients.

    task is the structured {dataset_id,target,quantity} object; null target or
    quantity demonstrates a valid needs_input stop. The default is three wire
    units from warehouse-a. Evidence is returned after owned storage closes.
    """
    if (
        type(kind) is not str
        or kind not in {"plan", "team"}
        or type(model_verification) is not bool
    ):
        raise ValidationError("Reference requires kind plan/team and boolean model_verification")
    from jsonschema import Draft202012Validator

    incoming = (
        {"dataset_id": "warehouse-a", "target": "wire", "quantity": 3}
        if task is None
        else json.loads(canonical(task))
    )
    if not Draft202012Validator(_REQUEST_SCHEMA).is_valid(incoming):
        raise ValidationError("Reference task requires structured dataset_id,target,quantity")
    business_offline = business_provider is None
    verification_offline = verification_provider is None or not model_verification
    providers = {
        "default": OfflineInventoryProvider() if business_provider is None else business_provider
    }
    if model_verification:
        providers["reviewer"] = (
            OfflineParentReviewer() if verification_provider is None else verification_provider
        )
    dataset = json.loads(_DATASET_JSON)
    policy = ParentCompletionPolicy(
        InventoryParentCompletionGate(dataset=dataset),
        model_stage=ModelParentVerificationStage(provider="reviewer")
        if model_verification
        else None,
    )

    async def execute(path):
        store = SQLiteStore(path)
        try:
            engine = LocalEngine(
                store,
                providers=providers,
                tools=_tools(dataset),
                parent_completion_policies={"inventory": policy},
            )
        except BaseException:
            store.close()
            raise
        with engine:
            handle = engine.submit(
                _definition(kind), incoming, command_id="inventory-reference", budget=12
            )
            snapshot = await engine.drive(handle.run_id)
            return _report(
                engine,
                handle,
                snapshot,
                business_offline=business_offline,
                verification_offline=verification_offline,
            )

    if db_path is not None:
        return await execute(Path(db_path))
    with _temporary_directory() as directory:
        return await execute(Path(directory) / "reference.sqlite")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run an offline receipt-gated inventory Plan or Team. Credits are not USD."
    )
    parser.add_argument("--kind", choices=("plan", "team"), default="plan")
    parser.add_argument("--model-verification", action="store_true")
    parser.add_argument("--db-path")
    parser.add_argument(
        "--task", help="Structured dataset_id,target,quantity JSON; defaults to three wire units."
    )
    args = parser.parse_args(argv)
    try:
        task = None if args.task is None else json.loads(args.task)
        report = asyncio.run(
            run_reference(
                args.kind,
                task=task,
                model_verification=args.model_verification,
                db_path=args.db_path,
            )
        )
    except (ValidationError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
