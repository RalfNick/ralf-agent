# Native Workspace Write Lifetime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline task-by-task. One final fresh strongest read-only reviewer; no implementer agents. Steps use checkboxes.

**Goal:** Close original real Temporal native write cancellation/close/lease evidence gap without weakening authority.
**Architecture:** Original managed Action → Source2/native FD/WriteJournal → owned real thread and original Worker drain → original History and PostgreSQL effects. No independent state machine.
**Tech Stack:** Python3.11+, existing Temporal/psycopg optional dependencies and owned temporary services.
**Spec:** docs/superpowers/specs/2026-10-12-native-write-lifetime-design.md

## Global Constraints

- Base11581df/dev80; original continuous user authorization, inline, local commits only/no push. No new implementation subagents; sole final reviewer required.
- Original definitions: Agent/sequence/Graph/Team/Dynamic/nested. Approved actual write blocked only at test-root note os.replace; no fake owner/handler completion.
- Thread wait≤30s, startup≤15s, case≤90s. Always finally release block and close original assemblies; actual original service stop+wait.
- Scoped persistent PostgreSQL EffectJournal and original Source2/native receipts; cancellation never grants success/new dispatch, missing effect stays unknown until genuine query evidence.
- Keepdev80 until requiredactual sixpass, then81. No model/Docker daemon/image operations. Existing default identities/22templates stable.

## Review Focus

- Real SDK cancellation ends observer while native write thread remains active: original FD/lease and Worker resources cannot be released (Task1).
- Timeout/failed close/repeated cancellation must retain original identity and effect evidence; later close is retriable (Tasks1/2).
- Graph/Team/Plan/nested cancellation reaches actual member and forbids later business dispatch (Task1).
- Late effect receipt/query cannot turn cancelled Run into success or run the original write again (Tasks1/2).
- Original Worker/Service/owned resources actually exit after failure paths, and installed actual evidence cannot silently skip (Task3).

### Task 1: Actual six-composition native write lifetime probe

**Files:** create tests/test_workspace_write_lifetime_service.py; optional test-only helper tests/workspace_write_lifetime_probe.py; inspect original temporal_activities.py/temporal_assembly_lifecycle.py/workspace_write_tools.py/native FD and journal code.
**Interfaces:** existing original Profile/Writer/definitions and managed approvals/cancel/diagnostics; no new public interface intended. Use declared postgres EffectJournal and native actual query_write after real owner release.

- [ ] Create owned temp services from previous proven runners at distinct17283/56381 endpoints; observe actual readiness, do not reuse stopped processes.
- [ ] Write tests before product: block actual native replace, original approvals, cancellation, zero-wait failed close, FD/second owner refusal, actual release/drain/close, original receipt query, restart/History and no duplicate effects across six definitions. Compare actual cancellation/quiescence evidence with original contract.
- [ ] Run `.venv/bin/python -m pytest tests/test_workspace_write_lifetime_service.py -q -W error` with actual both services, zeroSKIP; record failure if any, otherwise actual behavior proof. Fix discovered product issue only after true RED and document any required versioned boundary; never relax assertions to hide gap.

### Task 2: Recovery controls and documentation Minor closure

**Files:** tests/test_workspace_write_lifetime_service.py and meaningful offline lifecycle regression if product fix needed; docs/skill-documents.md, docs/remaining-work.md, architecture/specs and capability/status guides as appropriate.
**Interfaces:** same original public cancel/reconcile/owner lifecycle; pure doc clarification of YAML merge restriction and correct historical dev79 heading.

- [ ] Pin repeat cancel/failed-close then retry and genuine stable receipt query on restart; preserve unknown/terminal behavior and original actual handler ownership.
- [ ] Clarify intentionally refused YAML merge keys and restore dev79 historical section (two dev80 deferred Minors in this separate batch); no YAML behavior change.
- [ ] Run `.venv/bin/python -m pytest tests/test_workspace_write_tools.py tests/test_workspace_write_processes.py tests/test_workspace_write_execution.py tests/test_temporal_assembly_lifetime.py tests/test_temporal_assembly_cleanup.py tests/test_skill_documents.py tests/test_skill_document_review.py -q -W error`; formal completion and final batch commit.

### Task 3: Frozen verified capability delivery

**Files:** version/CI/guides/capability/status/progress/remaining/harness/CHANGELOG and architecture/reviews/2026-10-12-native-write-lifetime.md.
**Interfaces:** honest actual lifetime evidence, optional installed real services; no full R13/R01–R26 claim.

- [ ] Sole fresh strongest read-only review; all findings AND Declined regraded before one unified Important TDD pass; defer new Minors/no re-review.
- [ ] Full green suite, isolated core+SDK installed contracts and actual6 zeroSKIP, fixedsource/wheel/sdist/installhashes and guides, actual old80 defaultLocal/CLI/Temporal/native two-way recovery and22 templates.
- [ ] Stop+wait every owned service/Worker; local main and formalTask3/closure commits, rebuild/check payload after docs, archive this plan's ownSDD only; exhaustive rulings/minors retained, whole goal remains ACTIVE.
