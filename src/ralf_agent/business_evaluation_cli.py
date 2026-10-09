"""Bounded real business-task evaluation; credentials stay in local environment."""

import argparse
import asyncio
import json
import os

from .business_evaluation import evaluate_business, load_business_cases
from .errors import ValidationError
from .planning_evaluation import EvaluationLimits
from .planning_evaluation_cli import _http_provider
from .types import ModelResponse, ToolCall


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--provider", choices=["openai", "anthropic", "gemini"])
    source.add_argument("--offline", action="store_true")
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--model")
    model.add_argument("--model-env")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--base-url")
    endpoint.add_argument("--base-url-env")
    parser.add_argument("--key-env")
    parser.add_argument("--cases")
    parser.add_argument(
        "--receipt-gate",
        action="store_true",
        help="Require an approved apply_fix receipt before accepting resolved",
    )
    parser.add_argument("--max-cases", type=int, default=8)
    parser.add_argument("--max-calls", type=int, default=32)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--evidence-dir")
    parser.add_argument("--report")
    return parser.parse_args(argv)


class _OfflineBusinessProvider:
    """Deterministic evidence rules for regression, never live model quality."""

    identity = {"kind": "offline-business-fixture", "version": "1"}

    async def complete(self, messages, tools):
        task = messages[1]["content"]
        empty = {"ticket_id": None, "cause": None, "fix": None}
        if any(word in task.lower() for word in ("delete all", "destructive", "bypass")):
            return ModelResponse(output={"status": "refused", **empty})
        import re

        target = re.search(r"INC-[A-Z]+", task)
        if target is None:
            return ModelResponse(output={"status": "needs_input", **empty})
        evidence = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not evidence:
            return ModelResponse(tool_calls=[ToolCall("inspect_ticket", {"ticket_id": target[0]})])
        facts = evidence[0].get("facts")
        if not facts:
            return ModelResponse(output={"status": "needs_input", **empty})
        if facts.get("disk_free_percent") == 0:
            cause, fix = "disk_full", "rotate_logs"
        elif facts.get("error_started_after_deploy") and facts.get("previous_version_healthy"):
            cause, fix = "bad_deployment", "rollback"
        elif facts.get("active_connections", 0) >= facts.get("pool_limit", 10**9):
            cause, fix = "connection_pool_exhausted", "expand_pool"
        else:
            return ModelResponse(output={"status": "needs_input", **empty})
        if len(evidence) < 2:
            return ModelResponse(
                tool_calls=[ToolCall("apply_fix", {"ticket_id": target[0], "fix": fix})]
            )
        return ModelResponse(
            output={"status": "resolved", "ticket_id": target[0], "cause": cause, "fix": fix}
        )

    async def aclose(self):
        pass


async def run(args):
    limits = EvaluationLimits(
        max_cases=args.max_cases,
        max_calls=args.max_calls,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout,
        repeats=args.repeats,
        max_cost_usd=args.max_cost_usd,
    )
    provider, reason = None, None
    if args.offline:
        provider = _OfflineBusinessProvider()
    if args.provider:
        provider, reason = _http_provider(args, limits)
    prices = None
    if args.input_price_per_million is not None or args.output_price_per_million is not None:
        prices = {
            "input_per_million_usd": args.input_price_per_million,
            "output_per_million_usd": args.output_price_per_million,
        }
    try:
        verifier = None
        if args.receipt_gate:
            from .completion import ToolReceiptVerifier

            verifier = ToolReceiptVerifier(
                "apply_fix",
                when={
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "resolved"}},
                },
                result_schema={
                    "type": "object",
                    "required": ["applied"],
                    "properties": {"applied": {"const": True}},
                },
                argument_bindings={"ticket_id": "/ticket_id", "fix": "/fix"},
            )
        report = await evaluate_business(
            provider,
            cases=load_business_cases(args.cases),
            limits=limits,
            evidence_dir=args.evidence_dir,
            prices=prices,
            offline=args.offline,
            completion_verifier=verifier,
        )
        if reason:
            report["reason"] = reason
        return report
    finally:
        if provider is not None:
            await provider.aclose()


def main(argv=None):
    args = arguments(argv)
    stream = None
    try:
        if args.report:
            stream = os.fdopen(
                os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
            )
        report = asyncio.run(run(args))
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
        if stream:
            stream.write(encoded)
            stream.flush()
        print(encoded, end="")
        if report["status"] == "not_run":
            return 2 if args.provider else 0
        return 0 if report["passed"] == report["total"] else 1
    except (ValidationError, OSError):
        print(
            json.dumps(
                {"status": "not_run", "reason": "configuration_invalid", "model_quality": None}
            )
        )
        return 2
    finally:
        if stream:
            stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
