# H1 Agent Capability Bindings Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, following test-driven-development and verification-before-completion. The user requested implementation of the accepted architecture. Preserve local changes and evidence; no commit, push, cleanup or paid calls.

**Goal:** Make Local native Agents and sequential Workflows select separately versioned providers, pure policies, contexts, facts, knowledge and tool subsets in one authority.
**Architecture:** New immutable definition wrappers preserve old AgentSpec and submission identities. A host-scoped catalog resolves borrowed components; per-step execution views and manifests carry fixed bindings without mutable current-agent globals. Existing builder lifecycle owns only explicitly registered resources.
**Tech Stack:** Python 3.11+, SQLite, existing async ports, pytest/Ruff; no new dependencies.
**Spec:** architecture/specs/agent-capability-binding-contract.md; architecture/specs/agent-facade-session-contract.md.

## Global Constraints

- This increment is H1a, not all H1 or H2. Session inherits the existing backend or is explicitly disabled; Session resource overrides/selectors and queue semantics require later SessionAdmission.
- AgentDefinition wraps AgentSpec; BoundDefinition initially wraps only WorkflowSpec with sequence/steps/N paths. Unsupported Graph/Team/Dynamic/Temporal wrappers fail before dispatch.
- Preserve legacy AgentSpec, Profile v1, flat definitions, manifest local-4, command identities, controls and drive/close semantics.
- Provider/context/decision_policy are required; optional facts/knowledge/tool_set can disable. Workspace/sandbox/skills/verifier/stage_policy/limits refs are explicitly unsupported.
- Catalog entries are role/id/version scoped to trusted Scope, cannot silently replace identities, and borrowed clients are not closed. No free-form resource selection.
- Runtime catalog schema v2 permits binding component declarations; schema v1 rejects them and keeps its old digest.
- Caller payload lookup occurs before new resolution; accepted release pins actual per-step identity. Evidence received before drift remains durable.
- Work in the existing dirty feat branch. Keep task evidence; no git mutations or automatic environment services.

## Review Focus

1. Concurrent Agents or repeated logical provider names must not leak components across await boundaries.
2. Catalog removal/default movement must preserve original submit receipts; no fallback during resume.
3. Custom policy cannot offer tools outside the declared and bound intersection, or bypass HostPolicy/approval.
4. Mutated borrowed identities during model/session I/O must retain received evidence and prevent false success.
5. Factory failure/cancellation must close only owned resources and keep a retriable authority.

### Task 1: Immutable definitions and scoped catalog

**Files:** Create binding_types.py, binding_catalog.py, binding_definitions.py; tests/test_agent_bindings.py.
**Interfaces:** BindingSelection.inherit/ref/disabled and to_dict/from_dict; AgentBindingDescriptor(**roles); AgentDefinition(spec, bindings); BoundDefinition(definition, agent_bindings); BindingCatalog(scope).register(role,id,version,component); binding_component(role, selection, scope).

- [x] Write tests using real AgentSpec/WorkflowSpec, malformed/null/unknown choices, detached JSON, Scope denial, duplicate version and drift.
- [x] Run .venv/bin/python -m pytest tests/test_agent_bindings.py -q; expected failures for absent public implementation.
- [x] Implement immutable finite JSON declarations and pure validation/resolution; unsupported choices fail explicitly.
- [x] Re-run the task file; expected PASS.

### Task 2: Local execution routing and versioned release

**Files:** Create binding_runtime.py; modify types.py/engine.py/runtime_config.py load_spec; tests/test_binding_execution.py.
**Interfaces:** submission_request supports wrappers; binding runtime resolves step views with manifest and effective tools; LocalEngine(binding_catalog=None) uses explicit run-based selection.

- [x] Write integration tests with one SQLiteStore and two different contexts/providers/facts/knowledge, concurrent Runs, sequence identical provider aliases, stateless mode, tool subset denial/approval, replay/removal/drift.
- [x] Run .venv/bin/python -m pytest tests/test_binding_execution.py -q; expected missing routing/acceptance failures.
- [x] Add only new wrapper branches; route pure/model/reference/finalization boundaries from each Run, preserving legacy manifests.
- [x] Verify targeted engine/framework suites; expected PASS.

### Task 3: Declarative assembly, installed use and compatibility

**Files:** Modify runtime_config.py/runtime_builder.py/__init__.py; tests/test_binding_assembly.py; docs/agent-bindings.md; relevant roadmap/status/release metadata.
**Interfaces:** RuntimeProfile(..., binding_components=None), catalog schema v2, shared sync/async factories and existing BuildContext ownership.

- [x] Write JSON/TOML v2 and v1-refusal tests, custom factory cleanup/cancellation, ProfiledEngine old-release routing and installed wrapper use.
- [x] Run .venv/bin/python -m pytest tests/test_binding_assembly.py -q; expected missing config/build integration failures.
- [x] Assemble catalog with existing registry and lifecycle; export public DTOs; document examples and capability/refusal matrix.
- [x] Run full pytest, Ruff check/format, build and installed smoke/legacy wheel checks; record actual skips and results.
- [x] Perform a separate final review under the executing-plans skill, address important findings with reproductions, record completion locally.
