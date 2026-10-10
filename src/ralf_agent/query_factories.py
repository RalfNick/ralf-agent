"""Explicit deterministic query declarations; custom I/O ports remain SDK-owned."""

import json

from .errors import ValidationError
from .model_query import ModelQueryTransform, model_query_options
from .query_retrieval import QueryTransformRetriever
from .query_transform import AliasQueryTransform, IdentityQueryTransform
from .retrieval import KnowledgeContext, RetrievalQuery, _chunk_config, _text
from .types import canonical


def query_transform_config(declaration=None):
    if declaration is None:
        return {"type": "identity", "config": {}}
    if (
        type(declaration) is not dict
        or set(declaration) != {"type", "config"}
        or type(declaration["config"]) is not dict
    ):
        raise ValidationError("Query transform declaration requires type/config")
    kind, config = declaration["type"], declaration["config"]
    if kind == "identity" and not config:
        pass
    elif (
        kind == "aliases"
        and "aliases" in config
        and not set(config) - {"aliases", "include_original"}
    ):
        AliasQueryTransform(**config)
    elif kind == "model" and "provider" in config:
        provider = config["provider"]
        if type(provider) is not str or not provider.strip() or len(provider) > 128:
            raise ValidationError(
                "Query model requires an explicit provider alias of at most128 characters"
            )
        try:
            provider.encode("utf-8")
        except UnicodeError:
            raise ValidationError("Query provider alias requires valid Unicode scalars") from None
        model_query_options({k: v for k, v in config.items() if k != "provider"})
    else:
        raise ValidationError("Unknown query transform or unsupported declaration fields")
    return json.loads(canonical(declaration))


def configured_query_transform(declaration=None, *, context=None):
    declaration = query_transform_config(declaration)
    kind, config = declaration["type"], declaration["config"]
    if kind == "identity":
        return IdentityQueryTransform()
    if kind == "aliases":
        return AliasQueryTransform(**config)
    providers = getattr(context, "providers", {})
    if config["provider"] not in providers:
        raise ValidationError("Query model provider alias is unavailable")
    return ModelQueryTransform(
        providers[config["provider"]], **{k: v for k, v in config.items() if k != "provider"}
    )


def transformed_retriever(retriever, declaration, *, context=None):
    return QueryTransformRetriever(
        retriever, configured_query_transform(declaration, context=context)
    )


def preflight_query_providers(profile):
    """Resolve only the named built-in query paths; custom config stays opaque."""

    def check(kind, declaration):
        adapter, config = declaration["adapter"], declaration.get("config", {})
        if (kind, adapter) in {
            ("knowledge", "knowledge-resource"),
            ("memory_store", "facts-resource"),
        }:
            from .runtime_config import component_declaration

            if "backend" in config:
                check(kind, component_declaration(config["backend"]))
            return
        supported = (
            {
                "sqlite-lexical-query",
                "sqlite-hybrid",
                "sqlite-hybrid-http",
                "sqlite-hybrid-rerank-http",
                "postgres-qdrant-hybrid",
            }
            if kind == "knowledge"
            else {"semantic-recall-async"}
            if kind == "memory_store"
            else set()
        )
        if adapter not in supported or "query_transform" not in config:
            return
        value = query_transform_config(config["query_transform"])
        if value["type"] == "model" and value["config"]["provider"] not in profile.providers:
            raise ValidationError("Query model provider is missing from the Profile")

    for kind, declaration in profile.components.items():
        check(kind, declaration)
    for binding in profile.binding_components or []:
        role = {"facts": "memory_store", "knowledge": "knowledge"}.get(binding["role"])
        if role:
            check(role, binding["component"])


def register_query_knowledge(registry):
    from .runtime_builder import _completed, _fields

    def prepare(config):
        _fields(
            config,
            {"path", "namespace", "limit", "max_chars", "chunk_size", "overlap", "query_transform"},
        )
        query_transform_config(config.get("query_transform"))
        _chunk_config(config.get("chunk_size", 1000), config.get("overlap", 100))
        _text(config.get("namespace", "default"), "Query knowledge namespace")
        if "path" in config:
            _text(config["path"], "Query knowledge path")
        query = RetrievalQuery("", config.get("limit", 5), config.get("max_chars", 8000))
        if query.limit > 256 or query.max_chars > 262144:
            raise ValidationError("Query knowledge exceeds source bounds")
        return registry.prepare(
            "knowledge",
            {
                "adapter": "sqlite-lexical",
                "config": {k: v for k, v in config.items() if k != "query_transform"},
            },
        )

    def build(config, context):
        factory, options = prepare(config)
        base = _completed(factory(options, context), "Lexical knowledge")
        return KnowledgeContext(
            transformed_retriever(base.retriever, config.get("query_transform"), context=context),
            namespace=base.namespace,
            limit=base.limit,
            max_chars=base.max_chars,
        )

    registry.register(
        "knowledge", "sqlite-lexical-query", build, validator=lambda c: prepare(c) and None
    )
