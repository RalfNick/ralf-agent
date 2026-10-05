# M1 Local Runtime Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in this session. Steps use checkbox syntax for tracking.

**Goal:** Deliver the first runnable v0.1 increment: native Agent SDK, sequential Workflow, durable Local execution, governed Python tools, approvals, recovery, replaceable memory, CLI, and offline evaluation.

**Architecture:** One LocalEngine owns each SQLite execution database, enforced by an OS coordinator lock. Model decisions and stable proposed tools commit together; all effects have durable intents and result commits. Memory and providers use replaceable protocols; enterprise integrations remain explicit future deliverables.

**Tech Stack:** Python >=3.11, SQLite, asyncio, dataclasses, JSON Schema, HTTPX, pytest, Ruff, setuptools.

**Spec:** architecture/design.md; architecture/specs/run-command-contract.md; architecture/specs/action-recovery-contract.md; architecture/specs/runner-capability-contract.md.

## Global Constraints

- Python 优先；SDK、运行时、治理和自部署基础能力全部 Apache-2.0.
- 默认单进程 asyncio＋SQLite，无需外部调度服务.
- Engine is the only state writer; unknown writes never blindly retry.
- Approval binds fixed tool/version/arguments; adopted model decisions do not regenerate on recovery.
- Unknown usage retains its reservation. This increment budgets execution credits, not hard currency limits.
- Only configured trusted Python handlers execute; no claim of sandbox, OIDC, MCP, multi-process or Temporal production support.

## Review Focus

- A second process must not become coordinator while the original process owns the database.
- Changed tool/provider definitions after restart must reject recovery instead of substituting new code.
- Cancellation during an external call must prevent success and subsequent calls while retaining the late effect.
- Malformed model/tool output must not repeat a known write to repair its output.
- Context trimming must preserve complete assistant/tool groups and original task instructions.

## Task 1: Domain, tool registration and SQLite journal

**Files:** src/ralf_agent/types.py, errors.py, tools.py, storage.py; tests/test_storage.py.

**Interfaces:** ToolSpec/ToolRegistry; SQLiteStore.transaction(), command(), run(), events(), reserve(), settle(); Scope and CommandReceipt. Amounts are non-negative integer credits. Command keys are scoped by workspace and principal.

- [x] Write behavioral tests for idempotent budget reservations, concurrent reservations, unknown occupancy and command conflicts.
- [x] Run `python3 -m pytest tests/test_storage.py -q`: expected missing-package/feature failure before implementation.
- [x] Implement typed definitions and SQL constraints/BEGIN IMMEDIATE transactions; no external I/O inside a transaction.
- [x] Run the storage tests: expected all pass. Commit the tested domain and storage unit.

Representative contract:

```python
store.create_budget("run-1", 3)
store.reserve("run-1", "attempt-1", 2)
with pytest.raises(BudgetExceeded):
    store.reserve("run-1", "attempt-2", 2)
assert store.budget("run-1")["held"] == 2
```

## Task 2: Native loop, controls and recovery

**Files:** src/ralf_agent/engine.py, context.py; tests/test_engine.py, helpers.py.

**Interfaces:** LocalEngine(store, providers, tools, scope, session_store, memory_store); submit(AgentSpec|WorkflowSpec, input, command_id) -> RunHandle; async drive(run_id) -> RunSnapshot; approve(), cancel(), reconcile(); close(). Providers implement identity and async complete(messages, tools) -> ModelResponse.

- [x] Write tests using actual SQLite: approval survives reopening, adopted response is reused, terminal cancellation races, unknown writes, schema validation, sequential workflow and fixed-release recovery.
- [x] Run `python3 -m pytest tests/test_engine.py -q`: expected missing Engine behavior.
- [x] Implement immutable decision/action snapshots, stable identities, serialized command commits and safe recovery; recoverable provider retries keep prior usage unknown.
- [x] Run the complete current suite: expected all pass. Commit the native loop.

Representative recovery contract:

```python
run = engine.submit(spec, {"ticket": "INC-1"}, command_id="request-1")
snapshot = asyncio.run(engine.drive(run.run_id))
assert snapshot.state == "waiting_approval"
engine.close()
# Reopen the same database with the same release and approve its original pending operation.
```

## Task 3: Replaceable memory and HTTP model provider

**Files:** src/ralf_agent/memory.py, providers.py; tests/test_memory.py, test_providers.py.

**Interfaces:** SessionStore and LongTermMemoryStore protocols; SQLiteMemory and InMemoryMemory; OpenAIChatProvider(identity, complete). HTTP client injectable, hidden business retries disabled.

- [x] Write tests for scoped reads, CAS fact updates, expiration, namespace isolation, tool-call normalization, invalid responses and redacted provider errors.
- [x] Run the focused files: expected missing memory/provider features.
- [x] Implement storage adapters and Chat Completions provider; keys stay outside persisted definitions and errors.
- [x] Run all tests: expected pass. Commit memory/provider implementations.

## Task 4: CLI, sample and process-crash verification

**Files:** src/ralf_agent/cli.py, demo.py, __main__.py, __init__.py; examples/oncall.py; tests/test_cli.py, test_process_recovery.py.

**Interfaces:** ralf demo/status/events/approve/resume/cancel; --db selects execution database. Demo business service has its own SQLite receipt table keyed by effect_key; the scripted provider is explicitly offline, not an AI quality benchmark.

- [x] Write subprocess tests for separate submit/approve/resume commands and os._exit immediately after a downstream business commit.
- [x] Run tests: expected missing CLI/process behavior.
- [x] Implement commands with JSON output, typed error exit codes and no automatic approval. Add runnable SDK sample.
- [x] Run complete suite and the documented demo: expected one approved business write and stable run identity after restart. Commit CLI/sample.

## Task 5: Open-source packaging, evaluation and verification

**Files:** README.md, LICENSE, CONTRIBUTING.md, docs/implementation-status.md, examples/evaluate.py, .github/workflows/ci.yml.

- [x] Add offline scenario evaluation reporting completion, approved write count, budget and recovery; distinguish runtime regression metrics from live-model AI quality.
- [x] Document install/use, extension interfaces, actual supported capabilities and remaining M1 work including Temporal probe.
- [x] Run `python3 -m pytest -q`, `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m build` and installed-wheel CLI checks: expected pass.
- [x] Review the whole change against spec and these five Review Focus cases, fix important findings with regression tests, then commit verified work. Do not push a shared remote branch without an explicit request.
