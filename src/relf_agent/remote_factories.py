"""Explicit non-secret declarations for optional native async data clients."""

import asyncio
import os
import re

from .errors import ValidationError
from .recall import _integer, _name
from .retrieval import KnowledgeContext, LexicalRetriever, _chunk_config


def _env(config, name):
    reference = config.get(name)
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", reference):
        raise ValidationError("Remote connection declarations require environment variable names")
    value = os.environ.get(reference)
    _name(value, "Configured remote connection environment value")
    return value


def _validate(config, allowed, *, envs, identities):
    if not isinstance(config, dict) or set(config) - set(allowed):
        raise ValidationError("Unknown remote adapter configuration fields")
    for name in envs:
        _env(config, name)
    for name in identities:
        _name(config.get(name), "Stable remote backend identity")
    if "initialize" in config and type(config["initialize"]) is not bool:
        raise ValidationError("initialize must be a boolean")
    timeout = config.get("timeout", 10)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
        raise ValidationError("Remote timeout must be finite seconds in (0,300]")


def memory_config(config, *, redis=False):
    allowed = {"url_env" if redis else "dsn_env", "backend_id", "timeout"}
    allowed |= {"prefix"} if redis else {"initialize"}
    _validate(config, allowed, envs=["url_env" if redis else "dsn_env"], identities=["backend_id"])
    if redis:
        _name(config.get("prefix", "ralf"), "Redis prefix")


async def redis_memory(config, context):
    from .redis_memory import RedisMemory

    return context.own_async(
        await RedisMemory.connect(
            _env(config, "url_env"),
            backend_id=config["backend_id"],
            prefix=config.get("prefix", "ralf"),
            timeout=config.get("timeout", 10),
        )
    )


async def postgres_memory(config, context):
    from .postgres import PostgresMemory

    async with asyncio.timeout(config.get("timeout", 10)):
        backend = context.own_async(
            await PostgresMemory.connect(
                _env(config, "dsn_env"),
                backend_id=config["backend_id"],
            )
        )
        if config.get("initialize", False):
            await backend.initialize()
        return backend


def knowledge_config(config, *, vector=False):
    allowed = {
        "dsn_env",
        "backend_id",
        "chunk_size",
        "overlap",
        "namespace",
        "limit",
        "max_chars",
        "initialize",
        "timeout",
    }
    if vector:
        allowed |= {"url_env", "index_backend_id", "api_key_env", "collection", "dimensions"}
    _validate(
        config,
        allowed,
        envs=["dsn_env", *(["url_env"] if vector else [])],
        identities=["backend_id", *(["index_backend_id"] if vector else [])],
    )
    _chunk_config(config.get("chunk_size", 1000), config.get("overlap", 100))
    _name(config.get("namespace", "default"), "Knowledge namespace")
    _integer(config.get("limit", 5), "Knowledge limit", 1, 1000)
    _integer(config.get("max_chars", 8000), "Knowledge character bound", 2, 1000000)
    if vector:
        _name(config.get("collection"), "Qdrant collection")
        _integer(config.get("dimensions", 128), "Index dimensions", 1, 65536)
        if "api_key_env" in config:
            _env(config, "api_key_env")


async def postgres_knowledge(config, context, *, vector=False):
    from .postgres import PostgresKnowledgeStore

    async with asyncio.timeout(config.get("timeout", 10)):
        backend = context.own_async(
            await PostgresKnowledgeStore.connect(
                _env(config, "dsn_env"),
                backend_id=config["backend_id"],
                chunk_size=config.get("chunk_size", 1000),
                overlap=config.get("overlap", 100),
            )
        )
        if config.get("initialize", False):
            await backend.initialize()
        retriever = LexicalRetriever(backend)
        if vector:
            from .embeddings import HashEmbeddingProvider
            from .qdrant import QdrantVectorIndex
            from .vector import VectorRetriever

            index = context.own_async(
                QdrantVectorIndex(
                    _env(config, "url_env"),
                    collection=config["collection"],
                    dimensions=config.get("dimensions", 128),
                    backend_id=config["index_backend_id"],
                    api_key=_env(config, "api_key_env") if "api_key_env" in config else None,
                    timeout=config.get("timeout", 10),
                )
            )
            await index.initialize(create=config.get("initialize", False))
            retriever = VectorRetriever(
                backend, index, HashEmbeddingProvider(dimensions=index.dimensions)
            )
        return KnowledgeContext(
            retriever,
            namespace=config.get("namespace", "default"),
            limit=config.get("limit", 5),
            max_chars=config.get("max_chars", 8000),
        )
