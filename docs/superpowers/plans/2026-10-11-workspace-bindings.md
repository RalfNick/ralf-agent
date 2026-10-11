# Per-Agent Workspace Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL executing-plans INLINE; exactly one fresh whole-batch read-only reviewer, no implementation agents. Existing user continuous/local-commit-only/no-push authorization overrides repeated design and finish menus.

**Goal:** Make original readonly Workspace tools selectable for each actual Agent in Local and Temporal.
**Architecture:** Borrowed registered-tool resource and shared pure grant intersection. Original Engine/History/Source handles all execution, evidence and ownership.
**Tech Stack:** Existing Python/ToolRegistry/BindingCatalog/Profile/Temporal; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-11-workspace-bindings-design.md.

## Global Constraints

- Base is 93c32b8/dev75; preserve inherited default manifest/22 starters. version76 only after required actual authorities pass.
- WorkspaceBindingResource(registry,*,names):1..256 unique plain names <=128characters/512UTF8bytes, controls/DEL refuse, one identical native Workspace Source identity, all readonly original registrations.
- Resource pins full manifests, borrows registry/source/port, no allocation/discovery/close/FS I/O. No selectors/subroots/writes/ContextI/O/Sandbox claim.
- Ref requires already-granted matching original tool; stable intersection preserving business grants, no expansion/remapping. disabled excludes Workspace tools only. Shared pure select_workspace_tools called only explicit mode.
- Local explicit workspace uses kernel11; Temporal explicit workspace requires protocol1. Original authorities unchanged.
- Default workspace/registered-tools factory config exactly {names:[...]}, both builders use existing context.tools; no duplicate resources.

## Review Focus

1. Forged/mixed source registrations, same-name mismatched caps/root/Policy, malformed data and ordinary subclasses cannot change selected root or expand grants.
2. Resource/source/registry changes between accepted release and resumed execution cannot silently adopt another root, or read from excluded roots.
3. Nested member projection/tool_set intersection and disabled mode preserve business grants without widening parent/Agent permissions.
4. Default releases remain byte-identical and old Workers reject optin workspace roles before read; actual old wheel recovery is required.
5. Queued/running reads and partial configuration cleanup preserve original borrowed ownership and true-handler drain; no binding method performs hidden I/O.

### Task 1: Resource and Local selection

**Files:** create src/ralf_agent/binding_workspace.py, tests/test_workspace_bindings.py,test_workspace_binding_execution.py; modify binding_catalog.py,binding_runtime.py,__init__.py and original outdated workspace-refusal fixture.
**Interfaces:** consumes original ToolRegistry.manifests(names), Source fixed metadata, BindingSelection/AgentBindingDescriptor. Produces WorkspaceBindingResource(registry,*,names), detached identity and pure select_workspace_tools(names,manifests,resource_identity=None)->tuple[str,...].

- [x] Write missingAPI tests for two roots/prefixes, fullmanifest drift/removal, malformed names/mixed roots/nonreadonly, identity detachment/noFS/noownedclose. Run `.venv/bin/python -m pytest tests/test_workspace_bindings.py -q -W error`; Expected true missingAPI RED before implementation.
- [x] Implement resource and pure selection in one module; Catalog supports workspace resource, selectors remain refused. Run resource tests; Expected GREEN.
- [x] Write actual Local two-root Native/sequence/graph/team/dynamic/nested binding tests: selected source actual note result; excluded root proposal never invokes reader; business grants preserved; tool_set cannot expand; disabled blocks onlyworkspace. Approval restart original source/result and drift refusal. Run test_workspace_binding_execution.py; Expected workspace unsupported RED.
- [x] Add Local explicit record/filter/kernel11 without changing inherited values or StepComponents clients. Update old unsupported-workspace fixture to unavailable-host-resource behavior; preserve sandbox refusal. Run both new files plus test_binding_execution.py,test_composite_binding_execution.py,test_composite_binding_children.py; Expected allGREEN.
- [x] Formal task-done with same verified files; taskcommit folded into finallocalbatch per continuous authorization.

### Task 2: Configuration and Temporal

**Files:** workspace_factories.py,runtime_builder.py,temporal_bindings.py,temporal_state.py,temporal_activities.py; new tests/test_workspace_binding_configuration.py,test_workspace_binding_temporal.py,test_workspace_binding_temporal_service.py.
**Interfaces:** consumes Task1 resource/pure selection. Produces workspace/registered-tools factory and Temporal catalog workspace_binding_protocol1/effective_step grant intersection.

- [x] Write JSON/TOML SDK normal sync/async root-reuse declaration, invalid pure preflight, borrowed lifetime/partial cleanup and source identity tests. Run configuration file; Expected factory/mapping role RED.
- [x] Register sync resource factory and mapping. Run configuration plus original binding_assembly/composite_binding_configuration/temporal_assembly tests; Expected GREEN/no extra root opening.
- [x] Write Temporal pure History selection/protocol/Scope/mixedroot/unknownTool/disabled/member projection and original runtime drift tests. Run temporal binding file; Expected unsupported-role RED.
- [x] Implement original catalog registration + protocolvalidation + shared pure effective_step filter; no new client/state authority. Run pure tests and original Temporal binding/isolation suite; Expected GREEN.
- [x] Required actual temporal native/sequence/graph/team/dynamic/nested source selection and approval Worker restart/History saved-result/repeated control; excluded root neverread and drift refuses. Run actual source service file with fresh owned service address; Expected pass zero skips, then version76.
- [x] Formal task-done configuration/pureTemporal tests with exact existing paths; commit folded finalbatch.

### Task 3: Frozen delivery

**Files:** docs/workspace.md, capabilities/remaining/status/progress/harness/CHANGELOG/CI/version, architecture/reviews/2026-10-11-workspace-bindings.md.
**Interfaces:** consumes Tasks1–2 proof. Produces exact public usage, boundaries and frozen acceptance evidence.

- [x] Sync capability subset and build/install freshcore/SDK; actual installed tests/services and actual75↔76 Local/CLI/defaultTemporal/native recovery;22templates exact; older worker explicit-role refusal beforeI/O. Expected all required actual gates pass, no model/parity/Sandbox claims.
- [x] One fresh readonly whole-batch review; regrade and ledger every decline/ruling BEFORE one Important RED→GREEN pass; Minor deferred only. Expected fullreport, all Important covered/no secondreview.
- [ ] Freeze products/runfullsource/build/install/hashdocs/actualservice/compatibility; stop and wait original owned services, localcommit/formalTask3, archive/deleteonlyownSDD. Expected fullgoal remainsactive/no push.
