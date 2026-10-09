# dev34 / H2c2 — Temporal composite Agent facade

The registered Graph/Team/Dynamic/nested subset now uses the shared Agent API.
Native/parent History remains the only remote execution authority; the client
does not add a scheduler, state machine or synthetic parent control receipt.

## Delivered behavior

- Capabilities report registered definitions; original parent refs/receipts work
  with async attachment after queue/provider defaults move.
- pending reads actual native child controls through a single pinned dispatch
  view, verifying parent-derived command/Run IDs and request/manifest release.
  Parent aggregates are ignored. Attach the returned RunRef to control its owner.
- Traversal bounds are 4096 identities/16 levels. Duplicate/cyclic/missing/malformed
  evidence fails; pruning checks retained settlement/undispatched evidence before
  omitting a child. Caller cancellation ends observation only.
- Parent outcome_unknown is observable as human wait; root cancel/resume retain
  server propagation. A manual effect receipt does not prove a remote handler
  stopped, so ancestor unknown credit holds can remain.
- Terminal native snapshots omit unusable approvals, retaining action/receipt
  ledgers. This removes a false obstacle to cancelled-child settlement.
- Module-bound DAGNode/Literal imports resolve actual sandbox class duplication
  in sequential planning. A compatible ralf-parent-control-evidence-v2 marker
  separates private bookkeeping from resource evidence for new parent histories;
  snapshot/budget/stop/uncertainty remain strict. Marker-less histories keep v1.

## Review and fixes

One fresh gpt-6-astra/high reviewer examined the captured actual dev33 SDK delta,
authority/Worker boundaries and test evidence, and independently ran87 offline
tests. One Important finding, no Critical/Minor: typed settled/started flags could
hide an unknown child while retained evidence contradicted pruning. Seven
reproductions failed before the one fix pass; one legitimate undispatched,
cancelled/settled case passed. All71 focused tests passed after the fix. No re-review.

Additional actual-service gates found and fixed two existing Worker issues:
sequential planning initially failed from duplicate sandbox classes (11passed,
1failed); installed nested cancellation later reproduced same-revision control
bookkeeping conflict (11passed,1failed). A pure regression failed before the
v2 projection fix, with54 focused tests passing afterward. New/old actual History
replay verifies the compatible marker and preserved legacy rules.

## Verification

- Final full source suite: **2352 passed,56 skipped** with warnings-as-errors.
  Skips retain explicit unconfigured-service/optional-combination requirements;
  actual Temporal probes were run separately as recorded below.
- Final installed wheel contracts: **231 passed** outside the checkout.
- Actual persisted Service/Worker probes: **12 source +12 installed passed**;
  native, graph/parallel/team/DAG/linear-plan/nesting approval and reconnect,
  root cancellation, and every accepted parent/native History replay.
- Actual dev33 wheel accepted4 Runs/native+graph+nested+cancelled and7 parent/child
  Histories. Installed dev34 preserves original manifests/releases/receipts,
  replays saved old and current histories, and confirms three effects once each.
- Actual Local dev33↔dev34 wheel recovery:4 approvals each direction across
  native/sequence and schema1/schema2 Sessions; original receipts/manifests,
  completed Session eligibility and one effect per operation retained.
- Source/wheel/sdist/installed147 SDK modules byte-equal;294 optional-free exports,
  20 identical starter file maps; dependencies/extras/scripts unchanged. Private
  evidence, SQLite data and credential-shaped content excluded from packages.
- The first restricted full run failed solely on local socket permissions
  (2failed/24errors,2319passed54skipped); an authorized local-service run passed
  2351/56 before the additional evidence fix. After the additional evidence fix, the final full gate is2352passed56skipped.
  Ruff, format (499 files) and Git whitespace checks pass;26 changed public Markdown
  files have valid local relative link targets. The owned test Service was stopped.
- No paid model call, commit/push or publication. Evidence remains locally retained.

## Rulings and costs (complete list)

1. Continue inline on the user's existing feature checkout; preserve dirty work
   and private evidence without automatic integration. Cost: manual integration of
   uncommitted snapshots remains necessary.
2. Include native terminal approval projection repair because actual discovery
   exposed unusable approvals blocking settlement. Cost: consumers see fewer
   terminal pending items; actions/receipts remain original and replay is verified.
3. Move planning-value imports to the parent-state module boundary after actual
   sandbox failure. Cost: SDK/sandbox combinations still need service conformance;
   this installed/source combination and old/new replay were tested.
4. Version resource-evidence projection using a Temporal patch marker after the
   nested cancellation race. Cost: old histories retain v1 and its race; they are
   not automatically repaired. Old Workers on new v2 histories are not certified.
5. Reviewer declined model planning quality; accept execution-contract scope with
   offline providers. Cost: real task/plan quality needs separate acceptance.
6. Reviewer declined unchanged dev31–33 beyond delta interactions; retain source,
   installed, actual-wheel and full regression gates. Cost: inherited design gaps
   remain on the checklist; this is not a fresh whole-project architecture audit.

No deferred minors. Exact command/output evidence is retained in this plan's own
ignored workspace; no sibling private workspace was accessed. API and support
boundaries: [guide](../../docs/temporal-agent-api.md),
[remaining work](../../docs/remaining-work.md).

Complete H1/H2 remain open: Temporal bindings/shared Sessions, remote/composite
Session routes, queue/input/deadline/handoff and direct Tool/Transform graph nodes.
Raw DAG patch remains outside the facade subset. H3 default managed context/memory
chains and independent real-model quality are subsequent stages; no AgentScope
parity or production readiness is inferred from these tests.
