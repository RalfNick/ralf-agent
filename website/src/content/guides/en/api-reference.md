---
title: API & CLI reference
description: Find common Local Agent, Runtime, Session and CLI signatures, return values and recovery contracts.
locale: en
slug: api-reference
sources: [docs/api-reference.md, docs/agent-api.md, docs/session-api.md, docs/user-input.md, docs/sdk-model-tools.md, docs/recovery-guide.md, docs/runtime-assembly.md, docs/getting-started.md]
---

This is a curated reference for the common Local path, checked against SDK `0.1.0a1`. It is not an exhaustive generated API listing. Start with the [application tutorial](/en/docs/app-tutorial/) for a complete program; use [models and tools](/en/docs/models-tools/) for provider setup. Temporal and optional backends have separate contracts in [operations](/en/docs/operations/).

## Definitions and runnable entries

Import these names from `ralf_agent`.

| Entry | Common signature or defaults | Meaning |
| --- | --- | --- |
| `AgentSpec` | `AgentSpec(name, instructions, tools=(), provider="default", version="1", max_decisions=8, max_context_chars=32000, model_credits=1, output_schema=None)` | Immutable declaration. Tool names must be registered with the host. It has no `run` or `open_session` method. |
| `Agent` | `Agent(*, model, tools=(), name="assistant", instructions="Answer the request", db_path=".ralf/runs.sqlite", definition=None)` | Standalone async facade, with an explicitly supplied Provider. Creates and owns its Runtime. |
| `Agent` with shared host | `Agent(runtime=runtime, definition=spec)` or `runtime.create_agent(spec)` | Borrows an existing Runtime and its fixed components. Do not also supply `model` or `tools`. |
| `Runtime` | `Runtime(engine, *, owned=False, authority_locator=None, close_timeout=30, close_policy="drain")` | Hosts Local execution on one event loop. Injected engine is borrowed by default. |
| `LocalEngine` | `LocalEngine(store, providers=..., tools=..., ...)` | Lower level execution authority. Its `submit` records intent; the caller explicitly drives it. |
| `ToolRegistry` | `tools.tool(effect="read_only", ...)` / `tools.register_function(function, effect=..., ...)` | Registers a Python function and supported inferred argument schema. Explicit effect and host authorization still apply. |
| `ModelProvider` | finite `identity` dict; `async complete(messages, tools) -> ModelResponse` | A structural protocol: no inheritance is required. Provider proposes output or `ToolCall`; the engine authorizes and executes tools. |

Keep declarations named `spec` and runnable facades named `agent`. Changing the submitted declaration, such as `output_schema`, changes the request digest. Tool and Provider registration identities are fixed in the accepted release; use changed components for new tasks and retain original components to recover old Runs.

`Runtime.from_profile(profile, db_path, *, builder=None, scope=None, ...)` owns the built assembly. `await Runtime.afrom_profile(...)` supports asynchronous factories. [Runtime assembly details (Chinese)](repo:docs/runtime-assembly.md) describe component registration; the [English Local Agent contract](repo:docs/agent-api.md) covers hosting and shutdown.

## Submit, run and wait

All facade calls below are awaited. `command_id` is required for submitting business intent.

| Method | Returns | Defaults and behavior |
| --- | --- | --- |
| `agent.submit(input, *, command_id, budget=32)` | `AgentRun` | Durably submits and wakes hosted execution. Keep `.ref` and `.receipt`. |
| `agent.run(input, *, command_id, wait_timeout=None, terminal_only=False, budget=32)` | `WaitResult` | Submit followed by wait. It does not return the business output directly. |
| `run.wait(*, wait_timeout=None, terminal_only=False)` | `WaitResult` | Observes committed facts. Default timeout is unbounded; default returns on terminal state or a human/recovery pause. |
| `run.status()` | `RunSnapshot` | Pure observation: `state`, `result`, `error`, `pending`, `actions`, `state_revision`. |
| `run.events(*, after=0, limit=1000)` | list of `RunEvent` | Ordered events. Page with the last `seq`; `event_id` is `run_id:seq`. |
| `run.diagnostics()` | `RunDiagnostics` | Snapshot plus original manifest, release digest, budget and optional workflow details. |

`WaitResult` contains `ref`, `snapshot`, `wait_reason` and `observed_at`. Reasons are `state_reached`, `control_available` and `observation_timeout`. Always check `observed.snapshot.state` before using `observed.snapshot.result`. A pause or observation timeout is not business success. `terminal_only=True` waits through pauses and can need a finite observation timeout.

Cancelling an awaited wait does not cancel business execution. Use `await run.cancel(command_id=...)` for an explicit cancellation decision; cancellation does not roll back remote effects.

The raw engine has different return types and driving semantics:

```python
# Inside an async function; engine and spec are already assembled.
handle = engine.submit(spec, "Check INC-001", command_id="request-001", budget=32)
snapshot = await engine.drive(handle.run_id)
print(snapshot.state, snapshot.result)
```

`engine.submit(...)` is synchronous and returns `RunHandle(run_id, receipt)` without starting execution. `await engine.drive(...)` returns `RunSnapshot` at completion or a pause. Do not interchange `RunHandle`, `AgentRun` and `WaitResult`. Stateless facade submission rejects shared `session_id` and `queue=True`; use an explicit Session.

## Durable Sessions

| Awaited method | Returns / contract |
| --- | --- |
| `agent.open_session(session_id, *, command_id)` | `AgentSession` with `.ref` (`SessionRef`) and opening `.receipt`. Omit namespace for the ordinary native Agent path; explicit namespace selection has a separate composite contract. |
| `session.submit(input, *, command_id, budget=32)` | `AgentRun` with `.turn` (`TurnAdmission`), including original Turn/Run identity. |
| `session.run(input, *, command_id, wait_timeout=None, terminal_only=False, budget=32)` | `WaitResult`, with the same observation semantics as Agent. |
| `session.status()` | `SessionSnapshot`; check `.busy` before submitting a new Turn. |
| `session.turns(*, after=0, limit=100)` | Ordered Turn records; the supported limit is at most 1000. |
| `session.rebind(definition, *, expected_binding_revision, command_id)` | New `AgentSession` entry after an idle compare-and-swap; use its returned reference for future Turns. |
| `session.aclose()` | Detaches this entry; does not close the shared Runtime. |

A Session retains one unfinished Turn, including approval, input and unknown effects. A terminal snapshot alone does not establish that the lane is idle. Answer an old question on its original Run, then confirm the Session is idle before a new Turn. See [Sessions and memory](/en/docs/sessions-memory/), [user input](/en/docs/user-input/) and the [English Session contract](repo:docs/session-api.md).

## Pending work and controls

`await run.pending()` returns original pending evidence, including nested owners. Each item includes `ref`; attach that owner with `runtime.attach(RunRef.from_dict(item["ref"]))`. Inspect `kind` before choosing a control. An `auxiliary` item may describe a context/memory/save obligation; it is not an approval request.

| Awaited method on the original owner | Returns / contract |
| --- | --- |
| `run.approve(action_id, target_digest, *, command_id, approved=True)` | `CommandReceipt`; bind the reviewed decision to the original action and digest. `approved=False` rejects. |
| `run.send_input(pending_id, target_digest, value, *, command_id, expected_state_revision=None)` | `CommandReceipt`; value must satisfy the original question schema. Optional revision adds a state check. |
| `run.reconcile(action_id, result, *, command_id)` | `CommandReceipt`; confirm an unknown effect using verified business evidence. Do not invent success to unblock a Run. |
| `run.cancel(*, command_id)` | `CommandReceipt`; records an explicit stop decision. |
| `run.resume()` | `AgentRun`; wakes original hosted execution. No new submission or control receipt is created. |

For approvals use the item's `action_id` and `digest`; for input use `pending_id` and `target_digest`. Hosted facade controls wake the original root; an applied input reply continues its original Run. Raw `engine.approve` / `engine.send_input` and CLI controls only record the decision: explicitly drive/resume afterward. See the complete [input reply sequence](/en/docs/user-input/) and [approval/recovery path](/en/docs/recovery/).

## Identity, receipts and reconnect

| Identity / record | Keep it for |
| --- | --- |
| `command_id` | One immutable request or decision within the trusted Scope. Same ID + same request replays the original receipt; changed input, definition, budget or decision conflicts. Use a fresh ID for new intent. |
| Run ID / `RunRef` | One execution on its original authority, Scope and release. Serialize `run.ref.to_dict()`; rebuild with `RunRef.from_dict(...)`. |
| `SessionRef` / Turn | Original conversation address, binding revision, Turn sequence and its Run. A reply/control is not a new Turn. |
| `action_id` / digest | The exact proposed action reviewed or reconciled. |
| `InvocationContext.effect_key` | Stable downstream effect identity for a tool; the host injects it. A downstream idempotency/query contract must actually honor it. |
| `CommandReceipt` | `command_id`, `run_id`, `kind`, `record_state`, `apply_state`, `outcome`. Durable recording/application is not a successful business outcome. |

Use distinct, stable control IDs per Run/action/digest/decision. Repeating a decision retries that same ID. A fixed ID such as `approve-1` cannot approve every later action. `Scope(workspace="default", principal="local-owner")` comes from the trusted host; it is not enterprise authentication.

After closing, reconstruct the original engine/components/database and Runtime, then `runtime.attach(saved_ref)` (or `await runtime.aattach(saved_ref)`). Attach/status/events are observations; explicitly `await run.resume()` or apply a required control to continue. A `RunRef` contains no client or credentials and is not an execution authority or a database backup.

## Ownership and errors

Use `async with` for Agent/Runtime. Standalone Agent closes its created Runtime. Closing a borrowed Agent only detaches it. A Runtime drains its hosted work and closes the engine only with `owned=True`; `LocalEngine` owns its Store/Coordinator. Directly injected Providers, clients and other borrowed components remain their owner's responsibility. Profile builders can explicitly own resources.

Default close policy is `drain`, with a 30-second close timeout. `aclose()` returns `CloseReport(state, parked, owned)`. `CloseIncomplete` retains the report and shutdown responsibility: keep resources and retry `aclose()`. `close_policy="cancel"` requests cancellation and waits for actual managed work to settle; neither policy establishes rollback of remote writes.

| Signal | Next step |
| --- | --- |
| `ValidationError` | Fix schema, options or unsupported combination before retrying. |
| `IdempotencyConflict` | Replay the original request or choose a new command ID for genuinely new intent. |
| `DefinitionMismatch` | Restore the original component/configuration release and authority. |
| `BudgetExceeded` / `AgentLimitExceeded` / `CapacityExceeded` | Inspect the original ledger and configured execution/admission limits. Execution credits do not represent currency. |
| `AuthorizationDenied` / `NotFound` | Check trusted Scope and original Run/reference; do not bypass the authority. |
| `SessionBusy` | Follow `.run_ref`; the rejection has `.receipt`. Resolve the original Turn, confirm idle, then submit a new attempt with a new ID. |
| `SessionBindingMismatch` | Restore the original binding or explicitly rebind while idle. |
| `RuntimeClosed` / `ExecutionHostFailed` | Reconnect, or repair the original host and explicitly resume. Queries do not restart execution. |
| `snapshot.error` / paused state | Read durable failure/pending evidence. A returned observation can describe a failed business task without raising an SDK exception. |

Typed exceptions derive from `RalfError` and expose `.code`. CLI errors print a structured error (JSON by default) to stderr and return exit code 2. Business outcome is still in the snapshot; a successful CLI invocation alone does not prove task success.

## CLI lookup and control

Global options precede the subcommand: `--db` defaults to `.ralf/runs.sqlite`, `--format` to `json`; `--format text` gives a readable view. `--config runtime.toml` and `--factory module:callable` are mutually exclusive trusted assembly choices. Keep the same database and original assembly for mutation/recovery commands.

```bash
ralf --version
ralf --help
ralf run --help
ralf send-input --help
```

| Command after `ralf [global options]` | Result / driving behavior |
| --- | --- |
| `init my-agent --template config` | Writes an offline starter to a new directory. Follow its README. |
| `run --spec agent.toml --input hello --command-id hello-1 --budget 32` | Requires `--config` or `--factory`; submits and drives to completion/pause. `--input-json` selects JSON input instead. |
| `run ... --submit-only` | Returns serialized `RunHandle`; does not drive. |
| `status RUN_ID` | JSON snapshot; read-only. Text format uses the inspection summary. |
| `inspect RUN_ID` | Read-only release, budget, pending evidence and command hints. |
| `events RUN_ID --after 0 --limit 1000` | Read-only ordered event page. Resume pagination after the last `seq`. |
| `approve RUN_ID ACTION_ID --digest DIGEST --command-id DECISION_ID` | Records approval receipt; `--reject` records rejection. Then explicitly `resume RUN_ID`. |
| `send-input RUN_ID PENDING_ID --digest DIGEST --value-json '"answer"' --command-id REPLY_ID` | Records a schema-valid input reply. Optional `--expected-state-revision N`; then explicitly resume. |
| `resume RUN_ID` | Drives that original Run using its original assembly. |
| `cancel RUN_ID --command-id CANCEL_ID` | Records a stop decision; does not roll back effects. |

`status`/`inspect`/`events` read the local SQLite authority without importing a factory. They do not provide generic Temporal inspection. For an end-to-end CLI exercise use [user input](/en/docs/user-input/) or [quickstart](/en/docs/quickstart/). For regression and protocol commands use [testing and evaluation](/en/docs/testing/). The broader [repository API index (Chinese)](repo:docs/api-reference.md) is optional deeper reading.
