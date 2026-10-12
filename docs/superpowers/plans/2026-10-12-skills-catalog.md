# Skills Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. Steps use checkbox syntax. One final fresh read-only reviewer only; no implementation subagents.

**Goal:** Deliver replaceable bounded instruction catalogs and original managed read tools with Memory/File defaults.
**Architecture:** SkillSpec/pure snapshots → synchronous catalog defaults → original managed ToolSource and declarative builders. Original Local/Temporal remain authorities; no instruction-driven permission grant.
**Tech Stack:** Python3.11+, standard library, existing JSON Schema/ToolSource/Workspace; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-12-skills-catalog-design.md

## Global Constraints

- Baseac7b87e/dev77. Inline/only local commits; no push. Keep dev77 until actual six-composition new service proof, then dev78.
- Name slug1..64; description4096bytes; version256bytes; instruction per-port max1..16777216/default1048576; catalog max1..1000/default100; aggregate64MiB; File manifest1MiB.
- JSON metadata + ordinary Markdown default; no complete YAML, automatic permissions, script execution, new kernel/protocol or Agent.skills role claim.
- Existing22 starter bytes/default releases remain unchanged; every port/source call uses original Scope and real handler ownership.

## Review Focus

- Same-name changed content/metadata must change immutable identity; File drift cannot silently refresh (Tasks1/2).
- Lazy custom outputs/boolean numeric identity or forged Scope/hash must refuse without executing them (Task3).
- Source close and loop cancellation must retain a genuinely started file handler; borrowed catalog stays borrowed (Tasks2/3).
- Skill text naming protected tools must never grant those tools; member catalogs remain original grants (Task3).
- Invalid declarations must fail before any root/FD allocation and partial assembly must close owned resources (Task3).

---

### Task 1: Pure SkillSpec and Memory catalog

**Files:** create src/ralf_agent/skills.py; modify src/ralf_agent/__init__.py; tests/test_skills.py.
**Interfaces:** consumes Scope/ordinary validation from original Workspace. Produces exact public SkillError/SkillSpec/SkillCatalogPort/InMemorySkillCatalog signatures, skill_metadata/validate_skill_list/validate_skill_get helpers and list/get snapshots defined by Spec.

- [x] Write failing tests for metadata/digest/order/pagination/detachment, changed content identity, strict slugs/version/UTF8/Scope/numeric/aggregate bounds and close. `test_public_memory_skill_catalog_and_scope` asserts list/get exact Scope, sha256 and original instructions; denied Scope raises AuthorizationDenied.
- [x] Run `.venv/bin/python -m pytest tests/test_skills.py -q -W error`; Expected missing public API failure.
- [x] Implement immutable specs, pure metadata/snapshot validators and locked Memory default; no File/source/model I/O.
- [x] Run new suite plus original tests/test_workspace.py tests/test_workspace_writes.py; Expected all pass. Formal task completion only after command/actual exit read. Batch commit after final gates.

### Task 2: Frozen filesystem catalog

**Files:** create src/ralf_agent/filesystem_skills.py; tests/test_filesystem_skills.py; modify exports.
**Interfaces:** consumes SkillSpec/snapshots/Memory limits; produces FileSystemSkillCatalog exact constructor, stable full identity, original revision checks and owned close.

- [x] Write failing File tests: JSON manifest/default Markdown, same name/body drift, root/metadata/path aliases and missing files, denied Scope, typed limits/duplicate names/malformed metadata, constructor cleanup and actual blocked handler close.
- [x] Run `.venv/bin/python -m pytest tests/test_filesystem_skills.py -q -W error`; Expected missing File API.
- [x] Implement with original FileSystemWorkspace; fixed original root/manifest/file revisions and outer actual-operation ownership, no recursive loader or hidden refresh.
- [x] Run new + tests/test_skills.py tests/test_filesystem_workspace.py tests/test_workspace_review.py; Expected all pass; formal completion and final-batch commit.

### Task 3: Managed tools, default configuration and authority proofs

**Files:** create src/ralf_agent/skill_tools.py, src/ralf_agent/skill_factories.py, tests/test_skill_tools.py, tests/test_skill_configuration.py, tests/test_skill_execution.py, tests/test_skill_temporal_service.py; locate original factory-registration file before editing; exports.
**Interfaces:** consumes list/get strict snapshots/catalog identity and actual File close. Produces SkillToolSource constructor, skill_list/get descriptors, original owned factory tools/skills-file and six original composition proofs; dedicated skills binding stays rejected.

- [x] Write failing tests for Source identity/descriptors/results, lazy/forged custom port responses, read-only policies, borrowed close and real thread cancellation; invalid pure declarations before open and partial cleanup; JSON/TOML and SDK replacement.
- [x] Run new offline suites; Expected missing Source/factory or unsupported adapter. Implement native Source using original tracker and exact result validation; config values from Spec, no new execution state.
- [x] Write and pass six Local compositions with member tool-set selection, protected tool names in instruction text denied, original saved read recovery. Write actual six Temporal restart/History cases and run against owned local Service with no skips; wait actual test exit before claiming proof.
- [x] Run all new offline + original workspace/tool/thread contracts. Only after actual six pass bump dev78. Formal task command/exit and final-batch commit.

### Task 4: Documentation and frozen acceptance

**Files:** create docs/skills.md and architecture/reviews/2026-10-12-skills-catalog.md; update current capabilities/status/progress/remaining/harness/CHANGELOG/CI/version.
**Interfaces:** consumes all prior actual/default/replacement proofs; produces honest catalog subset/replacement guide and frozen delivery evidence.

- [x] Run installed Memory/File/Source/config/six contracts, required actual service, old77↔78 default Local/CLI/Temporal/native compatibility and22 unchanged templates; runnable isolated installed examples and exact module/doc hashes.
- [x] One fresh read-only whole-batch review; all grades/declines/rulings before ONE Important RED→GREEN pass; Minor deferred, no re-review.
- [x] Freeze green full source, build/install/hash/doc checks; stop/wait every owned service; only local commit, formal Task4, closure record and own SDD archive. Expected full capability goal stays active, no implicit Agent.skills/YAML/Sandbox/quality completion claim.
