---
title: Runtime & deployment
description: Choose Local or Temporal and manage versioned configuration, execution allowances, observation and resource lifetimes.
locale: en
slug: operations
sources: [docs/runtime-assembly.md, docs/agent-api.md, docs/agent-limits.md, docs/temporal-execution.md, docs/recovery-guide.md, docs/releases/0.1.0a6.md]
---

## Choose an execution backend

| Dimension | Local | Temporal |
| --- | --- | --- |
| Execution authority | Original local execution store and coordinator | Original workflow history |
| Starting dependencies | Python, local SQLite and the application factory | Explicit Temporal service, workers, task queue and release configuration |
| Progress | `drive` or a hosted runtime advances the original run | Service/workers execute; the facade sends controls and observes progress |
| Recovery | Original database, factory, component versions and business evidence | Original history, matching release, queue and effect evidence |
| Starting use | Local assistants, development pilots and low-dependency flows | Selected distributed combinations needing independent workers |

Local does not automatically become a distributed scheduler. Temporal does not wrap LocalEngine in an activity. They share concepts without complete parity for sessions, tool nodes or nested combinations. Temporal is explicitly configured within its experimental Alpha scope. Read the [Temporal guide](repo:docs/temporal-execution.md) and [current support status (Chinese)](repo:docs/implementation-status.md) before choosing it.

This website is static and can be hosted on Cloudflare. A Python agent application needs its own Python execution environment or worker. Hosting the website does not run an agent or provide a Temporal service.

## Manage components with a profile

After source installation, generate a new offline configuration project:

```bash
relf init my-config-agent --template config
cd my-config-agent
python -m agent_app --input hello --command-id hello-1
python -m agent_app --input pending --command-id pending-1 --submit-only
relf --config runtime.toml --format text inspect RUN_ID
relf --config runtime.toml resume RUN_ID
```

Replace `RUN_ID` with the second submission's ID. `runtime.toml` defines runtime components; `agent.toml` defines the agent. The template's `offline-echo` provider verifies assembly and execution.

A basic profile has the following shape. The template already contains editable, complete configuration:

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"

[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "example"
```

Configuration selects registered components without executing Python or dynamically importing arbitrary plugins. Relative resource paths resolve from the configuration directory. Across directories, retain the same absolute database and configuration paths and keep the original factory importable. Asynchronously constructed resources use the corresponding async assembly entry point.

## Change configuration and recover old tasks

A profile's `name/version` identifies configuration that cannot be overwritten. Moving a default affects new tasks; old runs resolve their original profiles. Retain declarations, adapter implementations and data. The catalog does not archive code or migrate databases for you.

The same command ID and request retrieve the original task. Changed input with the same ID conflicts. Use a new command ID for a new task under new configuration. Resolve `definition_mismatch` by restoring the original version, rather than changing aliases or relaxing defaults.

## Allowances, limits and completion checks

| Mechanism | What it controls | What it does not establish |
| --- | --- | --- |
| Run `budget` | Integer execution credits reserved and settled for attempts | Currency, exact tokens or a hard provider spending cap |
| Agent limits | Decisions, context characters and distinct tool-action counts | Host-wide CPU, concurrency, rate or actual remote termination |
| Graph/plan limits | Steps, revisions, concurrency and child budgets | Arbitrary scale or correct planning |
| Output schema / verifier | Output structure and explicit completion conditions | Truthful model text or automatic business success from a tool response |

Effective agent limits combine the spec, host and selected policy constraints. Pure limit policies perform no I/O and cannot expand permissions. Recovering an existing action does not allocate a new distinct tool-action slot. Limits are pinned with the original task.

## Observe, control and shut down

`status`, `events`, `inspect` and `attach` observe execution. A wait can end at a pause or observation timeout; inspect the snapshot's actual state. Resume explicitly when needed and submit a separate cancellation command to cancel.

At shutdown, stop new admission, finish or cancel and await your execution tasks, then close owned clients and data connections. Directly injected borrowed components remain their owner's responsibility. A cancelled Python await does not prove that a tool thread, subprocess or uncertain remote write has finished.

Backups need execution records, selected session/fact/knowledge/artifact stores and business-effect evidence. Copying one idle database file does not establish complete application recovery. See the [recovery guide (Chinese)](repo:docs/recovery-guide.md) for concrete procedures.

## Continue from a local pilot

Validate an offline task, a real tool and approval/recovery first. Add dependencies and services for your chosen models, remote data, MCP or Temporal. From the source repository root, install the Temporal extra with `python -m pip install -e '.[temporal]'`, then provide the service, workers and matching release. This guide starts no services implicitly.

APIs and some combinations remain Alpha. Evaluate deployment using evidence from your actual components and failure scenarios; current qualification is in the [implementation status (Chinese)](repo:docs/implementation-status.md). Use [approval and recovery](/en/docs/recovery/) to diagnose execution by state.

## Verified baseline and support boundaries

This site documents the SDK **0.1.0a6 source candidate** at the pinned commit shown above, verified on **2026-10-23**. The date records these tutorial checks, not a guarantee for every deployment or hosted model.

| Combination | Documentation status | Your next verification |
| --- | --- | --- |
| Local + SQLite + offline models/tools | Tutorial baseline | Run quickstart and the application test |
| Local Sessions, durable input, lexical/hybrid retrieval and explicit Facts | Offline recipes provided | Run the application and input tutorials with your own cases |
| Real models, embeddings and external tools | Explicit adapters and configuration | Check the exact endpoint, permissions, errors, cleanup and business outcomes |
| Remote storage or Temporal workers/releases | Experimental supported subsets | Follow the selected backend guide; these website tutorials do not verify those service combinations |

Use [API & CLI reference](/en/docs/api-reference/) for signatures, [durable user input](/en/docs/user-input/) for pauses, and [testing and evaluation](/en/docs/testing/) before changing providers or deploying. The pinned technical sources describe that snapshot; newer repository development does not change old-run recovery requirements.
