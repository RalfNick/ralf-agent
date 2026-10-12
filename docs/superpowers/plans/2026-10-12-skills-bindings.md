# Skills Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. Steps use checkbox syntax. One final fresh strongest read-only reviewer only; no implementation subagents.

**Goal:** Select or disable a fixed skill catalog per Agent through original binding and tool grants.
**Architecture:** Borrowed pure SkillBindingResource → Local/Temporal original binding resolution → original managed read Actions. Catalogs remain reference data; no new prompt or execution authority.
**Tech Stack:** Python3.11+, existing immutable JSON/tool/binding protocols, no new dependency.
**Spec:** docs/superpowers/specs/2026-10-12-skills-bindings-design.md

## Global Constraints

- Basecd1653e/dev78. Continuous inline authorization, local commits only/no push. Keep dev78 until required actual six-composition proof; then dev79.
- At most256 unique explicit names,1..128 characters/512UTF8bytes/no control; ordinary finite native identity. Exact Resource kind skill-binding-resource/version1/source/tools; Source kind skill-tool-source/version1/behavior_version/catalog/max_entries/max_bytes with ordinary SHA256 catalog_digest.
- Inherit/default manifests and22 existing starter bytes unchanged. Ref/disabled only reduce original Agent/tool_set grants for native Skills tools; ordinary business and Workspace grants unchanged.
- No selector/automatic Context/YAML/async catalog/plugin/Sandbox/Runner/fullgoal completion claim. Borrow registry; original Source owns real handlers and borrows catalog.
- Opt-in Local kernel local-bindings-13 and Temporal skills_binding_protocol=1. Verify old78 refusal before actual model/tool Activity; unknown field alone not assumed safe.

## Review Focus

- Nested canonical identity distinguishes bool/int and rejects lazy/custom types before copying (Task1).
- Disabled selection removes only Skills tools; simultaneous Workspace/tool_set selection never adds/removes unrelated grants (Task2).
- Ref catalog belongs to original host Scope/version and resources remain borrowed (Tasks1/2).
- Parent/member paths and fixed original release persist through restart, dynamic and nested selection (Tasks2/3).
- New opt-in can never run on old78 Worker before protocol refusal (Task3).

---

### Task 1: Pure borrowed resource and grant selection

**Files:** create src/ralf_agent/binding_skills.py, tests/test_skill_bindings.py; modify public exports only.
**Interfaces:** consumes original ToolRegistry.manifests, strict native Source1 registration and ordinary Skill data; produces SkillBindingResource(registry,*,names).identity and select_skill_tools(names,manifests,resource_identity)->tuple of effective original names. New helpers _names/_record may wrap original bounded names and strict snapshot validation.

- [x] Write tests for native two-tool resource, detached identity, single-source matching, malformed names/effects/digest/identity and canonical bool/int difference, changed registrations and borrowed close. Ref intersects existing names and retains business tools; disabled strips native skills only; zero match denies.
- [x] Run `.venv/bin/python -m pytest tests/test_skill_bindings.py -q -W error`; Expected absent public API/selector failures before product.
- [x] Implement pure Resource/selection using original registrations, no model/catalog/client I/O or resource close.
- [x] Run new plus tests/test_workspace_bindings.py tests/test_workspace_binding_review.py; Expected pass, formal task completion and final-batch commit after gates.

### Task 2: Local role and declarative default

**Files:** modify binding_catalog.py, binding_runtime.py, runtime_builder.py, skill_factories.py; create tests/test_skill_binding_configuration.py and tests/test_skill_binding_execution.py; locate existing capability/release allow lists before edit.
**Interfaces:** consumes pure Resource/selector and existing BindingSelection/AgentBindingDescriptor.skills; produces SELECTABLE skills role/ref/disabled, exact resource records, opt-in local-bindings-13 and skills/registered-tools default. Validator returns None, pure config exactly names; borrowed original context.tools registry.

- [x] Write failing role/default factory tests including explicit Scope, selector refusal, no already-granted match, both tool_set/Workspace intersection, typed forged identity and partial cleanup before/after allocation. Expected unsupported skills role/factory.
- [x] Implement component_identity, original resolver tool intersection and explicit kernel; inherited components and manifests retain old bytes.
- [x] Write/run six Local original approval/restart/saved-read cases selecting independent member catalogs via skills role. Dedicated role never executes instruction text or grants protected tools.
- [x] Run new Local/config plus tests/test_skill_bindings.py tests/test_workspace_binding_configuration.py tests/test_workspace_binding_execution.py tests/test_binding_execution.py. Expected pass; formal task command must use actual found paths, final-batch commit.

### Task 3: Temporal role and actual authority proof

**Files:** modify temporal_bindings.py, temporal_state.py, temporal_activities.py; create tests/test_skill_binding_temporal.py and tests/test_skill_binding_temporal_service.py; locate actual existing Temporal binding tests before edit.
**Interfaces:** consumes Resource/selector and existing fixed catalog/definition; produces skills role, typed protocol1 producer/validation, original History member dispatch/grants. No new Activity/state authority.

- [x] Write failing SDK tests for ref/disabled/selector/wrongScope/missingprotocol/falseprotocol, native resource identities and selected registration drift; expected unsupported role. Implement same shared pure selection and original published protocol before dispatch.
- [x] Required actual owned Temporal six-composition approval/Worker restart/repeatcommands/savedread/History plus per-member distinct catalog tests, zero skips; actual old78 Worker new opt-in refusal before ANY original model/tool Activity; stop/wait helper Workers.
- [x] Run new SDK/offline groups with original TemporalWorkspace/ToolSet grants; all pass. Only after required actual proof bump dev79; formal task completion and final-batch commit.

### Task 4: Documentation and frozen delivery

**Files:** docs/skills.md (or separate skills-bindings.md if clearer), architecture/reviews/2026-10-12-skills-bindings.md, capability/status/progress/remaining/harness/CHANGELOG/CI/version.
**Interfaces:** consumes all prior proof, produces honest per-Agent binding subset and usable installed guide.

- [x] Fresh installed core/SDK contracts and actual service, old78 default Local/CLI/Temporal/native two-way recovery,22 original starterbytes; exact source/wheel/sdist/install hashes and runnable guide/docs/CI paths.
- [x] One fresh strongest read-only whole-batch review; regrade all findings and Declined before ONE unified Important TDD fix pass. Minor deferred/no re-review.
- [x] Green final full suite, rebuilt final docs/package, owned services actual stop/wait, local main commit/formalTask4/closure commit, collect all rulings and archive only own SDD. Full R01–R26 remains ACTIVE.
