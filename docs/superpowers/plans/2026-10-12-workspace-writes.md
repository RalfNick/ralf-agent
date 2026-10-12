# Managed Workspace Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL executing-plans INLINE. One final fresh read-only reviewer, no implementation agents. Existing continuous user authorization covers written design/plan and local commits without repeated approval menus. Do not push.

**Goal:** Replaceable CAS/idempotent Workspace writes with durable POSIX recovery, native tools and Local/Temporal bindings.
**Architecture:** Downstream receipt journal and root write lease; original Engine/History/Action/Source remain authoritative. Pure Workspace binding intersection includes explicitly supported Source2 write registrations.
**Tech Stack:** Existing Python/POSIX/sqlite3/ToolRegistry/Profile/Temporal, no dependencies.
**Spec:** docs/superpowers/specs/2026-10-12-workspace-writes-design.md.

## Global Constraints

- Base0501054/dev76; inherited readonly APIs/manifests/22 starters unchanged. Version77 only after required actual authorities pass.
- Public methods/classes/signatures, exact receipt fields, key/version/byte/capacity bounds and CAS create-only semantics follow Spec Port section.
- One scoped key pins one canonical request. Queries/confirmed receipt reuse never rewrite user files. Equal content alone never proves an unknown write.
- Original POSIX root/nofollow/Scope rules; exclusive writer lease before SQL/WAL, persist intent before rename, true-handler drain before close. No arbitrary-writer/Sandbox guarantee.
- Source2 original reserved-key/approval/executor contract; Local explicit Source2 kernel12, Temporal protocol2; Source1 default bytes unchanged.
- All product behavior TDD; one whole-batch review and single Important fix pass; formal tasks and only local commit(s). Full capability goal remains active.

## Review Focus

1. Bool/subclass/numeric JSON identity tricks, malformed receipt/request data and key collisions must not bypass CAS/Scope or adopt another root.
2. Crash after rename with no receipt, matching foreign text but wrong inode, modified temporary proof and metadata aliases must not manufacture confirmation or repeat an unverified overwrite.
3. Global loop cancellation/queued sync work/partial close must not release the writer lease while a real handler can mutate files.
4. Member projection/tool_set/disabled/policy downgrade must not expose an excluded write, hide required approvals or widen parent grants.
5. Original read defaults and real76 release recovery remain unchanged; actual old Workers must refuse protocol2 before effects.

### Task 1: Write port and Memory default

**Files:** create src/ralf_agent/workspace_writes.py, tests/test_workspace_writes.py; export in src/ralf_agent/__init__.py.
**Interfaces:** consumes WorkspacePort/original path/Scope/bounds/canonical helpers. Produces WritableWorkspacePort, InMemoryWritableWorkspace and write_request/write_receipt/validate_write_receipt with Spec exact signatures shared by POSIX/Source.

- [x] Add missingAPI tests for create then CAS, same-key detached receipt after changed file, conflicting request key, no mutation on capacity/error, Scope/path/version/key/type/size/NUL rejection, stable identity and closed reads/writes/queries. Example: create("note","A",expected_version=None,effect_key="k1"); read.version equals receipt.file_version; CAS("B",expected_version=first.file_version,key="k2"); replay k1 returns original A receipt while read returns B; different k1 request raises IdempotencyConflict. Run `.venv/bin/python -m pytest tests/test_workspace_writes.py -q -W error`; Expected missing public API RED before product code.
- [x] Implement Spec exact port and Memory behavior under existing root lock; receipt/request validators reject nonordinary/invalid data. Run new tests plus tests/test_workspace.py,test_workspace_tools.py,test_workspace_bindings.py; Expected all GREEN and readonly APIs unchanged.
- [x] Formal task-done same verified files; commit may fold final batch per continuous authorization.

### Task 2: POSIX lease and durable file proof

**Files:** create src/ralf_agent/filesystem_workspace_writes.py,src/ralf_agent/workspace_write_journal.py,tests/test_filesystem_workspace_writes.py,tests/workspace_write_crash_fixture.py,tests/test_workspace_write_processes.py; export writer.
**Interfaces:** consumes Task1 pure request/receipt helpers and original FileSystemWorkspace safe FD/root helpers. Produces FileSystemWritableWorkspace exact Spec signatures and durable downstream receipt proof.

- [x] Write missingAPI/two-root/precondition/noalias/lease/close tests; Run filesystem file; Expected true missingAPI RED. Cover symlink/hardlink/private metadata aliases, wrong root identity, bounded single-link temp/capacity and no mutation before valid request.
- [x] Implement owned lease-before-SQL/journal and same-device temp-fsync→intent→rename→parent-fsync→receipt; validate pinned dataset/addresses and actual target proof. Run memory/filesystem files plus original filesystem/workspace_review/artifact process tests; Expected GREEN, resources retained on active/failed close.
- [x] Add true os._exit child windows before rename/after rename/after receipt, reopen/query/replay and tampered target/temp proofs; two process owners conflict until original exit, aliases share ownership. Run processes file; Expected recovery failures RED before corresponding recovery implementation.
- [x] Implement conservative original-inode recovery and receipt reuse, no user-file mutation in query. Run new files and original filesystem tests; Expected GREEN; formal task-done same verified files.

### Task 3: Source, binding and actual authorities

**Files:** create src/ralf_agent/workspace_write_tools.py,src/ralf_agent/workspace_write_factories.py,tests/test_workspace_write_tools.py,tests/test_workspace_write_configuration.py,tests/test_workspace_write_execution.py,tests/test_workspace_write_temporal_service.py; modify binding_workspace.py,binding_runtime.py,temporal_bindings.py,temporal_state.py,temporal_activities.py,workspace_factories.py,__init__.py.
**Interfaces:** consumes native write port/query proof; produces WritableWorkspaceToolSource Source2, workspace-read-write async factory, Source2 fixed grant intersection and protocol2. No additional state authority.

- [x] Write Source missingAPI/request-reserved-key/policy/real-thread/drain tests. Run tools file; Expected RED. Implement managed Source with original tracker, detached receipt adoption, native reconciler and original ToolPolicy; run port/source plus original tool_sources/thread tests; Expected GREEN.
- [x] Write JSON/TOML pure preflight/one allocation/owned close and Source2 ref/disabled Local six compositions, approvals/unknown response/restart/conflict/no excluded read or write, nested/tool_set constraints. Run config/execution; Expected unsupported factory/Source2 RED. Extend pure binding validation/kernel12/default async factory. Run all new offline files plus original six Workspace binding files except required service; Expected GREEN.
- [x] Write pure Temporal protocol2/scope/policy/history tests inside execution file and required six-composition service file. Implement opt-in protocol2/selected effective grants, Source1 defaults exact. Run offline tests then actual self-owned service; Expected every required actual case pass zero skips including Worker restarts/History and real handler lease holding. Then version77.
- [x] Formal task-done all verified offline new files; original runtime/source ownership remains sole execution boundary.

### Task 4: Frozen acceptance

**Files:** capabilities/status/remaining/progress/harness/Workspace guide/CHANGELOG/CI/version; create architecture/reviews/2026-10-12-workspace-writes.md.
**Interfaces:** consumes all native/actual proofs. Produces accurate current subset/default replacement guides and frozen delivery evidence.

- [x] Sync capability subset; build/install fresh core/SDK, installed contracts/required service and actual76↔77 Local/CLI/defaultTemporal/native compatibility/22 unchanged templates/old Worker protocol2 refusal; Expected actual gates all pass, no model-quality/Sandbox claim.
- [x] One fresh whole-batch read-only review; all severity/rulings BEFORE one unified Important RED→GREEN pass; minors deferred. Expected covering RED and GREEN/no secondreview.
- [ ] Freeze fullsource/build/module hashes/docs/install/realservice/compat; stop and wait original owned processes; localcommit/formalTask4; archive only own SDD. Expected fullgoal remainsactive, no push.
