# Configured Conversation Entry Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD, then one
> fresh final reviewer. User explicitly requests continuous execution without stops.

**Goal:** Make authorized Local root Sessions configurable and usable from an installed starter.
**Architecture:** Extend existing component assembly; borrow the original Store.
The original Engine/Session authority owns all state, reference files only reconnect.
**Tech Stack:** Python3.11+, existing JSON/TOML/SQLite/asyncio; no dependencies.
**Spec:** docs/superpowers/specs/2026-10-09-configured-conversation-entry.md

## Global Constraints

Baseline1cad308/dev36. Continue current checkout; never access sibling private
workspaces. Capture actual dev36 wheel in this plan's own workspace before SDK edits.
Keep294 exports/dependencies/extras/default Profile/Run identities and20 starters.
No remote push, credentials or paid calls. Local commits are authorized; preserve
the working tree and continuously take the next capability after verification.

## Review Focus

1. Invalid namespace or custom lazy/foreign resource must not leak a Coordinator,
   close a borrowed store or construct a database during preflight validation.
2. Profile drift/replay/restoration must preserve original approvals, SessionRef,
   RunRef and once-per-Action effects, including explicit None selection.
3. Building a configured Profile must not activate schema4 before a Session opens;
   old/default paths, all member components and selected leaf bindings stay original.
4. Starter references are reconnection data: missing/changed profile, forged Scope
   or refs, conflicting files and cancelled wait cannot become a second execution.
5. Pure starter status must work without valid model configuration and never build
   a runtime; installed package imports/startups must not depend on a checkout.

### Task 1: Configurable colocated root resource

**Files:** create src/ralf_agent/conversation_factories.py;
modify runtime_config.py/runtime_builder.py; create tests/test_conversation_configuration.py.
**Interfaces:** consumes BuildContext.store and namespace_options(namespaces,default);
produces conversation_config(config)->None and colocated_conversation(config,context)
->SessionBindingResource, registered as conversation_resource/colocated-session.

- [x] RED real JSON/TOML Profile + Runtime.from_profile/afrom_profile tests; currently
  RuntimeProfile rejects the unknown component. Literal root addresses differ;
  initial schema1 persists until open; restored approval only writes once.
  `pytest -q tests/test_conversation_configuration.py -W error` Expected: missing support.
  ```python
  profile = RuntimeProfile(
      "app",
      "1",
      {"default": {"adapter": "offline-echo"}},
      components={
          "conversation_resource": {
              "adapter": "colocated-session",
              "config": {"namespaces": ["red", "blue"], "default_namespace": "red"},
          }
      },
  )
  ```
- [x] Add the component kind and register its validator/factory; validator calls
  namespace_options after rejecting fields other than namespaces/default_namespace.
  Factory returns SessionBindingResource(SQLiteMemory(context.store),...).
- [x] GREEN new + runtime_builder/config/async/lifecycle + existing conversation suites.
  Expected: pass, no new dependency or execution authority. task-done records gate.

### Task 2: Installed durable Session starter

**Files:** create conversation_starter.py, tests/test_conversation_starter.py;
modify starter.py and cli.py template choices. Preserve previous20 templates.
**Interfaces:** consumes Runtime.from_profile, load_catalog/load_spec,
SessionRef/RunRef, SQLiteRunReader; produces SESSIONS_FILES passed to create_starter.

- [x] RED create_starter(...,template='sessions') then run actual subprocesses outside
  checkout, literal support/sales output and saved root addresses; duplicate run
  preserves Run/Turn, resume resolves original Profile, status with broken config
  dispatches nothing. Expected: template rejected before implementation.
  ```python
  create_starter(tmp_path / "app", template="sessions")
  # python -m session_app run --input question --command-id one --namespace support
  ```
- [x] Add offline TOML Profile, graph spec, module run/resume/status and README.
  Ref creation uses exclusive write/equality replay; saved original profile resolves
  before runtime creation on resume; Runtime APIs validate actual original refs.
- [x] GREEN starter + runtime/startup/conversation/lifecycle gates, including
  corrupted ref/profile rejection without new Run/effect. task-done records gate.

### Task 3: Distribution, review and continuous-development checkpoint

**Files:** bump init/pyproject dev37; update current docs/checklist/design/changelog;
create architecture/reviews/2026-10-09-configured-conversation-entry.md.
**Interfaces:** consumes Task1/2, captured actual dev36; produces verified dev37
distribution and published actual capability boundaries, no assumed parity.

- [x] Build wheel/sdist and install outside checkout; SDK bytes identical; actual
  old/new schema1/2/3/4 recovery and old declaration refusal; run new starter there and compare
  previous20 complete file trees. Expected: pass.
- [x] One fresh read-only reviewer of baseline1cad308→stage changes with five focus
  points. Re-grade findings, one Important/Critical RED→GREEN fix pass; defer minors,
  no second review. Record all rulings and practical costs.
- [x] Full pytest -W error, installed contracts, Ruff/format/whitespace/link/credential
  hygiene. Expected: pass; task-done attests actual completed gates.
- [x] Commit the verified increment locally and continue the next architecture
  capability; no finish/menu/approval pause or remote publication.
