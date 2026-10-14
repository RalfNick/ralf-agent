# Temporal bounded Agent graph Coding

This increment advances phase two R01/R13/R19: the existing parent scheduler can launch several original Agent children, but opt-in Coding currently refuses concurrency and owned shutdown stops scanning after one failed leaf. The deliverable is actual bounded concurrent Coding with one History authority and complete independent-stop handling, not only a permissive topology parser.

## Publication and compatibility

- Existing exact boolean `coding_execution=True, coding_composition=True` selects binding protocol **13**, composition **version 2**, topology **bounded-agent-graph**. No additional configuration switch or runtime dependency.
- New topology is static Graph Agent-only, depth one, `max_concurrency` bounded by the original registered TemporalExecutionPolicy. Serial graphs remain included. Root Agent/sequence retain their original native delegate behavior.
- Default unselected declarations/releases and original protocol 11 native implementation groups remain byte-identical. Preserve every original dev106 native/glue/PG callable body and native JSON asset.
- Protocol 12 describes dev107 serial-only behavior. Do not reinterpret a saved protocol 12 release as version 2 or accept old fingerprints as current code. Saved selected releases require their exact matching Worker/wheel; retain the accepted dev107 wheel for original12 recovery and reject mismatched releases before registration/business I/O. Current source cannot claim old12 replay after modifying its pinned pure functions. New13 is refused by actual installed107 Worker. Source/install legacy unselected History replay remains a separate gate.
- All actual new helper callables are pinned independently in pure or Worker inventories. Histories must not import or invoke Worker IO while validating pure inventories.

## Original children and scheduling

- Reuse existing slots, compiled static graph, child Run/command identity, original parent/child request, namespace UUID, SDK original epoch, per-Agent grants/bindings, whole child cap and dependency result/schema rules.
- Do not add a Coordinator, scheduling store, message authority or native attempt. Starting child Workflows may send Start RPCs sequentially; actual child business must overlap to establish concurrency.
- The original native Runner owns one operation. Within a parent, compute occupancy from actual projected Agent grants: independent Runners may overlap; the same Runner is backpressured by original History until its prior child is both settled and physically stopped. A financially settled child with missing physical proof still occupies that Runner; aliases deduplicate and excluded tools confer no occupancy. This is per-root scheduling, not a host-wide Runner pool.
- Stop intent is immutable. A failure or explicit cancel prevents all new child selection/dispatch and waits for every originally dispatched child physical proof. Unknown child effects/caps remain held independently from physical stop.
- Never infer physical stop from financially settled status or a missing Start reply. Preserve original receivers and actual owners until proof is adopted.

## Owned closure and exact PG evidence

- Drain actual SDK submission calls before closing original root admissions; keep the existing fresh-close nonce and retained shielded close task.
- For independently dispatched children, attempt original cancel/fence/ancestor adoption for **every** child even if another child fails. Collect unresolved obligations and return CloseIncomplete; no resource owner is released on incomplete proof. Wrong identity does not authorize acting on an uncertain leaf.
- Every PG resource in the selected scope must match the original History `action_id` and full native request, including Runner, dispatch effect and epoch. Fenced rows are still checked and retained for failed ancestor adoption. A same-Run/epoch foreign Action/request cannot be ignored.
- After stopping/adoption, rescan original resources before returning success. Any active or unmatched original intent prevents closing. This is evidence checking, not an independent results/budget authority.

## Deliberately pending prerequisites

Team/Dynamic selection callbacks presently lack a durable original invocation/end proof and permit an await-time cancellation dispatch race. Their support requires a distinct managed selection stage with original request/revision/epoch authorization, actual owner drainage and late-adoption rejection. Keep Team/Dynamic/nested/directTool/patch rejected in this version; list the selection-stage prerequisite rather than declaring all orchestration complete. Native authentication/real Coding quality, cross-host and uncertain Docker create/CID recovery stay open.

## Parallel file ownership

1. Publication owner: composition_protocol; Runtime ctor/publication; temporal.py capabilities/guard; binding helpers, joint protocol allowlists, control/session/lifecycle protocol dispatch ONLY via agreed isolated function ownership. No History or control helper implementations.
2. History owner: composition_state; temporal_state validation/Registry; parent state/workflow and leaf workflow, with dedicated concurrency/failure/unknown-cap tests. No publication or SDK close edits.
3. Control owner: composition_control and dedicated unit tests, exact PG-to-History helper, all-child close aggregation and final scan. Original native runner methods untouched. Notify publication owner of new pin names.
4. Root: contract/plan, actual service fixtures, independent review, source/install/compatibility/replay/artifact checks, capability docs and local commit. No push. No concurrent builds or services from authors.

## Acceptance

- TDD strict version/topology/concurrency admission, policy bounds, grants and all remaining refused kinds.
- Two independent original children with distinct Runners physically overlapping, shared original Runner safely serialized, and dependent join only after original successful settlement.
- Cancellation/failure with multiple original active children; one unknown child cap alongside a normally settled child; no next node until dependency evidence.
- First child stop failure does not prevent second child original stopping; retry includes already fenced rows; original PG row/request mismatch prevents cleanup success.
- Actual Temporal/PostgreSQL original Histories with namespace replay, one meaningful Worker replacement/fault window, installed final wheel matrix and original107 refusal.
- Default/full11 byte equality; original107 wheel recovers original12 rather than changing saved release; legacy saved History replay, source/install/sdist provenance. Risk-organized full regression on a frozen source, preserve failures and configured skips.
- Stop/wait own services, update evidence and remaining prerequisites, local commit only. The full R01–R26 goal remains active.
