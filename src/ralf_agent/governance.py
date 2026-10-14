"""Versioned execution limits; hosts still supply identity and resource ACLs."""

import math
from dataclasses import asdict, dataclass

from .errors import ValidationError
from .types import _require_text, canonical


@dataclass(frozen=True)
class DeploymentAdmissionPolicy:
    deployment_id: str
    version: str = "1"
    max_active_root_runs: int = 32
    max_active_root_runs_per_scope: int | None = None

    def __post_init__(self):
        _require_text(self.deployment_id, "Deployment identity")
        _require_text(self.version, "Admission policy version")
        for value in (self.max_active_root_runs, self.max_active_root_runs_per_scope):
            if value is not None and (type(value) is not int or not 1 <= value <= 10000):
                raise ValidationError("Deployment capacity requires exact counts from 1 to 10000")
        if self.max_active_root_runs is None or (
            self.max_active_root_runs_per_scope is not None
            and self.max_active_root_runs_per_scope > self.max_active_root_runs
        ):
            raise ValidationError("Scope capacity cannot exceed deployment capacity")
        canonical(self.identity)

    @property
    def identity(self):
        return {"kind": "deployment-admission-policy", **asdict(self)}

    @classmethod
    def from_identity(cls, value):
        if type(value) is not dict or value.get("kind") != "deployment-admission-policy":
            raise ValidationError("Invalid deployment admission identity")
        try:
            return cls(**{k: v for k, v in value.items() if k != "kind"})
        except TypeError:
            raise ValidationError("Invalid deployment admission fields") from None


@dataclass(frozen=True)
class LocalExecutionPolicy:
    version: str = "1"
    run_timeout_seconds: float | None = None
    approval_timeout_seconds: float | None = None

    def __post_init__(self):
        _require_text(self.version, "Execution policy version")
        for name in ("run_timeout_seconds", "approval_timeout_seconds"):
            value = getattr(self, name)
            if value is not None and (
                type(value) not in (int, float)
                or not 0 < value <= 86400
                or not math.isfinite(value)
            ):
                raise ValidationError("Local deadlines must be finite positive seconds up to 86400")
        canonical(self.identity)

    @property
    def identity(self):
        return {"kind": "local-execution-policy", **asdict(self)}

    @classmethod
    def from_identity(cls, value):
        if type(value) is not dict or value.get("kind") != "local-execution-policy":
            raise ValidationError("Invalid Local execution policy identity")
        try:
            return cls(**{k: v for k, v in value.items() if k != "kind"})
        except TypeError:
            raise ValidationError("Invalid Local execution policy fields") from None


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
