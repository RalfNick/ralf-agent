"""Versioned execution limits; hosts still supply identity and resource ACLs."""

import math
from dataclasses import asdict, dataclass

from .errors import ValidationError
from .types import _require_text, canonical


@dataclass(frozen=True)
class TemporalExecutionPolicy:
    version: str = "1"
    max_children: int = 256
    max_concurrency: int = 32
    max_depth: int = 8
    run_timeout_seconds: float | None = None
    approval_timeout_seconds: float | None = None
    allowed_tools: tuple[str, ...] | None = None

    def __post_init__(self):
        _require_text(self.version, "Execution policy version")
        for name, upper in [("max_children", 256), ("max_concurrency", 32), ("max_depth", 8)]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValidationError("Invalid execution policy capacity")
        for name in ("run_timeout_seconds", "approval_timeout_seconds"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= 86400
            ):
                raise ValidationError(
                    "Execution policy deadlines must be finite positive seconds up to 86400"
                )
        if self.allowed_tools is not None:
            if not isinstance(self.allowed_tools, (tuple, list)) or any(
                not isinstance(value, str) or not value.strip() for value in self.allowed_tools
            ):
                raise ValidationError("Execution tool allowlist requires names")
            object.__setattr__(self, "allowed_tools", tuple(self.allowed_tools))
        canonical(self.identity)

    @property
    def identity(self):
        value = asdict(self)
        value["allowed_tools"] = None if self.allowed_tools is None else list(self.allowed_tools)
        return {"kind": "temporal-execution-policy", **value}

    @classmethod
    def from_identity(cls, value):
        if not isinstance(value, dict) or value.get("kind") != "temporal-execution-policy":
            raise ValidationError("Invalid execution policy identity")
        try:
            return cls(**{k: v for k, v in value.items() if k != "kind"})
        except TypeError as exc:
            raise ValidationError("Invalid execution policy fields") from exc
