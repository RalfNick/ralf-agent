# dev21 managed memory and context review

2026-10-08, dirty local implementation following dev20. No remote submission.

Delivered: opt-in automatic successful-Run memory consolidation with deterministic
rule and managed model selectors; host-grounded append-only observations;
immutable per-command source/release bindings; sync/async CAS/recall/validation
adapters; explicit managed model summaries and frozen pure consumers; additive
Temporal pure ContextBuilder registrations and separately adopted History
snapshots; opt-in non-streaming JSON-object Provider configuration; eighteenth
offline installed starter.

One fresh independent reviewer reproduced four P2 issues. Initially expired or
newly expired writes received success receipts; lazy context iterables were adopted;
source-less dynamic methods could share a release digest; explicit streaming
bypassed JSON mode. One fix pass added expiry/currentness validation, completed
container validation without iteration, executable/wrapper fingerprints, and an
HTTP-preflight streaming refusal. Eight regression cases cover these failures and the same extractor/recall port boundaries,
including expiration during awaited writes and differing wrapped implementations.
No Critical or deferred Minor finding was reported.

Real-service contracts cover Redis/PostgreSQL consolidation and native Temporal
custom context with two separate Workers, approval pause, process restart,
summary Workflow and History replay. Defaults retain native v1 identity; custom
release implementations and captured configuration are pinned. Python executable
fingerprints omit filenames/line numbers, include wrappers and JSON captures,
and reject unverifiable code/captures. Python/runtime/helper dependencies still
belong in the application's explicit deployment identity; no code archive is shipped.

The [live trial](../../docs/live-model-quality.md) retains original failures and
separate follow-up configurations. It does not imply framework parity. Business
success, model proposal adoption and memory admission are separate. Automatic
semantic revision/retraction, globally atomic multi-fact admission, automatic
in-Run model compression, Temporal shared memory recall, exact token/billing
limits, retention/IAM and full M1 acceptance remain outside this delivery.

Final regression, installed-package and actual dev20 compatibility counts are
recorded in [implementation progress](../../docs/implementation-progress.md)
after completing the final gates.
