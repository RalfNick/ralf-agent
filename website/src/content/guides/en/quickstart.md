---
title: Quickstart
description: Generate a key-free offline agent and experience submission, approval and cross-process recovery.
locale: en
slug: quickstart
sources: [docs/installation.md, docs/getting-started.md, docs/recovery-guide.md]
---

This page covers the complete local path from installation to a completed task. Use **Python 3.11+**. SQLite and an offline provider require no model key, Redis, Temporal or Docker. If the SDK is already installed, continue from step 2.

## 1. Install from source

In a terminal, create a virtual environment and install:

```bash
git clone https://github.com/RalfNick/relf-agent.git
cd relf-agent
git checkout 0b9b6c9682c40285d91994cd831aa93d7e814bf1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

> This guide uses source installation. Check your actual revision. Relf-Agent is in Alpha, and APIs and deployment combinations continue to evolve. A public PyPI release has not been verified as the installation path for this guide.

The checkout pins the documentation baseline **0.1.0a1**, verified on 2026-10-21; confirm that version before continuing. See [installation](/en/docs/installation/) if your version differs.

## 2. Create an offline ticket project

Continue from the source checkout and choose a target directory that does not yet exist:

```bash
ralf --format text init ../my-agent
cd ../my-agent
python -m agent_app --db .ralf/runs.sqlite --ticket INC-001
```

The generated `agent_app/runtime.py` contains tools, an offline provider and a `create_engine(db_path)` factory. The project uses the installed SDK and does not depend on the framework checkout.

The offline provider emits fixed proposals to demonstrate the execution protocol. It makes no real model calls and is not a model quality evaluation.

## 3. Inspect the proposed operation

The first run stops at `waiting_approval`. Its output includes `run_id`, `pending` and the submission receipt. Replace the placeholder below with the real run ID:

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

`inspect` shows the original tool, arguments, operation digest and suggested commands. Read-only SQLite inspection does not load the factory or acquire an execution lease.

> `--db`, `--factory` and `--format` are global options. Put them before the subcommand. Output defaults to JSON; use `--format text` for human-readable output.

## 4. Approve and resume the original run

Inspect the operation, then use the actual commands returned by `inspect`. To fill them manually, take `ACTION_ID` and `OPERATION_DIGEST` from the original pending operation:

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  approve RUN_ID ACTION_ID \
  --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

An approval receipt with `applied` means the decision was recorded. `resume` advances execution and result adoption. Check that `state` is `succeeded`; a command's exit code alone does not prove business completion.

These commands can run in separate processes. Keep the same database, original factory and original configuration to continue the same run.

## 5. Inspect the result and retrieve the same task

Check `inspect` for `state: succeeded` and the actual result. Repeat the ticket entry point to observe that it refers to the same `run_id`:

```bash
python -m agent_app --db .ralf/runs.sqlite --ticket INC-001
```

Running the same ticket again uses the default `command_id`, `starter:INC-001`, and retrieves the original submission. Reusing an ID with a different definition, input, budget or session causes a conflict. New tasks need new IDs; an uncertain response calls for finding the original command first.

## 6. Connect your own business logic

After completing the local flow, learn about runs, actions and command identity in [core concepts](/en/docs/concepts/). Connect your own functions and a real model in [models and tools](/en/docs/models-tools/). Real models require credentials and model selection, and incur provider usage.

See [installation](/en/docs/installation/) for optional dependencies and troubleshooting. Read [approval and recovery](/en/docs/recovery/) for unknown writes, restarts and cancellation boundaries.
