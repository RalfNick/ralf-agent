# H3b1 managed context preparation

Opt-in Local native/sequence `ManagedContextPipeline` implements the existing pure
ContextBuilder and context binding. The original Engine, not the builder, owns
summary I/O, credits, source/intent/response checkpoints and recovery. Existing
explicit ManagedModelSummarizer and pure BudgetedContextAssembler remain unchanged.
Default Engine/Profile behavior and schema1–7 manifests are byte-compatible.

Freeze complete omitted assistant/tool groups from the current Run history, original
head, protected latest group, selected groups and authorized references. Summary
never replaces the original history, Session or Action evidence. First slice does
not summarize Session/RAG reference contents, latest evidence, or original task.
Reserve room for bounded summary before requesting it; if no room/source too large,
retain the existing bounded fallback. Pure excerpt is the default optional mode;
explicit model mode makes one tool-free call through a pinned host provider.

Summary coverage is host-assigned exact ordered group digests; model output is only
bounded nonblank JSON text. Insert it as untrusted user evidence, never system
authority. Final projection and actual Harness request are independently measured.
Counter/budgeter/pure excerpt components remain replaceable. Model summary costs
one execution credit from the same Run, in addition to business model/tool credits.
Optional failure or unknown call uses frozen fallback without replaying tools;
unknown credits remain held and calls are never automatically repeated.

Persist source and independent marker before selection/I/O, immutable request intent
and independent reservation before dispatch, received response before acceptance,
then response-derived summary and frozen business snapshot. Recovery reuses the
snapshot, or accepts a saved response without another provider call. Abandoned
dispatched intent without response becomes unknown; prepared undispatched intent may
be safely continued. Terminal recovery does no I/O and cannot upgrade Run state.
Missing markers, illegal state/receipt/budget or changed binding fails closed.
Cancellation/timeout preserves evidence and real handler ownership.

Pipeline selection supports existing per-Agent context inherit/ref bindings, plus
JSON/TOML managed-summary factory. Scope and provider identities are fixed. New
optional Store context_stage_version=1 activation atomically enables semantic8
and uses existing independent managed_stage_reservation evidence. Old dev40 refuses8.
Advanced Graph/Team/Dynamic/nested and Temporal preparation are explicitly rejected
at admission; automatic memory stages can coexist on native/sequence Runs.

Deliver SDK context_stages read receipts and auxiliary pending observations, tests
for excerpt/model/history protection/defaults, restart/response checkpoint/lost call/
budgets/drift/closure, installed wheel and actual old/new schema compatibility. Use
offline providers, no credential reads or paid calls; no push. Real model summary
quality, large result artifact offloading, Session reference summary, generalized
Prepare/Verify stages and full H3 remain undelivered.
