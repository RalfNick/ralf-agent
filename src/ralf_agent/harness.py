"""Pure, synchronous Agent policies; execution and state commits belong to Engine."""

import copy
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import ValidationError
from .types import AgentSpec, ModelResponse, ToolCall, canonical


def _detached_json(value):
    canonical(value)
    return copy.deepcopy(value)


def _records(value, label):
    if not isinstance(value, list) or not all(isinstance(record, dict) for record in value):
        raise ValidationError(f"{label} must be a list of JSON objects")
    return _detached_json(value)


@dataclass(frozen=True)
class ModelRequest:
    """Detached Provider input. Frozen fields do not make nested JSON immutable."""

    messages: list[dict]
    tools: list[dict]

    def __post_init__(self):
        object.__setattr__(self, "messages", _records(self.messages, "Model request messages"))
        object.__setattr__(self, "tools", _records(self.tools, "Model request tools"))


@dataclass(frozen=True)
class DecisionProposal:
    """Unaccepted output/tool proposals; no action identity or execution authority."""

    output: Any = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "output", _detached_json(self.output))
        if not isinstance(self.tool_calls, (tuple, list)):
            raise ValidationError("Decision proposals require a list or tuple of ToolCall")
        calls = []
        for call in self.tool_calls:
            if (
                not isinstance(call, ToolCall)
                or not isinstance(call.name, str)
                or not call.name.strip()
                or not isinstance(call.arguments, dict)
                or (call.call_id is not None and not isinstance(call.call_id, str))
            ):
                raise ValidationError("Decision proposal contained an invalid ToolCall")
            calls.append(ToolCall(call.name, _detached_json(call.arguments), call.call_id))
        object.__setattr__(self, "tool_calls", tuple(calls))


class Harness(Protocol):
    """Identity-pinned policy that prepares one request and proposes one decision.

    Implementations must be synchronous and pure: do not call models/tools,
    generate Action IDs, commit Run state or perform external I/O. The Engine
    validates the policy identity and all proposals at the adoption boundary.
    """

    identity: dict

    def prepare(self, spec: AgentSpec, messages: list[dict], tools: list[dict]) -> ModelRequest: ...

    def propose(self, spec: AgentSpec, response: ModelResponse) -> DecisionProposal: ...


class NativeHarness:
    """Default transparent policy; the Engine retains final-output validation."""

    identity = {"kind": "native-harness", "version": "1"}

    def prepare(self, spec: AgentSpec, messages: list[dict], tools: list[dict]) -> ModelRequest:
        return ModelRequest(messages, tools)

    def propose(self, spec: AgentSpec, response: ModelResponse) -> DecisionProposal:
        if not isinstance(response, ModelResponse):
            raise ValidationError("Harness requires a ModelResponse")
        return DecisionProposal(response.output, response.tool_calls)
