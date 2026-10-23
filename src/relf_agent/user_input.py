"""Pure bounded user-input values; execution authorities own their journals.

An intrinsic marker proposes a question. It never waits, executes an external
effect or receives an answer itself. Local/Temporal adopt and answer it using
their original command and transcript boundaries.
"""

import json
import re
from dataclasses import asdict

from jsonschema import Draft202012Validator

from .errors import DefinitionMismatch, ValidationError
from .orchestration_types import _JsonValue
from .tools import RegisteredTool, ToolRegistry, ToolSpec
from .types import Scope, canonical, digest

_POLICY_FIELDS = {
    "kind",
    "version",
    "reply_schema",
    "max_requests",
    "max_prompt_chars",
    "max_reply_bytes",
}
_REQUEST_FIELDS = {
    "schema_version",
    "pending_id",
    "target_digest",
    "owner",
    "source",
    "ordinal",
    "prompt",
    "reply_schema",
    "max_reply_bytes",
    "policy_digest",
}
_MAX_REPLY_BYTES = 1_048_576
_DESCRIPTION = (
    "Ask the user for required information and pause this Run until they reply. "
    "Call this tool alone, without any other tool calls in the same response."
)


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"Invalid user input {label}")


def _text(value, label, maximum=16384):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValidationError(f"Invalid user input {label}")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"User input {label} requires valid Unicode") from exc


def _sha(value, label):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError(f"User input {label} requires a SHA-256 digest")


def _json(value, *, max_bytes=_MAX_REPLY_BYTES, max_depth=32):
    def check(item, depth):
        if depth > max_depth:
            raise ValidationError("User input JSON exceeds depth limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValidationError("User input JSON keys must be strings")
            for nested in item.values():
                check(nested, depth + 1)
        elif type(item) is list:
            for nested in item:
                check(nested, depth + 1)
        elif item is not None and type(item) not in {str, bool, int, float}:
            raise ValidationError("User input requires completed ordinary JSON")

    try:
        check(value, 0)
        encoded = canonical(value)
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ValidationError("User input JSON exceeds byte limit")
        return json.loads(encoded)
    except (RecursionError, UnicodeError, ValueError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("User input requires bounded finite ordinary JSON") from exc


def _schema(value):
    """Validate local Schema resources without invoking a resolver or network.

    Local JSON pointers and recursive child schemas are supported. References
    which recurse on the same instance are rejected, as are resource rebinding
    and dynamic references; neither is necessary for a bounded reply Schema.
    """
    value = _json(value, max_bytes=65536)
    if type(value) is not dict:
        raise ValidationError("User input reply Schema must be an object")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ValidationError("Invalid user input reply Schema") from exc

    nodes = {}
    edges = {}

    def target(reference):
        if type(reference) is not str or not (reference == "#" or reference.startswith("#/")):
            raise ValidationError("User input Schema references must be local JSON pointers")
        resolved = value
        try:
            for token in reference[2:].split("/") if reference != "#" else ():
                if re.search(r"~(?![01])", token):
                    raise KeyError(token)
                token = token.replace("~1", "/").replace("~0", "~")
                if type(resolved) is list and re.fullmatch(r"0|[1-9][0-9]*", token):
                    resolved = resolved[int(token)]
                else:
                    resolved = resolved[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValidationError("User input Schema reference target is missing") from exc
        if type(resolved) not in {dict, bool}:
            raise ValidationError("User input Schema reference must identify a Schema")
        return resolved

    single = {
        "items",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "unevaluatedItems",
        "additionalItems",
    }
    multiple = {"allOf", "anyOf", "oneOf", "prefixItems"}
    maps = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
    same_instance = {"not", "if", "then", "else", "allOf", "anyOf", "oneOf", "dependentSchemas"}

    def visit(node):
        if type(node) is bool or id(node) in nodes:
            return
        nodes[id(node)] = node
        edges[id(node)] = []
        if any(keyword in node for keyword in ("$dynamicRef", "$recursiveRef")) or (
            node is not value and "$id" in node
        ):
            raise ValidationError(
                "User input Schema cannot rebind or dynamically resolve resources"
            )
        if "$ref" in node:
            referred = target(node["$ref"])
            if type(referred) is dict:
                edges[id(node)].append(id(referred))
            visit(referred)
        for keyword in single | multiple | maps:
            declared = node.get(keyword)
            if keyword in single:
                children = [declared] if type(declared) in {dict, bool} else []
                if keyword == "items" and type(declared) is list:
                    children = declared
            elif keyword in multiple:
                children = declared if type(declared) is list else []
            else:
                children = list(declared.values()) if type(declared) is dict else []
            for child in children:
                if type(child) not in {dict, bool}:
                    continue
                if keyword in same_instance and type(child) is dict:
                    edges[id(node)].append(id(child))
                visit(child)

    try:
        visit(value)
        active, complete = set(), set()

        def acyclic(node_id):
            if node_id in active:
                raise ValidationError("User input Schema contains a same-instance reference cycle")
            if node_id in complete:
                return
            active.add(node_id)
            for next_id in edges[node_id]:
                acyclic(next_id)
            active.remove(node_id)
            complete.add(node_id)

        for node_id in nodes:
            acyclic(node_id)
    except RecursionError as exc:
        raise ValidationError("User input Schema graph exceeds validation limits") from exc
    return value


class UserInputPolicy(_JsonValue):
    def __init__(
        self,
        reply_schema=None,
        *,
        version="1",
        max_requests=8,
        max_prompt_chars=4096,
        max_reply_bytes=65536,
    ):
        _text(version, "policy version", 128)
        _integer(max_requests, "request limit", 1, 32)
        _integer(max_prompt_chars, "prompt limit", 1, 16384)
        _integer(max_reply_bytes, "reply byte limit", 1, _MAX_REPLY_BYTES)
        schema = _schema(
            {"type": "string", "minLength": 1, "pattern": r"\S"}
            if reply_schema is None
            else reply_schema
        )
        self._data_json = canonical(
            {
                "kind": "user-input-policy",
                "version": version,
                "reply_schema": schema,
                "max_requests": max_requests,
                "max_prompt_chars": max_prompt_chars,
                "max_reply_bytes": max_reply_bytes,
            }
        )

    @property
    def identity(self):
        return self.to_dict()

    @classmethod
    def from_dict(cls, value):
        if (
            type(value) is not dict
            or set(value) != _POLICY_FIELDS
            or value["kind"] != "user-input-policy"
        ):
            raise ValidationError("Invalid user input policy identity")
        if type(value["reply_schema"]) is not dict:
            raise ValidationError("Stored user input policy requires its original Schema")
        return cls(**{key: item for key, item in value.items() if key != "kind"})


class InputRequestProposal(_JsonValue):
    def __init__(self, prompt):
        _text(prompt, "prompt")
        self._data_json = canonical({"prompt": prompt})

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {"prompt"}:
            raise ValidationError("Input proposal requires an exact prompt")
        return cls(value["prompt"])


def _owner(run_id, release_digest, scope):
    _text(run_id, "Run ID", 1024)
    _sha(release_digest, "release")
    scope = asdict(scope) if type(scope) is Scope else _json(scope, max_bytes=4096, max_depth=2)
    if type(scope) is not dict or set(scope) != {"workspace", "principal"}:
        raise ValidationError("User input requires the original trusted Scope")
    for part in scope.values():
        _text(part, "Scope", 1024)
    return {"run_id": run_id, "release_digest": release_digest, "scope": scope}


def _source(value):
    value = _json(value, max_bytes=8192, max_depth=2)
    if type(value) is not dict:
        raise ValidationError("User input requires an original source")
    if value.get("kind") == "tool" and set(value) == {
        "kind",
        "action_id",
        "node",
        "proposal_digest",
    }:
        _text(value["action_id"], "source Action", 1024)
        node = value["node"]
        if type(node) is int:
            _integer(node, "source node", 0, 1_000_000)
        elif node is not None:
            _text(node, "source node", 1024)
    elif value.get("kind") == "planner" and set(value) == {"kind", "revision", "proposal_digest"}:
        _integer(value["revision"], "planning revision", 0, 31)
    else:
        raise ValidationError("User input source fields are incomplete or undeclared")
    _sha(value["proposal_digest"], "source proposal")
    return value


def _pending_id(owner, source, ordinal):
    return "input:" + digest(
        {"schema_version": 1, "owner": owner, "source": source, "ordinal": ordinal}
    )


class PendingInput(_JsonValue):
    @classmethod
    def from_dict(cls, value):
        if (
            type(value) is not dict
            or set(value) != _REQUEST_FIELDS
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValidationError("Invalid pending input fields or protocol")
        owner = value["owner"]
        if type(owner) is not dict or set(owner) != {"run_id", "release_digest", "scope"}:
            raise ValidationError("Pending input requires its exact owner")
        owner = _owner(**owner)
        source = _source(value["source"])
        _integer(value["ordinal"], "ordinal", 1, 32)
        _text(value["prompt"], "prompt")
        _integer(value["max_reply_bytes"], "reply byte limit", 1, _MAX_REPLY_BYTES)
        _sha(value["policy_digest"], "policy")
        _sha(value["target_digest"], "target")
        schema = _schema(value["reply_schema"])
        if value["pending_id"] != _pending_id(owner, source, value["ordinal"]):
            raise ValidationError("Pending input differs from its original source identity")
        data = {
            **value,
            "owner": owner,
            "source": source,
            "reply_schema": schema,
        }
        if value["target_digest"] != digest(
            {key: item for key, item in data.items() if key != "target_digest"}
        ):
            raise ValidationError("Pending input differs from its original target digest")
        instance = cls.__new__(cls)
        instance._data_json = canonical(data)
        return instance


def make_input_record(*, run_id, release_digest, scope, source, prompt, policy, ordinal):
    if type(policy) is not UserInputPolicy:
        raise ValidationError("User input requires an explicit UserInputPolicy")
    _integer(ordinal, "ordinal", 1, policy.max_requests)
    _text(prompt, "prompt", policy.max_prompt_chars)
    owner = _owner(run_id, release_digest, scope)
    source = _source(source)
    data = {
        "schema_version": 1,
        "pending_id": _pending_id(owner, source, ordinal),
        "owner": owner,
        "source": source,
        "ordinal": ordinal,
        "prompt": prompt,
        "reply_schema": policy.reply_schema,
        "max_reply_bytes": policy.max_reply_bytes,
        "policy_digest": digest(policy.identity),
    }
    data["target_digest"] = digest(data)
    return {"request": PendingInput.from_dict(data).to_dict(), "state": "pending"}


def _reply(request, value):
    value = _json(value, max_bytes=request["max_reply_bytes"])
    try:
        Draft202012Validator(request["reply_schema"]).validate(value)
    except Exception as exc:
        raise ValidationError("Reply does not match the original user input Schema") from exc
    return value


def validate_input_record(record):
    if type(record) is not dict:
        raise ValidationError("Invalid user input journal")
    state = record.get("state")
    if type(state) is not str:
        raise ValidationError("Invalid user input journal state")
    fields = {"request", "state"}
    if state == "answered":
        fields |= {"value", "reply_digest", "command_id"}
    elif state not in {"pending", "cancelled"}:
        raise ValidationError("Invalid user input journal state")
    if set(record) != fields:
        raise ValidationError("User input journal fields are incomplete or undeclared")
    request = PendingInput.from_dict(record["request"]).to_dict()
    data = {"request": request, "state": state}
    if state == "answered":
        _text(record["command_id"], "reply command", 1024)
        value = _reply(request, record["value"])
        if record["reply_digest"] != digest(value):
            raise ValidationError("User reply differs from its original digest")
        data.update(
            value=value, reply_digest=record["reply_digest"], command_id=record["command_id"]
        )
    return data


def answered_input(record, value, command_id):
    record = validate_input_record(record)
    if record["state"] != "pending":
        raise ValidationError("Only a pending question can prepare a reply")
    _text(command_id, "reply command", 1024)
    value = _reply(record["request"], value)
    return {
        **record,
        "state": "answered",
        "value": value,
        "reply_digest": digest(value),
        "command_id": command_id,
    }


def validate_clarifications(records, *, max_records=256, scope=None):
    """Detach answered lineage; actual descendant ownership stays authoritative."""
    _integer(max_records, "clarification limit", 1, 256)
    if type(records) is not list or len(records) > max_records:
        raise ValidationError("Clarifications require a bounded list of answered journals")
    detached, seen, ordinals = [], set(), {}
    for original in records:
        record = validate_input_record(original)
        request = record["request"]
        if record["state"] != "answered" or request["pending_id"] in seen:
            raise ValidationError("Clarifications require unique answered requests")
        if scope is not None and request["owner"]["scope"] != scope:
            raise ValidationError("Clarification lineage differs from original parent Scope")
        source = request["source"]
        lane = (digest(request["owner"]), source["kind"], source.get("node"))
        if request["ordinal"] <= ordinals.get(lane, 0):
            raise ValidationError("Clarifications must retain their original question order")
        ordinals[lane] = request["ordinal"]
        seen.add(request["pending_id"])
        detached.append(record)
    return detached


def input_reply_payload(run_id, pending_id, target_digest, value, *, expected_state_revision=None):
    _text(run_id, "Run ID", 1024)
    if type(pending_id) is not str or re.fullmatch(r"input:[0-9a-f]{64}", pending_id) is None:
        raise ValidationError("Reply requires an original pending input identity")
    _sha(target_digest, "target")
    value = _json(value)
    data = {"run_id": run_id, "pending_id": pending_id, "digest": target_digest, "value": value}
    if expected_state_revision is not None:
        _integer(expected_state_revision, "expected revision", 0, 2**63 - 1)
        data["expected_state_revision"] = expected_state_revision
    return data


class UserInputHandler(_JsonValue):
    """Trusted intrinsic marker with immutable policy, never an executable tool."""

    def __init__(self, policy):
        if type(policy) is not UserInputPolicy:
            raise ValidationError("Intrinsic input tool requires an explicit policy")
        self._data_json = canonical(policy.to_dict())

    @property
    def policy(self):
        return UserInputPolicy.from_dict(self.to_dict())

    def __call__(self, arguments, context):
        raise ValidationError("The original execution authority must handle user input")


def _tool_spec(name, policy):
    _text(name, "tool name", 128)
    return ToolSpec(
        name,
        _DESCRIPTION,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["prompt"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": policy.max_prompt_chars,
                    "pattern": r"\S",
                }
            },
        },
        version=policy.version,
        effect="read_only",
        requires_approval=False,
        cost=0,
        config={"user_input": policy.to_dict()},
    )


def register_user_input(registry, *, name="request_input", policy=None):
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("Register user input into an original ToolRegistry")
    policy = UserInputPolicy() if policy is None else policy
    if type(policy) is not UserInputPolicy:
        raise ValidationError("Register an explicit UserInputPolicy")
    registry.register(_tool_spec(name, policy), UserInputHandler(policy))
    return name


def input_tool_policy(tool):
    if type(tool) is not RegisteredTool:
        raise ValidationError("Inspect an original registered tool")
    if type(tool.handler) is not UserInputHandler:
        return None
    policy = tool.handler.policy
    if tool.spec != _tool_spec(tool.spec.name, policy) or tool.reconciler is not None:
        raise DefinitionMismatch("Intrinsic user input descriptor differs from its fixed policy")
    return policy
