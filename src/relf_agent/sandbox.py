"""Bounded native Sandbox contracts; lifecycle evidence is separate from Run authority."""

import re
from dataclasses import dataclass
from typing import Protocol

from .errors import RalfError, ValidationError
from .types import Scope
from .workspace import _utf8

MAX_OUTPUT = 16777216


class SandboxError(RalfError):
    code = "sandbox_error"


class SandboxUnavailable(SandboxError):
    code = "sandbox_unavailable"


class SandboxExecutionRejected(SandboxUnavailable):
    """Trusted native owner distinguishes proven no-start from unknown dispatch."""

    def __init__(self, *, handler_not_started):
        if type(handler_not_started) is not bool:
            raise ValidationError("Sandbox start refusal requires an exact boolean")
        super().__init__("Sandbox execution was rejected by its native owner")
        self.handler_not_started = handler_not_started


class SandboxIsolationViolation(SandboxError):
    code = "sandbox_isolation_violation"


def invocation(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None
    ):
        raise ValidationError("Sandbox invocation requires bounded ordinary ASCII identity")
    return value


def native_identity(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError("Sandbox native identity requires lowercase SHA256")
    return value


def exit_code(value):
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ValidationError("Sandbox exit code requires ordinary signed32-bit integer")
    return value


def _wire(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValidationError("Sandbox wire data requires exact ordinary fields")
    return value


@dataclass(frozen=True)
class SandboxRequest:
    argv: tuple[str, ...]
    timeout: float = 30

    def __post_init__(self):
        if type(self.argv) not in (tuple, list) or not 1 <= len(self.argv) <= 64:
            raise ValidationError("Sandbox argv requires one to64 ordinary arguments")
        total = 0
        for item in self.argv:
            data = _utf8(item, "Sandbox argument", max_bytes=65536)
            if b"\x00" in data:
                raise ValidationError("Sandbox argument cannot contain NUL")
            total += len(data)
            if total > 65536:
                raise ValidationError("Sandbox argv exceeds its total byte allowance")
        if not self.argv[0].startswith("/"):
            raise ValidationError("Sandbox executable requires an absolute container path")
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 300:
            raise ValidationError("Sandbox timeout requires finite ordinary seconds in (0,300]")
        object.__setattr__(self, "argv", tuple(self.argv))

    def to_dict(self):
        SandboxRequest.__post_init__(self)
        return {"argv": list(self.argv), "timeout": self.timeout}

    @classmethod
    def from_dict(cls, value):
        _wire(value, {"argv"}, {"timeout"})
        return cls(**value)


@dataclass(frozen=True)
class SandboxObservation:
    invocation_id: str
    native_id: str | None
    state: str
    exit_code: int | None = None

    def __post_init__(self):
        invocation(self.invocation_id)
        if type(self.state) is not str or self.state not in {
            "not_found",
            "created",
            "running",
            "stopped",
            "unknown",
        }:
            raise ValidationError("Sandbox observation requires an explicit native state")
        if self.native_id is not None:
            native_identity(self.native_id)
        if self.state in {"created", "running", "stopped"} and self.native_id is None:
            raise ValidationError("Sandbox observation requires native environment identity")
        if self.state == "not_found" and self.native_id is not None:
            raise ValidationError("Missing Sandbox cannot report a native identity")
        if self.state == "stopped":
            exit_code(self.exit_code)
        elif self.exit_code is not None:
            raise ValidationError("Sandbox exit code requires actual native stop evidence")

    def to_dict(self):
        SandboxObservation.__post_init__(self)
        return {
            name: object.__getattribute__(self, name)
            for name in ("invocation_id", "native_id", "state", "exit_code")
        }

    @classmethod
    def from_dict(cls, value):
        _wire(value, {"invocation_id", "native_id", "state"}, {"exit_code"})
        return cls(**value)


@dataclass(frozen=True)
class SandboxResult:
    invocation_id: str
    native_id: str
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    observation: SandboxObservation

    def __post_init__(self):
        invocation(self.invocation_id)
        native_identity(self.native_id)
        exit_code(self.exit_code)
        if type(self.truncated) is not bool or type(self.timed_out) is not bool:
            raise ValidationError("Sandbox output flags require ordinary booleans")
        size = len(_utf8(self.stdout, "Sandbox stdout", max_bytes=MAX_OUTPUT))
        size += len(_utf8(self.stderr, "Sandbox stderr", max_bytes=MAX_OUTPUT))
        if size > MAX_OUTPUT:
            raise ValidationError("Sandbox output exceeds its total byte allowance")
        if type(self.observation) is not SandboxObservation:
            raise ValidationError("Sandbox result requires original completed observation")
        SandboxObservation.__post_init__(self.observation)
        if (
            self.observation.state != "stopped"
            or self.observation.invocation_id != self.invocation_id
            or self.observation.native_id != self.native_id
            or self.observation.exit_code != self.exit_code
        ):
            raise ValidationError("Sandbox result differs from its actual native stop evidence")

    def to_dict(self):
        SandboxResult.__post_init__(self)
        return {
            **{
                name: object.__getattribute__(self, name)
                for name in (
                    "invocation_id",
                    "native_id",
                    "exit_code",
                    "stdout",
                    "stderr",
                    "truncated",
                    "timed_out",
                )
            },
            "observation": SandboxObservation.to_dict(self.observation),
        }

    @classmethod
    def from_dict(cls, value):
        _wire(
            value,
            {
                "invocation_id",
                "native_id",
                "exit_code",
                "stdout",
                "stderr",
                "truncated",
                "timed_out",
                "observation",
            },
        )
        return cls(**{**value, "observation": SandboxObservation.from_dict(value["observation"])})


def validate_sandbox_result(value, invocation_id, *, max_output_bytes=1048576):
    """Validate the actual DTO before any copy, wire projection or result adoption."""
    invocation(invocation_id)
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT:
        raise ValidationError("Sandbox output allowance requires one to16MiB")
    if type(value) is not SandboxResult:
        raise ValidationError("Sandbox provider must return a completed native result")
    SandboxResult.__post_init__(value)
    if (
        value.invocation_id != invocation_id
        or len(value.stdout.encode("utf-8")) + len(value.stderr.encode("utf-8")) > max_output_bytes
    ):
        raise ValidationError("Sandbox result differs from its invocation or output allowance")
    return value


class SandboxProvider(Protocol):
    identity: dict

    async def run(
        self, scope: Scope, request: SandboxRequest, *, invocation_id: str
    ) -> SandboxResult: ...
    async def observe(self, scope: Scope, invocation_id: str) -> SandboxObservation: ...
    async def stop(self, scope: Scope, invocation_id: str) -> SandboxObservation: ...
    async def aclose(self, wait_timeout: float = 30) -> None: ...
