"""Immutable capability composition; the existing Harness stays a pure policy."""

import json
from dataclasses import dataclass

from .binding_definitions import decode_definition
from .spec_codec import decode_spec
from .types import AgentSpec, WorkflowSpec, canonical, digest, submission_request


@dataclass(frozen=True, init=False)
class AgentHarness:
    _definition_json: str

    def __init__(self, definition):
        object.__setattr__(
            self, "_definition_json", canonical(submission_request(definition, None)["definition"])
        )

    @property
    def definition(self):
        value = json.loads(self._definition_json)
        if value["kind"] in {"bound_agent", "bound_definition"}:
            return decode_definition(value)
        if value["kind"] in {"agent", "sequence"}:
            steps = [AgentSpec(**step) for step in value["steps"]]
            return (
                steps[0]
                if value["kind"] == "agent"
                else WorkflowSpec(value["name"], steps, value["version"])
            )
        return decode_spec(value)

    @property
    def identity(self):
        return {
            "kind": "agent-harness",
            "version": "1",
            "definition_digest": digest(json.loads(self._definition_json)),
        }
