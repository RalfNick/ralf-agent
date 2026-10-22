---
title: Capabilities overview
description: Choose agents, tools, memory, knowledge and execution patterns for your task, then compose them gradually.
locale: en
slug: overview
sources: [docs/basic-capabilities.md, docs/concepts.md, docs/support-journey.md, docs/releases/0.1.0a1.md]
---

## What Relf-Agent helps you build

Relf-Agent is an open-source Python agent framework. You define models, business tools and task structure. The framework records execution identities, model responses, approval decisions and tool receipts so tasks can be observed, controlled and recovered with their original configuration and evidence.

The name expands to **Reliable and Extensible Lifecycle Framework for Intelligent Agents**. **Build intelligent agents. Run them reliably.** Model reasoning, planning and member collaboration provide intelligence; replaceable components support customization; durable execution handles approval and recovery.

Previously named Ralf-Agent, the project has updated its display brand. The distribution remains `ralf-agent`, imports remain `ralf_agent`, the CLI remains `ralf`, and repository URLs are unchanged. These tutorials retain the labeled SDK 0.1.0a1 baseline; the latest public release is [0.1.0a2 Alpha](https://github.com/RalfNick/ralf-agent/releases/tag/v0.1.0a2). A brand update does not change version or recovery qualifications.

A ticket flow might read a ticket, retrieve a runbook, propose a change, wait for approval, execute a tool and inspect the result. Start with one agent. Compose fixed steps into a workflow, then add plans or teams when the task needs delegation.

Complete the [offline quickstart](/en/docs/quickstart/) first. It uses Python 3.11+ and local SQLite, with no model key, Redis, Temporal or Docker required.

## Choose capabilities by task

| Your goal | Relevant capabilities | Start here |
| --- | --- | --- |
| Let a model read orders, handle tickets or call business functions | Provider, `AgentSpec`, `ToolRegistry`, argument and output schemas | [Models & tools](/en/docs/models-tools/) |
| Confirm sensitive writes and continue after a process exits | Actions, operation digests, durable approvals, receipts and effect reconciliation | [Approval & recovery](/en/docs/recovery/) |
| Ask the user for missing information and resume the original task | Durable questions, fixed reply schemas and original-run continuation | [Durable user input](/en/docs/user-input/) |
| Continue a conversation and retain known preferences | Sessions, turns, facts, recall policies and context | [Sessions, memory & RAG](/en/docs/sessions-memory/) |
| Answer from runbooks or documents with traceable sources | Ingestion, versioned knowledge, lexical/vector/hybrid retrieval | [Sessions, memory & RAG](/en/docs/sessions-memory/) |
| Execute known steps sequentially or in parallel | Workflows, static dependency graphs, branches, input mapping and bounded parallelism | [Workflows & teams](/en/docs/workflows/) |
| Plan, delegate and verify among a finite set of members | Plans, teams, planners, verifiers and child runs | [Workflows & teams](/en/docs/workflows/) |
| Reuse MCP, HTTP endpoints, fixed CLIs or file references | Tool sources, workspaces, skills and explicit policies | [Integrations & extensions](/en/docs/integrations/) |
| Configure components and optionally use independent workers | Runtime profiles, versioned assembly, Local and Temporal | [Runtime & deployment](/en/docs/operations/) |

## How the pieces fit

```text
Input + Agent / Workflow definition
                 ↓
Session + Facts + Knowledge → Context → Provider
                                          ↓ response / tool proposal
                                Validate and record
                                          ↓
                             Approval needed? → pause
                                          ↓
                             Tool → receipt / reconcile
                                          ↓
                             Save result, finish original run
```

The provider proposes responses and tool calls. The engine or Temporal history owns execution authority. Retrieved documents, skill instructions and model proposals cannot expand tool permissions. Pure transforms and decision policies perform no external I/O; business calls belong in managed tools.

## Defaults and optional components

**Local foundation:** one Python process, a local execution database and ordinary Python tools. Add sessions, facts, local lexical retrieval and sequential or static workflows as needed. Verify the task and recovery path before replacing components.

**Explicit extensions:** real models, semantic embeddings, remote data stores, MCP/HTTP/CLI tools, sandboxes, coding delegation and Temporal each have configuration, resource and supported-subset requirements. Remote and service extensions remain experimental in the current Alpha and are not prerequisites for the default tutorial. See the [implementation status (Chinese)](repo:docs/implementation-status.md) for current support and acceptance boundaries.

A model adapter does not establish compatibility with every hosted model. A retriever does not establish business-level semantic quality. A successful local run does not verify every Temporal combination. Execution credits are an execution allowance, not currency, tokens or a hard provider spending cap.

## Three learning paths

### Business tool assistant

[Quickstart](/en/docs/quickstart/) → [Models & tools](/en/docs/models-tools/) → [Approval & recovery](/en/docs/recovery/). Start with read-only queries, then give writes the correct effect category, idempotency/reconciliation contract and approval policy.

### Knowledge and conversations

[Core concepts](/en/docs/concepts/) → [Sessions, memory & RAG](/en/docs/sessions-memory/) → [Integrations & extensions](/en/docs/integrations/). Distinguish conversation history, lasting facts and source documents before choosing recall and context policies.

### Multi-step business processes

[Workflows & teams](/en/docs/workflows/) → [Runtime & deployment](/en/docs/operations/) → [Approval & recovery](/en/docs/recovery/). Use static graphs for known steps. For planning, make allowed members, iterations, concurrency and budgets explicit.

Follow the site-local [application tutorial](/en/docs/app-tutorial/) to add models, Sessions, RAG, Facts and a workflow to one ticket application. For method signatures use [API & CLI reference](/en/docs/api-reference/); for offline regression, model compatibility and live-quality boundaries use [testing and evaluation](/en/docs/testing/).
