# Automatic model-selected memory (dev42)

Local native Agents and sequential Workflows can opt into a model selecting durable
observations from an already adopted final result. This extends the existing
[rule stage](managed-memory-stages.md); default behavior is unchanged and disabled.

```python
from ralf_agent import ManagedModelMemoryPolicy, MemoryAdmissionPolicy

stage = ManagedModelMemoryPolicy(
    writable_memory,
    provider="memory-selector",
    admission=MemoryAdmissionPolicy({"customer": ("result", "customer")}),
    namespace="observations",
    max_context_chars=32768,
    timeout=5,
)
# LocalEngine(..., stage_policy=stage), or register/select the existing
# BindingCatalog stage_policy role per Agent (inherit/ref/disabled).
```

`memory-selector` is an existing host provider alias. The accepted Run pins its actual
provider identity separately from the Agent's business provider. Targets are borrowed;
factory-created clients retain existing Runtime ownership. Facts read bindings cannot
grant writes. Pure request/select hooks are replaceable and pinned; I/O is Engine-owned.
The model returns only unique allowlisted keys, including an empty list. Values and
paths come from the original result and pass the independent base admission check.
Adding values, unknown keys, tools or unselected fields is rejected. Stored observations
have source/Run/release provenance and do not assert external truth or belief revision.

JSON/TOML uses the existing `stage_policy` component or binding declaration:

```json
{
  "adapter": "sourced-memory",
  "config": {
    "mode": "model",
    "provider": "default",
    "fields": {"customer": ["result", "customer"]},
    "namespace": "observations",
    "max_context_chars": 32768,
    "timeout": 5
  }
}
```

`sourced-memory-async` uses the same selection config through `RuntimeBuilder.abuild`.
The existing `memory` nested declaration selects SQLite/Redis/PostgreSQL/custom factories
and preserves their client lifecycle. Omitted mode remains the existing rule policy;
model-only settings are rejected in rule mode. No model credentials live in this policy.

## Accounting, failure and recovery

Original memory_stages now expose an optional `selection` receipt. Its request,
dispatch, response and accepted keys have separate checkpoints and independent markers
on the original final model Action. There is no standalone child Run or new authority.
Use `LocalEngine.memory_stages(run_id)` or `await AgentRun.memory_stages()` to inspect
without starting execution; pending/unknown stages remain auxiliary controls.

A dispatched selector reserves one original Run execution credit; each subsequent fact
retains the existing one-credit write reservation. These are execution credits, not
currency or exact token accounting. A returned invalid response is charged once and
writes nothing. Invalid/expired source, exhausted allowance or cancellation before
dispatch spends no selector credit. A dispatched call without a durable response holds
its credit as unknown; no automatic retry or rule fallback stores unselected fields.

Restart reuses a saved response or accepted key list, then resumes grounded proposal
and CAS recovery. Business model/tools and confirmed Session/fact writes are not replayed.
Missing/contradictory intent, response, selection or reservation evidence fails closed.
Prepared selectors cannot have an existing dispatch reservation. The exact independent
reservation and unexpired grant are rechecked inside dispatch before paid I/O. Actual
executing provider, policy, Scope and target method bindings are rechecked after hooks
and I/O; same-release registration replacements cannot hide their drift.

Cancellation keeps actual managed tasks/threads owned until completion. Terminal selector
recovery settles saved response evidence or marks abandoned calls unknown; it performs
no model call, creates no new facts and does not reopen business success. Evidence-only
selector settlement works with the provider offline; existing fact reconciliation retains
its pinned target/release requirements. Unknown selector credits have no remote query or
release protocol and stay discoverable.

Auxiliary selection failure preserves a completed business result. Target/release
violations still fail the business release rather than silently confirming drift.
Ordinary preparation/request validation failures are durable auxiliary failures with
no selector dispatch. Execution persistence errors continue to propagate for recovery.

## Supported scope

Opt-in first admission atomically enables semantic schema9; dev41 refuses9 before
reading/writing. Custom authorities need optional `model_memory_stage_version=1`,
`prepare_model_memory_stages()` and independent `managed_stage_reservation` contracts.
Schemas1–8 and existing defaults remain compatible.

Graph/Team/dynamic/nested/Temporal automatic memory remains explicitly unsupported.
Free-form synthesis, semantic revision/conflict/retraction, automatic Session/RAG
compression, artifacts, recommended presets and complete H3 remain pending. Offline
providers validate orchestration, not the model's field-selection quality.
See [remaining capabilities](remaining-work.md) and [verification](../architecture/reviews/2026-10-10-managed-model-memory.md).
