---
title: Approval & recovery
description: Inspect the original operation, record a human decision and recover the original run from real evidence.
locale: en
slug: recovery
sources: [docs/recovery-guide.md, docs/getting-started.md, docs/concepts.md]
---

## Observe the original run

Run these commands from the quickstart project's root. Keep the original database, scope, factory and component identities, and replace the placeholders:

```bash
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
relf --db .ralf/runs.sqlite events RUN_ID --after 0 --limit 100
```

`inspect`, `status` and `events` read SQLite without writing and currently observe the default local scope. Queries do not reschedule work. A successful CLI command does not mean that the run completed.

| State | Next action |
| --- | --- |
| `waiting_approval` | Inspect the tool, arguments and digest; approve or reject, then resume |
| `waiting_input` | Read the original question/Schema/digest, send a reply to its owner, then resume; see [durable input](/en/docs/user-input/) |
| `waiting_reconciliation` | Check the actual dispatched effect; keep waiting if it cannot be confirmed |
| `queued` / `running` | Confirm the previous executor stopped and use the original factory; an active lease prevents takeover |
| `succeeded` / `failed` / `cancelled` | Inspect unresolved effects; terminal run state does not settle every external effect |

## Approval belongs to the operation

A process can close normally while waiting for approval. A new process loads the same factory and decides on the original action and digest:

```bash
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine approve RUN_ID ACTION_ID --digest OPERATION_DIGEST --command-id approve-001
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text resume RUN_ID
```

To reject, add `--reject` to the approval command and give that decision its own `command_id`. Take the digest from the original pending operation. An approval receipt records the decision; the actual business result is established after execution continues.

The same command and request retrieve the original receipt. If a network response is uncertain, reuse the original command instead of immediately creating a new business write.

## Continue after a restart

Recovery uses the original database and matching configuration identities. Fully received, durably recorded model responses, tool observations and node results continue at their respective adoption boundaries.

This is not a promise that every external request avoids retries. If a model response was not durably received, recovery can make a new attempt and incur more provider usage. Inspect actions and events to distinguish saved evidence from unknown outcomes.

`definition_mismatch` means the configuration or implementation does not match the original run. Restore the matching version and configuration. A changed default alias cannot replace historical identity. Historical protocols also do not guarantee that every old run can resume on the current kernel.

## Reconcile unknown writes

A timeout does not prove that a remote operation never executed. Query the business system with the original `effect_key` when a write outcome is uncertain.

- The default Python executor can call a registered `reconciler(arguments, context)`, returning confirmed business JSON or `None` for an unknown outcome.
- Reconciliation must not silently repeat a write. “Not found” does not automatically mean “safe to write again.”
- There is currently no general CLI `reconcile` command. Use the SDK to submit manually verified evidence.

```python
import asyncio
from agent_app.runtime import create_engine

with create_engine(".ralf/runs.sqlite") as engine:
    # confirmed_result must come from the real business system.
    confirmed_result = {"receipt_id": "ACTUAL_RECEIPT", "applied": True}
    engine.reconcile(
        "RUN_ID", "ACTION_ID", confirmed_result,
        command_id="reconcile-001",
    )
    print(asyncio.run(engine.drive("RUN_ID")))
```

This is an operation template. Replace the run, action and result with actual verified data. Placeholder values are not evidence. Remain paused when the effect cannot be confirmed. The framework does not promise cross-system exactly-once effects.

## Cancellation and shutdown

```bash
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine cancel RUN_ID --command-id cancel-001
```

Cancellation stops further scheduling. It does not undo dispatched business operations. Before shutdown, finish or cancel and await your managed drive task, wait for actual thread calls to finish, then close the engine. Do not delete leases or databases to bypass an executor that still owns active work.

## Diagnose by symptom

| Symptom | Check first | Next step |
| --- | --- | --- |
| `idempotency_conflict` | Reused ID with changed input, definition, budget or approval? | Retrieve the original request; use a new ID for a new intent |
| `definition_mismatch` | Changed factory, tool, model, profile or data identity? | Restore original versions and configuration, retaining records |
| `session_busy` | Which turn still owns the conversation? | Find `SessionBusy.run_ref`, resolve the turn and wait for idle |
| `coordinator_busy` | An engine or actual call still alive on this database? | Inspect its host and handlers and complete normal shutdown |
| `close_incomplete` | Unsettled tool, thread, connection or effect? | Resolve the cause and retry closing the original object; retain leases |
| Old RAG answer after updates | Original query command repeated? | Keep the original result; use a new ID for a new query |

Retain the run/action, state, event cursor, non-secret configuration version and error code to reproduce the same failure window. Keep credentials and sensitive business text out of diagnostic reports.

See the repository's [recovery guide (Chinese)](repo:docs/recovery-guide.md) for full state handling, backup procedures and failure windows. Read [sessions, memory and RAG](/en/docs/sessions-memory/) for conversations, and [runtime and deployment](/en/docs/operations/) for configuration and backends.

A reply receipt records the answer; it does not establish business completion. For child questions, inspect the actual owner from pending records. Do not answer by opening a new run or Session turn. See [API & CLI reference](/en/docs/api-reference/) for control return values and [testing and evaluation](/en/docs/testing/) for regression checks.
