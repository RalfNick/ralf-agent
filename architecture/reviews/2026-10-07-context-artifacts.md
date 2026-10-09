# dev20 context/artifact review and evidence

Scope: accepted D3a design. Pure replaceable measurement/group selection/excerpt
summary, optional actual-request validation after Harness, explicit scoped JSON
artifacts with memory/SQLite defaults, additive factory and seventeenth installed
starter. Default ContextAssembler, original sixteen starter dictionaries and
native local-4/Temporal release are preserved.

New public defaults are experimental. Token estimates are not billing or exact
model windows; excerpts are untrusted sampled historical evidence. Artifacts
are application-selected storage contracts, not automatic offloading, enterprise
IAM or a distributed artifact backend. Fact extraction and custom Temporal
context remain pending. No real model credentials or paid requests were used.

One fresh independent read-only review found two P2 defects, with no P1 or minor:

1. The optional request validator received the actual mutable message list
   after the character cap check. A retaining/mutating validator could dispatch
   more content than its reported measurement. Engine now supplies detached
   input and rechecks the final character cap.
2. The memory artifact store retained the same frozen reference object returned
   to callers. Mutating the DTO through object.__setattr__ could corrupt metadata
   and capacity accounting. Store now retains a separate validated reference and
   verifies duplicate content/metadata.

Both defects failed permanent tests before changes; one fix pass produced three
green regressions, including the already-safe SQLite case. The 204 related tests
passed. There are no remaining important findings; no second reviewer was used.

Evidence so far: actual dev19 wheel native/graph/team/flat/DAG/nested receipt and
approval recovery, original sixteen template equality, native Temporal Run and
registry History replay/continuation; 96 SDK modules identical across source,
wheel, sdist and installed package; 237 duplicate-free exports; two base
dependencies/six extras unchanged; installed outside-checkout 431 contracts plus
three review regressions pass; optional SDKs blocked 369 passed/seven expected
service/optional skips. The initial actual-service suite passed 1649 tests; the next suite (with three
review regressions) passed 1651 and exposed one existing cancellation-test race.
Original History proved parent cancel acceptance at 14:55:39.851Z, child reconcile
at 14:55:39.869Z and a second model at 14:55:39.909Z, before any child cancel
adoption. Runtime authority modules match the dev19 wheel. The test now waits
for child cancellation before its recovery query, retaining exact spent=2,
parent unknown=8, non-quiescent and single-write assertions. This is a test
precondition correction, not a change to execution semantics. One actual rerun and six consecutive repeats passed, as did the installed-wheel
case. Final actual-service suite: **1652 passed in 395.38s** under -W error.

Real artifact processes prove before-COMMIT loss leaves no entry and after-COMMIT
loss retains the complete immutable entry; original put returns the same
reference. Concurrent writers share one capacity authority. UTF-8, TTL, alias,
path replacement, uncommitted transaction, corrupted payload, namespace and
backend refusal tests pass. The long-history guide example runs with actual
summary inclusion; the installed context starter completes reference/sample
tools and cross-process submit-only/factory recovery.

Rulings: use the authorized shared dirty feature workspace and actual prior
wheel/probes without redundant skill approvals/commits or deleting retained
evidence. Choose a SQLite content-addressed default to provide atomic local
capacity with no new dependency; file/S3/remote stores remain future work. D3a
delivers deterministic context and explicit artifacts; automatic memory/model
summary/paid quality and enterprise/Temporal custom context remain separate
gates. These scope choices do not claim full M1 or AgentScope parity.

Source plan/spec: [plan](../../docs/superpowers/plans/2026-10-07-context-artifacts.md),
[spec](../../docs/superpowers/specs/2026-10-07-context-artifacts.md).


Final checks: Ruff, formatting, Git whitespace, relative guide/review links,
standard-library CI YAML parse and pip requirements pass. Actual PostgreSQL,
Qdrant and persisted Temporal Service supplied full-suite gates. Source/wheel
upgrade and native History tests use dev19 artifacts rather than old HEAD.
Editable SDK/metadata are aligned at 0.1.0.dev20. Builds are local preview
artifacts; no Git commit/push, tag, PyPI upload or GitHub Release was requested.
Task-owned service shutdown is confirmed after artifact verification.
