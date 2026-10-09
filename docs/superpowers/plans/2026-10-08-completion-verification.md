# Completion Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox tracking.

**Goal:** Deliver an opt-in durable Local completion gate and selectable verifier capability.
**Architecture:** Pure verifier DTO/port and receipt rule, separate Engine adoption helper; execution authority owns records and bounded retries. Default legacy releases remain byte-identical.
**Tech Stack:** Python 3.11+, existing jsonschema, asyncio, SQLite, pytest/Ruff; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-08-completion-verification.md

## Global Constraints

- Local-only; no changes to PlanVerifier or Temporal binding support.
- Preserve dirty accumulated workspace; no Git commits, pushes, publishing or cleanup.
- No model credential persistence or output. Live tests optional and bounded under existing authorization.
- Snapshot dev28 SDK and wheel in this plan's private workspace before production edits.

## Review Focus

- A custom verifier mutates input/returns a lazy unsupported object: detached request and strict return refuse authority leakage.
- Verifier changes identity/replaced during call: actual object and selected release both checked before acceptance.
- Restart between verification commit and Session append: no repeated verification/retry feedback or tool writes.
- Parallel/nested nodes accidentally consume sibling evidence: current node/child receipts only.
- Old wheel opens new verifier release: no model/tool dispatch, original evidence unchanged.

### Task 1: Pure verification and durable Local completion

**Files:** Create completion.py, completion_runtime.py, tests/test_completion_verification.py. Modify engine.py, errors.py, binding_runtime.py (component plumbing only).
**Interfaces:** CompletionRequest(task,output,receipts), CompletionVerdict(status,feedback=None); CompletionVerifier.verify; SchemaCompletionVerifier and ToolReceiptVerifier; verify_completion(engine,run_id,result)->bool.

- [x] Write behavioral tests for request isolation, invalid verdicts/pointers/schema; schema-valid false resolved without receipt, feedback retry leads approval and exactly one approved write; reject leaves no Session; max_decisions bounds retries; cancellation/drift; restart after committed acceptance and retry feedback. Use real SQLite and ScriptedProvider.
- [x] Run `.venv/bin/python -m pytest tests/test_completion_verification.py -q` and inspect expected missing-module/API RED.
- [x] Implement DTOs/rule and pure verification helper. Engine calls helper after Schema normalization before Session I/O; skip previously retried final Action, reuse recorded accepted verdict; optional verifier identity in manifest only when present.
- [x] Run the whole new test module and existing engine/model adoption tests. Expected PASS with legacy behavior preserved.

### Task 2: Binding, assembly and business evaluation

**Files:** Modify binding_catalog/runtime.py, runtime_config/builder.py, business_evaluation/cli.py, exports. Create tests/test_completion_bindings.py.
**Interfaces:** verifier registry role and runtime component; inherited optional verifier with no default manifest addition; explicit references kernel5; evaluator opt-in completion_verifier and receipt gate.

- [x] Write RED tests for catalog default/ref/disabled; configuration/async factories; missing version/replacement; graph parallel/team/dynamic/nested boundaries; evaluator correct independent oracle and false resolved with retry.
- [x] Run module and observe missing support failures.
- [x] Implement plumbing and factories; use receipts from actual accepted current-node Actions, preserve schema gate even disabled. Add evaluator optional parameter applied both original and restart Engine; explicit report identity only when selected.
- [x] Run completion modules plus existing binding/configuration and business tests. Expected PASS.

### Task 3: Documentation, compatibility and final evidence

**Files:** docs/completion-verification.md; remaining-work/status/progress/API/bindings docs and architecture contract; version dev29 and changelog.
**Interfaces:** local-only current support; real installed old/new wheel evidence.

- [x] Add documentation and usable example; keep full H1/H2/managed model verifier pending. Build wheel/sdist with `--no-isolation`.
- [x] Run full pytest with temporary localhost fixture approval, Ruff/format/Git whitespace. Expected all selected tests PASS; external unconfigured services remain skipped.
- [x] Install real old/new wheels outside checkout and run completion/binding/business contracts. Generate old approvals, recover under new wheel without manifest/receipt drift; old wheel rejects new verifier release. Check SDK bytes and credential/artifact exclusions.
- [x] Dispatch one fresh final reviewer required by executing-plans skill, against this plan's SDK snapshot delta and contracts. One TDD fix pass for important findings, document minor deferrals.
- [x] Attest actual logs/artifacts in completion ledger; preserve private evidence because nothing is committed; no remote changes.
