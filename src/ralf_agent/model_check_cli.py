"""Explicit bounded model compatibility checks; no provider means no calls."""

import argparse
import asyncio
import json

from .deepseek_thinking import DeepSeekThinkingProvider
from .errors import RalfError, ValidationError
from .gemini_functions import GeminiFunctionProvider
from .model_compatibility import CASES, evaluate_model_compatibility
from .model_native import AnthropicProvider, GeminiProvider
from .model_protocol import ModelStreamEvent
from .model_responses import OpenAIResponsesProvider
from .planning_evaluation import EvaluationLimits
from .providers import DeepSeekChatProvider, OpenAIChatProvider
from .runtime_builder import _model
from .types import ModelResponse, ToolCall


class OfflineCompatibilityProvider:
    """Deterministic protocol fixture, never evidence of model intelligence."""

    identity = {"kind": "offline-model-compatibility", "version": "1"}

    async def complete(self, messages, tools):
        usage = {"input_tokens": 2, "output_tokens": 1}
        if tools and not any(m["role"] == "tool" for m in messages):
            return ModelResponse(
                tool_calls=(ToolCall("ralf_model_echo", {"value": "RALF_TOOL_CHECK"}, "call"),),
                usage=usage,
            )
        return ModelResponse({"ok": True}, usage=usage)

    async def stream(self, messages, tools):
        yield ModelStreamEvent("text", text='{"ok":true}')
        yield ModelStreamEvent(
            "response",
            response=ModelResponse({"ok": True}, usage={"input_tokens": 2, "output_tokens": 1}),
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--offline", action="store_true")
    choice.add_argument("--model")
    adapters = {
        "chat-completions": (OpenAIChatProvider, "OPENAI_API_KEY"),
        "openai-responses": (OpenAIResponsesProvider, "OPENAI_API_KEY"),
        "deepseek-chat": (DeepSeekChatProvider, "DEEPSEEK_API_KEY"),
        "deepseek-thinking": (DeepSeekThinkingProvider, "DEEPSEEK_API_KEY"),
        "anthropic-messages": (AnthropicProvider, "ANTHROPIC_API_KEY"),
        "gemini-content": (GeminiProvider, "GEMINI_API_KEY"),
        "gemini-functions": (GeminiFunctionProvider, "GEMINI_API_KEY"),
    }
    parser.add_argument("--adapter", choices=tuple(adapters), default="chat-completions")
    parser.add_argument("--api-key-env")
    parser.add_argument("--base-url")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"])
    args = parser.parse_args(argv)
    try:
        if args.reasoning_effort is not None and (
            args.adapter != "deepseek-thinking" or args.offline
        ):
            raise ValidationError("Reasoning effort requires explicit deepseek-thinking selection")
        limits = EvaluationLimits(
            max_cases=5,
            max_calls=args.max_calls,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout,
        )
        provider = None
        if args.offline:
            provider = OfflineCompatibilityProvider()
        elif args.model:
            cls, key_env = adapters[args.adapter]
            config = {
                "model": args.model,
                "max_output_tokens": args.max_output_tokens,
                "timeout": args.timeout,
            }
            if args.api_key_env:
                config["api_key_env"] = args.api_key_env
            if args.base_url:
                config["base_url"] = args.base_url
            if args.reasoning_effort is not None:
                config["reasoning_effort"] = args.reasoning_effort
            provider = _model(config, cls, key_env)
        report = asyncio.run(
            evaluate_model_compatibility(
                provider,
                cases=args.cases.split(","),
                limits=limits,
                evidence_dir=args.evidence_dir,
                offline=args.offline,
                model_continuation=args.adapter in {"gemini-functions", "deepseek-thinking"},
            )
        )
    except RalfError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "not_run" or report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
