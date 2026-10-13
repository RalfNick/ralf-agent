"""Questions/replies are detached finite control evidence, never tool effects.

Production mutations these tests catch: dispatching a copied-config marker,
accepting remote Schema references, changing a question during reply, allowing
nonfinite/deferred replies, and losing original owner/digest identity on restore.
"""

import copy
import importlib
import importlib.util
import math

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ToolRegistry, ToolSpec
from ralf_agent.types import Scope, digest


def api():
    assert importlib.util.find_spec("ralf_agent.user_input") is not None, (
        "The shared durable input protocol is not implemented"
    )
    return importlib.import_module("ralf_agent.user_input")


def question(*, policy=None, source=None, ordinal=1):
    module = api()
    return module.make_input_record(
        run_id="original-run",
        release_digest="a" * 64,
        scope=Scope("tests", "owner"),
        source=source
        or {"kind": "tool", "action_id": "action-1", "node": 0, "proposal_digest": "b" * 64},
        prompt="Which environment?",
        policy=policy or module.UserInputPolicy(),
        ordinal=ordinal,
    )


def test_question_restores_stable_exact_owner_and_detached_schema():
    module = api()
    original_schema = {"type": "string", "enum": ["test", "production"]}
    policy = module.UserInputPolicy(reply_schema=original_schema)
    original_schema["enum"].append("forged")
    first, second = question(policy=policy), question(policy=policy)
    assert first == second
    assert set(first) == {"request", "state"}
    request = first["request"]
    assert set(request) == {
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
    assert request["owner"] == {
        "run_id": "original-run",
        "release_digest": "a" * 64,
        "scope": {"workspace": "tests", "principal": "owner"},
    }
    assert request["reply_schema"]["enum"] == ["test", "production"]
    assert request["pending_id"].startswith("input:")
    assert module.PendingInput.from_dict(request).to_dict() == request
    policy.identity["reply_schema"]["enum"].append("another-forgery")
    assert policy.identity["reply_schema"]["enum"] == ["test", "production"]
    assert module.UserInputPolicy.from_dict(policy.to_dict()).to_dict() == policy.to_dict()


@pytest.mark.parametrize(
    "field",
    ["owner", "source", "ordinal", "prompt", "reply_schema", "max_reply_bytes", "policy_digest"],
)
def test_tampered_question_identity_is_rejected(field):
    module = api()
    request = question()["request"]
    if field == "owner":
        request[field]["run_id"] = "other-run"
    elif field == "source":
        request[field]["action_id"] = "other-action"
    elif field == "ordinal":
        request[field] = 2
    elif field == "reply_schema":
        request[field] = {"type": "null"}
    elif field == "max_reply_bytes":
        request[field] += 1
    elif field == "policy_digest":
        request[field] = "c" * 64
    else:
        request[field] = "Different question?"
    with pytest.raises(ValidationError):
        module.PendingInput.from_dict(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_requests", 0),
        ("max_requests", 33),
        ("max_requests", True),
        ("max_prompt_chars", 0),
        ("max_prompt_chars", 16385),
        ("max_reply_bytes", 0),
        ("max_reply_bytes", 1048577),
        ("version", " "),
        ("version", False),
    ],
)
def test_policy_bounds_reject_invalid_configuration(field, value):
    with pytest.raises(ValidationError):
        api().UserInputPolicy(**{field: value})


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.invalid/schema"},
        {"$ref": "file:///private/tmp/schema.json"},
        {"$ref": "other.json#/type"},
        {"properties": {"x": {"$ref": "https://example.invalid/schema"}}},
        {"$dynamicRef": "#node"},
        {"$recursiveRef": "#"},
        {"$ref": "#/$defs/missing"},
        {"$ref": "#"},
        {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"},
        {"type": "wrong-type"},
        True,
        [],
    ],
)
def test_schema_references_fail_without_external_resolution(schema):
    with pytest.raises(ValidationError):
        api().UserInputPolicy(reply_schema=schema)


def test_local_schema_fragment_and_finite_recursive_children_are_supported():
    module = api()
    simple = module.UserInputPolicy(
        reply_schema={
            "$defs": {"answer": {"type": "string", "minLength": 1}},
            "$ref": "#/$defs/answer",
        }
    )
    assert module.answered_input(question(policy=simple), "yes", "reply-1")["value"] == "yes"
    tree = module.UserInputPolicy(
        reply_schema={
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/$defs/node"},
                        "value": {"type": "string"},
                    },
                    "additionalProperties": False,
                }
            },
            "$ref": "#/$defs/node",
        }
    )
    reply = {"value": "root", "child": {"value": "leaf"}}
    assert module.answered_input(question(policy=tree), reply, "reply-tree")["value"] == reply


@pytest.mark.parametrize("value", [None, "", " ", False, 1, {}, []])
def test_default_reply_requires_nonempty_text(value):
    with pytest.raises(ValidationError):
        api().answered_input(question(), value, "reply-1")


def test_explicit_null_schema_supports_a_legitimate_null_reply():
    module = api()
    policy = module.UserInputPolicy(reply_schema={"type": "null"})
    assert module.answered_input(question(policy=policy), None, "reply-null")["value"] is None


def test_answer_journal_restores_exact_control_evidence_without_mutating_question():
    module = api()
    pending = question()
    original = copy.deepcopy(pending)
    answered = module.answered_input(pending, "production", "reply-1")
    assert pending == original
    assert answered == {
        **original,
        "state": "answered",
        "value": "production",
        "reply_digest": digest("production"),
        "command_id": "reply-1",
    }
    assert module.validate_input_record(answered) == answered
    answered["value"] = "changed"
    with pytest.raises(ValidationError):
        module.validate_input_record(answered)


@pytest.mark.parametrize("state", ["answered", "cancelled", "unknown"])
def test_only_pending_question_can_prepare_a_new_answer(state):
    module = api()
    record = question()
    if state == "answered":
        record = module.answered_input(record, "test", "reply-1")
    else:
        record["state"] = state
    with pytest.raises(ValidationError):
        module.answered_input(record, "production", "reply-2")


@pytest.mark.parametrize("value", [math.nan, math.inf, {1: "wrong-key"}, object(), ("tuple",)])
def test_ordinary_json_replies_reject_nonfinite_or_deferred_values(value):
    module = api()
    policy = module.UserInputPolicy(reply_schema={})
    with pytest.raises(ValidationError):
        module.answered_input(question(policy=policy), value, "reply-1")


def test_reply_bounds_count_utf8_bytes_and_json_depth():
    module = api()
    policy = module.UserInputPolicy(reply_schema={}, max_reply_bytes=8)
    module.answered_input(question(policy=policy), "中文", "reply-1")
    with pytest.raises(ValidationError):
        module.answered_input(question(policy=policy), "中文字", "reply-2")
    nested = "leaf"
    for _ in range(33):
        nested = [nested]
    with pytest.raises(ValidationError):
        module.answered_input(
            question(policy=module.UserInputPolicy(reply_schema={})), nested, "reply-deep"
        )


def test_reply_payload_detaches_value_and_omits_absent_precondition():
    module = api()
    value = {"environment": "test"}
    payload = module.input_reply_payload("run", "input:" + "a" * 64, "b" * 64, value)
    value["environment"] = "forged"
    assert payload == {
        "run_id": "run",
        "pending_id": "input:" + "a" * 64,
        "digest": "b" * 64,
        "value": {"environment": "test"},
    }
    assert (
        module.input_reply_payload(
            "run", "input:" + "a" * 64, "b" * 64, None, expected_state_revision=0
        )["expected_state_revision"]
        == 0
    )
    with pytest.raises(ValidationError):
        module.input_reply_payload(
            "run", "input:" + "a" * 64, "b" * 64, None, expected_state_revision=True
        )


def test_marker_is_explicit_and_never_dispatches_a_handler():
    module = api()
    registry = ToolRegistry()
    assert module.register_user_input(registry) == "request_input"
    intrinsic = registry.get("request_input")
    assert module.input_tool_policy(intrinsic).to_dict() == module.UserInputPolicy().to_dict()
    assert intrinsic.spec.cost == 0
    assert intrinsic.spec.effect == "read_only"
    assert intrinsic.spec.requires_approval is False
    assert intrinsic.reconciler is None
    with pytest.raises(ValidationError, match="authority"):
        intrinsic.handler({"prompt": "Question?"}, None)
    ordinary = ToolRegistry()
    ordinary.register(intrinsic.spec, lambda arguments, context: "ordinary-result")
    assert module.input_tool_policy(ordinary.get("request_input")) is None
    with pytest.raises(DefinitionMismatch):
        module.register_user_input(registry)


def test_marker_rejects_drifted_descriptor_and_keeps_original_policy_detached():
    module = api()
    registry = ToolRegistry()
    module.register_user_input(registry, name="ask_environment")
    registered = registry.get("ask_environment")
    changed = ToolSpec(**{**registered.spec.__dict__, "cost": 1})
    other = ToolRegistry()
    other.register(changed, registered.handler)
    with pytest.raises(DefinitionMismatch):
        module.input_tool_policy(other.get("ask_environment"))


@pytest.mark.parametrize("state", [[], {}, 0, None, True])
def test_malformed_journal_state_raises_public_validation_error(state):
    record = question()
    record["state"] = state
    with pytest.raises(ValidationError):
        api().validate_input_record(record)


def test_policy_restore_rejects_null_schema_instead_of_substituting_default():
    identity = api().UserInputPolicy().to_dict()
    identity["reply_schema"] = None
    with pytest.raises(ValidationError):
        api().UserInputPolicy.from_dict(identity)


@pytest.mark.parametrize("value", ["\ud800", "\udfff"])
def test_question_proposal_rejects_invalid_unicode_without_serializer_leak(value):
    with pytest.raises(ValidationError):
        api().InputRequestProposal(value)


def test_reply_schema_supports_root_id_and_ref_shaped_literal_data():
    module = api()
    literal = {"$ref": "https://example.invalid/literal-business-value"}
    policy = module.UserInputPolicy(
        reply_schema={
            "$id": "https://example.invalid/declared-reply-schema",
            "$defs": {"answer": {"const": literal}},
            "$ref": "#/$defs/answer",
        }
    )
    assert (
        module.answered_input(question(policy=policy), literal, "reply-literal")["value"] == literal
    )


def test_custom_tool_registry_subclass_keeps_intrinsic_registration_contract():
    class BusinessToolRegistry(ToolRegistry):
        pass

    registry = BusinessToolRegistry()
    assert api().register_user_input(registry, name="ask_customer") == "ask_customer"
    assert (
        api().input_tool_policy(registry.get("ask_customer")).identity
        == api().UserInputPolicy().identity
    )
