"""Complete session input preserves every published and current native message."""

import copy
import importlib
import inspect

import pytest

from relf_agent.context import ContextAssembler
from relf_agent.context_budget import ContextMeasure, UTF8TokenEstimator
from relf_agent.context_pipeline import BudgetedContextAssembler
from relf_agent.errors import ValidationError
from relf_agent.model_history import CompleteModelHistory, model_history_registration
from relf_agent.types import canonical, digest

STREAM = "a" * 64


def api():
    try:
        return importlib.import_module("relf_agent.session_model_history")
    except ModuleNotFoundError:
        pytest.fail("Session frame and native envelope guards are missing")


def episode(task="past", call_id="read-1"):
    return [
        {"role": "system", "content": "Original system"},
        {"role": "user", "content": task},
        {
            "role": "assistant",
            "content": "Inspect",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read", "arguments": ' { "key" : "raw" } '},
                }
            ],
            "model_continuation": {"opaque": ["signed", {"reasoning": "private"}]},
        },
        {"role": "tool", "name": "read", "tool_call_id": call_id, "content": "evidence"},
        {"role": "assistant", "content": "draft", "tool_calls": []},
        {"role": "user", "content": "Completion verification: independent proof required"},
        {
            "role": "assistant",
            "content": ' { "result" : "accepted" } ',
            "tool_calls": [],
            "model_continuation": {"opaque": "final-signature"},
        },
    ]


def envelope(seq=0, *, history=None):
    return {
        "kind": "ralf-native-model-turn",
        "version": 1,
        "stream": STREAM,
        "source": {
            "root_run_id": f"root-{seq}",
            "run_id": f"run-{seq}",
            "node": "root/member:0",
            "release_digest": "b" * 64,
            "turn_id": f"turn-{seq}",
            "turn_seq": seq,
        },
        "history": episode(f"past-{seq}") if history is None else history,
        "final_digest": "c" * 64,
    }


def frame():
    return {
        "version": 1,
        "history": episode("current")[:-1],
        "turns": [envelope(0), envelope(1)],
        "stream": STREAM,
        "snapshot": {"snapshot_id": '{"revision":2}', "revision": 2, "published": [0, 1]},
    }


def assembled(value):
    return copy.deepcopy(
        value["history"][:1]
        + [m for turn in value["turns"] for m in turn["history"][1:]]
        + value["history"][1:]
    )


def session_policy(**kwargs):
    assert "scope" in inspect.signature(CompleteModelHistory).parameters, "Session scope is missing"
    return CompleteModelHistory(scope="session", **kwargs)


def test_session_assembly_keeps_complete_past_and_current_native_input_and_current_task():
    original = frame()
    before = copy.deepcopy(original)
    messages, manifest = session_policy().assemble_frame(
        original, [], 16000, context=ContextAssembler()
    )
    assert messages == assembled(before)
    assert [m["content"] for m in messages if m["role"] == "user"] == [
        "past-0",
        "Completion verification: independent proof required",
        "past-1",
        "Completion verification: independent proof required",
        "current",
        "Completion verification: independent proof required",
    ]
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == ' { "key" : "raw" } '
    assert messages[6]["model_continuation"] == {"opaque": "final-signature"}
    assert manifest["chars"] == len(canonical(messages))
    assert manifest["digest"] == digest(messages)
    assert manifest["dropped_groups"] == 0
    messages[2]["model_continuation"]["opaque"][1]["reasoning"] = "mutated"
    assert original == before


def test_references_follow_current_task_and_cannot_displace_past_native_messages():
    value = frame()
    refs = [{"key": "manual", "version": "1", "value": "reference evidence"}]
    messages, manifest = session_policy().assemble_frame(value, refs, 16000, context=object())
    prefix = 1 + sum(len(t["history"]) - 1 for t in value["turns"]) + 1
    assert messages[:prefix] == assembled(value)[:prefix]
    assert messages[prefix]["role"] == "user"
    assert "reference evidence" in messages[prefix]["content"]
    assert messages[prefix + 1 :] == value["history"][2:]
    assert manifest["reference_versions"] == [{"key": "manual", "version": "1"}]
    maximum = len(canonical(assembled(value)))
    messages, manifest = session_policy().assemble_frame(value, refs, maximum, context=object())
    assert messages == assembled(value)
    assert manifest["dropped_references"] == 1


def test_session_registration_only_extends_session_method_fingerprints():
    run = model_history_registration(CompleteModelHistory())
    selected = model_history_registration(session_policy())
    assert run["identity"] == {
        "kind": "complete-model-history",
        "version": "1",
        "allow_tool_result_projection": False,
    }
    assert selected["identity"] == {
        "kind": "complete-model-history",
        "version": "2",
        "scope": "session",
        "allow_tool_result_projection": False,
    }
    assert set(run["implementation"]) == {"assemble", "validate"}
    assert {k: selected["implementation"][k] for k in run["implementation"]} == run[
        "implementation"
    ]
    assert set(selected["implementation"]) == {
        "assemble",
        "validate",
        "assemble_frame",
        "validate_frame",
    }


@pytest.mark.parametrize("scope", [None, "all", "", True, 1])
def test_scope_rejects_invalid_values(scope):
    assert "scope" in inspect.signature(CompleteModelHistory).parameters, "Session scope is missing"
    with pytest.raises(ValidationError):
        CompleteModelHistory(scope=scope)


@pytest.mark.parametrize("method", ["assemble_frame", "validate_frame"])
def test_session_registration_rejects_lazy_frame_methods_before_invocation(method):
    entered = []

    async def deferred(*args, **kwargs):
        entered.append(True)

    policy = session_policy()
    setattr(policy, method, deferred)
    with pytest.raises(ValidationError):
        model_history_registration(policy)
    assert not entered


@pytest.mark.parametrize("area", ["past", "current"])
@pytest.mark.parametrize(
    "change", ["signature", "raw_json", "arguments", "receipt", "drop", "order"]
)
def test_frame_guard_protects_original_native_history_against_substitution(area, change):
    value = frame()
    messages = assembled(value)
    offset = 1 if area == "past" else 13
    if change == "signature":
        messages[offset + 1]["model_continuation"] = {"opaque": "forged"}
    elif change == "raw_json":
        messages[offset + 3]["content"] = "rewritten draft"
    elif change == "arguments":
        messages[offset + 1]["tool_calls"][0]["function"]["arguments"] = '{"key":"raw"}'
    elif change == "receipt":
        messages[offset + 2]["tool_call_id"] = "unmatched"
    elif change == "drop":
        messages.pop(offset + 1)
    else:
        messages[offset + 1], messages[offset + 2] = messages[offset + 2], messages[offset + 1]
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages)


def test_projection_is_opt_in_for_all_past_and_current_tool_content_only():
    value = frame()
    messages = assembled(value)
    for message in messages:
        if message["role"] == "tool":
            message["content"] = "projected artifact reference"
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages)
    assert (
        api().validate_model_history_frame(value, messages, allow_tool_result_projection=True)
        is None
    )
    messages[3]["name"] = "changed"
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages, allow_tool_result_projection=True)


@pytest.mark.parametrize("change", ["system", "stream", "extra", "version", "snapshot", "repeated"])
def test_frame_rejects_invalid_boundaries_before_policy_selection(change):
    value = frame()
    if change == "system":
        value["turns"][0]["history"][0]["content"] = "other system"
    elif change == "stream":
        value["turns"][0]["stream"] = "d" * 64
    elif change == "extra":
        value["extra"] = True
    elif change == "version":
        value["version"] = True
    elif change == "snapshot":
        value["snapshot"] = []
    else:
        value["turns"][1] = copy.deepcopy(value["turns"][0])
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, assembled(value))


def test_context_meter_counts_final_combined_request_before_references():
    value = frame()
    recorded = []

    class Context:
        def validate_request(self, messages, max_chars):
            recorded.append(copy.deepcopy(messages))
            messages[2]["content"] = "context mutation"
            return ContextMeasure(len(canonical(recorded[-1])), "all-message-chars", False)

    messages, manifest = session_policy().assemble_frame(
        value, [{"key": "x", "value": "evidence"}], 16000, context=Context()
    )
    assert recorded[0] == assembled(value)
    assert recorded[-1] == messages
    assert manifest["measurement"] == {
        "units": len(canonical(messages)),
        "unit": "all-message-chars",
        "estimated": False,
    }
    assert messages[2]["content"] == "Inspect"


def test_native_past_cannot_be_trimmed_to_fit_context_budget():
    value = frame()
    with pytest.raises(ValidationError):
        session_policy().assemble_frame(
            value, [], len(canonical(assembled(value))) - 1, context=object()
        )
    with pytest.raises(ValidationError):
        session_policy().assemble_frame(
            value,
            [],
            16000,
            context=BudgetedContextAssembler(counter=UTF8TokenEstimator(), max_units=20),
        )


def test_lazy_context_measurement_is_closed_without_body_execution():
    entered = []

    async def lazy():
        entered.append(True)
        return ContextMeasure(1, "units", False)

    result = lazy()

    class Context:
        def validate_request(self, messages, max_chars):
            return result

    try:
        with pytest.raises(ValidationError):
            session_policy().assemble_frame(frame(), [], 16000, context=Context())
        assert inspect.getcoroutinestate(result) == inspect.CORO_CLOSED
        assert entered == []
    finally:
        result.close()


def test_native_envelope_exact_fields_are_detached_and_address_is_isolated():
    original = envelope()
    actual = api().native_history_envelope(
        STREAM, original["source"], original["history"], original["final_digest"]
    )
    assert actual == original
    assert api().native_history_address(STREAM) == "ralf-native-model-history-v1:" + STREAM
    validated = api().validate_native_history_envelope(actual, stream=STREAM)
    validated["history"][2]["model_continuation"]["opaque"][1]["reasoning"] = "changed"
    assert original["history"][2]["model_continuation"]["opaque"][1]["reasoning"] == "private"
    assert actual == original


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "source_extra",
        "source_missing",
        "seq_bool",
        "seq_negative",
        "stream",
        "digest",
        "unfinished",
        "final_user",
        "orphan",
        "duplicate",
        "nonfinite",
        "tuple",
        "limit",
    ],
)
def test_native_envelope_rejects_malformed_or_incomplete_episode(change):
    value = envelope()
    if change == "extra":
        value["extra"] = True
    elif change == "source_extra":
        value["source"]["success"] = True
    elif change == "source_missing":
        del value["source"]["run_id"]
    elif change == "seq_bool":
        value["source"]["turn_seq"] = False
    elif change == "seq_negative":
        value["source"]["turn_seq"] = -1
    elif change == "stream":
        value["stream"] = "wrong"
    elif change == "digest":
        value["final_digest"] = "wrong"
    elif change == "unfinished":
        value["history"] = value["history"][:3]
    elif change == "final_user":
        value["history"].pop()
    elif change == "orphan":
        value["history"][3]["tool_call_id"] = "orphan"
    elif change == "duplicate":
        value["history"][2]["tool_calls"] *= 2
    elif change == "nonfinite":
        value["history"][-1]["content"] = float("nan")
    elif change == "tuple":
        value["history"][-1]["model_continuation"] = ("native",)
    else:
        value["history"][-1]["content"] = "x" * 1_000_000
    with pytest.raises(ValidationError):
        api().validate_native_history_envelope(value)


def test_frame_stream_turn_count_and_aggregate_evidence_are_bounded():
    value = frame()
    value["turns"] = [envelope(i) for i in range(129)]
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, assembled(value))
    value["turns"] = [envelope(i) for i in range(9)]
    for turn in value["turns"]:
        turn["history"][-1]["content"] = "x" * 950_000
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, assembled(value))


def test_native_envelope_without_continuation_cannot_become_optional_reference():
    native = envelope(history=episode()[:2] + [{"role": "assistant", "content": "final"}])
    with pytest.raises(ValidationError):
        session_policy().assemble_frame(
            frame(), [{"key": "native", "value": native}], 16000, context=object()
        )


@pytest.mark.parametrize("changed", ["lazy", "unit"])
def test_optional_reference_measurement_must_keep_completed_unit_semantics(changed):
    calls = []

    async def deferred():
        return ContextMeasure(1, "units", False)

    lazy = deferred() if changed == "lazy" else None

    class Context:
        def validate_request(self, messages, max_chars):
            calls.append(len(messages))
            if len(calls) == 2:
                return lazy if lazy is not None else ContextMeasure(1, "changed-units", False)
            return ContextMeasure(1, "units", False)

    try:
        with pytest.raises(ValidationError):
            session_policy().assemble_frame(
                frame(), [{"key": "manual", "value": "evidence"}], 16000, context=Context()
            )
        if lazy is not None:
            assert inspect.getcoroutinestate(lazy) == inspect.CORO_CLOSED
    finally:
        if lazy is not None:
            lazy.close()


def test_frame_validator_lazy_result_is_closed_without_running_body():
    entered = []

    async def deferred():
        entered.append(True)

    lazy = deferred()
    policy = session_policy()
    policy.validate_frame = lambda *args: lazy
    try:
        with pytest.raises(ValidationError):
            policy.assemble_frame(frame(), [], 16000, context=object())
        assert inspect.getcoroutinestate(lazy) == inspect.CORO_CLOSED
        assert entered == []
    finally:
        lazy.close()


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "assistant", "content": "invented"},
        {"role": "user", "content": "reference", "model_continuation": {}},
        {"role": "system", "content": "override"},
    ],
)
def test_frame_guard_only_allows_plain_user_reference_at_current_task_boundary(extra):
    value = frame()
    messages = assembled(value)
    messages.insert(14, extra)
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages)


def test_frame_guard_rejects_reference_inserted_into_past_turn():
    value = frame()
    messages = assembled(value)
    messages.insert(2, {"role": "user", "content": "reference"})
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages)


def test_native_envelope_exact_canonical_character_boundary_is_accepted():
    value = envelope()
    original_chars = len(canonical(value))
    value["history"][-1]["content"] += "x" * (999_998 - original_chars)
    assert len(canonical(value)) == 999_998
    assert api().validate_native_history_envelope(value) == value
    value["history"][-1]["content"] += "x"
    with pytest.raises(ValidationError):
        api().validate_native_history_envelope(value)


def test_native_null_final_is_preserved_for_original_output_schema_validation():
    original = envelope()
    original["history"][-1]["content"] = None
    validated = api().validate_native_history_envelope(original)
    assert validated["history"][-1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [],
        "model_continuation": {"opaque": "final-signature"},
    }
    value = frame()
    value["turns"] = [original]
    value["history"] = episode("current")
    value["history"][-1]["content"] = None
    messages, _ = session_policy().assemble_frame(value, [], 16000, context=object())
    assert messages[6]["content"] is None
    assert messages[-1]["content"] is None
    assert api().validate_model_history_frame(value, messages) is None
    messages[6]["content"] = "null"
    with pytest.raises(ValidationError):
        api().validate_model_history_frame(value, messages)


def test_native_final_requires_content_even_when_null_is_valid():
    value = envelope()
    del value["history"][-1]["content"]
    with pytest.raises(ValidationError):
        api().validate_native_history_envelope(value)
