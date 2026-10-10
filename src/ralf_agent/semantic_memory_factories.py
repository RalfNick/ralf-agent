"""Explicit semantic Facts assembly; original factories own backend and HTTP resources."""

import math

from .errors import ValidationError
from .knowledge_factories import embedding_options
from .ports import is_async_callable
from .query_factories import configured_query_transform, query_transform_config
from .recall import _integer
from .remote_factories import _env
from .retrieval import _text
from .runtime_config import component_declaration
from .semantic_embedding import ManagedEmbeddingProvider
from .semantic_memory import SemanticMemoryStore
from .semantic_recall import TaskRecallPlanner


def register_semantic_memory(registry):
    from .runtime_builder import _completed, _fields, _policy

    def prepare(config):
        _fields(
            config,
            {
                "backend",
                "embedding",
                "query_transform",
                "max_candidates",
                "max_candidate_chars",
                "min_score",
            },
        )
        if not {"backend", "embedding"} <= set(config):
            raise ValidationError("Semantic Facts requires explicit backend and embedding")
        backend = component_declaration(config["backend"])
        if backend["adapter"] in {"semantic-recall-async", "facts-resource", "session-resource"}:
            raise ValidationError("Semantic Facts cannot recursively wrap data resources")
        if backend["adapter"] == "sqlite":
            _fields(backend["config"], {"path"})
            if "path" in backend["config"]:
                _text(backend["config"]["path"], "Semantic Facts source path")
        elif backend["adapter"] == "in-memory":
            _fields(backend["config"], {"backend_id"})
            if "backend_id" in backend["config"]:
                _text(backend["config"]["backend_id"], "Semantic Facts source identity")
        kind, options = embedding_options({"embedding": config["embedding"]})
        if kind != "openai":
            raise ValidationError("Semantic Facts factory requires explicit HTTP embedding")
        values = config["embedding"]["config"]
        if "base_url" not in values:
            raise ValidationError("Semantic Facts requires an explicit embedding endpoint")
        options = {
            **options,
            "api_key": _env(values, "api_key_env") if "api_key_env" in values else None,
        }
        transform = query_transform_config(config.get("query_transform"))
        _integer(config.get("max_candidates", 256), "Semantic candidate limit", 1, 256)
        _integer(config.get("max_candidate_chars", 64000), "Semantic candidate chars", 2, 262144)
        score = config.get("min_score", -1)
        if type(score) not in (int, float) or not -1 <= score <= 1 or not math.isfinite(score):
            raise ValidationError("Semantic threshold must be finite in[-1,1]")
        return registry.prepare("memory_store", backend), options, transform

    async def build(config, context):
        (factory, values), options, declaration = prepare(config)
        transform = configured_query_transform(declaration, context=context)
        backend = (
            await factory(values, context)
            if is_async_callable(factory)
            else _completed(factory(values, context), "Semantic Facts source")
        )
        provider = context.own_async(ManagedEmbeddingProvider(**options))
        return SemanticMemoryStore(
            backend,
            provider,
            transform,
            **{
                k: config[k]
                for k in ("max_candidates", "max_candidate_chars", "min_score")
                if k in config
            },
        )

    registry.register_async(
        "memory_store", "semantic-recall-async", build, validator=lambda c: prepare(c) and None
    )

    def planner(config):
        return TaskRecallPlanner(_policy(config, None))

    registry.register(
        "recall_planner",
        "task-text",
        lambda c, ctx: planner(c),
        validator=lambda c: planner(c) and None,
    )
