# Shared Model / Context Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Fix all three dev23 reproduced defects and share the adoption/context rules.
**Architecture:** Pure acceptance helpers; each authority records evidence and writes
its own state. Temporal dispatches by recorded evidence version; shared reference
selection only projects optional Session data into a bounded request.
**Tech Stack:** Existing Python3.11–3.13 and dependencies.
**Spec:** [shared contracts](../specs/2026-10-08-shared-model-context-contracts.md).

## Global constraints

- Preserve valid native manifests, original snapshots and previous20starters.
- No hidden retries/I/O or authority in validators/selectors.
- No remote publication, credentials or paid calls; retain dirty workspace/evidence.

## Task1 — shared model acceptance and recorded evidence

Modify decisions.py, engine.py, temporal_activities.py, temporal_state.py;
create model_evidence.py; tests/test_model_adoption_contracts.py.

- [x] RED shared backend cases: duplicate IDs yields zero tool Actions;
  complete invalid Schema keeps raw response/usage, spent1 and no unknown hold;
  typed defaults remain authorized effective values; cancelled late evidence only settles.
- [x] Implement snapshot_model_response(response), validate_model_usage(usage),
  settlement_usage(usage), validate_decision(spec, proposal, tool_manifests),
  validate_call_ids(ids). All pure, completed detached JSON/DecisionProposal.
- [x] Wire Local resolved proposals and Temporal version2 received evidence through
  common validation. Keep legacy Activity payload History transitions unchanged.
- [x] GREEN targeted model, receiver, defaults, Temporal control/conformance suites.

## Task2 — recommended recent Session projection

Create context_references.py; modify context.py/context_pipeline.py;
tests/test_recent_session_context.py.

- [x] RED three-run Session600 case for both assemblers; actual Provider sees73;
  whole recent tool turn selected, no incomplete call/result; contiguous suffix
  and fitting full references remain unchanged; input data detached and budgets honored.
- [x] Implement select_references(references, fits) -> (selected, session_manifest)
  with whole-turn suffix selection; both contexts consume this same helper.
- [x] GREEN default/budgeted/context/memory/recall contract suites.

## Task3 — release, review and actual gates

- [x] dev24 metadata/docs/CI; update review status with explicit resolution; existing
  template dictionaries unchanged. Record receipt-version and recall limits.
- [x] Exactly one fresh whole-increment reviewer; Important/Critical RED→GREEN once,
  report deferred Minor and all scope rulings/costs.
- [x] Full actual services, installed/base/new Temporal/provider fault cases,
  actualdev23 local/History/starter compatibility, build/byte identities, static
  checks and credential exclusion; stop owned services, retain local-only artifacts.

## Review focus

1. Receipt/error envelope disagreements cannot authorize tools or lose known usage.
2. Historical evidence replays unchanged; newly rejected decisions do not overwrite
   completed effects or old unknown holds.
3. Cancel/release drift/lazy outputs preserve known evidence without new dispatch.
4. Session projection cannot split tool evidence, skip a too-large latest turn,
   mutate stored data, or exceed char/unit limits.
5. Effective default arguments and generated fallback call IDs retain approval/
   effect identity and uniqueness after normalization.
