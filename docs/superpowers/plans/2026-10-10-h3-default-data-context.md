# H3 default data context implementation plan

Spec: ../specs/2026-10-10-h3-default-data-context.md
Base: ec9b5f5, feat/m1-local-runtime. Execute inline, no approval handoff.

1. Synchronize current dev42 capability boundaries, preserving historical evidence.
2. RED→GREEN: pure ManagedDataContext projections and source coverage; reuse old context journal through a new subclass, without changing old pure hook bodies.
3. RED→GREEN: original-Run artifact intent/receipt journal, semantic Schema 10 activation, actual target pinning, pre-dispatch validation and recovery boundaries.
4. RED→GREEN: versioned recommended Profiles and owned SQLite artifact factory; replaceable SDK/registry factories, sync/async assembly and installed usage.
5. Fresh read-only whole-change review; one Important/Critical fix pass with RED→GREEN. Full suite, static gates, wheel build/install and backwards compatibility. Local commit, no push.

Review Focus: journal marker deletion/forgery; lost put acknowledgment; async target mutation with unchanged identity; cancellation while sync handlers live; adopted model response versus live artifact availability; compact references versus original validation; latest paired tool group; old default manifests and schemas; owned/borrowed close and factory preflight.
