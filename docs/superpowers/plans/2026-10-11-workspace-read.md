# Read-only Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans INLINE. No implementation agents; exactly one fresh final reviewer. The user explicitly authorized continuous implementation and local commits, no push; do not repeat stage/finish permission menus.

**Goal:** Deliver replaceable bounded read-only Workspace defaults through original managed tools.
**Architecture:** Synchronous data port and POSIX/Memory defaults; async ToolSource owns true handlers; original Engine/History adopts all execution facts.
**Tech Stack:** Python stdlib/os/threading/hashlib and existing ToolSource/RuntimeBuilder/Temporal APIs; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-11-workspace-read-design.md.

## Global Constraints

- Base de59df6/dev74; original manifests and22 starter contents unchanged; version75 only after required actual authority proof.
- Signatures/output fields exactly spec. Pure path length4096bytes/128components; entries1..1000, read1..16777216/default1048576; rawscan max_entries+3.
- Protected `.git`/`.ralf`, exact trusted Scope allowlist, no caller physical root, writes or automatic Context I/O.
- Memory4096files/16MiB each/64MiB total. Pin real root/device/inode/ownedFD; no UUID metadata creation.
- FD-relative nofollow/regular/singlelink/samedevice, before/after address/revision checks and finally close.
- Closing retains in-use FD; source borrows port; original dual tracker/owned ledger drain before port close.
- No new authority/Agent.workspace role/Sandbox/Runner/parity or full capability completion.

## Review Focus

1. Ancestor/root/leaf replacement, hardlinks or special entries cannot bypass host-selected root or return stale unconfirmed content.
2. Path aliases, surrogate Unicode and Scope/config type tricks must refuse before filesystem I/O and leak no host diagnostics.
3. List/read scan, growth and memory input accounting must obey bounds without silent truncation.
4. Queued/running cancellation and closed originating loops retain real operation ownership and root FD until actual exit.
5. Discovery/configuration/source identity changes and partial resource cleanup cannot bypass original Policy/Action/History or close borrowed ports.

### Task 1: Workspace contract and two defaults

**Files:** create src/ralf_agent/workspace.py,filesystem_workspace.py; export __init__.py; tests/test_workspace.py,test_filesystem_workspace.py.
**Interfaces:** produces WorkspacePort/WorkspaceError, InMemoryWorkspace/FileSystemWorkspace signatures and result records in spec. Consumes existing Scope and RalfError/AuthorizationDenied/DefinitionMismatch.

- [x] Write missingAPI RED using both adapters' real stat/list/read/Scope/UTF8/bounds and copied results; assert no implicit root metadata.
- [x] Implement port validation and Memory snapshot; POSIX root FD traversal and independent active lifetime. Run tests; add real replacement/mutation/FD and Unicode/unsafe entry probes RED→GREEN before any extra implementation.
- [x] Formal task-done new port/default tests; version74 stays. Expected: same caller-visible contract, sanitized refusal, no write and root retained during true operation.

### Task 2: Managed source, assembly and recovery

**Files:** create workspace_tools.py,workspace_factories.py; modify runtime_builder.py/__init__.py; tests/test_workspace_tools.py,test_workspace_configuration.py,test_workspace_temporal_service.py.
**Interfaces:** consumes Task1 port/identity/results. Produces WorkspaceToolSource(workspace,version,caps), original async tools/workspace-read config and three fixed read tools.

- [x] Write missingAPI/factory RED; original Registry SDK injection, caller Scope and fixed caps; true canceled running/queued/closed-loop source ownership and borrowed close.
- [x] Implement original dual tracker/source checks and read_only descriptors/policies; pure config before allocation, owned port→source ledger and partial close. Formal related source/builder tests GREEN.
- [x] Actual Local Graph/native accepted-result restart and Temporal FS/Memory approval/restart/repeated command/History tests required with zero skips; version remains74 until proof. Expected: no rediscovery side effects, original result evidence survives data changes, no new execution protocol.
- [x] Formal task-done source/config plus original tool sources/thread/builder/async contracts.

### Task 3: Installed usage and final delivery

**Files:** docs/workspace.md, capability/status/progress/remaining/harness docs, architecture/reviews/2026-10-11-workspace-read.md, CI/version.
**Interfaces:** consumes Tasks1–2 proof; produces explicit SDK/config/replaceable usage and honestly bounded capability record.

- [x] Sync scope/75, build/install minimal+SDK; actual installed services, dev74 defaults/22 templates/CLI identity compatible; no false workspace-role claim.
- [x] ExactlyONE fresh whole-batch read-only review; full report/regrade every decline and all rulings before ONE unified Important RED→GREEN fixpass; ledger Minor only.
- [ ] Frozen fullsource/build/install/service/old74compatibility/hashdocs; stop and wait original owned service sessions; localcommit then formalTask3done; archive/delete only own completedSDD. Expected: all required true services pass, no push, fullgoal stays active.
