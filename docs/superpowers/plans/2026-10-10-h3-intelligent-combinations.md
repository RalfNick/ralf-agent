# H3 intelligent combinations implementation plan

> For agentic workers: use superpowers:executing-plans inline. User explicitly authorizes continuous implementation and final local commit, no push.

**Goal:** usable and replaceable H3 semantic retrieval, ranked bounded recall and Plan/Team starting combinations.
**Architecture:** existing HybridRetriever/Memory/ManagedDataContext/AgentHarness/Runtime; pure selected indices, owned factory resources and original Run authority.
**Tech:** existing Python/httpx/SQLite/pytest; no dependencies or live model calls.
**Spec:** docs/superpowers/specs/2026-10-10-h3-intelligent-combinations.md

## Global Constraints

- Preserve old preset version-1 and ManagedDataContext identities; new behavior opt-in.
- Pure selectors cannot modify references, call models, select outside candidates or expand Scope.
- Semantic profile requires explicit HTTP embedding, no hash fallback; abuild owns cleanup.
- Plan/Team use original managed children and declarations; no new authority.
- Final local commit, no push, no credential files or network bootstrap.

## Review Focus

- Selector can mutate arguments or return lazy/invalid indices; original references and permission boundaries stay fixed.
- Query-relevant Facts still compete with recent Session and Knowledge; preserve semantic branch order and complete recent turns.
- Model-summary adoption after restart must retain original selection and source identities.
- Custom Plan/Team members retain original independent bindings and stable declaration identity during approval recovery.
- Original profiles and default data context recover across wheel versions; selected new profiles do not alter old identities.

### Task 1: synchronize current capabilities and ranked reference context

**Files:** docs/implementation-status.md, remaining-work.md, architecture/viewpoints/{framework-capabilities,harness-runtime}.md, docs/m1-acceptance.md; create src/ralf_agent/reference_selection.py and relevant_context.py; create relevant_context_factories.py; update runtime_builder.py, __init__.py; tests/test_relevant_context.py.
**Interfaces:** ReferenceSelector.select(task,references)->list[int]; OverlapReferenceSelector(max_references=32,max_query_chars=4096); RelevantDataContext(artifacts,selector=None,**managed_data_options).

- [x] Update current tables to dev46 Local ten/Temporal five roles and actual memory/context support; label old baselines historical.
- [x] Write tests selecting relevant Fact over irrelevant one under limited context, preserve Knowledge order and newest Session; reject mutated/lazy/duplicate/outside indices and drift.
- [x] Run `.venv/bin/pytest -q tests/test_relevant_context.py`: expected absent new classes/fact priority failures.
- [x] Implement pure validated selection and pinned opt-in managed context/factory reuse; no Engine edits.
- [x] Add summary fallback/finish restore and factory cleanup tests; run new tests plus existing data/managed context and recommended profile regressions, expected green.

### Task 2: semantic/memory profiles and Plan/Team declarations

**Files:** recommended.py; create recommended_orchestration.py; __init__.py; tests/test_h3_combinations.py, test_recommended_orchestration.py.
**Interfaces:** recommended_profile(kind,embedding=None,knowledge_namespace='default',existing_options); recommended_harness(kind,members=None,agent_bindings=None,**existing_spec_options)->AgentHarness.

- [x] Write tests `recommended_profile('semantic-knowledge',embedding=...)`, missing/hash embedding rejection, memory-recall fixed namespace, default/custom Plan/Team facade and bindings.
- [x] Run new tests; expected unknown preset/missing public helper failures.
- [x] Add versioned opt-in declarations using existing sqlite-hybrid-http/relevant-data and original orchestration specs; preserve all original presets.
- [x] Exercise real localhost embedding fixture -> explicit ingestion/index -> Agent, then source change refusal; JSON/TOML, async ownership and failed assembly cleanup.
- [x] Verify default/custom Plan/Team approval/restart/duplicate submit and one business effect, including model Planner fixture and nested members; expected green.

### Task 3: acceptance and dev47 local release

**Files:** docs/h3-intelligent-combinations.md, existing capability/recommended guides, architecture/reviews/2026-10-10-h3-intelligent-combinations.md, README/CHANGELOG, pyproject.toml/__init__.py.
**Interfaces:** consume new declarations through installed Runtime/AgentHarness, unchanged original profiles.

- [x] Add process-exit recovery for original managed-summary received response and source-preserving selection; run acceptance tests, expected green.
- [x] Bump dev47 and record exact supported scope, no live semantic/answer quality claims, existing interfaces and owned/borrowed behavior.
- [x] Run whole pytest suite plus Ruff check/format and git diff --check; expected green with skips counted.
- [x] Build wheel/sdist with local deps, install into scratch and run new contracts outside checkout, original profile identity and dev46/dev47 approval snapshot compatibility.
- [x] One fresh reviewer using full diff/spec/focus; fix Important in one RED/GREEN pass and rerun suite, record rulings/minors.
- [x] Final local commit, no push; remove only own plan scratch after committed acceptance record.

Final review correction: complete Session turns and native task/result reach the original budgeter; ordinary Fact keys participate in scoring; positive Facts interleave with Knowledge while preserving its relative semantic order. Seven reproduced failures turned green; no original base policy change. Final whole-suite rerun passed 2972/92; installed75, original-profile six-way approval compatibility and actual eight process exits passed.
