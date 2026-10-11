# Fixed Business Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans INLINE, no implementation agents. One final fresh-context review. Continuous human authorization overrides repeated spec/plan/finish menus; local commits only, no push.

**Goal:** Improve host-fixed CLI adoption and add bounded HTTP JSON ToolSource through original execution contracts.
**Architecture:** Host-fixed transport adapters, explicit policies and actual request ownership; original Engine/History controls approval, effect identity and recovery.
**Tech Stack:** stdlib/httpx/jsonschema/pytest, no new base dependency.
**Spec:** docs/superpowers/specs/2026-10-11-fixed-business-tools-design.md.

## Global Constraints

- Base1ee4695/dev72; preserve default manifests, Local/Temporal authority and existing21 starter contents.
- HTTP fixedPOST URL without credentials/query/fragment/control whitespace, defaultempty headers/environment; no redirect or automatic retry.
- timeout(0,300], byte limits1..16777216/default1048576, UTF8 finite JSON/no duplicates/surrogates.
- Actual source+ambient ThreadExecutionTracker owns synchronous request/Client close after caller cancellation; close may await bounded socket timeout, never implies downstream cancellation.
- CLI version1 original generated apps retained; new starter Profile version2 read/plan/write, no hidden model calls.

## Review Focus

1. Await cancellation/closed loop or shutdown must preserve actual HTTP handler and client ownership, including queued calls.
2. URL parsing/headers/defaultenvironment/redirects cannot turn fixed input into another destination or expose credential diagnostics.
3. Streaming/compressed/malformed/oversized/lone-surrogate responses and partial network failures must not become successful evidence or unbounded accepted payloads.
4. Bad configuration and partially constructed async resources must refuse or drain through original ledger without changing historical releases.
5. CLI read/plan restart and HTTP committed-write/response-loss must preserve original effect keys/receipts, Temporal History and default72 compatibility.

### Task 1: CLI declaration and complete starter

**Files:** modify cli_tools.py, cli_tool_factories.py, cli_starter.py; tests/test_cli_tools.py, test_cli_tool_configuration.py, test_cli_starter.py; docs/cli-tools.md.
**Consumes:** original fixed CLI ToolSource/GraphNode/Transform/Policy. **Produces:** consistent pure cwd refusal, empty non-executable argv compatibility, new version2 read/plan/write starter.

- [x] Add tests: SDK false/zero/empty cwd raises ValidationError/no process; explicitNone defaults; factory declaredNone/False/0/empty refusesprepare before store; fixedempty argument delivered unchanged; starter read/plan persisted before approval, no business write and no repeatedread after restart; run RED.
- [x] Implement only these boundaries and new starter pure Transform/configuration; retain old apps. Run cli contract/config/starter plus original ToolSource/workflow/starter suites GREEN.
- [x] Task1 formal task-done test gate; no independent taskreview. Batch commit after finaldelivery.
Expected: valid cwd/defaults unchanged, original21templates unchanged, actual one approved write and read once.

### Task 2: HTTP JSON source

**Files:** create http_tools.py,http_tool_transport.py (and focused shared JSON helper only if needed); export __init__.py; tests/http_tool_fixture.py,test_http_tools.py.
**Consumes:** ToolDescriptor/InvocationContext/ThreadExecutionTracker/canonical JSON. **Produces:** HTTPToolSource signature in spec, original source protocol/ownership.

- [x] Write missingAPI real-localserver POST tests, immutable headers/no env/redirect/error/bytes/schema/finiteUnicode, queued/running cancellation and actual close; run RED.
- [x] Implement pure validation/fixed identity and actual bounded request, retained source+ambient tracker and retryable drain; run new tests plus original CLI/source/thread suites GREEN.
- [x] Formal task-done gate for source tests; version remains72 until actual behavior evidence.
Expected: sanitized ToolSourceError, no request on invalid input/discovery, one POST and no implicit retry, real client closes before actual handler completion.

### Task 3: HTTP declarations and delivery

**Files:** create http_tool_factories.py; wire runtime_builder.py; tests/test_http_tool_configuration.py,test_http_temporal_service.py; docs/http-tools.md,capability/status/acceptance/CI/version.
**Consumes:** Task2source; original async ledger/ToolPolicy. **Produces:** tools/http-json factory/owned cleanup and package evidence.

- [x] RED factory bad config before allocation/partial-ownedcleanup and Localapproval/committed-write/lost-response; implement1..256 declarations, existing effect-key mapping; same source in actual Temporal Activity+PG journal/replay.
- [x] Sync docs to actual boundaries; candidateinstalled source/default72/CLI-v1 proof; ONE wholebatch fresh readonly review using BASE→WORKTREE/allnewfiles, regrade all/ledger declines/minors, unified ImportantRED→GREEN.
- [x] Freeze fullsuite/build/install/core/actualservices/default72compat, hashpackage/docs, stop and wait own services; localcommit then Task3taskdone, archiveownworkspace. Fullgoal remainsactive.
Expected: each mandatory actual-service probe passes/no skips, old default identities/receipts once effects retained; no claim fullR12/parity.
