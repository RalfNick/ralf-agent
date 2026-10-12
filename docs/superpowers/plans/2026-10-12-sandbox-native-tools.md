# Native Sandbox Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline task-by-task. One strongest fresh read-only final reviewer, no implementer agents. Steps use checkboxes.

**Goal:** Deliver replaceable SandboxProvider, a restricted real Docker default, original tools/per-Agent binding and truthful actual-stop/recovery evidence.
**Architecture:** Explicit fixed native environment provider → SandboxToolSource → original ToolRegistry/Engine Action; native lifecycle evidence only, no new Run authority.
**Tech Stack:** Python3.11+, existing httpx Unix Docker API, original mechanical ownership and pure bindings; no mandatory new dependency.
**Spec:** docs/superpowers/specs/2026-10-12-sandbox-native-tools-design.md.

## Global Constraints

- Base d9b5f1a/dev82 finalized5089PASS386configuredSKIP. User authorizes continuous roadmap, local commits only/no push; no repeatapprovalmenus. Write spec/plan before code, inline execution, solefinalreview.
- Frozen SandboxRequest argv1..64/≤65536 UTF8/absolute executable/noNUL, timeout finite(0,300]; nativeIDs64hex/invocationASCII≤128/ScopeUTF8≤512.
- Completed raw DTOs only, no custom copyhooks/lazy; outputtotal≤16MiB. Observationstate explicit; created!=exited and Running=false alone is not proof of executed command.
- Docker localUnix/Linux, explicit preinstalled imageSHA256, API default1.44; no implicit daemon/image start/pull. UID65534, rootreadonly, nohostmounts/network/device/privilege, seccomp/no-new-privileges/capdropALL, finite quotas.
- Defaults256MiB/swap equal/CPU1/pids64/concurrency4/output1MiB/scratch32MiB each; admissible bounds exact spec. actual stop/native query before slot release/close; uncertain cleanup retains ownership.
- Original Source/Policy/approval/budget/effects/adoption and Local/Temporal authority reused. Sandbox ref/disabled intersects existing grants; defaults/22starters byteidentical.
- Product stays82 until actual defaults/original sixcomposition gates pass. Final83 frozen/full/installed/old82/ownedactualstop evidence. FullR01–R26ACTIVE.

## Review Focus

- Image implicitVolumes/entrypoint/healthchecks or daemon/Unixsocket mutation cannot bypass declared nohost/noegress restrictions.
- Ambiguous native create/start/kill acknowledgment and reused name cannot start foreign/duplicate execution; actual observation source/Scope/request identity is fixed.
- Cancellation of await, native transport or observer does not certify real stop; original container/work slot/ownedclient retained through retryableclose.
- Malformed completed/custom/lazy DTOs or unbounded stream/multiplex frames must fail before copying/adoption; diagnostic failure cannot mask live work.
- Per-Agent sandbox selection cannot grant tools or conflict with business/Workspace/Skills roles, old fixed release/new markers refused before businessI/O.

### Task 1: Public bounded Sandbox contracts

**Files:** create src/ralf_agent/sandbox.py; modify __init__.py; create tests/test_sandbox.py.
**Interfaces:** SandboxProvider Protocol, SandboxRequest(argv,timeout=30), SandboxObservation(invocation_id,native_id,state,exit_code=None), SandboxResult(invocation_id,native_id,exit_code,stdout,stderr,truncated,timed_out,observation), typed Sandbox errors and pure source result validation.

- [x] Readspec/brief; write public API/normal frozen roundtrip/source equality/scopedidentity and rawtypes/copy/lazy/UTF8/finite/allbounds tests BEFORE code.
- [x] Run .venv/bin/python -m pytest tests/test_sandbox.py -q -W error; Expected missingAPI trueRED. Implement narrow raw ordinary validation, no providerI/O/importDocker onconstruction.
- [x] Run focused contracts with original Tool DTO/source tests; ExpectedallGREEN/no extra imports. RecordTDD/rulings and localcommit.

### Task 2: Actual restricted Docker provider

**Files:** create src/ralf_agent/docker_sandbox.py, docker_sandbox_transport.py; tests/test_docker_sandbox.py, test_docker_sandbox_service.py.
**Interfaces:** DockerSandbox async open/run/observe/stop/aclose, identity/fixedengineimage/provenance and original mechanical task/real-stop ownership.

- [x] Write pure validation/HTTPtransport invalidenvelope/nativeownership/copy/limits/ambiguousACK/closedcapacity/lazyclient tests BEFOREcode. Expected missingprovider trueRED.
- [x] Inspect officialAPI1.44 + actual1.52/Linux fields; implement narrow boundedUnixtransport/exactnativepath/strictnonTTYmultiplex, create/admit/start/wait/inspect/ownedkill/remove. NativeState.created never success.
- [x] ExplicitprepareONEtinytestimage only; freeze actual image SHA256 and execute own labelled containers. Product run neverpull.
- [x] Run actual readonly/nonroot/nohostmount/noegress/resource/timeout/output/actualstop+cleanup/Scope/identity/refusedimageVolumes cases; zeroSKIP. Inject acknowledgedlost create/start responses with actual query, no duplicatecontainers.
- [x] Prove observer cancel/zero-close retains actualcontainer/task and retriableclose drains realexit; recordprovider actualevidence/localcommit. Fakeport tests never called isolationproof.

### Task 3: Original native ToolSource and declarations

**Files:** create src/ralf_agent/sandbox_tools.py, sandbox_factories.py; modify runtime_builder.py; tests/test_sandbox_tools.py, test_sandbox_configuration.py; docs/sandbox.md.
**Interfaces:** SandboxToolSource original native descriptor sandbox_run argv/timeout; tools/sandbox-docker ownedasync factory.

- [x] Write source arbitrarymalformed/lazyport fixedidentity/replacedmethod/preflightnoallocation/originalPolicy/readonlyprofile/ownedborrowedclose tests BEFOREcode; ExpectedmissingAPI trueRED.
- [x] Implement original register_tool_source composition with trusted Scope/invocation identity, original actual taskownership, completedSandboxResult boundary, defaultapprovaltrue/cost1/read_only ONLY restrictedprofile.
- [x] Factorypurepreflight/explicitdaemon+imageadmission, originalresourceledger rollback; no model resourcefields/hiddenpull. Customport default replacement example explicit and honest.
- [x] Run packageguide actualnoSDK/originalCLI/workspace/skills/toolsource regressions, localcommit.

### Task 4: Per-Agent Sandbox binding and original recovery

**Files:** create src/ralf_agent/binding_sandbox.py; modify binding_catalog/runtime/manifests, temporal_bindings/activities/state and originalbindingfactories; tests/test_sandbox_bindings.py, test_sandbox_binding_execution.py, test_sandbox_binding_temporal_service.py.
**Interfaces:** SandboxBindingResource borrows original native Source/ToolRegistry; select_sandbox_tools puregrants intersection, protocol1 explicitadmission.

- [x] BEFOREwiring proveold82 pure admission rejects chosen newrole/protocol marker; write ref/disabled/grantintersection/drift/unsupportedselectors/validnativehandler tests and sixLocal/sixTemporal fixtures. Expectedmissingrole trueRED.
- [x] Implement pure selection + fixed native source registration, original effective records/root/member paths/borrowed lifecycle. Preserve defaults and original terminal/approval/effect evidence.
- [x] ActualsixLocal/sixTemporal+approval/restart/replay/cancel/stop/quiescence, original acceptedresult recovery withoutrerunningcommand; cold native handler/orphan observations controlledactualcases.
- [x] Complete focusedbinding/assembly/regression and true actual containerend/cleanup, zeroSKIP/localcommit. State precisely any unsupportedwarm/cold combination.

### Task 5: Fixed capability delivery and sole review

**Files:** version/CI/API/guides/remaining/status/progress/harness/CHANGELOG + architecture/reviews/2026-10-12-sandbox-native-tools.md.
**Interfaces:** restrictedSandbox default and thirteen-role subset evidence, honestR13/H4/R01–R26boundary.

- [x] Solefreshstrongestreadonlywholebatchreview; ALLfindings/ALLDeclinedregradebeforeONEunifiedImportanttrueRED→GREENpass; Minorledger/no secondreview.
- [x] Fixedsource full suite with permissions for localHTTP/Redis fixture; NEVERconcurrentbuild againstsharedbuild/bdist. Installed core/SDK/actualDocker+Temporal zeroSKIP, frozenmodule/wheel/sdist/fixture hashes, old82two-waydefaults/22templates andactualnewprofilepreIOrefusal.
- [x] Guides/config/API/CIargv/docs/payload accurate; onlyownedtestcontainer/service cleanup, actualstop/wait. Localclosurecommit and archiveONLYownSDD with exhaustiverulings/costs/minors. No push or globalcompletionclaim.
