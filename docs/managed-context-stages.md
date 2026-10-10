# Managed automatic context preparation (dev41)

Dev44 also supports Local graph/parallel/Team/dynamic/nested Agent decisions and explicit Temporal managed registration; see [advanced context](composite-temporal-context.md). Automatic memory writes remain narrower.

Opt-in Local native Agents and sequential Workflows can summarize **complete omitted
history groups from the same Run** before freezing a business model request. Original
Run/Action/tool evidence and Session messages are retained. The latest complete tool
group, original system instruction and task are protected. Session/Facts/RAG references
are selected normally and are **not** sent to the summary model in this increment.

```python
from ralf_agent import ManagedContextPipeline

# Pass as LocalEngine(context_assembler=context), or register the existing
# BindingCatalog "context" role and select it per Agent.
context = ManagedContextPipeline()  # deterministic excerpts, no model I/O
context = ManagedContextPipeline(
    mode="model",
    provider="summary",
    summary_max_chars=512,
    timeout=5,
)
```

`summary` is an explicit alias in the host's existing providers map. The summary
provider and pure policy are fixed in the accepted release; changing either requires
a new release. Pure `ContextBuilder.assemble` remains synchronous. The original Engine
performs and owns the optional model call; there is no child Run or second authority.
Existing `ManagedModelSummarizer` remains an explicit standalone API.

JSON/TOML RuntimeProfile uses the existing component and binding factory:

```json
{
  "context_assembler": {
    "adapter": "managed-summary",
    "config": {
      "mode": "model",
      "provider": "default",
      "summary_max_chars": 512,
      "source_max_chars": 32768,
      "timeout": 5,
      "counter": "utf8-estimate",
      "max_units": 8000
    }
  }
}
```

This is the `components` entry of a Profile, not a complete catalog. Default mode is
`excerpt`; omitted component retains the old ContextAssembler and release identity.
SDK callers can inject a BudgetedContextAssembler with their own pure MessageCounter
and ContextBudgeter, and a pure ContextSummarizer in excerpt mode. Model mode does not
accept a hidden excerpt summarizer. UTF-8 measurement is an estimate, not billing.

## Evidence and recovery

- No omitted group, or no room alongside the protected latest group, means no stage.
  Required history exceeding the allowance still fails as before.
- The host fixes ordered coverage digests and source snapshots; the model only returns
  bounded nonblank JSON `{"text":"..."}`. Summaries enter a user evidence message with
  an explicit untrusted/incomplete label, never as a system instruction.
- Stage intent, summary dispatch, received response and frozen projection have distinct
  original-Run checkpoints. Independent markers and reservation evidence are checked
  on observation and recovery. The business Action links to its exact preparation.
- Each dispatched model summary reserves **one execution credit from the original Run**.
  A returned invalid response is charged once and uses the frozen fallback. A missing
  response after dispatch holds the credit as unknown and is never automatically retried.
  Excerpts consume no model credit; source limits and exhausted summary allowance skip
  optional work. These credits are not a currency or exact token ceiling.
- Saved responses are adopted without another model call; saved projections are reused.
  Frozen reference versions are validated before actual business-model disclosure.
  A changed provider/source cannot confirm the old release silently.
- Cancellation owns the actual managed operation until it finishes. Terminal recovery
  only consumes durable evidence or marks interrupted calls unknown; it never calls a
  summary model or reopens business success. There is no remote summary-query protocol,
  so unknown summary credits remain held and discoverable.

Read `LocalEngine.context_stages(run_id)` or `await AgentRun.context_stages()` for the
original receipts. The Facade exposes partial/unknown stages as auxiliary controls
with `source="context"`; observation starts no execution. Events have a
`context_preparation_` prefix. These records contain source evidence: apply the same
access/retention policy as Run storage.

Opt-in admission requires optional Store `context_stage_version=1`, synchronous
`prepare_context_stages()` and `managed_stage_reservation(run_id,id)` extensions.
The builtin SQLite authority atomically enables semantic schema8; dev40 refuses8
before reads or writes. Defaults and schemas1–7 remain readable with original releases.
Custom ExecutionStore implementations must implement the atomic evidence contract;
implementing JSON persistence alone is insufficient.

Graph/Team/dynamic/nested and Temporal automatic preparation are explicitly refused.
Automatic Session/RAG compression, large-result artifact offloading, model extraction,
async completion verification, background Jobs and complete H3 remain pending.
Offline providers validate orchestration and recovery, not summary/model task quality.
See [remaining capabilities](remaining-work.md) and [verification record](../architecture/reviews/2026-10-09-managed-context-preparation.md).
