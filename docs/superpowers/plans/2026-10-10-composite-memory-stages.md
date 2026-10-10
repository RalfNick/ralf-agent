# Composite memory stages implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Complete Local advanced Agent automatic rule/model-selected memory through existing H3 defaults and recovery.
**Architecture:** Original Run/node projections own journals and scoped facts; real child Runs own member memory. Existing policies, write ports and budgets are reused; Schema12 opt-in refuses old readers.
**Tech Stack:** Python 3.11+, existing SQLite, pytest; no runtime dependency additions.
**Spec:** docs/superpowers/specs/2026-10-10-composite-memory-stages.md

## Global Constraints

- Preserve native/sequence policy class implementations, fact identities and accepted releases.
- composite_memory_stage_version=1 plus synchronous prepare_composite_memory_stages() activate Schema12 within original admission transaction.
- No Temporal memory writes, implicit Planner extraction, new execution authority, credential access or remote push.
- Commit locally after full suite, packaging and one final read-only review.

## Review Focus

- Two parallel node=0 frames selecting the same field must produce distinct scoped facts and credits.
- Missing whole execution projection or changed workflow_node must fail against original Action evidence.
- Cancellation or terminal recovery must never add selector calls/CAS writes.
- Child unknown facts must retain parent allowance until explicit child evidence recovery.
- Per-member target/namespace and actual backend must remain fixed after awaits; unsupported Store activation must roll back admission.

### Task 1: Composite original-authority memory

**Files:** src/ralf_agent/managed_memory.py, managed_memory_stage.py, composite_context.py, engine.py, storage.py, sqlite_sessions.py; tests/test_composite_memory_stages.py.
**Interfaces:** consumes finish_memory_stage(engine, run_id, result), validate_journal(engine, run) and NodeEngine original projection. Produces versioned admission and node-scoped original memory evidence for existing memory_stages(run_id).

- [x] Write tests for rule/model selection × graph/parallel/team/dynamic-flat/dynamic-DAG/nested, requiring two distinct facts, balanced original budget and no repeat on restart.
```python
@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic", "dynamic-dag", "nested"])
@pytest.mark.parametrize("mode", ["rule", "model"])
def test_composites_memory(tmp_path, kind, mode):
    memory, provider = InMemoryMemory(backend_id="facts"), Provider()
    with engine(tmp_path / "runs.sqlite", provider, stage_policy=policy(memory, mode)) as local:
        run = local.submit(definition(kind), "task", command_id="s", budget=32)
        assert asyncio.run(local.drive(run.run_id)).state == "succeeded"
        assert len(memory.facts(local.scope, "observations")) == 2
```
- [x] Run `.venv/bin/pytest -q tests/test_composite_memory_stages.py`; expect current unsupported-stage admission failure.
- [x] Add Schema12 optional activation; recursively inspect member manifests and preserve native activation. Derive projected fact keys from original workflow_node; validate source ownership and all frame journals. Reuse terminal frame recovery for memory. Change obsolete refusal tests to unsupported optional Store cases.
- [x] Run `.venv/bin/pytest -q tests/test_composite_memory_stages.py tests/test_managed_memory_stage.py tests/test_managed_memory_stage_review.py tests/test_memory_selection.py tests/test_memory_selection_boundaries.py tests/test_managed_model_memory.py tests/test_composite_data_context.py`; expect all pass.

### Task 2: Default composition and real recovery

**Files:** src/ralf_agent/composite_memory.py, src/ralf_agent/engine.py, tests/test_composite_memory_stages.py, tests/composite_memory_crash_fixture.py, tests/test_recommended_profiles.py.
**Interfaces:** consumes Task1 source markers/scoped facts/Schema12 and existing RuntimeBuilder/AgentRun methods. Produces process-death, per-Agent target replacement, cancel/unknown budget and installed default acceptance evidence.

- [x] Add RED tests for missing frame, changed projected source, unsupported Store rollback, terminal receipt recovery, no-dispatch cancellation, target drift and child unknown escrow.
```python
def test_missing_frame_rejects_memory_query(local, handle):
    with local.store.transaction():
        run = local.store.run(handle.run_id)
        run["workflow"]["nodes"]["a"].pop("execution")
        local.store.save_run(run)
    with pytest.raises(DefinitionMismatch):
        local.memory_stages(handle.run_id)
```
- [x] Use SQLite audit calls and os._exit(77) after original durable commits/CAS; restart the original Run and assert exact received selector/CAS not repeated. Add declared per-node bindings and managed-memory profile sync/async facade/reconnect paths.
- [x] Pin the common Facade root-resume gap with flat/nested terminal children holding unknown facts, then implement `recover_terminal_children(engine, run_id)` through original owned terminal child drive locks only. Pure observation stays unchanged; missing facts retain allowance and changed child ownership rejects recovery.
- [x] Run `.venv/bin/pytest -q tests/test_composite_memory_stages.py tests/test_recommended_profiles.py tests/test_composite_bindings.py tests/test_managed_memory_configuration.py tests/test_model_memory_configuration.py`; expect all pass with explicit retained unknown cases.

### Task 3: Capability and release evidence

**Files:** docs/composite-memory-stages.md, docs/remaining-work.md, docs/recommended-harness.md, docs/implementation-status.md, docs/agentscope-alignment.md, architecture/viewpoints/framework-capabilities.md, architecture/viewpoints/harness-runtime.md, architecture/reviews/2026-10-10-composite-memory-stages.md, CHANGELOG.md, pyproject.toml and src/ralf_agent/__init__.py.
**Interfaces:** consumes Task1/2 guarantees and evidence; produces dev45 honest capability matrix and verified wheel/sdist.

- [x] Document source observations versus beliefs, per-Agent namespace selection, pure parent/child queries, Schema12 compatibility, unknown budget and remaining Temporal/semantic quality gates.
- [x] Run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `git diff --check`; expect passing suite/checks with configured-service skips counted.
- [x] Run `.venv/bin/python -m build --no-isolation`; install wheel into task scratch and run installed advanced/default/recovery contracts with repo pythonpath disabled; run old/new native/sequence compatibility and old Schema12 refusal. Expect successful build/install and unchanged original policy classes.
- [x] One fresh read-only final reviewer covers e413ddc..candidate plus working tree; fix Important findings in one RED→GREEN pass; whole suite green before final local commit. No push; delete only this plan's scratch after recording all rulings.
