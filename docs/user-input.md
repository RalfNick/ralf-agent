# Durable user input

An explicitly registered input tool pauses its original Run until a matching
answer is accepted. A selected dynamic planner can request the same durable
question. Close/restart retains the question, Run, release and Session Turn.
Ordinary business results such as `{"status":"needs_input"}` keep their existing
meaning. This capability is opt-in; it does not interpret ordinary text as an
approval or answer.

## Single Agent, RAG and Team members

Register the framework tool in the existing registry and include its returned
name in the Agent's tool allowlist. Its request arguments are exactly
`{"prompt":"Which environment?"}`. It must be the only tool call in that model
decision. No Python handler or Activity waits for the user.

```python
from relf_agent import (
    AgentSpec,
    LocalEngine,
    Runtime,
    SQLiteStore,
    ToolRegistry,
    UserInputPolicy,
    register_user_input,
)

tools = ToolRegistry()
ask = register_user_input(
    tools,
    policy=UserInputPolicy(
        reply_schema={"type": "string", "enum": ["production", "staging"]},
    ),
)
spec = AgentSpec("assistant", "Ask for the environment when needed.", tools=(ask,))

# provider is your configured ModelProvider. Existing business tools remain in tools.
async with Runtime(
    LocalEngine(
        SQLiteStore("runs.sqlite"),
        providers={"default": provider},
        tools=tools,
    ),
    owned=True,
) as runtime:
    run = await runtime.create_agent(spec).submit("Check the deployment", command_id="request-1")
    waiting = await run.wait()
    question = next(item for item in await run.pending() if item["kind"] == "input")
    receipt = await run.send_input(
        question["pending_id"],
        question["target_digest"],
        "production",
        command_id="answer-1",
    )
    result = await run.wait(terminal_only=True)
```

The answer becomes the original tool call's result. The existing decision/tool
limits and remaining credits still apply; answering never resets them. The tool
costs zero execution credits and has no external attempt. Input-control receipts
are supplemental user evidence, not business-effect receipts.

`UserInputPolicy` is immutable. Its default reply Schema is a nonblank string.
Defaults are eight questions, 4096 prompt characters and 65536 reply UTF-8 bytes.
You can set `max_requests` (1–32), `max_prompt_chars` (1–16384), and
`max_reply_bytes` (1–1048576). Reply Schemas are bounded JSON objects with local
fragment references only; remote and dynamic references are rejected without I/O.
Replies must be finite ordinary JSON at depth at most 32 and match the fixed
host Schema.

For a Team, graph or nested child, `root.pending()` includes the original owner
RunRef. Attach that owner before replying:

```python
from relf_agent import RunRef

question = next(item for item in await root.pending() if item["kind"] == "input")
owner = await runtime.aattach(RunRef.from_dict(question["ref"]))
receipt = await owner.send_input(
    question["pending_id"],
    question["target_digest"],
    "production",
    command_id="answer-1",
)
```

The Facade wakes the original root. Question discovery retains all owners even
when another child needs approval or effect reconciliation. These other controls
must be addressed independently.

Default `wait()` also observes selected input controls while a sibling still
executes. It returns `wait_reason="control_available"` with the unchanged
authoritative root snapshot, which may still say `running`. Read `pending()` to
obtain the actual question owner. This observation does not declare the root or
its handlers quiescent. `terminal_only=True` keeps waiting for terminal state;
owned close continues retaining actual sibling handler responsibility.

## Configuration and independent replacement

Both Local `RuntimeProfile` and `TemporalProfile` accept the configured policy
family. This declaration installs `request_input` into the already-built tool
registry; an existing custom Python/tools component is retained.

```json
{
  "user_input_policies": {
    "adapter": "configured",
    "config": {
      "policies": {
        "environment": {
          "version": "1",
          "reply_schema": {"type": "string", "enum": ["production", "staging"]},
          "max_requests": 4
        }
      },
      "tools": {"request_input": {"policy": "environment"}}
    }
  }
}
```

Place the family under the Profile's `components`. The equivalent TOML section is:

```toml
[components.user_input_policies]
adapter = "configured"

[components.user_input_policies.config.policies.environment]
version = "1"
max_requests = 4
reply_schema = { type = "string", enum = ["production", "staging"] }

[components.user_input_policies.config.tools.request_input]
policy = "environment"
```

Policy Schema, names, selections and bounds are validated before component I/O.
Known HTTP/CLI declaration name collisions are also rejected during preflight.
Arbitrary custom tool factories remain opaque until constructed; all marker name
collisions are then checked before any marker is published. No existing tool is
overwritten. A normal tool named `request_input`, or a copied tool config, remains
an ordinary tool: the authority recognizes the exact framework marker and pinned
descriptor. Marker registration does not expand any Agent's allowlist.

A selected policy family or intrinsic marker also requires a custom Local Engine
factory to supply synchronous `send_input` controls before business acceptance.
The Temporal Facade requires async controls when its release selects the input
protocol.
Failed construction closes owned resources through the usual builder lifecycle;
borrowed resources retain their original owner. Unselected legacy Engines keep
the existing control contract.

For direct SDK assembly, pass `user_input_policies={"environment": policy}` to
the Engine/TemporalRuntime and select a name in the dynamic definition. Registered
tools independently carry their own fixed policy. You can replace named policies,
Providers and business tools before a new release is accepted; original Runs
continue using their original pinned versions.

## Dynamic Plan clarification

Select `DynamicWorkflowSpec(..., input_policy="environment", max_revisions=3)`
and register that named policy. A typed
`PlanningConclusion("needs_input", "Which environment?")` becomes a parent-owned
question. `refused` stays terminal. Without selection, `needs_input` retains its
legacy result behavior.

The flat `ModelPlanner(input_requests=True)` explicitly accepts these typed
conclusions. Its Profile declaration is
`{"adapter":"model","config":{"input_requests":true}}`. The default remains
unchanged; ModelDAGPlanner already supports typed planning conclusions.

Each accepted planning answer consumes a new planning revision. If there is no
next revision, question creation fails before an impossible wait. The next
PlanningRequest receives an ordered `clarifications` list of validated answers
to that planner owner's original questions, on both Local and Temporal. Child
tool replies remain in their original child results and native history; they do
not consume the planner's own clarification allowance. Its original `task`,
earlier children/results and budgets remain fixed.
The planner must explicitly use each journal's `value`; answers are not merged
into the submitted task. Completion policies likewise receive optional lineage
and continue enforcing their declared original task/business receipts.

## Receipts, restart and Session occupancy

`send_input(run_id, pending_id, target_digest, value, *, command_id,
expected_state_revision=None)` is an optional Engine control. Its Facade form
uses the current owner Run and omits `run_id`.

| Situation | Result |
| --- | --- |
| Same command ID and exact same reply/conditions | Original receipt, including after completion/cancellation |
| Same command ID with changed reply or target | `idempotency_conflict` |
| New command for a consumed/stale question | Rejected receipt, `stale_pending_target` |
| Cancelled/cancelling/terminal owner | Rejected receipt, `target_closed` |
| Reply fails fixed Schema | Rejected receipt, `invalid_input`; question remains open |
| Optional owner revision changed | Rejected receipt, `version_conflict` |

Malformed commands and unauthorized targets fail before acceptance. A successful
reply receipt means the command was applied, not that the business task succeeded.
When using raw Engine controls, explicitly `drive`/`resume` the original root;
the online Facade hosts that continuation automatically.

Closing an owned Local Runtime can park a stable wait after actual sibling
handlers finish, returning reconnectable RunRefs. A new original-release Runtime
can attach the saved RunRef and recover the same question. Temporal clients
detach from server execution on close. Cancelling `wait()`, observation timeout,
or transport disconnect does not answer, cancel or release the Run.

An open input question keeps its Session busy. `Session.submit/run` remains a new
Turn request and returns SessionBusy; use the original Run's `send_input` for the
answer. Rebind remains idle-only. A reply does not allocate another Turn. Explicit
business cancellation retires pending questions, and late answers cannot reopen
the Run.

## CLI, starter and A2A

Create an installed offline example with `relf init input-app --template user-input`.
Its README walks through independent processes that submit, reply and resume.
It uses an actual intrinsic wait, with no model key or network service.

```sh
relf --db runs.sqlite --factory my_app:create_engine --format text inspect RUN_ID
relf --db runs.sqlite --factory my_app:create_engine send-input RUN_ID PENDING_ID --digest TARGET_DIGEST --value-json '"production"' --command-id answer-1
relf --db runs.sqlite --factory my_app:create_engine resume RUN_ID
```

`inspect` displays the question/Schema and a shell-quoted reply hint. Replace its
placeholder with a Schema-valid JSON value. The command returns the input receipt
without implicitly driving execution. ProfiledEngine looks up an original reply
receipt before reconstructing its Profile, allowing repeated accepted controls
after that Profile has been removed.

A2A hosts opt in with `enable_user_input=True`. Their Agent Card advertises
`urn:ralf:a2a:user-input:v1`. `A2AClient.send_input(task_id, pending_id,
target_digest, value, *, command_id, expected_state_revision=None)` sends an
explicitly targeted continuation. The wire message uses the original owner
`taskId`, `metadata.ralfInput` (`pendingId`, `targetDigest`, optional
`expectedStateRevision`), and one JSON data part `{ "value": ... }`.
The Task response includes `metadata.ralf.inputReceipt`. Repeated message IDs
deduplicate the full wire request. Ordinary task text is still rejected as a
continuation. Existing endpoint request/response byte limits apply independently
of policy reply limits. LocalA2AService wakes the original managed root after an
applied child reply.

With this extension selected, polling the original root Task also exposes input
questions in `metadata.ralf.pending`. Each input entry includes `kind="input"`,
`ownerTaskId`, and the original `PendingInput` owner, source, prompt, reply Schema,
pending identity and target digest. Use `ownerTaskId` as the reply's `task_id`;
a child question keeps its original child target. Team, graph and nested questions
remain discoverable when another child independently waits for approval or
reconciliation. Existing root approval entries retain their original shape.

Composite extension hosts require original diagnostic discovery before accepting
business requests. Local discovery also verifies original managed parent links;
Temporal discovery validates original child intents/releases and rereads actual
child Histories. Optional observation bindings and Scope are checked before and
after async work. The read-only projection visits at most 4096 original owners
and questions, with managed depth at most 16, and rejects cycles or foreign data.
It creates no Runtime, supervisor, lease or second authority. Unselected A2A hosts
retain the existing port contract. Native input remains available through its
original root snapshot when no composite discovery port is needed.
An explicitly enabled extension requires a pinned `send_input` control in the
same synchronous/native async mode before accepting a message into the Inbox or
business authority. Read-only input discovery itself does not require this control.

Public completion can precede the actual managed drive's exit. Local service close
skips a too-late cancel on an already terminal root, while retaining and draining
its original drives and actual handlers before releasing the coordinator.

These offline examples and protocol tests do not establish live model quality,
external adoption, durable FIFO, deadlines, or completion of R01–R26/H3/M1.
