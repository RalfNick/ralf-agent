# Durable user input design (dev93)

Status: implementation in progress; no acceptance claim. Baseline: `a04b20e`, dev92.

## Intent and scope

R01/R02/R10 require a developer to pause an Agent or planner for a user answer,
close and restart the host, and continue the original Run/Turn. This batch adds
one shared bounded question/reply protocol, an explicit framework input tool,
and opt-in dynamic planner continuation. Sequence, graph, nested and Team
parents expose the original question owner. Local and Temporal remain the
only authorities; Facades, tools and message transports do not own a wait queue.

The user authorized continuous implementation, independent parallel work and
local commits only. No push, publish, model-key discovery or blanket capability
completion claim is part of this batch.

## Selected approach

Use `register_user_input(registry, name="request_input", policy=...)` to install
an exact intrinsic marker. It is discoverable through the existing Agent tool
allowlist. A normal tool with the same name or copied config remains a normal
tool; the original marker plus matching pinned descriptor select the protocol.
Its callable fails if dispatched: no thread, Activity, Python handler, remote
journal or external effect attempt waits for the human. The authority intercepts
it after authorization and adopts an input request on the original Tool Action.

The input call must be the sole tool call in its decision. Its input is exactly
`{"prompt": text}`. The reply Schema and bounds come from the host's policy,
never model-provided Schema. The accepted answer is the original call's tool
result, preserving native call IDs, reasoning and continuation. Existing model
and tool Action limits apply. The marker costs zero execution credits; it does
not reserve external attempt credit or fabricate an external effect receipt.

Alternatives considered: planner-only continuation misses single Agents and
Team members; interpreting final business output requires a second nonfinal
model adoption contract. Explicit output-policy adapters may later produce the
same question primitive. No ordinary `needs_input` business JSON changes meaning.

## Shared values and exact limits

`user_input.py` owns detached pure values and validators, not execution state.

- `UserInputPolicy(reply_schema=None, version="1", max_requests=8,
  max_prompt_chars=4096, max_reply_bytes=65536)` is immutable and configurable.
  Default Schema is a nonempty string. `max_requests`: 1–32; prompt limit:
  1–16384 characters; reply limit: 1–1048576 UTF-8 bytes. Policy Schema is an
  ordinary finite JSON object, at most 65536 UTF-8 bytes and depth 32. No remote
  Schema references or dynamic references; local JSON-pointer fragment references
  are allowed. Root `$id` metadata is supported; nested resource rebinding and
  same-instance reference cycles are rejected. Recursive finite child schemas work.
- `InputRequestProposal(prompt)` is concrete, detached nonempty text. It has
  no authority, handler, awaitable or independently configured Schema.
- `PendingInput` is restored with `from_dict`, emits `to_dict`, and contains
  exactly `schema_version`, `pending_id`, `target_digest`, `owner`, `source`,
  `ordinal`, `prompt`, `reply_schema`, `max_reply_bytes`, `policy_digest`.
  `owner` is exactly `{run_id, release_digest, scope}`. Scope is exactly
  `{workspace, principal}`. Source is tool `{kind, action_id, node,
  proposal_digest}` or planner `{kind, revision, proposal_digest}`. Digests
  are lowercase SHA-256; integer types exclude booleans. Node is a nonnegative
  integer, nonempty string or None. Ordinal is 1–32. Prompt/Schema/reply data
  obey finite JSON, byte, depth and Schema bounds.
- Authority-created `pending_id` is `input:` plus SHA-256 of protocol, owner,
  source and ordinal. `target_digest` covers all request fields except itself.
  Unrelated state revisions cannot change it. Proposal digest binds the exact
  accepted Tool proposal or planner conclusion, not a newly generated question.
- The authority's `input_requests` journal is a mapping from pending ID to record,
  ordered for projection by original question ordinal within each owner/frame.
  Each record stores `{request, state}` with
  `state="pending"`; an answered record adds exactly `value`, `reply_digest`,
  `command_id`; cancellation retires an open request with `state="cancelled"`.
  Answers are finite ordinary JSON at depth at most 32 and policy byte bound.
  Restore validates actual reply digest, Schema and original question identity.

Shared interfaces: `register_user_input(...) -> str`,
`input_tool_policy(RegisteredTool) -> UserInputPolicy | None`,
`make_input_record(*, run_id, release_digest, scope, source, prompt, policy,
ordinal) -> dict`, `validate_input_record(record) -> dict`,
`answered_input(record, value, command_id) -> dict`,
`input_reply_payload(run_id, pending_id, target_digest, value, *,
expected_state_revision=None) -> dict`. The payload contains `run_id`,
`pending_id`, `digest`, `value`, and omits an absent expected revision.

## Authority command and observation

Optional Engine capability (do not add a required `ExecutionEngine` member):

```python
send_input(run_id, pending_id, target_digest, value, *, command_id,
           expected_state_revision=None) -> CommandReceipt
```

The existing synchronous or asynchronous command transaction/Workflow Update
checks trusted Scope first, deduplicates the exact payload, validates the fixed
owner/request/release, consumes one answer, and selects continuation atomically.
Identical repeated commands return the original receipt after advancement,
terminal completion, cancellation or Profile removal. Different payloads with
the same command ID conflict. A new command targeting a consumed/stale question
returns a stable rejected receipt (`stale_pending_target`); a closed Run returns
`target_closed`; an optional owner revision mismatch returns `version_conflict`;
invalid reply returns `invalid_input`. Rejections append no transcript, mint no
credits, change no question and start no model/tool execution. Malformed commands
and unauthorized calls fail before acceptance. Reply receipt means command
application, not subsequent business success.

Snapshot approval entries retain their old bytes. New input pending entries
contain `kind="input"` plus the detached question. Facade `pending()` adds the
original owner `ref`, recursively validates descendants, and exposes every
question even when other siblings need approval/reconciliation. Child control
targets its actual owner; the Facade wakes the existing original root owner.
CLI renders questions and supports explicit `send-input` with target ID/digest
and JSON value. A2A can advertise and accept an explicit input continuation
extension; ordinary text/task messages never implicitly become replies.

Observation cancellation, timeout and client disconnect remain observation-only.
No answer creates a new Run, Session Turn, input request identity or allowance.
`run.input`, submit command digest, release and original current task stay fixed.
Session remains busy while waiting across restart; Session rebind is idle-only.
Owned close parks a stable wait after actual sibling handlers end; borrowed close
detaches. Cancellation retires questions, retains effect evidence and propagates
child stop responsibilities. Late answers cannot reopen execution.

## Agent and composite execution

Local intercepts the marker before executor dispatch, creates the request and
`waiting_input` atomically, and returns a stable pause. Explicit resume cannot
unpause or redispatch it. Reply commits through original `_tool_result`, with
receipt `source="user-input"`, original pending/digest, command and reply digest.
There is no external attempt. Parallel graph control locates the original node
frame before applying transcript mutation. Accepted Tool replies are journaled
through existing native message provenance before continued model dispatch.

Temporal uses the same pure validators, descriptor and request identity. Its
History adopts the question and answer; no custom callable runs inside Workflow
and no Tool Activity/effect journal is created for the marker. Native tool receipt
is on its original Action, matching existing session-history publication proof.
While unanswered, no completion gate, memory extraction, native episode freeze
or successful Session save runs. Workflow sleeps on actual control/child changes;
root-owned questions do not generate periodic context/model Activities.

Composite state folds explicitly propagate `waiting_input`. Precedence when
paused children coexist: reconciliation/unknown effect, approval, input. All
actual owners remain visible independently of the folded state. Escrow settles
only on original child settlement; waiting/answer never settles unknown effects.

## Dynamic planner continuation

`DynamicWorkflowSpec(..., input_policy=None)` omits the field when absent.
`user_input_policies` is a named Engine/Profile family of pinned policies. An
explicit selection maps `PlanningConclusion("needs_input", reason)` to a
parent-owned question. `refused` remains terminal and unselected `needs_input`
retains legacy completion behavior. Both flat and DAG planners can produce the
typed conclusion; the managed ModelPlanner adapter is updated explicitly.

An accepted reply advances the existing planning revision, consuming the declared
`max_revisions` capacity. If no next revision is available, creating a question
fails explicitly before an impossible wait. Original planner child/conclusion,
accepted DAG revisions, results, finished children, receipts and budgets remain
immutable. Only select-stage request/proposal state is reset. New planner child
identity uses the new revision, so the old successful child cannot be reused.
`PlanningRequest.clarifications` contains ordered validated answers to this
planner owner's original questions, identically on Local and Temporal. Child
tool answers remain in their original child results and native history; they do
not consume the planner's own question allowance. The field is omitted when
absent and carries unchanged original `task`.

Replies are supplemental evidence, not an implicit JSON merge. This batch does
not introduce a generic effective-task resolver. Parent completion source gets
optional validated `clarifications` (omitted when absent) so custom gates/model
stages can explicitly consume reply lineage. A gate requiring original submitted
fields still enforces that contract; adding a reply does not silently satisfy or
weaken it. Input-control receipts are not business-effect evidence. Existing
Inventory gate continues requiring its declared original task and actual receipts.

## Compatibility, assembly and acceptance

Python >=3.11; no new required dependencies. Unselected definitions, Profiles,
Provider identities, descriptors and old default manifests remain byte-identical.
Selected Local uses `local-9` / `local-bindings-17` and `user_input_protocol=1`.
Selected Temporal uses `binding_protocol=10` and `user_input_protocol=1` with
explicit registered policies/markers. Update closed protocol sets only for this
selected release; an old SDK/Worker must reject before any external I/O.

SDK registration, named policy replacement, JSON/TOML configuration and an
installed standalone starter are required. Configuration preflights Schema,
names, selected policy and bounded values before component I/O. No borrowed
client ownership or resource-lifecycle behavior changes.

Acceptance includes pure malformed/deferred/remote-ref cases; matching Local
and Temporal native request/reply; actual process restart before/after answer
commit; lost control response; same/conflicting/stale/foreign replies; cancellation;
Session occupancy; native DeepSeek/Responses continuation; parent/parallel/nested
question ownership; planning child identity and retained completed work; revision,
decision and budget exhaustion; default byte compatibility; installed SDK/CLI;
actual source/wheel Temporal History fetch/replay and old Worker refusal. Fixture
Providers are runtime evidence only. Real model quality/external adoption remain
unaccepted without their separate actual evidence. Whole-source regression,
static checks, final artifact provenance and one fresh whole-batch review precede
the local commit. R01–R26/M1/H3 overall completion remains open.
