"""Serializable public domain values; runtime secrets never belong here."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import ValidationError


def canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("Values must be finite JSON data") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def credits(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Credits must be a non-negative integer")


@dataclass(frozen=True)
class Scope:
    workspace: str = "default"
    principal: str = "local-owner"

    def __post_init__(self):
        if not self.workspace or not self.principal:
            raise ValidationError("Workspace and principal must be non-empty")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    instructions: str
    tools: tuple[str, ...] = ()
    provider: str = "default"
    version: str = "1"
    max_decisions: int = 8
    max_context_chars: int = 32000
    model_credits: int = 1
    output_schema: dict | None = None

    def __post_init__(self):
        if not self.name or not self.instructions or self.max_decisions < 1:
            raise ValidationError(
                "Agent name, instructions and positive decision limit are required"
            )
        if self.max_context_chars < 256:
            raise ValidationError("Context limit must be at least 256 characters")
        credits(self.model_credits)


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    steps: tuple[AgentSpec, ...]
    version: str = "1"

    def __post_init__(self):
        if not self.name or not self.steps or not all(isinstance(s, AgentSpec) for s in self.steps):
            raise ValidationError("A workflow needs a name and at least one AgentSpec")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    call_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    output: Any = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict | None = None


@dataclass(frozen=True)
class InvocationContext:
    scope: Scope
    run_id: str
    action_id: str
    attempt_id: str
    effect_key: str
    execution_epoch: str


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    run_id: str
    kind: str
    record_state: str = "durably_recorded"
    apply_state: str = "applied"
    outcome: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    seq: int
    kind: str
    data: dict

    @property
    def event_id(self):
        return f"{self.run_id}:{self.seq}"


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    state: str
    state_revision: int
    result: Any
    error: dict | None
    pending: tuple[dict, ...]
    actions: tuple[dict, ...]
    consistency: str = "authoritative"

    @classmethod
    def from_record(cls, run):
        pending = tuple(
            {
                "action_id": action["id"],
                "digest": action["digest"],
                "tool": action["tool"],
                "arguments": action["arguments"],
            }
            for action in run["actions"]
            if action["status"] == "waiting_approval"
        )
        return cls(
            run["id"],
            run["state"],
            run["revision"],
            run["result"],
            run["error"],
            pending,
            tuple(run["actions"]),
        )


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    receipt: CommandReceipt

    def status(self, engine):
        return engine.status(self.run_id)

    def events(self, engine, after: int = 0):
        return engine.events(self.run_id, after=after)

    def to_dict(self):
        return asdict(self)
