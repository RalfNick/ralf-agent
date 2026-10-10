"""Additive explicit hybrid declarations; resources share the assembly ledger."""

from .embedding_http import OpenAIEmbeddingProvider
from .embeddings import HashEmbeddingProvider
from .errors import ValidationError
from .remote_factories import _env
from .rerank_factories import configured_reranker, reranker_options
from .retrieval import (
    KnowledgeContext,
    LexicalRetriever,
    SQLiteKnowledgeStore,
    _chunk_config,
    _integer,
    _text,
)
from .retrieval_pipeline import HybridRetriever
from .retrieval_ranking import RRFFusion
from .vector import SQLiteVectorIndex, VectorRetriever

_COMMON = {
    "namespace",
    "limit",
    "max_chars",
    "chunk_size",
    "overlap",
    "dimensions",
    "embedding",
    "branch_limit",
    "candidate_limit",
    "max_candidate_chars",
    "failure_policy",
    "reranker",
    "fusion",
}
_HTTP = {
    "model",
    "dimensions",
    "base_url",
    "send_dimensions",
    "batch_size",
    "max_text_chars",
    "max_batch_chars",
    "max_response_bytes",
    "timeout",
    "api_key_env",
    "anonymous",
}


def embedding_options(config):
    declaration = config.get("embedding", {"type": "hash", "config": {}})
    if (
        not isinstance(declaration, dict)
        or set(declaration) != {"type", "config"}
        or not isinstance(declaration["config"], dict)
    ):
        raise ValidationError("Embedding declaration requires type/config")
    kind, values = declaration["type"], declaration["config"]
    if kind == "hash":
        if set(values) - {"dimensions"}:
            raise ValidationError("Unknown hash embedding fields")
        dims = values.get("dimensions", config.get("dimensions", 128))
        HashEmbeddingProvider(dimensions=dims)
        options = {"dimensions": dims}
    elif kind == "openai":
        if set(values) - _HTTP or "model" not in values or "dimensions" not in values:
            raise ValidationError("Explicit HTTP embedding requires model/dimensions")
        if "anonymous" in values and type(values["anonymous"]) is not bool:
            raise ValidationError("anonymous must be boolean")
        if "api_key_env" in values and values.get("anonymous", False):
            raise ValidationError("Select credential reference or explicit anonymous endpoint")
        key = _env(values, "api_key_env") if "api_key_env" in values else None
        if key is None and not values.get("anonymous", False):
            raise ValidationError("Declare embedding credential env or anonymous=True explicitly")
        options = {k: v for k, v in values.items() if k not in {"api_key_env", "anonymous"}}
        OpenAIEmbeddingProvider(api_key=key, **options)
        dims = options["dimensions"]
    else:
        raise ValidationError("Unknown embedding type")
    if "dimensions" in config and (
        type(config["dimensions"]) is not int or config["dimensions"] != dims
    ):
        raise ValidationError("Embedding and index dimensions differ")
    return kind, options


def hybrid_options(config, *, reranker=None):
    fusion = config.get("fusion", {})
    if not isinstance(fusion, dict) or set(fusion) - {"rank_constant", "weights"}:
        raise ValidationError("Unknown fusion fields")
    fusion = RRFFusion(**fusion)
    if set(fusion.identity["weights"]) - {"lexical", "vector"}:
        raise ValidationError("Fusion weights name an unregistered branch")
    reranker = (
        configured_reranker(config.get("reranker", "preserve-order"))
        if reranker is None
        else reranker
    )
    for name in ["branch_limit", "candidate_limit"]:
        _integer(config.get(name, 10 if name == "branch_limit" else 32), name, minimum=1)
    if (
        config.get("branch_limit", 10) * 2 > config.get("candidate_limit", 32)
        or config.get("candidate_limit", 32) > 256
    ):
        raise ValidationError("Hybrid branches exceed capacity")
    chars = config.get("max_candidate_chars", 64000)
    _integer(chars, "Candidate chars", minimum=2)
    if chars > 1024 * 1024 or config.get("failure_policy", "strict") not in {"strict", "degrade"}:
        raise ValidationError("Invalid hybrid policy/character bound")
    return {
        "fusion": fusion,
        "reranker": reranker,
        **{
            k: config[k]
            for k in ["branch_limit", "candidate_limit", "max_candidate_chars", "failure_policy"]
            if k in config
        },
    }


def hybrid_config(config, *, remote=False, http=False, rerank_http=False):
    allowed = _COMMON | (
        {
            "dsn_env",
            "backend_id",
            "url_env",
            "index_backend_id",
            "collection",
            "initialize",
            "timeout",
            "api_key_env",
        }
        if remote
        else {"path", "index_path"}
    )
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValidationError("Unknown hybrid knowledge configuration fields")
    _chunk_config(config.get("chunk_size", 1000), config.get("overlap", 100))
    _text(config.get("namespace", "default"), "Knowledge namespace")
    _integer(config.get("limit", 5), "Knowledge limit", minimum=1)
    _integer(config.get("max_chars", 8000), "Knowledge chars", minimum=2)
    if config.get("limit", 5) > 256 or config.get("max_chars", 8000) > 1024 * 1024:
        raise ValidationError("Knowledge output bounds exceed limits")
    kind, _ = embedding_options(config)
    if not remote and (kind == "openai") != http:
        raise ValidationError("Select explicit async HTTP or offline hash assembly")
    hybrid_options(config)
    rank_kind, _ = reranker_options(config.get("reranker", "preserve-order"))
    if rank_kind == "http" and not (remote or http or rerank_http):
        raise ValidationError("HTTP reranker requires explicit async knowledge assembly")
    if rerank_http and rank_kind != "http":
        raise ValidationError("Select HTTP reranker for sqlite-hybrid-rerank-http")
    if remote:
        for name in ["dsn_env", "url_env"]:
            _env(config, name)
        for name in ["backend_id", "index_backend_id", "collection"]:
            _text(config.get(name), name)
        if "initialize" in config and type(config["initialize"]) is not bool:
            raise ValidationError("initialize must be boolean")
        timeout = config.get("timeout", 10)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 300
        ):
            raise ValidationError("Remote timeout must be in (0,300]")
        from .qdrant import _url

        _url(_env(config, "url_env"))
        if "api_key_env" in config:
            _env(config, "api_key_env")
    else:
        for name in ["path", "index_path"]:
            if name in config:
                _text(config[name], "Knowledge path")


def _embedding(config, context):
    kind, options = embedding_options(config)
    if kind == "hash":
        return HashEmbeddingProvider(**options)
    values = config["embedding"]["config"]
    return context.own_async(
        OpenAIEmbeddingProvider(
            api_key=_env(values, "api_key_env") if "api_key_env" in values else None, **options
        )
    )


def _context(config, store, index, embedding, context):
    vector = VectorRetriever(store, index, embedding)
    retriever = HybridRetriever(
        store,
        {"lexical": LexicalRetriever(store), "vector": vector},
        **hybrid_options(
            config, reranker=configured_reranker(config.get("reranker", "preserve-order"), context)
        ),
    )
    return KnowledgeContext(
        retriever,
        namespace=config.get("namespace", "default"),
        limit=config.get("limit", 5),
        max_chars=config.get("max_chars", 8000),
    )


def sqlite_hybrid(config, context):
    store = context.own(
        SQLiteKnowledgeStore(
            context.path(config["path"])
            if "path" in config
            else context.db_path + ".knowledge.sqlite",
            chunk_size=config.get("chunk_size", 1000),
            overlap=config.get("overlap", 100),
        )
    )
    embedding = _embedding(config, context)
    index = context.own(
        SQLiteVectorIndex(
            context.path(config["index_path"])
            if "index_path" in config
            else context.db_path + ".vectors.sqlite",
            dimensions=embedding.dimensions,
        )
    )
    return _context(config, store, index, embedding, context)


async def sqlite_hybrid_http(config, context):
    return sqlite_hybrid(config, context)


async def postgres_qdrant_hybrid(config, context):
    import asyncio

    from .postgres import PostgresKnowledgeStore
    from .qdrant import QdrantVectorIndex

    async with asyncio.timeout(config.get("timeout", 10)):
        store = context.own_async(
            await PostgresKnowledgeStore.connect(
                _env(config, "dsn_env"),
                backend_id=config["backend_id"],
                chunk_size=config.get("chunk_size", 1000),
                overlap=config.get("overlap", 100),
            )
        )
        if config.get("initialize", False):
            await store.initialize()
        embedding = _embedding(config, context)
        index = context.own_async(
            QdrantVectorIndex(
                _env(config, "url_env"),
                backend_id=config["index_backend_id"],
                collection=config["collection"],
                dimensions=embedding.dimensions,
                timeout=config.get("timeout", 10),
                api_key=_env(config, "api_key_env") if "api_key_env" in config else None,
            )
        )
        await index.initialize(create=config.get("initialize", False))
        return _context(config, store, index, embedding, context)
