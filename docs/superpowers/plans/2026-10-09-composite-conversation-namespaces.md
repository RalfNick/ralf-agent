# Composite conversation namespaces implementation plan

> Use superpowers:executing-plans inline, TDD, own ledger, one fresh final reviewer.

**Goal:** H2b3 authorized colocated composite root namespaces on existing authority.
**Architecture:** Separate host conversation resource from member defaults; original
Session binding records root resource/selection, shared release checks revalidate it.
**Spec:** docs/superpowers/specs/2026-10-09-composite-conversation-namespaces.md
**Tech:** Python3.11+, SQLite/asyncio, existing ports; no new dependency.

## Global constraints

Current dirty dev35 is the baseline; capture its148 SDK modules/actual wheel in this
plan's own workspace before edits. Preserve existing changes/HEAD5626c17; no auto
commit/push or sibling private-workspace access. Keep schema1/2/3/default identities,
owned/borrowed lifecycle and existing member bindings. Namespace only by host
allowlist; records/port calls in original transaction, no SQLiteMemory construction
inside it. Continue user-approved architecture without duplicate approval gates.

## Review Focus

1. Same logical ID across namespaces must not share parent/child history or be
   bypassed by raw/selected-backend aliases; ordinary member defaults stay original.
2. Original root resource/selector must be checked before effects, including child
   dispatch, while received effects remain durable if configuration changes late.
3. Duplicate requests/controls survive moved defaults and original approved
   parameters; observations remain pure and actual handlers/unknown holds stay busy.
4. Schema4 enablement is transactional/monotonic; default1/2/3 remains compatible,
   actual dev35 refuses4 before any model/tool dispatch.
5. Failed initialization/port/lifecycle never closes borrowed resources or transfers
   another authority; malformed/root metadata must refuse rather than fall back.

### Task 1: Root selection and optional admission extension

**Files:** create session_conversations.py; modify engine.py, local_sessions.py,
agent.py/agent_runtime.py, session_ports.py/sqlite_sessions.py/storage.py;
create tests/test_conversation_namespaces.py.
**Interfaces:** LocalEngine.conversation_resource, optional open_session namespace,
root selection descriptor in binding; optional prepare_conversations/Store marker3.

- [x] Write real red/blue seven-composition tests (literal distinct saved addresses),
  host allowlist/default/explicit None and raw alias refusal. Run RED; Expected:
  unsupported constructor/namespace today, no paid dispatch.
- [x] Implement separate validated colocated host resource, selection/pinning,
  canonical parent storage ID and schema4 optional extension. Default paths unchanged.
- [x] Run new/default Session/binding/composite/lifecycle suites; Expected: pass.
- [x] task-done records actual gate; keep work local.

### Task 2: Original binding recovery and effect boundaries

**Files:** session_conversations.py/engine.py/local_sessions.py;
tests/test_conversation_namespace_recovery.py.
**Interfaces:** original-binding revalidation via existing release checks, same-route
CAS rebind, original command replay, exact resource/port completion checks.

- [x] RED restart approval/control receipts, moved defaults replay, Scope/backend/
  allowlist drift before tool dispatch, late drift preserves received evidence,
  native↔composite same-route rebind and lazy/foreign port activation rollback.
- [x] Add minimal original-binding checks without new execution authority;
  raw admission and observations retain original behavior.
- [x] Run focused suites with warnings-as-errors; Expected: pass. task-done.

### Task 3: Actual installed compatibility, docs and final review

**Files:** dev36 version; Session API, status/checklist/design/README/changelog and
architecture/reviews/2026-10-09-composite-conversation-namespaces.md.
**Interfaces:** captured actual dev35/new wheel schema1/2/3 compatibility and4 refusal,
installed schema4 original approval recovery, unchanged exports/deps/starters.

- [x] Build/install outside checkout; old/new1/2/3 recover both directions; old refuses4,
  new restores configured namespaces/receipts/once-per-Action effects. Byte/metadata gates.
- [x] Record actual support and all costs, remaining remote/Temporal/H3 scope.
- [x] One fresh read-only most-capable reviewer of own captured dev35 delta. Re-grade;
  Important/Critical one RED→GREEN fix pass, no re-review; ledger minor deferrals.
- [x] Full pytest -Werror, installed contracts, Ruff/format/whitespace/docs/package
  checks; Expected: pass. task-done attests actual evidence; no automatic integration.
