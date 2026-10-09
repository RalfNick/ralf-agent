# Shared model adoption and recent Session context — dev24

The user authorized fixing the three reproduced dev23 defects and continuing
architecture optimization. This increment makes the existing Local/Temporal
adoption rules share a pure boundary, preserves completed model evidence and
fixes recent-session selection in default and budgeted contexts. Per-Agent
capability bindings and the application facade remain the next dependency step.

## Decisions

1. Extend the pure decision layer: detached typed proposals, allowlisted tools,
   effective argument Schema, explicit call-ID uniqueness, final output and usage
   checks. No I/O, UUID generation, authorization grants or state writes here.
   Authorities generate fallback Action/call IDs and check effective uniqueness.
   Typed defaults resolve before validation/operation approval as already required.
2. Capture finite ModelResponse evidence before proposing/validating a decision.
   Known completion settles execution credits even when adoption is refused.
   Invalid/missing token usage remains unknown usage, not unknown execution.
   Raw response and proposal are separate. No automatic retry or loss of a
   received response after release drift, proposal failure or cancellation.
3. Temporal Activity evidence includes a version2 discriminator plus the original
   received response. Valid top-level output/tool_calls fields remain compatible.
   Version2 failed decisions carry received evidence; History records/settles it
   before rejection. Past version1 payloads replay their original transitions.
   This is evidence-version dispatch, not a second scheduler or History rewrite.
   Mixed-version worker deployment is not certified; old unknown attempts remain.
4. Share a pure reference selector between ContextAssembler and budgeted context.
   Fully fitting references preserve original shape/order. If a Session reference
   does not fit, select a contiguous suffix of whole recent conversation turns,
   keeping assistant tool calls and corresponding results together. Preserve
   chronological order, original Session data, current task/latest Run evidence,
   caller budgets and detached inputs. Refuse malformed/incomplete turn suffixes
   rather than pretending incomplete tool observations are complete.
   Record omitted Session messages/turns in the context manifest. Existing saved
   Action snapshots stay unchanged; this corrects optional recall selection for
   new requests. It does not implement storage pagination or model summaries.

## Acceptance

- Same replacement-Provider cases through Local and Temporal Activity/state:
  duplicate/invalid call IDs, invalid final Schema, invalid tool arguments,
  undeclared tool, empty/null output, known/missing/invalid usage and valid defaults.
  Invalid proposals produce zero new tool Actions, retain received response and
  settle credits; true call uncertainty stays held. Partial batches are not adopted.
- Rejection/late evidence cannot reopen cancelled/succeeded Runs or create new
  operations. Original model response and decision proposals are detached.
- The actual three-run 600-character Session case retains 73. Both assemblers
  preserve full tool groups, refuse to skip an oversized newest complete turn
  to manufacture a misleading older suffix, and obey character/unit budgets.
- Actual dev23 native/local/graph/team/plan/DAG/nested recovery and Temporal
  History replay/continuation, new actual-service malformed-provider cases, installed
  wheel/base contracts, previous20starter contents and package byte identities pass.
- No new required dependencies, paid model calls, credentials, commits/push or
  destructive checkout cleanup. Exactly one fresh final reviewer, one Important
  fix pass; prior user changes and local evidence are retained.

Final review clarification: a returned ModelResponse with an invalid JSON field
still proves provider completion. Keep independently serializable fields and
valid usage, record invalid_fields without raw-object repr, close synchronous
lazy coroutine/generator values without awaiting, and reject decision adoption.
Do not classify this content rejection as uncertain dispatch.
