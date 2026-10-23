"""Explicit reranker declarations; the original factory ledger owns HTTP clients."""

from .errors import ValidationError
from .remote_factories import _env
from .rerank_http import HTTPReranker
from .retrieval_ranking import PreserveOrderReranker, TokenOverlapReranker

_FIELDS = {
    "model",
    "base_url",
    "api_key_env",
    "anonymous",
    "timeout",
    "max_documents",
    "max_query_chars",
    "max_document_chars",
    "max_total_chars",
    "max_response_bytes",
}


def reranker_options(declaration="preserve-order"):
    if isinstance(declaration, str):
        if declaration not in {"preserve-order", "token-overlap"}:
            raise ValidationError("Unknown default reranker")
        return declaration, {}
    if (
        not isinstance(declaration, dict)
        or set(declaration) != {"type", "config"}
        or declaration["type"] != "http"
        or not isinstance(declaration["config"], dict)
    ):
        raise ValidationError("HTTP reranker declaration requires type/config")
    config = declaration["config"]
    if set(config) - _FIELDS or not {"model", "base_url"} <= set(config):
        raise ValidationError("Explicit HTTP reranker requires model/base_url and supported limits")
    if "anonymous" in config and type(config["anonymous"]) is not bool:
        raise ValidationError("Reranker anonymous must be boolean")
    if "api_key_env" in config and config.get("anonymous", False):
        raise ValidationError("Select reranker credential reference or explicit anonymous endpoint")
    key = _env(config, "api_key_env") if "api_key_env" in config else None
    if key is None and not config.get("anonymous", False):
        raise ValidationError("Declare reranker credential env or anonymous=True explicitly")
    options = {k: v for k, v in config.items() if k not in {"api_key_env", "anonymous"}}
    options["api_key"] = key
    HTTPReranker(**options)  # Finite protocol/lifecycle preflight; no client allocation.
    return "http", options


def configured_reranker(declaration="preserve-order", context=None):
    kind, options = reranker_options(declaration)
    if kind == "token-overlap":
        return TokenOverlapReranker()
    if kind == "preserve-order":
        return PreserveOrderReranker()
    value = HTTPReranker(**options)
    return value if context is None else context.own_async(value)
