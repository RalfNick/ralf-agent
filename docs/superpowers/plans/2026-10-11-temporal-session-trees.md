# Temporal Session Trees Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax. No implementation delegation; one final fresh-context read-only reviewer per requesting-code-review.

**Goal:** Extend the original external Session contract to Graph/Team/Dynamic/nested roots and stable private member Sessions, with original Parent final-save gates and actual child/handler quiescence.

**Architecture:** A replaceable pure Session topology proposes stable addresses; mandatory Scope, resource and membership checks remain in original Histories. Native children own private saves, the original top-level Parent owns its root Conversation save, and the Session Coordinator only owns Turns/occupancy/projection. Reuse dev66 exact receipts, actual-handler ownership, admission and budgets; do not add a new executor or synthetic business Run.

**Tech Stack:** Python3.11+, existing Local/Temporal contracts, native Session SPI, original Temporal History.

**Spec:** architecture/specs/temporal-session-data-contract.md; architecture/specs/agent-facade-session-contract.md; architecture/specs/agent-capability-binding-contract.md.

## Global Constraints

- Full R01–R26 and complete H1/H2/H3/M1 remain the goal; this batch does not replace the full target.
- Original business Run/Parent alone accepts writes and success; actual Session Coordinator alone accepts Turns/busy.
- Default dev66 Manifest/request/data behavior remains; new topology is explicit and versioned. Old Workers refuse new releases before model/tool/data I/O.
- Root Conversation and private member data are separate, sourced once, bounded and Scope/resource/version checked.
- Unknown effect/real handler and delivered end notification remain owned through cancellation; no model/tool repeat during save recovery.
- Rebind never migrates root data. Private continuation is explicit: original root SessionKey + root binding revision + structured declaration/member path + actual Agent declaration identity.
- All registered data/client resources are borrowed. Owned actual handlers must stop/deliver evidence before closing them.
- Every step is RED→GREEN; local commits after final checks, no push; no live model secret/logging.

## File Structure

- `temporal_session_topology.py`: pure replaceable address proposal and mandatory validation; no I/O/state authority.
- `temporal_session_identity.py`, `temporal_session_state.py`, `temporal_bindings.py`: original root identity, capability acceptance, typed original ancestry/membership and subtree projection.
- `temporal_session_data_state.py`, `temporal_session_data.py`, `temporal_managed_context.py`: root/private read evidence, original protected snapshot and source classification.
- `temporal_parent_session.py`: pure Parent root read/save gates and original aggregate-source evidence; reuse save-stage rules where compatible, never fake a model response.
- `temporal_parent_state.py`, `temporal_parent_workflow.py`, `temporal_activities.py`: Parent reservations, accepted aggregate result, data Activities/end Updates and pure views.
- Existing native save/execution modules remain original write/admission/actual-handler implementations.
- Focused topology, parent/member, actual Worker/remote/installed tests plus guides/capability/acceptance records.

## Review Focus

1. Separator-containing node names, nested paths and dynamic node IDs must not alias another member or the root.
2. Rebind and dynamic replanning must not silently inherit another definition's private history or migrate the original root resource.
3. An apparently succeeded child or Parent cannot release a Turn before actual descendants/root save/unknown reservations settle.
4. Root source None (History-only) with external private members, mixed member sources and disabled private members retain independent source categories and checks.
5. Forged descendant Scope/namespace/parent/path/source evidence must refuse before data/model I/O; old default and native save releases stay restorable.

### Task 1: pure topology and member-address contract

**Produces:** `NativeSessionTopology` (legacy private/run address and root behavior unchanged) and `CompositeSessionTopology` (versioned root/private address proposals), plus original metadata-only identity/method binding contract. Integration remains disabled until Tasks2/3.
**Interfaces:** root SessionRef, structured tuple/list of nonempty bounded Unicode declaration path atoms, 64-hex Agent definition digest, selected member namespace; output bounded versioned logical message-storage address. Root address is exactly original root key.storage_key. Member logical ID hashes original root key/binding revision/path/Agent declaration; actual selected namespace uses the existing session_storage_key encoder. No mutable global counters, Run IDs or random IDs in persistent member identity.

- [x] Write tests for same member across two Turns, distinct separator/nested paths/definitions/root revisions/Scope, root vs private separation, selected namespace, invalid/lazy/bool inputs and native legacy addresses.
- [x] Run `pytest tests/test_temporal_session_topology.py`; expect missing topology module RED.
- [x] Implement pure defaults and mandatory input validation. A custom proposal may not rewrite Scope/root or escape bounded addressing; method/configuration identity fixed at host registration.
- [x] Run topology + dev66 persistent/native/Session read contracts; expect GREEN and advanced existing preflight still refuses.

Task1 evidence:113 passed. Tasks2/3 are implemented and verified by related251,
installed206, core-only two Turns, and actual40 Service/Redis/PostgreSQL cases.
The final review identified root-reader timeout ownership: RED2 state +1 actual
thread case, fixed within the single final fix pass. Final frozen verification
remains Task4; the foundation3745/226 run predates the integrated product.

### Task 2: original tree binding, ancestry and source-once snapshots

**Consumes:** Task1 topology, existing catalog resources, original Session coordinator binding/turn.
**Produces:** explicit topology registration/new tree protocol; actual namespace/root data identity preserved, root read snapshot and original root/member ancestry projection. Root source can remain History-only when only private sources are selected. With external root, use host's allowed root source/namespace; do not infer a shared root from arbitrary member stores. Members may select independent sources/namespace or disable private data; mandatory root persistence remains enforced.

- [x] RED tests original root identity/no-migration, source/Scope/namespace mismatches, structured paths through graph/team/DAG/nesting/planner, alias and generation changes, explicit disabled members and mixed sources.
- [x] Publish an explicit replaceable topology parameter/protocol; default legacy unchanged. New protocol requires admitted supported original capability, no fabricated opaque Local binding objects in History.
- [x] Accept root read before child dispatch; project protected original root snapshot and separate private member evidence once, including managed compression/offload. Original snapshots never reread on replay.
- [x] Verify actual SDK parent relationship/namespace and original accepted membership before I/O. Preserve root-only vs observer-only responsibility and dynamic-node approved definition identity.
- [x] Run pure Session/binding/read/context/parent suites, source role replacement and installed protocol refusal tests; expect GREEN.

### Task 3: original Parent aggregate save and private child completion

**Consumes:** original Task2 accepted topology/root/private snapshots and actual child evidence.
**Produces:** actual original Parent completion gate, root write reservation, aggregate-source write intent/received/adopt, independent actual-handler end proof and pure observation. Original children save their private records using dev66 stages; nested Parents never duplicate top-root save.

- [x] RED graph/team/plan/DAG/nested tests: every intended private record and root aggregate exactly once, Source schema independent of model-only evidence, actual child quiescence and root no-success-before-adopt.
- [x] Reserve mandatory root-write credit before distributing child caps; include original own reservations in Parent budget/quiescent diagnostics. No synthetic Agent/model evidence or extra business Run.
- [x] Reuse save execution/admission/receipt rules through a shared pure host boundary; preserve old native policy identity and requests. Parent receives actual stop Updates and records original intent/receipt/adoption separately.
- [x] RED/Green cancellation, initial inspect failures, missing/corrupt/oversized receipts, old-attempt notifications, timeout before admission and aggregate-before-root-save windows. Never reschedule models/tools; only original allowed saves.
- [x] Run graph/team/dynamic/nested/Session/budget/managed data/old-native suites; expect GREEN with original authorities unchanged.

### Task 4: final evidence, documentation and local commit

- [x] Actual separate Worker kill/restart at accepted root read, private member saves, aggregate prepared/root committed/lost ACK, received-before-adopt; original Scope/path/ID, actual model/tool/write counts and History replay.
- [x] Real SQLite same-host and Redis/PostgreSQL rooted/private source replacements; actual cancellation/live handler/borrowed close; no fixture or skip counted as service proof.
- [x] One final fresh-context readonly review. Re-grade findings and fix important ones once with RED→GREEN, no re-review.
- [x] Freeze product; full/source/installed/core-only/build/module/METADATA/guides plus actual dev66↔new default/native History compatibility and old-Worker new protocol refusal.
- [x] Synchronize capability table/default usability/remaining gates and acceptance records using actual results; stop/wait own services, local commit, no push.

Incomplete work stays in this plan ledger; do not replace the target with address helpers or an easier graph-only subset.

Final gates: source3801/267 in508.59s; frozeninstalled198/9.80s +actual41/455.60s;
226source/wheel/sdist/core modules+METADATA andpackageddocs equal; core-only and
actual66↔67 native/default/oldprotocol refusal passed. OwnPG/Temporal normally exited.
Local commit follows these verified gates; no push. EntireR01–R26 remains active.
