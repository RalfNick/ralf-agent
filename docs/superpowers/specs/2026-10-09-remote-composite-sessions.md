# H2b4b — remote composite root Session saves

User requests continuous capability development and verified local commits. Build
on dev38/e6a6de7, existing AgentSession, root conversation resource and receipt-v1
ports. No approval stop, new scheduler or execution authority.

## Scope and identities

Graph (sequential/parallel/direct transforms), Team, Dynamic linear/DAG and nested
Local Turns may select an explicit host SessionBindingResource backed by Redis,
PostgreSQL or a receipt-v1 custom backend. Root namespace selection remains host
authorized. Member bindings/sessions remain independent; root final message uses
original task/result/name and stable run_id + ':turn:result'. Root address is the
physical SessionKey storage key, unlike native logical Session IDs projected by
SessionView. Declared resource, namespace, protocol and remote descriptor are
independently fixed at admission; None cannot downgrade after metadata loss.

Existing defaults and schema1–5 retain behavior/release bytes. First accepted
remote composite open/rebind atomically enables schema6 via optional synchronous
prepare_remote_composites and explicit admission marker5. Old dev38 refuses6;
marker5 also supports already delivered native remote and colocated capabilities.
The authority keeps conservative Scope/address admission and actual descendant,
frame, thread and unknown-effect occupancy. No cross-authority sharing is promised.

## Completion and recovery

Execution authority accepts the composite final result from existing interpreter,
team policy or plan verifier. Before remote I/O, it persists the result-save intent
and independent corresponding marker in original workflow/orchestration state.
Required save uses original receipt-v1 inspection/append/CAS/confirmation rules;
there is no SQLite transaction spanning network I/O. Missing confirmation pauses
once per explicit drive. Receipt is persisted before original authority commits
success. A pending root result resumes only the save/final commit, without another
planner/verifier selection or child/model/business-tool execution.

Native per-node saves stay unchanged; graph member messages do not become root
success. Colocated composites retain the original same-transaction final save.
Terminal cancelled/failed recovery only queries original intents, preserves state,
and does not append. Missing/empty/partial journals or source markers refuse rather
than infer no write. Returned remote data is an observation, not proof of business
success; remote/local commit remains non-atomic and retention is operator-owned.

All network tasks are managed by the original Engine guard/parallel/orchestration
ownership. No nested same-Run guard may overwrite inflight tracking. Pure Session
status/turns/pending use durable evidence and do not inspect remote availability.

## Assembly and evidence

Register the existing session-resource factory for conversation_resource, reusing
nested SQLite/Redis/PostgreSQL factories, host namespace validation and async
owned lifecycle. Existing colocated-session adapter/defaults remain unchanged.

TDD actual foreign SQLite async port plus actual isolated Redis/configured PG;
all composite kinds, namespace None/named, approval restart, lost acknowledgement,
terminal cancellation, descendant occupancy, configuration drift, metadata loss
and no replay. Build/install real wheels; source/module/export/starter equality,
old schemas1–5 bidirectional recovery and old6 refusal. One fresh read-only review,
one Important/Critical fix pass, full/install/lint gates and local commit.

Remaining: cross-authority leases, Temporal bindings/shared Sessions, FIFO,
input/deadline, enterprise identity/isolation and broad model quality. No paid
calls, credentials or remote push in this increment.
