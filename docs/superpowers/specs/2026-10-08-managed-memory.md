# Managed memory and model context, dev21

Implement the user's four requested capabilities together, preserving the dev20
local and native Temporal contracts. No commit, push, or external publication.

Automatic extraction is an opt-in application pipeline: run the business Agent,
capture its successful scoped result as immutable evidence, run a rule extractor
or a tool-free managed model Agent, then admit append-only sourced facts through
the existing memory CAS port. Business success and memory completion remain
separate receipts. Extraction cannot overwrite curated facts, change Scope,
promote tool text into authorization, or invent values: admitted values must equal
an allowlisted JSON source path. Model extraction selects grounded fields; it
does not establish truth. Conflicts, expiry, stale sources, changing bindings and
partial admission must fail explicitly and permit safe replay.

Model summarization is explicit async preparation through an ordinary managed
Agent Run with schema, credits and durable response evidence. Coverage digests
are computed by the host, never accepted from the model. The resulting frozen
summary implements the pure synchronous ContextSummarizer port. Changed coverage
is rejected. Excerpt summaries remain the offline default; neither ContextBuilder
nor a memory port performs hidden model I/O.

Temporal accepts registered custom synchronous ContextBuilders, including the
budgeted pipeline, through an additive release. A context Activity produces a
bounded snapshot before the model Activity; History records adoption. Pin object,
method, identity and optional request validator. Verify before and after execution
and after awaits. Default native release bytes and old History behavior remain
compatible. Native Temporal authority must not be replaced with LocalEngine.

Run a bounded DeepSeek trial: business tasks, planning proposals, grounded memory
and summary preservation. Report task-level failures as well as success, usage,
latency and call caps. Credential stays in a private 0600 file, outside packages;
errors and reports contain no raw HTTP bodies or headers. A failed live provider
is evidence, never an offline substitute labelled as model quality.

Not delivered: autonomous belief revision, semantic fact truth guarantees,
globally atomic multi-fact writes, hard currency limits, exact tokenizer limits,
enterprise retention/IAM, or parity/superiority claims from a small trial.
