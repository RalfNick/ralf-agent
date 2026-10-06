"""Serializable public domain values; runtime secrets never belong here."""

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

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
        raise ValidationError("Credits must be a non-negative integer")


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")


@dataclass(frozen=True)
class Scope:
    workspace: str = "default"
    principal: str = "local-owner"

    def __post_init__(self):
        _require_text(self.workspace, "Workspace")
        _require_text(self.principal, "Principal")


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
    output_schema: dict | bool | None = None

    def __post_init__(self):
        for label in ("name", "instructions", "provider", "version"):
            _require_text(getattr(self, label), f"Agent {label}")
        if type(self.max_decisions) is not int or self.max_decisions < 1:
            raise ValidationError("Agent decision limit must be a positive integer")
        if type(self.max_context_chars) is not int or self.max_context_chars < 256:
            raise ValidationError("Context limit must be an integer of at least 256 characters")
        if not isinstance(self.tools, (tuple, list)):
            raise ValidationError("Agent tools must be a list or tuple of tool names")
        for name in self.tools:
            _require_text(name, "Agent tool name")
        if len(set(self.tools)) != len(self.tools):
            raise ValidationError("Agent tool names must be unique")
        object.__setattr__(self, "tools", tuple(self.tools))
        credits(self.model_credits)
        if self.output_schema is not None:
            canonical(self.output_schema)
            try:
                Draft202012Validator.check_schema(self.output_schema)
            except SchemaError as exc:
                raise ValidationError("Invalid Agent output Schema") from exc
            object.__setattr__(self, "output_schema", copy.deepcopy(self.output_schema))


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    steps: tuple[AgentSpec, ...]
    version: str = "1"

    def __post_init__(self):
        _require_text(self.name, "Workflow name")
        _require_text(self.version, "Workflow version")
        if (
            not isinstance(self.steps, (tuple, list))
            or not self.steps
            or not all(isinstance(s, AgentSpec) for s in self.steps)
        ):
            raise ValidationError("Workflow steps must be a non-empty list or tuple of AgentSpec")
        object.__setattr__(self, "steps", tuple(self.steps))


def submission_request(spec, input, *, budget=32, session_id=None):
    """Caller-controlled identity shared by native acceptance and read-only replay."""
    if isinstance(spec, AgentSpec):
        definition = {
            "kind": "agent",
            "name": spec.name,
            "version": spec.version,
            "steps": [asdict(spec)],
        }
    elif isinstance(spec, WorkflowSpec):
        definition = {
            "kind": "sequence",
            "name": spec.name,
            "version": spec.version,
            "steps": [asdict(step) for step in spec.steps],
        }
    else:
        raise ValidationError("Submit an AgentSpec or sequential WorkflowSpec")
    payload = {
        "definition": definition,
        "input": copy.deepcopy(input),
        "budget": budget,
        "session_id": session_id,
    }
    canonical(payload)
    return payload


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


def runtime_profile_identity(value):
    """Validate a non-secret reference to an immutable runtime profile."""
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "name", "version", "digest"}
        or value["kind"] != "runtime-profile"
    ):
        raise ValidationError("Invalid runtime profile identity")
    _require_text(value["name"], "Profile name")
    _require_text(value["version"], "Profile version")
    if (
        not isinstance(value["digest"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["digest"]) is None
    ):
        raise ValidationError("Profile digest must be a SHA-256 identity")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class RunDiagnostics:
    snapshot: RunSnapshot
    manifest: dict
    release_digest: str
    budget: dict

    def __post_init__(self):
        if not isinstance(self.snapshot, RunSnapshot):
            raise ValidationError("Diagnostics require a RunSnapshot")
        if not isinstance(self.manifest, dict) or not isinstance(self.budget, dict):
            raise ValidationError("Diagnostics require JSON manifest and budget objects")
        _require_text(self.release_digest, "Release digest")
        canonical(asdict(self))
        object.__setattr__(self, "snapshot", copy.deepcopy(self.snapshot))
        object.__setattr__(self, "manifest", copy.deepcopy(self.manifest))
        object.__setattr__(self, "budget", copy.deepcopy(self.budget))


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
