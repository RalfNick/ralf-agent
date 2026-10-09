# DeepSeek dev21 trial — 2026-10-08

This is a small real API trial using `deepseek-flash`, non-thinking mode, with
2048 output tokens and a 60-second timeout per call. The authenticated model list
also returned `deepseek-v4-pro`; this trial used only flash. The Provider explicitly
disables thinking, matching [DeepSeek's protocol](https://api-docs.deepseek.com/guides/thinking_mode/).
The optional JSON-object mode follows [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/).

The full sanitized [machine-readable report](../evals/results/deepseek-dev21.json)
contains case selection, task results, usage and per-phase configuration. Credentials,
HTTP headers, private filesystem paths and raw databases are excluded.

| Phase | Cases | Result | Paid calls |
| --- | --- | --- | --- |
| Original business Agent instructions | All eight frozen business cases | 0/8 | 15 |
| Existing model DAG planner | Six selected planning cases | 3/6 | 6 |
| Managed summaries | Language/identifier, unresolved evidence, tool injection | 3/3 bounded checks | 3 |
| Managed memory selector | Two preference records and unsupported null fields | 3/3 | 3 |
| Explicit output schema/codes/approval instructions | Pool, disk, ambiguous target, bypass approval | 3/4 | 8 |
| Explicit native JSON-object mode | Missing target, ambiguous target, missing evidence | 3/3 | 3 |

Total: **38 calls**, **17,873 input tokens**, **3,844 output tokens**. The hard
call allowance was 40; two calls remained unused. No monetary price estimate is
presented. Independent phases used 900/300/300-second wall limits; this is not one
enforced cumulative 900-second deadline. Follow-up phases retain latency in the
report; initial latency was not retained.

The initial business failures were predominantly output-contract failures: the
model added Markdown/prose or fields, used descriptive cause text instead of
machine-readable codes, or lacked target information. Some business writes had
already succeeded under approval before final answer validation failed; the
original records preserve those effects. The follow-up fixed the application
instructions, not the dataset or success oracle: exact schema, cause codes,
null fields for abstention, and a distinction between tool proposals and approved
receipts. Pool and disk then completed diagnosis, approved write, stop and restart
recovery checks. The ambiguous target was correctly recognized but prose before
JSON remained invalid. Native JSON mode subsequently passed that abstention case.

Planning passed missing-environment, policy refusal and no-silent-extra,
but failed incident sequencing, partial-order dependency and authorized-adjustment
argument semantics. A schema-valid plan is not necessarily a valid business plan. The
planner and oracle were not altered to improve these scores.

Summary scoring checked retained identifiers, character bounds, uncertainty
keywords and not following a tool's injected instruction. Memory scoring checked
allowlisted field selection from fixture source results; host validation still
enforces exact source values. These tests do not establish general summarization
quality, semantic fact truth, or autonomous belief revision.

The first private runner used an incorrect Provider close method after tests had
finished, before it saved the aggregate report. Its call count, usage, per-case
outputs and planning checks were reconstructed from durable execution records;
the failure and original 0/8 score remain in the report. No paid calls were replayed
to recover these records. The later runners saved complete reports.

The final JSON phase covers missing-input/refusal paths. It does **not** prove an
8/8 final-config business result. No AgentScope/LangGraph implementation ran in
this trial, so the evidence supports no comparative quality or reliability claim.
The remaining work is to rerun the full frozen set under one retained final
configuration, repeat it, and add end-to-end RAG answers/citations and external
developer adoption evidence.

To repeat a separate bounded business trial, use the existing evaluator with an
explicit model, key environment variable, output-token/timeout/call limits and a
fresh private evidence directory. For JSON mode, construct
`DeepSeekChatProvider(..., json_mode=True)` and call `evaluate_business(...)` from
the SDK. JSON-object mode is explicit and non-streaming; it guarantees neither
schema correctness nor task success. Empty/incomplete/invalid responses remain
rejected. See [business evaluation](business-evaluation.md) and
[managed memory](managed-memory.md).
