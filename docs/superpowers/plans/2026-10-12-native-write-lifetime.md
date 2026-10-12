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

- [x] Create owned temp services from previous proven runners at distinct17283/56381 endpoints; observe actual readiness, do not reuse stopped processes.
- [x] Write tests before product: block actual native replace, original approvals, cancellation, zero-wait failed close, FD/second owner refusal, actual release/drain/close, original receipt query, restart/History and no duplicate effects across six definitions. Compare actual cancellation/quiescence evidence with original contract.
- [x] Run `.venv/bin/python -m pytest tests/test_workspace_write_lifetime_service.py -q -W error` with actual both services, zeroSKIP; record failure if any, otherwise actual behavior proof. Fix discovered product issue only after true RED and document any required versioned boundary; never relax assertions to hide gap.

### Task 2: Explicit managed Tool end protocol and recovery controls

**Files:** create src/ralf_agent/tool_execution.py, temporal_tool_execution.py, temporal_tool_execution_state.py and temporal_tool_execution_activities.py; modify temporal_activities.py/temporal_state.py/temporal_workflow.py/temporal_builder.py/temporal_profile.py and public exports; create tests/test_tool_execution.py tests/test_temporal_tool_execution.py tests/test_temporal_tool_execution_configuration.py; original actual service test and doc Minor files.
**Interfaces:** ToolExecutionPort/ToolExecutionOwner(*,version,max_calls=8); TemporalRuntime(tool_execution=None), Temporal-only Profile tool_execution/tracked; explicit tool_execution_protocol1 on temporal-3, strict original admission/end Updates. Consume original actual owner and preserve original sole History authority; no standalone scheduler.

- [x] Read the spec protocol addendum and original actual failure evidence. Public owner/default/config/strict metadata and pure History gate tests BEFORE implementation; trueRED missingAPI/newmarker, actualcoldcases already failremote-stop conservatively.
- [x] Implement fixed registration, actual defaultowner and borrowedcustomport, explicit Temporal-only factory, original envelope intention/admission/end/effect/stop gates and diagnostics; keep legacy defaults unchanged. Runtime/Assembly drain actualToolOwner AND endACK before Worker/resources close.
- [x] Run new pure/config/owner tests and actual lost-receipt Agent/Graph plus six legacy default compositions, zeroSKIP; no clearing remote_uncertain from query alone. Add wrong/duplicate/late proof and closure/cancellation/error/identity regressions as specified. Newprotocol changes must be explicit and oldWorker refusal proven in Task3.
- [x] Pin repeat cancel/failed-close then retry and genuine stable receipt query on restart; preserve unknown/terminal behavior and original actual handler ownership.
- [x] Clarify intentionally refused YAML merge keys and restore dev79 historical section (two dev80 deferred Minors in this separate batch); no YAML behavior change.
- [x] Run `.venv/bin/python -m pytest tests/test_workspace_write_tools.py tests/test_workspace_write_processes.py tests/test_workspace_write_execution.py tests/test_temporal_assembly_lifetime.py tests/test_temporal_assembly_cleanup.py tests/test_skill_documents.py tests/test_skill_document_review.py tests/test_tool_execution.py tests/test_temporal_tool_execution.py tests/test_temporal_tool_execution_configuration.py -q -W error`; formal completion and final batch commit.

### Task 3: Frozen verified capability delivery

**Files:** version/CI/guides/capability/status/progress/remaining/harness/CHANGELOG and architecture/reviews/2026-10-12-native-write-lifetime.md.
**Interfaces:** honest actual lifetime evidence, optional installed real services; no full R13/R01–R26 claim.

- [x] Sole fresh strongest read-only review; all findings AND Declined regraded before one unified Important TDD pass; defer new Minors/no re-review.
- [x] Full green suite, isolated core+SDK installed contracts and actual6 zeroSKIP, fixedsource/wheel/sdist/installhashes and guides, actual old80 defaultLocal/CLI/Temporal/native two-way recovery and22 templates.
- [x] Stop+wait every owned service/Worker; local main and formalTask3/closure commits, rebuild/check payload after docs, archive this plan's ownSDD only; exhaustive rulings/minors retained, whole goal remains ACTIVE.

Task2 adds two explicit lost-receipt fault-injection cases (Agent and Graph) alongside the six real default cases: test-only borrowed proxy delegates actual PostgreSQL begin/observation/ack, refuses received until original assembly closes, then permits genuine native query on restart. This is an injected receiver-boundary loss, not an actual PostgreSQL server crash.
