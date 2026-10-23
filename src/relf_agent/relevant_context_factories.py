"""Explicit pure selection factories; artifact ownership stays in the original builder."""

from .context_pipeline import _Pure
from .errors import ValidationError
from .ports import is_async_callable
from .reference_selection import OverlapReferenceSelector
from .relevant_context import RelevantDataContext
from .runtime_config import component_declaration
from .semantic_selection import OrderedReferenceSelector


def register_relevant_context(registry):
    from .runtime_builder import _completed, _fields

    def selector_config(config):
        _fields(config, {"max_references", "max_query_chars"})
        OverlapReferenceSelector(**config)

    registry.register(
        "reference_selector",
        "overlap",
        lambda c, ctx: OverlapReferenceSelector(**c),
        validator=selector_config,
    )

    def ordered_config(config):
        _fields(config, {"max_references"})
        OrderedReferenceSelector(**config)

    registry.register(
        "reference_selector",
        "ordered",
        lambda c, ctx: OrderedReferenceSelector(**c),
        validator=ordered_config,
    )

    def prepare(config, asynchronous):
        if not isinstance(config, dict):
            raise ValidationError("Relevant context requires a configuration object")
        base = registry.prepare(
            "context_assembler",
            {
                "adapter": "managed-data-async" if asynchronous else "managed-data",
                "config": {k: v for k, v in config.items() if k != "selector"},
            },
        )
        selector = registry.prepare(
            "reference_selector",
            component_declaration(config.get("selector", {"adapter": "overlap"})),
        )
        if is_async_callable(selector[0]):
            raise ValidationError("Reference selector factory must complete synchronously")
        return base, selector

    def combine(base, selector):
        _Pure(selector, "select")
        return RelevantDataContext(
            base.artifacts,
            scope=base.scope,
            selector=selector,
            assembler=base._assembler,
            summarizer=base._summarizer.component if base.mode == "excerpt" else None,
            **{
                k: getattr(base, k)
                for k in (
                    "namespace",
                    "tool_result_chars",
                    "preview_chars",
                    "reference_chars",
                    "mode",
                    "provider",
                    "timeout",
                    "summary_max_chars",
                    "source_max_chars",
                )
            },
        )

    def build(config, context):
        (factory, options), (select, selection) = prepare(config, False)
        return combine(
            _completed(factory(options, context), "Data context"),
            _completed(select(selection, context), "Reference selector"),
        )

    async def abuild(config, context):
        (factory, options), (select, selection) = prepare(config, True)
        return combine(
            _completed(await factory(options, context), "Data context"),
            _completed(select(selection, context), "Reference selector"),
        )

    registry.register(
        "context_assembler", "relevant-data", build, validator=lambda c: prepare(c, False) and None
    )
    registry.register_async(
        "context_assembler",
        "relevant-data-async",
        abuild,
        validator=lambda c: prepare(c, True) and None,
    )
