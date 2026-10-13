"""Evaluate complete managed Plan or Team tasks with explicit model configuration."""

import argparse
import asyncio
import json
import os
from contextlib import AsyncExitStack

from .errors import ProviderError, ValidationError
from .orchestration_evaluation import (
    OfflineOrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from .planning_evaluation import EvaluationLimits, _prices
from .planning_evaluation_cli import (
    _http_provider,
    _reasoning_arguments,
    _validate_reasoning_effort,
)


def _common_arguments(parser, *, max_cases):
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--provider",
        choices=[
            "openai",
            "anthropic",
            "gemini",
            "gemini-functions",
            "deepseek-thinking",
            "openai-responses-reasoning",
        ],
    )
    source.add_argument(
        "--offline", action="store_true", help="Offline regression, never model quality"
    )
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--model")
    model.add_argument("--model-env", help="Environment variable containing the generation model")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--base-url")
    endpoint.add_argument("--base-url-env")
    parser.add_argument("--key-env", help="Environment variable containing the generation API key")
    parser.add_argument(
        "--cases", help="Version 1 case JSON; the installed default suite is frozen"
    )
    parser.add_argument("--max-cases", type=int, default=max_cases)
    parser.add_argument(
        "--max-calls", type=int, default=64, help="Global generation call cap across all repeats"
    )
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=60, help="Seconds per adapter invocation")
    _reasoning_arguments(parser)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        help="Fails closed when a hard currency cap cannot be guaranteed",
    )
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--evidence-dir", help="Fresh directory for private managed Run evidence")
    parser.add_argument(
        "--report", help="Exclusive new private JSON report; also printed to stdout"
    )


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    _common_arguments(parser, max_cases=5)
    parser.add_argument("--kind", choices=["plan-and-execute", "team"], default="plan-and-execute")
    parser.add_argument(
        "--completion-gate",
        action="store_true",
        help="Require declared inventory receipts before parent success",
    )
    parser.add_argument(
        "--member-verification",
        action="store_true",
        help="Require inventory member receipts with --completion-gate; bounded retry feedback",
    )
    return parser.parse_args(argv)


def _configuration(args):
    _validate_reasoning_effort(args)
    limits = EvaluationLimits(
        max_cases=args.max_cases,
        max_calls=args.max_calls,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout,
        repeats=args.repeats,
        max_cost_usd=args.max_cost_usd,
    )
    prices = None
    if args.input_price_per_million is not None or args.output_price_per_million is not None:
        prices = _prices(
            {
                "input_per_million_usd": args.input_price_per_million,
                "output_per_million_usd": args.output_price_per_million,
            }
        )
    return limits, prices


def _own_client(owned, component):
    # Native HTTPModelProvider owns a temporary client per request and closes
    # it in its request context. Persistent adapters expose explicit aclose.
    close = getattr(component, "aclose", None)
    if close is not None:
        if not callable(close):
            raise ValidationError("Evaluation client close method must be callable")
        owned.push_async_callback(close)


async def run(args):
    if type(args.completion_gate) is not bool:
        raise ValidationError("Parent completion gate enablement must be boolean")
    member_verification = getattr(args, "member_verification", False)
    if type(member_verification) is not bool or member_verification and not args.completion_gate:
        raise ValidationError("Member verification requires a boolean and the parent gate")
    limits, prices = _configuration(args)
    cases = load_orchestration_cases(args.cases)
    async with AsyncExitStack() as owned:
        provider, reason = None, None
        if args.offline:
            provider = OfflineOrchestrationProvider()
        elif args.provider:
            provider, reason = _http_provider(args, limits)
            if provider is not None:
                _own_client(owned, provider)
        report = await evaluate_orchestration(
            provider,
            kind=args.kind,
            cases=cases,
            limits=limits,
            evidence_dir=args.evidence_dir,
            offline=args.offline,
            prices=prices,
            model_continuation=args.provider
            in {"gemini-functions", "deepseek-thinking", "openai-responses-reasoning"},
            completion_gate=args.completion_gate,
            **({"member_verification": True} if member_verification else {}),
        )
        if reason:
            report["reason"] = reason
            report["requested_provider"] = args.provider
        return report


def _main(args, runner):
    destination, report = None, None
    try:
        if args.report:
            descriptor = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                destination = os.fdopen(descriptor, "w", encoding="utf-8")
            except BaseException:
                os.close(descriptor)
                raise
        report = asyncio.run(runner(args))
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
        if destination:
            destination.write(encoded)
            destination.flush()
        print(encoded, end="")
        if report["status"] == "not_run":
            return 2 if args.provider or args.offline else 0
        return 0 if report["passed"] == report["total"] else 1
    except (ValidationError, ProviderError, OSError):
        # Never echo private provider exceptions, URLs, credentials or task data.
        if report is None:
            report = {
                "status": "not_run",
                "reason": "configuration_invalid",
                "calls": 0,
                "model_quality": None,
            }
        else:
            report["report_write_error"] = True
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
        if destination:
            try:
                destination.write(encoded)
                destination.flush()
            except OSError:
                pass
        print(encoded, end="")
        return 2
    finally:
        if destination:
            destination.close()


def main(argv=None):
    return _main(arguments(argv), run)


if __name__ == "__main__":
    raise SystemExit(main())
