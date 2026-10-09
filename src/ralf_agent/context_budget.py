"""Pure, replaceable measurement and complete-group selection proposals."""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationError
from .types import canonical


def _positive(value, label, maximum=8 * 1024 * 1024):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError(f"{label} must be a bounded positive integer")
    return value


@dataclass(frozen=True)
class ContextMeasure:
    units: int
    unit: str
    estimated: bool

    def __post_init__(self):
        if type(self.units) is not int or not 0 <= self.units <= 100000000:
            raise ValidationError("Context measurement must be a bounded non-negative integer")
        if not isinstance(self.unit, str) or not self.unit.strip() or len(self.unit) > 128:
            raise ValidationError("Context measurement requires a bounded unit name")
        if type(self.estimated) is not bool:
            raise ValidationError("Context measurement estimated must be boolean")


class MessageCounter(Protocol):
    identity: dict

    def count(self, messages: list[dict]) -> ContextMeasure: ...


class ContextBudgeter(Protocol):
    identity: dict

    def select(
        self,
        head: list[dict],
        groups: list[list[dict]],
        *,
        measure: Callable[[list[dict]], ContextMeasure],
        max_chars: int,
        max_units: int,
    ) -> tuple[int, ...]: ...


class CanonicalCharacterCounter:
    identity = {"kind": "canonical-character-counter", "version": "1"}

    def count(self, messages):
        return ContextMeasure(len(canonical(messages)), "canonical-chars", False)


class UTF8TokenEstimator:
    """ceil(canonical UTF-8 bytes / 4), not a model tokenizer or billing limit."""

    identity = {"kind": "utf8-token-estimate", "version": "1", "bytes_per_unit": 4}

    def count(self, messages):
        try:
            size = len(canonical(messages).encode("utf-8"))
        except UnicodeEncodeError:
            raise ValidationError("Context must contain valid UTF-8 text") from None
        return ContextMeasure((size + 3) // 4, "estimated-tokens", True)


class WholeGroupBudgeter:
    identity = {"kind": "whole-group-tail", "version": "1"}

    def select(self, head, groups, *, measure, max_chars, max_units):
        _positive(max_chars, "Character limit")
        _positive(max_units, "Measurement limit", 100000000)
        first = 0
        while True:
            messages = copy.deepcopy(head + [m for g in groups[first:] for m in g])
            if len(canonical(messages)) <= max_chars and measure(messages).units <= max_units:
                return tuple(range(first, len(groups)))
            if first >= len(groups) - 1:
                raise ValidationError("Required task and latest evidence exceed the context limit")
            first += 1
