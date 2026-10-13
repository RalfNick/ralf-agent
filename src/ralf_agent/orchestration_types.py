"""Finite caller definitions and detached proposals for managed child Runs."""

import json
import re
from typing import Protocol

from .errors import ValidationError
from .recall import _integer
from .types import _require_text, canonical, credits


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", value):
        raise ValidationError("Members and calls require stable identifiers")
    return value


class _JsonValue:
    def __setattr__(self, name, value):
        if "_data_json" in self.__dict__:
            raise AttributeError("Orchestration values are immutable")
        object.__setattr__(self, name, value)

    def to_dict(self):
        return json.loads(self._data_json)

    def __getattr__(self, name):
        value = self.to_dict()
        if name in value:
            return value[name]
        raise AttributeError(name)


def _definition(name, members, version, child_budget, max_concurrency, max_depth):
    from .spec_codec import encode_spec, validate_definition_tree

    _require_text(name, "Orchestration name")
    _require_text(version, "Orchestration version")
    credits(child_budget)
    _integer(max_concurrency, "Child concurrency", 1, 64)
    if not isinstance(members, dict) or not 1 <= len(members) <= 64:
        raise ValidationError("Register 1 to 64 named Agent members")
    prepared = {}
    for alias, member in members.items():
        _identifier(alias)
        prepared[alias] = encode_spec(member)
    extra = {}
    if max_depth is not None:
        _integer(max_depth, "Nested depth limit", 1, 8)
        extra["max_depth"] = max_depth
    if any(value.get("kind", "agent") != "agent" for value in prepared.values()):
        validate_definition_tree({"kind": "team", "members": prepared})
    return {
        "name": name,
        "version": version,
        "members": prepared,
        "member_order": list(prepared),
        "child_budget": child_budget,
        "max_concurrency": max_concurrency,
        **extra,
    }


def _load_definition(cls, value, kind):
    from .spec_codec import decode_spec, validate_definition_tree

    if not isinstance(value, dict):
        raise ValidationError("Orchestration declarations must be JSON objects")
    value = validate_definition_tree(value)
    if value.pop("kind", kind) != kind:
        raise ValidationError("Unexpected orchestration declaration kind")
    try:
        members = value.pop("members")
        order = value.pop("member_order", list(members))
        if (
            not isinstance(members, dict)
            or not isinstance(order, list)
            or any(not isinstance(name, str) for name in order)
            or len(order) != len(set(order))
            or set(order) != set(members)
        ):
            raise ValidationError("Member order must list each registered member exactly once")
        return cls(members={name: decode_spec(members[name]) for name in order}, **value)
    except (TypeError, KeyError) as exc:
        raise ValidationError("Invalid orchestration declaration fields") from exc


class TeamSpec(_JsonValue):
    @classmethod
    def from_dict(cls, value):
        return _load_definition(cls, value, "team")

    def __init__(
        self,
        name,
        members,
        *,
        strategy="sequential",
        strategy_config=None,
        child_budget=8,
        max_concurrency=1,
        max_depth=None,
        version="1",
        completion_policy=None,
    ):
        _require_text(strategy, "Team strategy")
        if completion_policy is not None:
            _require_text(completion_policy, "Parent completion policy")
        config = {} if strategy_config is None else strategy_config
        if not isinstance(config, dict):
            raise ValidationError("Team strategy config must be a JSON object")
        self._data_json = canonical(
            {
                "kind": "team",
                **_definition(name, members, version, child_budget, max_concurrency, max_depth),
                "strategy": strategy,
                "strategy_config": config,
                **(
                    {"completion_policy": completion_policy}
                    if completion_policy is not None
                    else {}
                ),
            }
        )


class DynamicWorkflowSpec(_JsonValue):
    @classmethod
    def from_dict(cls, value):
        return _load_definition(cls, value, "dynamic")

    def __init__(
        self,
        name,
        members,
        *,
        planner="rule",
        verifier="complete",
        child_budget=8,
        max_revisions=3,
        max_steps=32,
        max_concurrency=1,
        max_depth=None,
        plan_mode="flat",
        version="1",
        completion_policy=None,
        input_policy=None,
    ):
        _require_text(planner, "Planner")
        _require_text(verifier, "Plan verifier")
        if completion_policy is not None:
            _require_text(completion_policy, "Parent completion policy")
        if input_policy is not None:
            _require_text(input_policy, "User input policy")
        _integer(max_revisions, "Plan revision limit", 1, 32)
        _integer(max_steps, "Plan step limit", 1, 256)
        if plan_mode not in {"flat", "dag"}:
            raise ValidationError("Plan mode must be flat or dag")
        if plan_mode == "dag" and planner == "rule":
            planner = "dag-rule"
        self._data_json = canonical(
            {
                "kind": "dynamic",
                **_definition(name, members, version, child_budget, max_concurrency, max_depth),
                "planner": planner,
                "verifier": verifier,
                "max_revisions": max_revisions,
                "max_steps": max_steps,
                **({"plan_mode": "dag"} if plan_mode == "dag" else {}),
                **(
                    {"completion_policy": completion_policy}
                    if completion_policy is not None
                    else {}
                ),
                **({"input_policy": input_policy} if input_policy is not None else {}),
            }
        )


class ChildCall(_JsonValue):
    def __init__(self, id, member, input):
        _identifier(id)
        if member not in ("@planner", "@verifier"):
            _identifier(member)
        self._data_json = canonical({"id": id, "member": member, "input": input})


class TeamRequest(_JsonValue):
    def __init__(self, task, members, results, config):
        self._data_json = canonical(
            {
                "task": task,
                "members": list(members),
                "results": results,
                "config": config,
            }
        )


class TeamSelection(_JsonValue):
    def __init__(self, calls=(), *, done=False, result=None):
        if (
            not isinstance(calls, (tuple, list))
            or len(calls) > 64
            or any(not isinstance(call, ChildCall) for call in calls)
            or type(done) is not bool
            or (done and calls)
            or (not done and not calls)
        ):
            raise ValidationError("Team selection requires finite calls or a final result")
        self._data_json = canonical(
            {
                "calls": [call.to_dict() for call in calls],
                "done": done,
                "result": result,
            }
        )


class AgentCaller(Protocol):
    async def call(self, call_id: str, member: str, input) -> object: ...


class TeamStrategy(Protocol):
    identity: dict

    def select(self, request: TeamRequest) -> TeamSelection: ...
