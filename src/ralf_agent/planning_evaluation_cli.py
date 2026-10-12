"""Explicit HTTP model configuration and an offline fixture evaluation command."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from .errors import ProviderError, ValidationError
from .planning_evaluation import EvaluationLimits, evaluate_planning, load_planning_cases
from .types import ModelResponse, digest


class _FixtureProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self._identity = {
            "kind": "scripted-planning-fixture",
            "version": "1",
            "fixture_sha256": digest(responses),
        }

    @property
    def identity(self):
        return self._identity

    async def complete(self, messages, tools):
        try:
            value = next(self.responses)
        except StopIteration as exc:
            raise ProviderError("Offline fixture is exhausted") from exc
        if value.get("error"):
            raise ProviderError("Explicit offline failure fixture")
        return ModelResponse(output=value["output"], usage=value.get("usage"))


def _fixture(path, cases, repeats):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        responses = document["responses"]
        if (
            document.get("version") != "1"
            or set(document) != {"version", "responses"}
            or not isinstance(responses, list)
            or not responses
        ):
            raise ValueError("Invalid fixture")
        by_id = {case["id"]: case for case in cases}
        seen, selected, repeated = set(), [], []
        for response in responses:
            if (
                not isinstance(response, dict)
                or set(response) - {"case_id", "output", "usage", "error"}
                or "case_id" not in response
                or ("output" not in response and "error" not in response)
            ):
                raise ValueError("Invalid response fixture")
            id = response["case_id"]
            if id in seen or id not in by_id:
                raise ValueError("Unknown or duplicate fixture case")
            seen.add(id)
            selected.append(by_id[id])
            repeated.extend([response] * repeats)
        return _FixtureProvider(repeated), selected
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValidationError("Planning fixture document is invalid") from exc


def _arguments(argv):
    parser = argparse.ArgumentParser(
        description="Evaluate proposed DAG semantics through a managed ModelDAGPlanner child. No worker actions are executed."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--provider",
        choices=["openai", "anthropic", "gemini", "gemini-functions", "deepseek-thinking"],
    )
    mode.add_argument(
        "--fixture", help="Explicit offline response fixture JSON; never reported as model quality"
    )
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--model")
    model.add_argument("--model-env", help="Environment variable containing the model name")
    url = parser.add_mutually_exclusive_group()
    url.add_argument("--base-url")
    url.add_argument("--base-url-env", help="Environment variable containing the HTTP endpoint")
    parser.add_argument(
        "--key-env",
        help="Environment variable containing a local API key; values are never printed",
    )
    parser.add_argument(
        "--cases",
        help="Version 1 planning case JSON; default suite is frozen in the installed package",
    )
    parser.add_argument("--max-cases", type=int, default=20)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=60, help="Seconds per request")
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        help="A hard currency cap fails closed without guaranteed provider input/billing bounds",
    )
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--report", help="Write JSON to a new report file, also printed to stdout")
    parser.add_argument(
        "--evidence-dir",
        help="Fresh directory retaining private SQLite managed Run records and raw rejected model proposals",
    )
    return parser.parse_args(argv)


def _validate_reasoning_effort(args):
    if args.reasoning_effort is not None and args.provider != "deepseek-thinking":
        raise ValidationError("Reasoning effort requires explicit deepseek-thinking selection")


def _http_provider(args, limits):
    from .deepseek_thinking import DeepSeekThinkingProvider
    from .gemini_functions import GeminiFunctionProvider
    from .model_native import AnthropicProvider, GeminiProvider
    from .providers import OpenAIChatProvider

    _validate_reasoning_effort(args)
    model = os.environ.get(args.model_env) if args.model_env else args.model
    if not model:
        return None, "model_not_configured"
    default_key = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "gemini-functions": "GEMINI_API_KEY",
        "deepseek-thinking": "DEEPSEEK_API_KEY",
    }[args.provider]
    key = os.environ.get(args.key_env or default_key)
    if not key:
        return None, "credential_not_configured"
    base_url = os.environ.get(args.base_url_env) if args.base_url_env else args.base_url
    if args.base_url_env and not base_url:
        return None, "endpoint_not_configured"
    options = {
        "api_key": key,
        "max_output_tokens": limits.max_output_tokens,
        "timeout": limits.timeout_seconds,
    }
    if base_url:
        options["base_url"] = base_url
    if args.reasoning_effort is not None:
        options["reasoning_effort"] = args.reasoning_effort
    cls = {
        "openai": OpenAIChatProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "gemini-functions": GeminiFunctionProvider,
        "deepseek-thinking": DeepSeekThinkingProvider,
    }[args.provider]
    return cls(model, **options), None


async def _run(args):
    _validate_reasoning_effort(args)
    limits = EvaluationLimits(
        max_cases=args.max_cases,
        max_calls=args.max_calls,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout,
        repeats=args.repeats,
        max_cost_usd=args.max_cost_usd,
    )
    cases = load_planning_cases(args.cases)
    prices = None
    if args.input_price_per_million is not None or args.output_price_per_million is not None:
        if args.input_price_per_million is None or args.output_price_per_million is None:
            raise ValidationError("Supply both input and output prices")
        prices = {
            "input_per_million_usd": args.input_price_per_million,
            "output_per_million_usd": args.output_price_per_million,
        }
    provider, reason = None, None
    if args.fixture:
        provider, cases = _fixture(args.fixture, cases, limits.repeats)
    elif args.provider:
        provider, reason = _http_provider(args, limits)
    report = await evaluate_planning(
        provider,
        cases=cases,
        limits=limits,
        prices=prices,
        evidence_dir=args.evidence_dir,
        offline=bool(args.fixture),
        model_continuation=args.provider in {"gemini-functions", "deepseek-thinking"},
    )
    if reason:
        report["reason"] = reason
        report["requested_provider"] = args.provider
    return report


def main(argv=None):
    args = _arguments(argv)
    destination, report = None, None
    try:
        if args.report:
            # Preflight before dispatching any model request, while preserving
            # prior reports through exclusive creation and private permissions.
            descriptor = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            destination = os.fdopen(descriptor, "w", encoding="utf-8")
        report = asyncio.run(_run(args))
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
        if destination:
            destination.write(encoded)
            destination.flush()
        print(encoded, end="")
        if report["status"] == "not_run":
            return 2 if args.provider or args.fixture else 0
        return 0 if report["passed"] == report["total"] else 1
    except (ValidationError, OSError):
        # External exception bodies, environment values and task text are never
        # echoed when a request or output destination cannot be configured.
        if report is not None:
            report["report_write_error"] = True
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "status": "not_run",
                        "scope": "model-planning-quality",
                        "reason": "invalid_configuration",
                        "calls": 0,
                        "model_quality": None,
                    }
                )
            )
        return 2
    finally:
        if destination:
            destination.close()


if __name__ == "__main__":
    raise SystemExit(main())
