"""Explicit deterministic query declarations; custom I/O ports remain SDK-owned."""

from .errors import ValidationError
from .query_retrieval import QueryTransformRetriever
from .query_transform import AliasQueryTransform, IdentityQueryTransform
from .retrieval import KnowledgeContext, RetrievalQuery, _chunk_config, _text


def configured_query_transform(declaration=None):
    if declaration is None:
        return IdentityQueryTransform()
    if (
        type(declaration) is not dict
        or set(declaration) != {"type", "config"}
        or type(declaration["config"]) is not dict
    ):
        raise ValidationError("Query transform declaration requires type/config")
    kind, config = declaration["type"], declaration["config"]
    if kind == "identity" and not config:
        return IdentityQueryTransform()
    if (
        kind == "aliases"
        and "aliases" in config
        and not set(config) - {"aliases", "include_original"}
    ):
        return AliasQueryTransform(**config)
    raise ValidationError("Unknown query transform or unsupported declaration fields")


def transformed_retriever(retriever, declaration):
    return QueryTransformRetriever(retriever, configured_query_transform(declaration))


def register_query_knowledge(registry):
    from .runtime_builder import _completed, _fields

    def prepare(config):
        _fields(
            config,
            {"path", "namespace", "limit", "max_chars", "chunk_size", "overlap", "query_transform"},
        )
        configured_query_transform(config.get("query_transform"))
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
            transformed_retriever(base.retriever, config.get("query_transform")),
            namespace=base.namespace,
            limit=base.limit,
            max_chars=base.max_chars,
        )

    registry.register(
        "knowledge", "sqlite-lexical-query", build, validator=lambda c: prepare(c) and None
    )
