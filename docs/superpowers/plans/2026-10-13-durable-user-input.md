# Durable User Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. The user authorized independent parallel implementation; one fresh integrated review follows all tasks.

**Goal:** Resume the original Agent or dynamic Plan after durable user input on Local and Temporal.

**Architecture:** One pure bounded question/reply contract feeds the original Local Coordinator or Temporal History. An explicit intrinsic tool and selected planner adapter produce questions; Facades project and route original-owner controls.

**Tech Stack:** Python >=3.11, existing JSON Schema/SQLite/Temporal SDK, pytest, Ruff; no new required dependencies.

**Spec:** `docs/superpowers/specs/2026-10-13-durable-user-input-design.md`

## Global Constraints

- Python >=3.11; no new required dependencies.
- No push, publish, model-key discovery or blanket capability completion claim.
- Old absent fields and default manifests remain byte-identical.
- Local `local-9` / `local-bindings-17`; Temporal `binding_protocol=10`; `user_input_protocol=1` only when selected.
- Policy: `max_requests` 1–32 (default 8); prompt 1–16384 (4096); reply 1–1048576 bytes (65536); Schema at most 65536 bytes; JSON depth at most 32.
- Original Run/release/input/Turn/finished actions/remaining allowances do not change.
- Native transcript provenance, actual handler quiescence and original command dedupe remain authoritative.
- Exclusive ownership below; no agent commits, full-suite runs or uncontrolled service launch. Root integrates, validates, reviews and locally commits.

## Review Focus

1. Schema local recursion/remote references and deferred Python values must fail deterministically without I/O.
2. Reply commit before host wake or response delivery must restore one original answer, not repeat effects.
3. Simultaneous sibling question/approval/unknown effect must retain all original owners and actual escrow.
4. Replayed answered commands after Profile removal must return original receipt without component construction.
5. Native signed history and parent completion must retain question/answer provenance without treating replies as business effects or mutating submitted task.

## Task 1: Shared detached input protocol (root)

**Files:** Create `src/ralf_agent/user_input.py`, `tests/test_user_input.py`; modify `src/ralf_agent/parent_completion.py`, `src/ralf_agent/planning.py`, `src/ralf_agent/orchestration_types.py`, `src/ralf_agent/__init__.py`.

**Interfaces:** Produce the seven shared signatures in the spec; optional `DynamicWorkflowSpec.input_policy`, `PlanningRequest.clarifications`, `ParentCompletionRequest.clarifications`, all omitted when absent. Journal/request shapes are exactly the spec. Other agents consume them without editing these files.

- [x] Write pure request/schema/reply/marker tests and old omitted-field compatibility assertions; run `pytest tests/test_user_input.py -q`, expected feature-missing failure.
- [x] Implement immutable values, no-I/O schema validation, exact descriptor marker detection and pure reply preparation.
- [x] Run the shared tests, planning/type/completion anchor tests, expected all pass; preserve RED/GREEN logs under private dev93 evidence.
- [x] Record Task 1 verification; include changes in final integrated local commit.

## Task 2: Local authority and composition (Local worker)

**Files:** Modify `engine.py`, `binding_runtime.py`, `binding_manifests.py`, `orchestration.py`, `dag_runtime.py`, `workflow_parallel.py`, `workflow_runtime.py`, `local_parent_completion.py`, and focused related Local modules; create `local_user_input.py` and `tests/test_local_user_input*.py`. Do not edit Task 1/3/4 files.

**Interfaces:** Consume shared functions; produce synchronous `LocalEngine.send_input(run_id, pending_id, target_digest, value, *, command_id, expected_state_revision=None)`. Constructor optional `user_input_policies=None`; selected manifests journal exact shared policy. Local frames own tool results; original planner revision owns question and next child.

- [x] Write and watch fail single/native Agent, flat/DAG planner, graph/Team/nested parent, cancel/schema/dedupe/Session/restart tests.
- [x] Implement original-store adoption/reply/continuation, selected version gates, frame control routing, pause aggregation, optional completion clarification source. Exclude intrinsic replies from business receipts.
- [x] Run focused Local anchors; expected no duplicate answer/transcript/effect, same Run/Turn, exact remaining budgets; report logs and actual process handles.
- [x] Record Task 2 verification; root commits after integration acceptance.

## Task 3: Temporal authority and recovery (Temporal worker)

**Files:** Modify `temporal.py`, `temporal_state.py`, `temporal_workflow.py`, `temporal_activities.py`, `temporal_parent_state.py`, `temporal_parent_workflow.py`, `temporal_parent_completion_state.py`, `temporal_bindings.py`, and relevant closed Temporal protocol validators. Create `temporal_user_input.py` and `tests/test_temporal_user_input*.py`. Do not edit Task 1/2/4 files (Task 4 owns `temporal_agent_*` facade modules and `temporal_profile.py`).

**Interfaces:** Consume shared functions; produce async `TemporalEngine.send_input` with identical parameters/receipt semantics, History-owned journal and optional named policies in runtime. Pure intrinsic markers never schedule Tool Activities/effects. Expose snapshot pending inputs for Task 4.

- [x] Write and watch fail native/parent question adoption, reply dedupe/rejections, Session/cancel, old-history/default and closed-protocol tests.
- [x] Implement original Update/History state advancement, original native Action reply journaling and planner revision continuation; no dynamic Python callback in Workflow.
- [x] Run focused Temporal state/Workflow anchors; supply actual service fixtures for question→restart, accepted answer/lost ACK→restart, native/provider continuity, planner retained work and old Worker refusal.
- [x] Do not launch a second service; coordinate one root-owned source/wheel acceptance service. Record Task 3 verification, root commits.

## Task 4: Public Facade, configuration and installed starter (API worker)

**Files:** Modify `types.py`, `ports.py`, `agent_runtime.py`, `runtime_router.py`, `temporal_agent_runtime.py`, `temporal_agent_controls.py`, `task_controls.py`, `temporal_profile.py`, `runtime_builder.py`, `runtime_config.py`, `cli.py`, `cli_views.py`, `a2a.py`, relevant A2A service modules. Create `user_input_factories.py`, `user_input_starter.py`, `tests/test_user_input_api*.py`; own `docs/user-input.md`. Root owns exports and overall capability records.

**Interfaces:** Optional synchronous/asynchronous input-control protocol; `AgentRun.send_input` and Temporal counterpart; kind-aware original-owner pending routing; Profile receipt-first lookup. SDK marker selection and `user_input_policies` configured adapter with named policies. Installed starter drives an actual input cycle, not business JSON pretending to pause.

- [x] Write and watch fail public discovery/reply, Profile replay-without-activation, optional legacy adapter compatibility, CLI JSON reply and explicit A2A extension tests.
- [x] Implement typed owner routing, safe rejection receipt validation, declared configuration preflight, CLI and A2A discoverability with no implicit text continuation.
- [x] Run focused Facade/Profile/CLI/A2A anchors; expected originals unchanged, observer timeout/cancel harmless; installed SDK/CLI tested by root after build.
- [x] Record Task 4 verification and usable documentation; root commits.

## Task 5: Integrated acceptance, documents and local commit (root)

**Files:** Relevant cross-layer tests; `docs/implementation-status.md`, `docs/remaining-work.md`, `architecture/viewpoints/framework-capabilities.md`, `architecture/viewpoints/harness-runtime.md`, `architecture/specs/run-command-contract.md`, new review/acceptance record, README, CHANGELOG, version/CI when justified.

**Interfaces:** Entire selected release; original shared protocols above. Source and exact installed artifact must agree; current evidence is stronger than remembered claims.

- [x] Integrate independent changes and run meaningful cross-layer/mixed-pause/native/restart tests, preserve failures and repairs.
- [x] Freeze candidate; run full source regression once, focused actual source/wheel Temporal service with subprocess kill/restart and History replay; wait/reap every owned handle.
- [x] Obtain one fresh whole-batch review; fix substantive findings RED→GREEN and verify impacted scope plus whole-suite as warranted.
- [x] Build/install outside checkout; compare source/wheel/sdist and verify installed SDK/CLI, old default byte compatibility and old-worker zero-I/O refusal; static/Markdown/credential checks after build terminal.
- [x] Synchronize accepted subsets and unverified service/model/adoption boundaries. Keep full R01–R26 goal open.

Local commit closure is recorded by Git and the private acceptance ledger after final packaging and static checks; commit only the reviewed files, verify a clean worktree and do not push.

## Self-review

All spec sections map to Tasks 1–5. Shared signatures/journal versions and file ownership are consistent. The five Review Focus items have pure, authority, facade and integrated acceptance tests assigned. Replies remain supplemental lineage; no task inserts an unpinned input merge or another execution authority. Standing user authorization supplies the execution method and permits continued implementation without repeated approval prompts.
