"""Owned default artifact storage; registry replacement for sync/async ports."""

from .artifacts import InMemoryArtifactStore, SQLiteArtifactStore
from .context_factories import managed_context
from .context_summaries import ExcerptContextSummarizer
from .data_context import ManagedDataContext
from .errors import ValidationError
from .file_artifacts import FileArtifactStore
from .ports import is_async_callable
from .runtime_config import component_declaration

FIELDS = {"artifacts", "namespace", "tool_result_chars", "preview_chars", "reference_chars"}


def register_data_context(registry):
    from .runtime_builder import _completed, _fields

    def artifact_options(config):
        _fields(config, {"path", "backend_id", "max_bytes", "capacity"})
        if "path" in config and (not isinstance(config["path"], str) or not config["path"].strip()):
            raise ValidationError("Artifact path must be non-empty text")
        InMemoryArtifactStore(**{k: v for k, v in config.items() if k != "path"})

    def sqlite(config, context):
        path = (
            context.path(config["path"])
            if "path" in config
            else context.db_path + ".artifacts.sqlite"
        )
        return context.own(
            SQLiteArtifactStore(path, **{k: v for k, v in config.items() if k != "path"})
        )

    registry.register("artifact_store", "sqlite", sqlite, validator=artifact_options)

    def file_options(config):
        artifact_options(config)
        try:
            import fcntl  # noqa: F401
        except ImportError:
            raise ValidationError("File artifacts require POSIX locks") from None

    def file(config, context):
        path = context.path(config["path"]) if "path" in config else context.db_path + ".artifacts"
        return context.own(
            FileArtifactStore(path, **{k: v for k, v in config.items() if k != "path"})
        )

    registry.register("artifact_store", "file", file, validator=file_options)

    def prepare(config, asynchronous):
        if not isinstance(config, dict):
            raise ValidationError("Data context config must be a JSON object")
        base = managed_context({k: v for k, v in config.items() if k not in FIELDS})
        ManagedDataContext(
            InMemoryArtifactStore(),
            **{k: v for k, v in config.items() if k in FIELDS - {"artifacts"}},
        )
        target = registry.prepare(
            "artifact_store", component_declaration(config.get("artifacts", {"adapter": "sqlite"}))
        )
        if not asynchronous and is_async_callable(target[0]):
            raise ValidationError("Async artifacts require managed-data-async and abuild")
        return base, target

    def policy(config, context, base, artifacts):
        return ManagedDataContext(
            artifacts,
            scope=context.scope,
            assembler=base._assembler,
            summarizer=ExcerptContextSummarizer(
                **{k: config[k] for k in ("excerpt_chars", "max_excerpts") if k in config}
            )
            if config.get("mode", "excerpt") == "excerpt"
            else None,
            **{k: v for k, v in config.items() if k in FIELDS - {"artifacts"}},
            **{
                k: v
                for k, v in config.items()
                if k in {"mode", "provider", "timeout", "summary_max_chars", "source_max_chars"}
            },
        )

    def construct(config, context):
        base, (factory, options) = prepare(config, False)
        return policy(
            config, context, base, _completed(factory(options, context), "Artifact factory")
        )

    async def aconstruct(config, context):
        base, (factory, options) = prepare(config, True)
        value = (
            await factory(options, context)
            if is_async_callable(factory)
            else factory(options, context)
        )
        return policy(config, context, base, _completed(value, "Artifact factory"))

    registry.register(
        "context_assembler",
        "managed-data",
        construct,
        validator=lambda c: prepare(c, False) and None,
    )
    registry.register_async(
        "context_assembler",
        "managed-data-async",
        aconstruct,
        validator=lambda c: prepare(c, True) and None,
    )
