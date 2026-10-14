"""No-submit capacity projection releases only the original acknowledged intent."""

import copy
import json

import pytest

from ralf_agent import coding_execution_rules as rules
from ralf_agent.errors import RalfError
from tests.test_codex_runner_capacity import DISPATCH, GENERATION, RUNNER, slot
from tests.test_codex_runner_capacity import root as root
from tests.test_coding_create_not_dispatched import environment, no_create


def projection(claim):
    env = environment({"expected_generation": GENERATION})
    return rules.create_not_dispatched_projection(
        no_create(env), env, token=claim["token"], dispatch_digest=DISPATCH, runner_digest=RUNNER
    )


def test_native_intent_does_not_rewind_and_exact_no_create_projection_releases(root):
    holder, waiter = slot(root), slot(root, dispatch_digest="d" * 64)
    try:
        claim = holder.try_acquire()
        holder.mark_native_intent(claim["token"])
        assert waiter.try_acquire() is None
        with pytest.raises(RalfError):
            holder.release(claim["token"], definitely_undispatched=True)
        holder.release(claim["token"], create_not_dispatched_proof=projection(claim))
        assert json.loads((root / ".coding-capacity.json").read_text())["obligation"] is None
        next_claim = waiter.try_acquire()
        assert next_claim["token"] != claim["token"]
        waiter.release(next_claim["token"], definitely_undispatched=True)
    finally:
        holder.close()
        waiter.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("token", "f" * 32),
        ("dispatch_digest", "f" * 64),
        ("runner_digest", "f" * 64),
        ("generation", "f" * 32),
        ("create_operation_digest", "bad"),
        ("supervision_receipt_digest", "bad"),
        ("proof_digest", "bad"),
        ("metadata_present", False),
        ("gate_sealed", False),
        ("cli_gate_accepted", True),
        ("cli_exec_started", True),
        ("helpers_ended", False),
        ("control_drained", False),
        ("namespace_query_succeeded", False),
        ("namespace_confirmed", False),
        ("container_present", True),
        ("container_id", None),
        ("version", True),
        ("cli_gate_accepted", 0),
        ("helpers_ended", 1),
        ("supervision_declaration_digest", "bad"),
    ],
)
def test_foreign_or_unproven_projection_keeps_original_obligation(root, field, value):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        holder.mark_native_intent(claim["token"])
        proof = projection(claim)
        proof[field] = value
        before = copy.deepcopy(holder.claim)
        with pytest.raises(RalfError):
            holder.release(claim["token"], create_not_dispatched_proof=proof)
        assert holder.claim == before
    finally:
        holder.close()


def test_cold_original_token_can_release_after_ack_but_duplicate_cannot(root):
    original = slot(root)
    claim = original.try_acquire()
    original.mark_native_intent(claim["token"])
    original.close()
    recovery = slot(root)
    try:
        cold = recovery.try_acquire(recovery=True)
        assert cold["token"] == claim["token"] and cold["recovery_only"] is True
        recovery.release(claim["token"], create_not_dispatched_proof=projection(claim))
        with pytest.raises(RalfError):
            recovery.release(claim["token"], create_not_dispatched_proof=projection(claim))
    finally:
        recovery.close()


def test_full_evidence_rehash_cannot_hide_possible_exec_in_projection(root):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        holder.mark_native_intent(claim["token"])
        proof = projection(claim)
        proof["evidence"] = no_create(proof["evidence"]["identity"], cli_exec_started=True)
        proof["proof_digest"] = proof["evidence"]["proof_digest"]
        proof["cli_exec_started"] = True
        with pytest.raises(RalfError):
            holder.release(claim["token"], create_not_dispatched_proof=proof)
        assert holder.claim["phase"] == "native_intent"
    finally:
        holder.close()
