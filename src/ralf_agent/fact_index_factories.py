"""Explicit indexed Facts composition with independently replaceable data roles."""

from .embeddings import HashEmbeddingProvider
from .errors import ValidationError
from .fact_index import IndexedMemoryStore
from .fact_index_ports import FactIndexCatalog
from .knowledge_factories import embedding_options
from .memory import InMemoryMemory, SQLiteMemory
from .ports import is_async_callable
from .recall import _integer, _name
from .runtime_config import component_declaration
from .semantic_embedding import ManagedEmbeddingProvider
from .vector import InMemoryVectorIndex, SQLiteVectorIndex


def register_fact_index(registry):
    from .runtime_builder import _completed, _fields

    def vector_options(config):
        _fields(config, {"path", "backend_id", "dimensions"})
        _integer(config.get("dimensions"), "Fact vector dimensions", 1, 32768)
        for name in ("path", "backend_id"):
            if name in config:
                _name(config[name], "Fact vector " + name)

    def vector(config, context):
        return context.own(
            SQLiteVectorIndex(
                context.path(config["path"])
                if "path" in config
                else context.db_path + ".fact-vectors.sqlite",
                dimensions=config["dimensions"],
                **({"backend_id": config["backend_id"]} if "backend_id" in config else {}),
            )
        )

    registry.register("vector_index", "sqlite", vector, validator=vector_options)
    registry.register(
        "vector_index",
        "in-memory",
        lambda c, ctx: ctx.own(InMemoryVectorIndex(**c)),
        validator=lambda c: (
            (_fields(c, {"backend_id", "dimensions"}) or vector_options(c)) and None
        ),
    )

    def qdrant_options(config):
        from .qdrant import _timeout, _url
        from .remote_factories import _env, _validate

        _validate(
            config,
            {
                "url_env",
                "api_key_env",
                "backend_id",
                "collection",
                "dimensions",
                "timeout",
                "initialize",
            },
            envs=["url_env", *(["api_key_env"] if "api_key_env" in config else [])],
            identities=["backend_id"],
        )
        _url(_env(config, "url_env"))
        _timeout(config.get("timeout", 10))
        _name(config.get("collection"), "Fact vector collection")
        _integer(config.get("dimensions"), "Fact vector dimensions", 1, 32768)

    async def qdrant(config, context):
        from .qdrant import QdrantVectorIndex
        from .remote_factories import _env

        index = context.own_async(
            QdrantVectorIndex(
                _env(config, "url_env"),
                collection=config["collection"],
                dimensions=config["dimensions"],
                backend_id=config["backend_id"],
                timeout=config.get("timeout", 10),
                api_key=_env(config, "api_key_env") if "api_key_env" in config else None,
            )
        )
        await index.initialize(create=config.get("initialize", False))
        return index

    registry.register_async("vector_index", "qdrant", qdrant, validator=qdrant_options)

    def hash_options(config):
        _fields(config, {"dimensions"})
        _integer(config.get("dimensions", 128), "Fact embedding dimensions", 1, 32768)

    registry.register(
        "embedding_provider",
        "hash",
        lambda c, ctx: HashEmbeddingProvider(**c),
        validator=hash_options,
    )

    def http_options(config):
        kind, options = embedding_options({"embedding": {"type": "openai", "config": config}})
        _integer(options["dimensions"], "Fact embedding dimensions", 1, 32768)
        return options

    registry.register(
        "embedding_provider",
        "http",
        lambda c, ctx: ctx.own_async(ManagedEmbeddingProvider(**http_options(c))),
        validator=lambda c: http_options(c) and None,
    )

    def memory_options(declaration):
        declaration = component_declaration(declaration)
        if declaration["adapter"] in {
            "indexed-recall-async",
            "semantic-recall-async",
            "facts-resource",
            "session-resource",
        }:
            raise ValidationError("Fact index requires an original writable data backend")
        if declaration["adapter"] == "sqlite":
            _fields(declaration["config"], {"path"})
            if "path" in declaration["config"]:
                _name(declaration["config"]["path"], "Fact source path")
        if declaration["adapter"] == "in-memory":
            _fields(declaration["config"], {"backend_id"})
            InMemoryMemory(**declaration["config"])
        return registry.prepare("memory_store", declaration)

    async def create(prepared, context):
        factory, options = prepared
        result = (
            await factory(options, context)
            if is_async_callable(factory)
            else factory(options, context)
        )
        return _completed(result, "Fact index component factory")

    def catalog_options(config):
        _fields(config, {"backend", "namespace_prefix"})
        if "namespace_prefix" in config:
            prefix = config["namespace_prefix"]
            _name(prefix, "Index metadata prefix")
            if len(prefix) > 64:
                raise ValidationError("Index metadata prefix exceeds 64 characters")
        if "backend" in config:
            memory_options(config["backend"])

    async def catalog(config, context):
        backend = (
            await create(memory_options(config["backend"]), context)
            if "backend" in config
            else context.own(SQLiteMemory(context.db_path + ".fact-index-catalog.sqlite"))
        )
        return FactIndexCatalog(
            backend,
            **(
                {"namespace_prefix": config["namespace_prefix"]}
                if "namespace_prefix" in config
                else {}
            ),
        )

    registry.register_async("fact_index_catalog", "memory-cas", catalog, validator=catalog_options)

    def prepare(config):
        _fields(
            config,
            {
                "backend",
                "embedding",
                "index",
                "catalog",
                "batch_size",
                "max_page_bytes",
                "max_records",
                "min_score",
            },
        )
        backend = memory_options(config.get("backend", {"adapter": "sqlite"}))
        embedding = component_declaration(config.get("embedding", {"adapter": "hash"}))
        embedding_prepared = registry.prepare("embedding_provider", embedding)
        index = component_declaration(config.get("index", {"adapter": "sqlite"}))
        if "dimensions" not in index["config"]:
            dimensions = embedding["config"].get(
                "dimensions", 128 if embedding["adapter"] == "hash" else None
            )
            if dimensions is None:
                raise ValidationError("Declare index dimensions for custom embedding adapters")
            index = {**index, "config": {**index["config"], "dimensions": dimensions}}
        index_prepared = registry.prepare("vector_index", index)
        catalog_prepared = registry.prepare(
            "fact_index_catalog",
            component_declaration(config.get("catalog", {"adapter": "memory-cas"})),
        )
        _integer(config.get("batch_size", 32), "Fact index batch", 1, 128)
        _integer(config.get("max_page_bytes", 64000), "Fact page bytes", 2, 64000)
        _integer(config.get("max_records", 100000), "Fact index total records", 1, 100000)
        # Reuse constructor threshold validation without creating durable resources.
        from math import isfinite

        score = config.get("min_score", -1)
        if type(score) not in (int, float) or not isfinite(score) or not -1 <= score <= 1:
            raise ValidationError("Invalid Fact index threshold")
        return backend, embedding_prepared, index_prepared, catalog_prepared

    async def build(config, context):
        targets = prepare(config)
        source, embedding, index, metadata = [await create(target, context) for target in targets]
        return IndexedMemoryStore(
            source,
            embedding,
            index,
            metadata,
            **{
                k: config[k]
                for k in ("batch_size", "max_page_bytes", "max_records", "min_score")
                if k in config
            },
        )

    registry.register_async(
        "memory_store", "indexed-recall-async", build, validator=lambda c: prepare(c) and None
    )
