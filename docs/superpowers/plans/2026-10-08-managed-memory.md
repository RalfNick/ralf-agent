# Managed Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline.

**Goal:** Deliver sourced automatic memory, durable model summaries, native
Temporal custom context and bounded real DeepSeek evidence without remote writes.

**Architecture:** Opt-in application coordinators use existing managed Agent Runs
and memory CAS ports. Pure context consumers receive frozen proposals. Temporal
adds a registered context Activity path, preserving its default native release.

**Tech Stack:** Python 3.11+, existing httpx/jsonschema, SQLite defaults, optional
Redis/PostgreSQL/Temporal; no new dependencies.

Spec: [managed-memory](../specs/2026-10-08-managed-memory.md).

## Task 1: grounded memory pipeline

- [x] Define immutable source evidence, FactProposal, admission policy and pure
  rule extraction, plus model extractor using one schema-constrained managed Run.
- [x] RED: automatic success-only extraction, unsupported values/paths, Scope,
  CAS conflict, duplicate restart, backend/source drift and bounded reads.
- [x] Implement MemoryPipeline.run/consolidate and sync/async memory support.
  Per-fact append-only identity records provenance; partial writes replay safely.

Produces: memory_extraction types/ports, memory_pipeline coordinator. Consumes:
Engine submit/status/drive, Scope, RecallQuery/RecallPage, put_fact CAS. Identity
and method bindings are fixed; source revalidation surrounds awaited writes.

## Task 2: managed model summary

- [x] RED: managed summary receipt recovery, schema/length, complete-group
  coverage, empty output, frozen input and no implicit model calls.
- [x] Implement ManagedModelSummarizer and FrozenContextSummarizer; expose SDK
  examples and an installed offline memory starter without altering old templates.

Produces: model_context API. Consumes: same managed Run API and ContextSummary,
BudgetedContextAssembler. The model writes text only; host assigns coverage.

## Task 3: Temporal context registration

- [x] RED: additive custom registration, context snapshot before model, bounded
  final request, lazy result and same-identity implementation replacement.
- [x] Implement native Activity/History path and actual-service restart/replay
  tests. Preserve default registration and baseline History compatibility.

Produces: additive context_registration release, pinned ContextBuilder contract.
Consumes: existing TemporalRuntime/TemporalRunState and context Activity. No I/O
in Workflow or pure builder. Model request validation applies to actual request.

## Task 4: real quality, review and packaging

- [x] Verify current DeepSeek model IDs using primary docs and authenticated
  model listing. Use private credential, 40 completion/2048 token/60s call caps,
  independent 900/300/300s phase deadlines (see the observed limit ruling). Freeze selected cases before running.
- [x] One fresh read-only final reviewer; important findings RED→GREEN inline.
- [x] Full actual-service regression, installed wheel contracts, optional-SDK
  blocked checks, baseline native History/starter compatibility, Ruff/format/build,
  docs and credential exclusion. Stop task-owned services. No remote submission.

## Review Focus

Check fabricated source paths, structured source mutation, empty extraction,
partial CAS success/restart, expired duplicates, poisoned tool evidence, backend
replacement while awaiting, model provenance/usage vs business receipts, and
summary coverage mismatch. Check custom Temporal implementation identity,
Activity retry bounds, hostile/lazy/mutating builders and validators, actual
request budgets, old-release replay, and private credential/report/package
exclusion. Assess quality claims against actual live case evidence and caps.
