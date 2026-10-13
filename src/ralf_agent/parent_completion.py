"""Detached parent evidence and pure completion policy declarations.

Execution ownership, quiescence and consumption truth remain authority-owned.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .types import Scope, canonical, digest

if TYPE_CHECKING:
    from .binding_definitions import AgentDefinition
    from .types import AgentSpec

PARENT_COMPLETION_VERDICT_SCHEMA = {
    "type": "object",
    "required": ["status", "feedback", "evidence_ids"],
    "additionalProperties": False,
    "properties": {
        "status": {"enum": ["accept", "reject", "replan"]},
        "feedback": {"type": ["string", "null"], "minLength": 1, "maxLength": 4096},
        "evidence_ids": {
            "type": "array",
            "maxItems": 256,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^(child|tool):[0-9a-f]{64}$"},
        },
    },
    "allOf": [
        {
            "if": {"properties": {"status": {"const": "accept"}}},
            "then": {"properties": {"feedback": {"type": "null"}}},
        },
        {
            "if": {"properties": {"status": {"const": "replan"}}},
            "then": {"properties": {"feedback": {"type": "string"}}},
        },
    ],
}
_REQUEST_FIELDS = {
    "schema_version",
    "parent_id",
    "parent_kind",
    "scope",
    "release_digest",
    "revision",
    "task",
    "plan",
    "candidate",
    "children",
    "receipts",
    "constraints",
}
_CHILD_FIELDS = {
    "id",
    "call_id",
    "role",
    "member_path",
    "run_id",
    "release_digest",
    "state_revision",
    "planning_revision",
    "input",
    "input_digest",
    "input_consumed",
    "result",
    "result_digest",
    "final_action_id",
    "final_snapshot_digest",
    "final_models",
}
_FINAL_FIELDS = {"member_path", "action_id", "snapshot_digest", "input_digest", "input_consumed"}
_RECEIPT_FIELDS = {
    "id",
    "run_id",
    "member_path",
    "action_id",
    "tool",
    "arguments",
    "result",
    "receipt",
    "effect_key",
    "consumed_by",
}
_CONSTRAINT_FIELDS = {
    "remaining_steps",
    "remaining_revisions",
    "max_concurrency",
    "verifier_budget",
    "parent_budget",
}


def _json(value):
    """Normalize finite ordinary JSON without arbitrary serializers."""

    def check(item):
        if type(item) in {dict, list, tuple}:
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValidationError("Parent completion JSON keys must be strings")
                for nested in item.values():
                    check(nested)
            else:
                for nested in item:
                    check(nested)
        elif item is not None and type(item) not in {str, bool, int, float}:
            raise ValidationError("Parent completion requires completed ordinary JSON")

    try:
        check(value)
        return json.loads(canonical(value))
    except RecursionError as exc:
        raise ValidationError("Parent completion JSON nesting exceeds limits") from exc


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValidationError(f"{label} requires non-empty text")


def _integer(value, label, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        raise ValidationError(f"Invalid {label} bound")


def _digest(value, label):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError(f"{label} requires a SHA-256 digest")


def _path(value):
    if type(value) not in {tuple, list} or not 1 <= len(value) <= 32:
        raise ValidationError("Evidence requires a non-empty declared member path")
    for part in value:
        _text(part, "Member path")
    return list(value)


def _child(value, revision):
    if type(value) is not dict or set(value) != _CHILD_FIELDS:
        raise ValidationError("Child evidence fields are incomplete or undeclared")
    for name in ("run_id", "call_id"):
        _text(value[name], "Child " + name)
    _digest(value["release_digest"], "Child release")
    _integer(value["state_revision"], "Child state revision")
    _integer(value["planning_revision"], "Child planning revision", maximum=revision)
    path = _path(value["member_path"])
    if value["role"] != "worker" or value["id"] != "child:" + digest(
        [value["run_id"], value["release_digest"]]
    ):
        raise ValidationError("Child evidence requires its original worker identity")
    for name in ("input", "result"):
        if value[name + "_digest"] != digest(value[name]):
            raise ValidationError("Child evidence value differs from its digest")
    finals = value["final_models"]
    if type(finals) is not list or len(finals) > 256:
        raise ValidationError("Child final model proofs must be bounded")
    seen = set()
    for final in finals:
        if type(final) is not dict or set(final) != _FINAL_FIELDS:
            raise ValidationError("Child final model proof fields are incomplete")
        final_path = _path(final["member_path"])
        if final_path[: len(path)] != path:
            raise ValidationError("Final model must belong to its original child path")
        _text(final["action_id"], "Final model action")
        _digest(final["snapshot_digest"], "Final model snapshot")
        _digest(final["input_digest"], "Final model input")
        if type(final["input_consumed"]) is not bool or final["action_id"] in seen:
            raise ValidationError("Final models require unique original action proofs")
        seen.add(final["action_id"])
    top = [value[name] for name in ("input_consumed", "final_action_id", "final_snapshot_digest")]
    if all(item is None for item in top):
        if any(len(final["member_path"]) <= len(path) for final in finals):
            raise ValidationError(
                "Container final models require original step/node descendant paths"
            )
        return
    if type(value["input_consumed"]) is not bool or len(finals) != 1:
        raise ValidationError("Native child requires one complete final model proof")
    expected = {
        "member_path": path,
        "action_id": value["final_action_id"],
        "snapshot_digest": value["final_snapshot_digest"],
        "input_digest": value["input_digest"],
        "input_consumed": value["input_consumed"],
    }
    if finals[0] != expected:
        raise ValidationError("Native final model differs from original child fields")


class ParentCompletionRequest(_JsonValue):
    def __init__(
        self,
        *,
        parent_id,
        parent_kind,
        scope,
        release_digest,
        revision,
        task,
        plan,
        candidate,
        children,
        receipts,
        constraints,
    ):
        _text(parent_id, "Parent ID")
        _digest(release_digest, "Parent release")
        _integer(revision, "Parent revision")
        if (
            type(parent_kind) is not str
            or parent_kind not in {"dynamic", "team"}
            or parent_kind == "team"
            and revision != 0
        ):
            raise ValidationError("Parent completion requires dynamic/team and a legal revision")
        scope = asdict(scope) if type(scope) is Scope else scope
        if type(scope) is not dict or set(scope) != {"workspace", "principal"}:
            raise ValidationError("Parent completion requires its original Scope")
        for value in scope.values():
            _text(value, "Scope")
        if (
            type(children) not in {list, tuple}
            or len(children) > 256
            or type(receipts) not in {list, tuple}
            or len(receipts) > 256
        ):
            raise ValidationError("Parent evidence must be finite bounded lists")
        if plan is not None and type(plan) is not dict:
            raise ValidationError("Parent plan must be an adopted proposal or None")
        data = _json(
            {
                "schema_version": 1,
                "parent_id": parent_id,
                "parent_kind": parent_kind,
                "scope": scope,
                "release_digest": release_digest,
                "revision": revision,
                "task": task,
                "plan": plan,
                "candidate": candidate,
                "children": list(children),
                "receipts": list(receipts),
                "constraints": constraints,
            }
        )
        by_run, ids = {}, set()
        for value in data["children"]:
            _child(value, revision)
            if value["id"] in ids or value["run_id"] in by_run:
                raise ValidationError("Child evidence IDs and Runs must be unique")
            ids.add(value["id"])
            by_run[value["run_id"]] = value
        for value in data["receipts"]:
            if type(value) is not dict or set(value) != _RECEIPT_FIELDS:
                raise ValidationError("Tool evidence fields are incomplete or undeclared")
            for name in ("action_id", "tool", "effect_key"):
                _text(value[name], "Tool " + name)
            if type(value["arguments"]) is not dict or type(value["receipt"]) is not dict:
                raise ValidationError(
                    "Tool evidence requires actual arguments and committed receipt"
                )
            path = _path(value["member_path"])
            if type(value["run_id"]) is not str:
                raise ValidationError("Tool evidence requires original Run identity")
            owner = by_run.get(value["run_id"])
            if (
                owner is None
                or value["id"] != "tool:" + digest([value["run_id"], value["action_id"]])
                or value["id"] in ids
            ):
                raise ValidationError("Tool evidence requires its original owned Action identity")
            matching = [item for item in owner["final_models"] if item["member_path"] == path]
            container_path = owner["member_path"]
            direct_tool = (
                owner["final_action_id"] is None
                and len(path) > len(container_path)
                and path[: len(container_path)] == container_path
                and value["consumed_by"] == []
            )
            if not matching and not direct_tool:
                raise ValidationError("Tool path must name an original completed model slot")
            legal = {"model:" + digest([owner["run_id"], item["action_id"]]) for item in matching}
            consumed = value["consumed_by"]
            if (
                type(consumed) is not list
                or len(consumed) > 256
                or any(type(item) is not str or item not in legal for item in consumed)
                or len(set(consumed)) != len(consumed)
            ):
                raise ValidationError("Tool consumption requires original final model Action IDs")
            ids.add(value["id"])
        constraints = data["constraints"]
        if (
            type(constraints) is not dict
            or set(constraints) != _CONSTRAINT_FIELDS
            or type(constraints["parent_budget"]) is not dict
        ):
            raise ValidationError("Constraints require the authority budget snapshot")
        for name in ("remaining_steps", "remaining_revisions", "verifier_budget"):
            _integer(constraints[name], "Constraint " + name)
        _integer(constraints["max_concurrency"], "Constraint concurrency", 1, 64)
        if parent_kind == "team" and constraints["remaining_revisions"] != 0:
            raise ValidationError("Team completion cannot reserve replanning")
        self._data_json = canonical(data)

    @classmethod
    def from_dict(cls, value):
        if (
            type(value) is not dict
            or set(value) != _REQUEST_FIELDS
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
        ):
            raise ValidationError("Parent request requires exact schema_version=1 fields")
        return cls(**{key: item for key, item in value.items() if key != "schema_version"})


class ParentCompletionVerdict(_JsonValue):
    def __init__(self, status, *, feedback=None, evidence_ids=()):
        if type(status) is not str or status not in {"accept", "reject", "replan"}:
            raise ValidationError("Parent verdict must accept, reject or replan")
        if feedback is not None and (
            type(feedback) is not str or not feedback.strip() or len(feedback) > 4096
        ):
            raise ValidationError("Parent feedback must contain 1 to 4096 characters")
        if status == "accept" and feedback is not None or status == "replan" and feedback is None:
            raise ValidationError("Accepted verdict has no feedback; replan requires feedback")
        if (
            type(evidence_ids) not in {list, tuple}
            or len(evidence_ids) > 256
            or any(
                type(item) is not str or re.fullmatch(r"(?:child|tool):[0-9a-f]{64}", item) is None
                for item in evidence_ids
            )
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ValidationError("Parent verdict requires bounded unique evidence IDs")
        self._data_json = canonical(
            {"status": status, "feedback": feedback, "evidence_ids": list(evidence_ids)}
        )

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {"status", "feedback", "evidence_ids"}:
            raise ValidationError("Parent verdict requires exact declared fields")
        return cls(**value)


class ParentCompletionGate(Protocol):
    identity: dict

    def verify(self, request: ParentCompletionRequest) -> ParentCompletionVerdict: ...


class ParentVerificationStage(Protocol):
    identity: dict
    agent: AgentSpec | AgentDefinition

    def prepare(self, request: ParentCompletionRequest): ...

    def interpret(self, request: ParentCompletionRequest, output) -> ParentCompletionVerdict: ...


class ParentCompletionPolicy:
    def __init__(
        self,
        gate,
        *,
        model_stage=None,
        verifier_budget=1,
        max_source_bytes=262144,
        max_receipts=256,
        max_evidence_children=256,
    ):
        from .parent_completion_protocol import _initialize_policy

        _integer(verifier_budget, "Verifier budget")
        _integer(max_source_bytes, "Parent source bytes", 1, 1_048_576)
        _integer(max_receipts, "Parent receipts", 1, 256)
        _integer(max_evidence_children, "Parent evidence children", 1, 256)
        self.gate, self.model_stage = gate, model_stage
        self.verifier_budget, self.max_source_bytes = verifier_budget, max_source_bytes
        self.max_receipts, self.max_evidence_children = max_receipts, max_evidence_children
        _initialize_policy(self)

    @property
    def identity(self):
        return json.loads(self._identity_json)
