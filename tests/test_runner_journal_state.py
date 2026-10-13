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
