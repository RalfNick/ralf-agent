"""Shared native evidence rules, independent of storage and Run authority."""

import json

import pytest

from ralf_agent.errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from ralf_agent.types import canonical


def test_submission_permission_is_not_reissued_or_reset_after_receipt():
    from ralf_agent.runner_journal_state import new_record, receive_record, submit_record

    record = new_record(("w", "p", "e"), canonical({"version": 1}))
    record, execute = submit_record(record, "intent", "thread_submitted")
    assert execute is True
    duplicate, execute = submit_record(record, "intent", "thread_submitted")
    assert execute is False and duplicate == record
    record = receive_record(
        record, {"thread_id": "t", "process_epoch": "owner"}, "thread_submitted", "thread_confirmed"
    )
    later, execute = submit_record(record, "intent", "thread_submitted")
    assert execute is False and later["stage"] == "thread_confirmed"


def test_applied_cancel_prevents_next_submission_but_keeps_late_receipt():
    from ralf_agent.runner_journal_state import (
        cancel_record,
        new_record,
        receive_record,
        submit_record,
    )

    record = new_record(("w", "p", "e"), canonical({"version": 1}))
    record, _ = submit_record(record, "intent", "thread_submitted")
    record = cancel_record(record)
    record = receive_record(
        record, {"thread_id": "t", "process_epoch": "owner"}, "thread_submitted", "thread_confirmed"
    )
    with pytest.raises(ValidationError):
        submit_record(record, "thread_confirmed", "turn_submitted")
    assert record["cancel_requested"] is True


def test_receipt_and_observation_remain_bound_to_original_native_handle():
    from ralf_agent.runner_journal_state import (
        append_observation,
        new_record,
        receive_record,
        submit_record,
    )

    record = new_record(("w", "p", "e"), canonical({"version": 1}))
    record, _ = submit_record(record, "intent", "thread_submitted")
    record = receive_record(
        record, {"thread_id": "t", "process_epoch": "owner"}, "thread_submitted", "thread_confirmed"
    )
    with pytest.raises(IdempotencyConflict):
        receive_record(
            record,
            {"thread_id": "other", "process_epoch": "owner"},
            "thread_submitted",
            "thread_confirmed",
        )
    with pytest.raises(IdempotencyConflict):
        append_observation(record, canonical({"thread_id": "other"}))
    once = append_observation(record, canonical({"thread_id": "t", "kind": "ack"}))
    twice = append_observation(once, canonical({"thread_id": "t", "kind": "ack"}))
    assert len(twice["observations"]) == 1


def test_saved_record_requires_original_scope_effect_and_binding():
    from ralf_agent.runner_journal_state import new_record, validate_record

    key, binding = ("w", "p", "e"), canonical({"version": 1})
    record = new_record(key, binding)
    assert validate_record(canonical(record), key, binding) == record
    with pytest.raises(IdempotencyConflict):
        validate_record(canonical(record), key, canonical({"version": 2}))
    invalid = json.loads(canonical(record))
    invalid["turn_id"] = "not-submitted"
    with pytest.raises(DefinitionMismatch):
        validate_record(canonical(invalid), key, binding)


@pytest.mark.parametrize(
    "value",
    [" x ", "x\x7f", "x\x80", "x\x9f", "x\ud7ff", "x\ue000", "x\U00010000", "x\U0010ffff"],
)
def test_native_handle_text_preserves_legal_unicode_boundaries(value):
    from ralf_agent.runner_journal_state import _text

    assert _text(value, "Native handle") == value


@pytest.mark.parametrize(
    "character", [chr(n) for n in range(32)] + ["\ud800", "\udbff", "\udc00", "\udfff"]
)
def test_native_handle_text_rejects_controls_and_all_surrogate_boundaries(character):
    from ralf_agent.runner_journal_state import _text

    with pytest.raises(ValidationError):
        _text("x" + character, "Native handle")


@pytest.mark.parametrize("value", ["\x00\t\n\x1f", "\ud7ff\ue000", "\U00010000\U0010ffff"])
def test_runner_evidence_values_keep_escaped_controls_and_unicode(value):
    from ralf_agent.runner_journal_state import _json

    encoded = _json({"value": value}, "Evidence")
    assert json.loads(encoded) == {"value": value}


@pytest.mark.parametrize("value", ["\ud800", "\udbff", "\udc00", "\udfff"])
def test_runner_evidence_rejects_nested_unpaired_surrogates(value):
    from ralf_agent.runner_journal_state import _json

    with pytest.raises(ValidationError):
        _json({"nested": [{"value": "x" + value}]}, "Evidence")


def test_runner_evidence_unicode_byte_limit_is_independent_of_character_limit():
    from ralf_agent.runner_journal_state import _json

    assert json.loads(_json({"v": "é"}, "Evidence", limit=10)) == {"v": "é"}
    with pytest.raises(ValidationError):
        _json({"v": "é"}, "Evidence", limit=9)
