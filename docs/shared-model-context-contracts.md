# Shared model acceptance and recent Session recall — dev24

The Local and Temporal authorities share pure acceptance rules. The rules check
declared tools, effective arguments, final output and call-ID uniqueness for a
whole batch. Typed defaults are resolved by the registry first. Action allocation,
approval, dispatch, credits and state commits remain owned by each authority.
A duplicate explicit ID, including collision with a generated fallback ID,
rejects the batch before any tool Action is adopted.

A returned `ModelResponse` is evidence, even when its proposal is invalid.
Serializable fields survive independently. Non-finite or lazy fields are marked
in `invalid_fields`, replaced with a safe JSON placeholder, and never adopted;
coroutines/generators are closed without awaiting. Invalid raw objects cannot be
reconstructed from these markers. Raw output/tool calls/usage are retained separately from accepted
proposals. Known execution settles its execution credit; missing or invalid
usage is explicit unknown token accounting, not an unknown execution hold.
No hidden retry or billing guarantee is introduced.

New Temporal model Activity receipts carry `model_evidence_version: 2` and
`received_response`. Post-receipt Schema failure, policy refusal or registered
component drift retains this evidence. A late completed response settles after
cancellation without adopting tools or reopening the Run. Legacy receipts without
the marker preserve their recorded History transitions, including historical
unknown outcomes and decisions; they are not retroactively repaired. Mixed-version
worker deployment and deployment-version migration remain uncertified.

Both `ContextAssembler` and `BudgetedContextAssembler` now select optional
references through one pure selector. Fitting references retain their original
shape/order. An oversized `session` reference becomes a chronological contiguous
suffix of complete recent turns. Conversational turns keep tool calls and results
together; native completed assistant records retain their `task` and metadata.
An oversized or incomplete newest turn is not skipped to include older evidence.
`session_projection` in the assembly manifest reports selected/omitted message and
turn counts. Current task/evidence remains protected and character/unit budgets
still apply. Source Session data and saved model request snapshots do not change.

This is optional reference projection, not automatic summarization or storage
compaction. Legacy Session reads can still materialize full history. Per-Agent
bindings, a simple Agent/Session facade and recommended managed memory/RAG chains
remain separate follow-up work. See the [architecture review](../architecture/reviews/2026-10-08-agent-framework-alignment.md)
and [implementation status](implementation-status.md).
