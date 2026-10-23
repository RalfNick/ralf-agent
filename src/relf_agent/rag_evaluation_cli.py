"""Evaluate ingestion, retrieval, answers and citations through managed native Runs."""

import argparse
import os
from contextlib import AsyncExitStack

from .errors import ValidationError
from .orchestration_evaluation_cli import _common_arguments, _configuration, _main, _own_client
from .planning_evaluation_cli import _http_provider
from .rag_evaluation import OfflineRAGProvider, evaluate_rag
from .rag_evaluation_cases import load_rag_cases


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    _common_arguments(parser, max_cases=8)
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--embedding-model")
    model.add_argument("--embedding-model-env")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--embedding-base-url")
    endpoint.add_argument("--embedding-base-url-env")
    parser.add_argument(
        "--embedding-key-env",
        help="Explicit embedding credential environment variable; no generation-key fallback",
    )
    parser.add_argument("--embedding-dimensions", type=int)
    parser.add_argument(
        "--max-embedding-calls",
        type=int,
        default=128,
        help="Global single-text embedding adapter invocation cap",
    )
    parser.add_argument(
        "--typed-answers",
        action="store_true",
        help="Use explicit scalar/object JSON answer instructions for the reference tasks",
    )
    return parser.parse_args(argv)


def _embedding_provider(args, limits):
    from .embedding_http import OpenAIEmbeddingProvider

    model = (
        os.environ.get(args.embedding_model_env)
        if args.embedding_model_env
        else args.embedding_model
    )
    if not model:
        return None, "embedding_model_not_configured"
    if args.embedding_dimensions is None:
        return None, "embedding_dimensions_not_configured"
    if not args.embedding_key_env or not os.environ.get(args.embedding_key_env):
        return None, "embedding_credential_not_configured"
    base_url = (
        os.environ.get(args.embedding_base_url_env)
        if args.embedding_base_url_env
        else args.embedding_base_url
    )
    if args.embedding_base_url_env and not base_url:
        return None, "embedding_endpoint_not_configured"
    options = {
        "dimensions": args.embedding_dimensions,
        "api_key": os.environ[args.embedding_key_env],
        "timeout": limits.timeout_seconds,
        "batch_size": 1,
    }
    if base_url:
        options["base_url"] = base_url
    return OpenAIEmbeddingProvider(model, **options), None


async def run(args):
    typed_answers = getattr(args, "typed_answers", False)
    if type(typed_answers) is not bool:
        raise ValidationError("Typed answer enablement must be boolean")
    limits, prices = _configuration(args)
    if not 1 <= args.max_embedding_calls <= 100000:
        raise ValidationError("Embedding call limit must be a bounded positive integer")
    if args.embedding_dimensions is not None and not 1 <= args.embedding_dimensions <= 65536:
        raise ValidationError("Embedding dimensions must be bounded positive integer")
    cases = load_rag_cases(args.cases)
    async with AsyncExitStack() as owned:
        provider, embedding, reason = None, None, None
        if args.offline:
            provider = OfflineRAGProvider()
        elif args.provider:
            provider, reason = _http_provider(args, limits)
            if provider is not None:
                _own_client(owned, provider)
                embedding, reason = _embedding_provider(args, limits)
                if embedding is not None:
                    owned.push_async_callback(embedding.aclose)
        # Incomplete live configuration is a no-I/O not_run report. SDK clients
        # are borrowed; this CLI closes only clients it constructed itself.
        report = await evaluate_rag(
            provider if reason is None else None,
            embedding=embedding,
            cases=cases,
            limits=limits,
            evidence_dir=args.evidence_dir,
            offline=args.offline,
            prices=prices,
            max_embedding_calls=args.max_embedding_calls,
            model_continuation=args.provider
            in {"gemini-functions", "deepseek-thinking", "openai-responses-reasoning"},
            **({"typed_answers": True} if typed_answers else {}),
        )
        if reason:
            report["reason"] = reason
            report["requested_provider"] = args.provider
        return report


def main(argv=None):
    return _main(arguments(argv), run)


if __name__ == "__main__":
    raise SystemExit(main())
