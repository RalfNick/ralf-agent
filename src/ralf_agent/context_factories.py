"""Additive pure context assembly declarations; custom ports remain SDK-owned."""

from .context_budget import CanonicalCharacterCounter, UTF8TokenEstimator
from .context_pipeline import BudgetedContextAssembler
from .context_summaries import ExcerptContextSummarizer
from .errors import ValidationError


def budgeted_context(config):
    if not isinstance(config, dict) or set(config) - {
        "counter",
        "max_units",
        "summarizer",
        "summary_max_chars",
        "excerpt_chars",
        "max_excerpts",
    }:
        raise ValidationError("Unknown budgeted context fields")
    if config.get("counter", "canonical-chars") not in {"canonical-chars", "utf8-estimate"}:
        raise ValidationError("Unknown context counter")
    if config.get("summarizer", "none") not in {"none", "excerpt"}:
        raise ValidationError("Unknown context summarizer")
    excerpt = ExcerptContextSummarizer(
        **{k: config[k] for k in ("excerpt_chars", "max_excerpts") if k in config}
    )
    return BudgetedContextAssembler(
        counter=UTF8TokenEstimator()
        if config.get("counter") == "utf8-estimate"
        else CanonicalCharacterCounter(),
        summarizer=excerpt if config.get("summarizer") == "excerpt" else None,
        **{k: config[k] for k in ("max_units", "summary_max_chars") if k in config},
    )


def managed_context(config):
    """Automatic summaries reuse host providers, measurement and original authority."""
    from .managed_context import ManagedContextPipeline

    fields = {
        "mode",
        "provider",
        "timeout",
        "summary_max_chars",
        "source_max_chars",
        "counter",
        "max_units",
        "excerpt_chars",
        "max_excerpts",
    }
    if not isinstance(config, dict) or set(config) - fields:
        raise ValidationError("Unknown managed context fields")
    base = budgeted_context({k: config[k] for k in ("counter", "max_units") if k in config})
    excerpt = ExcerptContextSummarizer(
        **{k: config[k] for k in ("excerpt_chars", "max_excerpts") if k in config}
    )
    if config.get("mode", "excerpt") == "model" and set(config) & {"excerpt_chars", "max_excerpts"}:
        raise ValidationError("Model mode cannot configure hidden excerpt settings")
    return ManagedContextPipeline(
        assembler=base,
        summarizer=excerpt if config.get("mode", "excerpt") == "excerpt" else None,
        **{
            k: config[k]
            for k in ("mode", "provider", "timeout", "summary_max_chars", "source_max_chars")
            if k in config
        },
    )
