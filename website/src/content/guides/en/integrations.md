---
title: Integrations & extensions
description: Connect models, MCP, HTTP, CLI tools, workspaces and skills while retaining the existing execution protocol.
locale: en
slug: integrations
sources: [docs/model-adapters.md, docs/managed-tools.md, docs/mcp-http.md, docs/http-tools.md, docs/cli-tools.md, docs/workspace.md, docs/workspace-writes.md, docs/skills.md, docs/sandbox.md, docs/extending.md]
---

## Choose the integration boundary

| Existing capability | Integration | What the application defines |
| --- | --- | --- |
| Python business function | `ToolRegistry.tool` / `register_function` | Argument schema, effects, version, approval and reconciliation |
| MCP tool service | `MCPToolSource` with stdio or HTTP transport | Selected tools, fixed targets, credentials, policies and cleanup |
| Business HTTP JSON endpoint | `HTTPToolSource` | Fixed URL, POST, schemas, response bounds and effect semantics |
| Trusted local CLI | `CLIToolSource` | Fixed argv, JSON input/output, environment and process lifetime |
| File references | Workspace and managed file tools | Fixed root, relative paths, scope and read limits |
| Reusable operating instructions | Skill catalogs and managed loading | Allowed skills, versioned content, sources and tool permissions |

Tools still run through registration, authorization, approval, actions and receipts. The trusted host configures endpoints, executables and directories rather than allowing the model to choose arbitrary targets. See [models and tools](/en/docs/models-tools/) for Python registration.

## Choose a model protocol

| Protocol family | Existing entry points | Selection notes |
| --- | --- | --- |
| Chat Completions compatible | `OpenAIChatProvider` / `chat-completions` | Explicit model, base URL and parameters; verify each endpoint |
| OpenAI Responses | `openai-responses`, plus a reasoning continuation adapter | Text and client-function subsets; reasoning state needs dedicated continuation configuration |
| DeepSeek | `deepseek-chat` / `deepseek-thinking` | Select non-thinking or thinking continuation explicitly |
| Anthropic Messages | `anthropic-messages` | Text and client tools; no implied thinking or multimodal support |
| Gemini | `gemini-content` / `gemini-functions` | Text in the former; functions need the dedicated adapter and continuation configuration |

Adapters declare protocol capabilities. Verify your account, region, model, tool round trips and streaming cancellation in your environment. Applications explicitly select models; failures do not silently fall back to offline results or another protocol. Credentials come from the environment or a trusted credential service; profiles retain credential variable names.

SSE text fragments are temporary display data. A complete, validated and recorded response is required before a tool proposal can be adopted. Fragments are not durable run events, and token-level resumable streaming is not provided. See the [model adapter guide (Chinese)](repo:docs/model-adapters.md).

## Run a real offline MCP tool

The MCP starter starts a local subprocess service and uses a separate SQLite business-receipt database. It needs no model key. The current stdio path requires an environment with POSIX process management.

```bash
ralf init my-mcp-agent --template mcp
cd my-mcp-agent
python -m agent_app --value 3 --command-id first-change
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

Replace `RUN_ID` with the submitted run ID. Inspect the tool, arguments and digest, execute the approval command printed by `inspect`, then resume:

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine resume RUN_ID
```

The sample business service deduplicates with the framework-injected `effect_key`. An identical submission retrieves the original run. This verifies local integration, approval and receipts, rather than compatibility with every MCP service or model task quality.

## The host chooses external-tool policies

`register_tool_source` registers only tools explicitly selected in `policies`. Remote descriptions and annotations cannot grant permissions. `ToolPolicy` starts with conservative write and approval defaults; declare `read_only` only after confirming the actual behavior.

- **Idempotent writes:** the downstream system must genuinely accept and deduplicate the stable effect key. Declaring a category alone is insufficient.
- **Queryable writes:** provide a reconciler through the SDK to query the original effect. Reconciliation must not silently execute the operation again.
- **HTTP:** a fixed JSON POST boundary, with no model-selected URL, method or headers. This is not a general browser or arbitrary REST proxy.
- **CLI:** a fixed program and argv, with no implicit shell. Process management alone does not provide sandbox isolation.
- **MCP HTTP:** the implemented JSON/POST SSE subset does not imply OAuth, resources, prompts or tasks support.

A timeout or cancelled wait does not prove the remote operation stopped. Follow [reconciliation and recovery](/en/docs/recovery/) for uncertain effects, and wait for actual calls and connections to finish.

## Workspaces, skills and sandboxes

**Workspaces** expose managed reads within a host-selected root and allowed scope. Writes require the corresponding capability and its version/CAS contract. `Scope.workspace` is a logical scope, not a filesystem directory or authenticated identity.

**Skills** hold reusable instructions with versioned metadata, content and digests. Reading a skill still permits only already-authorized tools. Loading instructions does not automatically execute their scripts or replace approval.

**Sandboxes** are explicitly selected execution capabilities. The existing Docker default requires a host-provided Linux Docker Engine and a local immutable image. It does not start Docker, pull images or inject credentials. Configure tool policies and resource limits using the [sandbox guide (Chinese)](repo:docs/sandbox.md).

These Alpha components are enabled within their experimental scope. Importing the SDK does not grant general system access.

## Replace the layer you need

Providers, tool sources, context, memory, retrievers, embeddings and executors have distinct extension contracts. Structural ports generally do not require framework inheritance. Implementations need stable identities, correct sync/async methods, completed return values and explicit cleanup.

Pure policies propose choices without network, model or storage I/O. Components needing asynchronous construction use existing entry points such as `abuild`. Directly injected resources follow owned/borrowed lifetime rules. See [extension contracts (Chinese)](repo:docs/extending.md) and [runtime and deployment](/en/docs/operations/).
