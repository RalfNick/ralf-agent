"""Explicit deterministic historical excerpts; no inference, storage or I/O."""

from dataclasses import dataclass
from typing import Protocol

from .context_budget import _positive
from .errors import ValidationError
from .types import canonical, digest


@dataclass(frozen=True)
class ContextSummary:
    text: str
    group_digests: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.text, str) or len(self.text) > 32768:
            raise ValidationError("Context summary requires bounded text")
        if not isinstance(self.group_digests, (tuple, list)) or len(self.group_digests) > 1024:
            raise ValidationError("Summary coverage must be a bounded completed sequence")
        coverage = tuple(self.group_digests)
        if any(
            not isinstance(d, str) or len(d) != 64 or any(c not in "0123456789abcdef" for c in d)
            for d in coverage
        ):
            raise ValidationError("Summary coverage requires group digests")
        object.__setattr__(self, "group_digests", coverage)


class ContextSummarizer(Protocol):
    identity: dict

    def summarize(self, groups: list[list[dict]], *, max_chars: int) -> ContextSummary: ...


class ExcerptContextSummarizer:
    """Bounded excerpts, with full coverage digests separate from sampled text."""

    def __init__(self, *, excerpt_chars=128, max_excerpts=16):
        self._excerpt_chars = _positive(excerpt_chars, "Excerpt size", 4096)
        self._max_excerpts = _positive(max_excerpts, "Excerpt count", 64)

    @property
    def identity(self):
        return {
            "kind": "historical-group-excerpt",
            "version": "1",
            "excerpt_chars": self._excerpt_chars,
            "max_excerpts": self._max_excerpts,
        }

    def summarize(self, groups, *, max_chars):
        _positive(max_chars, "Summary limit", 32768)
        if not isinstance(groups, list) or len(groups) > 1024:
            raise ValidationError("Summary requires bounded complete groups")
        coverage = tuple(digest(g) for g in groups)
        excerpts = []
        for index, group in enumerate(groups[: self._max_excerpts]):
            entry = {
                "group": index,
                "digest": coverage[index],
                "excerpt": canonical(group)[: self._excerpt_chars],
            }
            if len(canonical([*excerpts, entry])) > max_chars:
                break
            excerpts.append(entry)
        return ContextSummary(canonical(excerpts) if excerpts else "", coverage)
