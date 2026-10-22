---
title: Build one support application
description: Advance one source file from an offline Agent through Sessions, RAG, explicit Facts and a sequential Workflow.
locale: en
slug: app-tutorial
sources: [docs/support-journey.md, docs/installation.md, docs/agent-api.md, docs/session-api.md, docs/recall-and-rag.md, docs/managed-memory.md, docs/orchestration.md, docs/recovery-guide.md]
---

Follow ticket `INC-001` through five stages in one application file: an Agent with a read-only tool, a persistent Session, local RAG, lasting Facts and a sequential Workflow. Each stage composes existing SDK components. The default provider is an offline fixture; it demonstrates execution and evidence plumbing without model credentials or network services.

This tutorial targets the **0.1.0a1 Local SDK** at published commit `0b9b6c9682c40285d91994cd831aa93d7e814bf1`. Complete [installation](/en/docs/installation/) and the [approval quickstart](/en/docs/quickstart/) first. The stages below run without Temporal, Docker, embeddings or an external database. Online model compatibility and task quality need separate [testing and evaluation](/en/docs/testing/).

## 1. Prepare the application file

Use [support_journey.py](repo:examples/support_journey.py) from the published source. It imports only the installed SDK and Python's standard library; it does not import the repository's `examples` package. A wheel installs the SDK but does not include this example file; the source distribution includes it.

If you followed source installation, run this **from the framework checkout root**, with its virtual environment active. Choose a new target directory:

```bash
mkdir ../support-app
git show 0b9b6c9682c40285d91994cd831aa93d7e814bf1:examples/support_journey.py \
  > ../support-app/support_journey.py
cd ../support-app
python support_journey.py --help
```

If you installed a wheel without a checkout, open the linked source, choose its raw file and save it as `support_journey.py` in a new working directory. Save Python source rather than the GitHub HTML page, activate the environment containing the SDK and run the same `--help` command there. It should list `agent`, `session`, `rag`, `memory` and `workflow`.

All remaining commands run beside this file. By default, `.ralf/support-journey/` contains five independent stage databases, including their execution history, Sessions, Knowledge and Facts. Each stage assembles its own data from the same source file; it does not migrate or share the preceding stage's Run or Session.

| Stage | Added component | Main customization point | Database |
| --- | --- | --- | --- |
| `agent` | Provider, Python tool, `AgentSpec` | `provider_for`, `tools_for` | `agent.sqlite` |
| `session` | Persistent conversation and Turns | `agent.open_session`, `session.submit` in `run` | `session.sqlite` |
| `rag` | SQLite document and lexical retrieval | `Document`, `KnowledgeContext` in `run` | `rag.sqlite` |
| `memory` | Explicit versioned Facts | `memory.put_fact`, `MemoryRecallPolicy` in `run` | `memory.sqlite` |
| `workflow` | Two sequential Agent steps | `WorkflowSpec` in `run` | `workflow.sqlite` |

## 2. Run an Agent and retrieve its original result

```bash
python support_journey.py agent --command-id agent-1
python support_journey.py agent --command-id agent-1
```

The first JSON output should contain these fields; your `run_id` will differ:

```json
{
  "stage": "agent",
  "state": "succeeded",
  "model_calls": 2,
  "result": {
    "ticket": {"ticket_id": "INC-001", "service": "cache", "status": "connection-error"},
    "advice": "Check cache health and connectivity; do not restart without approval.",
    "knowledge": [],
    "facts": {},
    "session_records": 0
  }
}
```

The fixture first requests `lookup_ticket`, then copies its observation into the answer. The unchanged second command retrieves the **same `run_id` and saved result**, with `model_calls: 0`. These counts are offline provider invocations, rather than billed model usage or quality scores.

For a new request using the same definition, choose a new `--command-id`. Reusing `agent-1` with different input, budget or definition can conflict. Keep the original ID when checking an uncertain response; do not erase the database to avoid the identity check.

## 3. Optionally select a real model

Skip this step to keep the entire tutorial offline. To opt in, make `DEEPSEEK_API_KEY` available through your own credential management and replace `YOUR_MODEL` with a model supported by your account:

```bash
python support_journey.py agent \
  --provider deepseek-chat --model YOUR_MODEL \
  --data-dir .ralf/support-live --command-id live-1
```

Alternatively choose `--provider chat-completions`, provide `OPENAI_API_KEY` and an appropriate explicit model. `provider_for` selects `DeepSeekChatProvider` or `OpenAIChatProvider`. Missing configuration fails explicitly; it does not fall back to the fixture. Live requests may incur provider charges, and `model_calls` is `null` because this example does not count their usage.

The fixed offline answer is not an expected answer for a live model. Check tool calling, evidence use and business outcome with your own cases. Follow [models and tools](/en/docs/models-tools/) for provider setup and [testing](/en/docs/testing/) for compatibility and quality checks. This tutorial's verification made no live calls.

Keep live data separate from offline data. If you change the model, instructions, tools or policy, use new request identities and a new data directory or properly configured new Session. Historical recovery still needs the original configuration. The remaining commands default to the offline provider; they do not inherit this command's live selection.

## 4. Continue the same Session across processes

```bash
python support_journey.py session --command-id turn-1
python support_journey.py session --command-id turn-2 \
  --input 'What should we check next?'
python support_journey.py session --command-id turn-2 \
  --input 'What should we check next?'
```

Each invocation is a new process. The application opens the same Session `INC-001` in `session.sqlite`; the first two commands create different Turns and Runs. Both should succeed. The second output has `result.session_records` greater than zero (`1` in a fresh directory), showing that a saved prior Turn reached the current context. The third command retrieves the second Run, with `model_calls: 0`.

`Runtime.create_agent(definition)` creates the runnable `agent`; `AgentSpec` is only its definition. The file includes the full async entry point and resource lifetime, so it can be run independently of the [Session guide](/en/docs/sessions-memory/).

Finish or handle the previous Turn before submitting the next. An open approval, input question or unfinished execution keeps its Session busy. Resolve that original Run, then wait for idle. A reply to an existing question uses [durable input](/en/docs/user-input/), rather than `session.submit()` with another message. A timeout in observing a Run does not release the Session. A previously recorded busy rejection remains associated with its command ID; after resolving it, a new submission attempt needs a new ID.

## 5. Add local RAG

```bash
python support_journey.py rag --command-id rag-1
```

Expect `state: succeeded` and this entry in `result.knowledge`:

```json
{"document_id": "cache-recovery", "version": 1, "source_uri": "local://runbooks/cache-recovery"}
```

The application imports one cache recovery runbook into namespace `runbooks`, then uses `KnowledgeContext(LexicalRetriever(...))`. `local://...` is a source identifier stored in SQLite, rather than a remote request. Creation uses `expected_version=0`; restarting does not overwrite an existing version or resurrect a deleted document.

To use your own document, change the `Document` content, identity and source URI in `run` for a new application data directory. To update a document already stored, read its current version and perform a version-checked update; editing the seed text does not update persisted Knowledge. Repeat queries with a new command ID after an intended source update. An old request continues to expose its recorded answer.

This stage uses lexical retrieval and downloads no embedding model. A hit demonstrates source retrieval and reference propagation. It does not establish semantic relevance or answer quality. [Sessions, memory and RAG](/en/docs/sessions-memory/) includes ingestion and hybrid retrieval setup in English; the optional repository [hybrid retrieval specification (Chinese)](repo:docs/hybrid-retrieval.md) has additional technical detail.

## 6. Add explicit lasting Facts

```bash
python support_journey.py memory --command-id memory-1
python support_journey.py memory --command-id memory-2
```

Both should succeed and include `result.facts: {"response-style": "concise"}`. The trusted host first writes this Fact to the `support` namespace with `expected_version=0`. The second process preserves its value and recalls it again; it also has a prior Session record. This stage seeds its own runbook in `memory.sqlite`, so its result includes Knowledge as well.

The Fact namespace matches the `support` Agent. Keep the original Scope and namespace boundaries when replacing the store. Updating an existing Fact requires its current version; changing the initial seed value does not replace saved Facts.

This example performs explicit writes and persistent recall. It does not perform automatic extraction, conflict revision or forgetting. If you select managed extraction, configure source-field allowlists and check its separate completion evidence; a model's assertion is not automatically a verified Fact. See [memory configuration](/en/docs/sessions-memory/) and the optional [managed memory specification (Chinese)](repo:docs/managed-memory.md).

## 7. Compose a sequential Workflow

```bash
python support_journey.py workflow --command-id workflow-1
```

Expect `state: succeeded`, `model_calls: 4`, the runbook reference and `response-style: concise`. `WorkflowSpec` runs `triage` first, then `support`; the preceding step's output becomes the next input. The Workflow stage assembles its own Knowledge and Facts, reusing the earlier component choices. All business tools remain read-only.

This is a fixed sequence of two Agent definitions. The offline result demonstrates that both steps execute; it does not establish planning, Team collaboration or general support accuracy. Change the `WorkflowSpec` in `run` to customize the order or definitions. Continue with [workflows and collaboration](/en/docs/workflows/) for graph, Plan and Team choices.

## 8. Inspect and recover the original task

Every output supplies a `run_id`. For example, inspect a Session stage Run with its own database:

```bash
ralf --db .ralf/support-journey/session.sqlite --format text inspect RUN_ID
ralf --db .ralf/support-journey/session.sqlite events RUN_ID --after 0 --limit 100
```

Use `agent.sqlite`, `rag.sqlite`, `memory.sqlite` or `workflow.sqlite` for the corresponding stage, and adjust the directory if you supplied `--data-dir`. These commands observe the default Local Scope; inspection does not resume execution. This example does not expose a `module:create_engine` CLI factory.

After a stopped process, rerun the original application command with the same file, stage, provider, model, data directory, input and command ID. Its submit path retrieves the original Run and hosts its continuation. An already completed request returns its saved result. Do not start another process while the previous executor still owns active work; normal lease checks prevent takeover.

| Symptom | Next step |
| --- | --- |
| `ModuleNotFoundError: ralf_agent` | Activate the environment containing the installed SDK; verify [installation](/en/docs/installation/) |
| Python cannot open the file, or reports HTML syntax | Prepare the raw `support_journey.py` source and run beside it |
| JSON `{"error":"validation_error"}` | Check arguments and configuration; live mode requires an explicit model and credentials, and the fixture supports only `INC-001` |
| `idempotency_conflict` | Recover the original request unchanged; use a new ID for a new intent |
| `definition_mismatch` | Restore the original model, file and component configuration; a changed application belongs in new data |
| `session_busy` | Inspect and resolve the original Turn, then wait for idle; use a new ID for a new attempt after a saved busy rejection |
| `coordinator_busy` or an active lease | Find the original executor and let it finish or close normally |
| `close_incomplete` | Retain the original resources, resolve actual outstanding calls/effects and retry normal close |

The example shares one SQLite connection: Knowledge and Memory borrow it, while the owned Runtime drains and closes its Engine. Do not force-close borrowed resources or delete leases. See [recovery](/en/docs/recovery/) for unresolved effects and [runtime and deployment](/en/docs/operations/) for resource ownership.

## 9. Customize and validate your application

- Replace the model in `provider_for`; adapt `OfflineSupportProvider` when maintaining an offline regression fixture.
- Replace the read-only business query in `tools_for`. A different ticket also requires updating the fixture's hard-coded tool call, instructions and Session ID in `run`. Changing only `--input` does not turn this fixture into a general ticket service.
- Replace the Knowledge and Memory ports in `run`, retaining Scope, namespaces, source checks and version-checked writes. Use new data for changed definitions; retain the original file/configuration for historical recovery.
- Introduce writes only with the appropriate effect classification, approval and reconciliation contract from [models and tools](/en/docs/models-tools/) and the [quickstart](/en/docs/quickstart/). A read-only declaration must describe the actual tool behavior.
- Establish offline regressions, model protocol checks and task quality cases through [testing and evaluation](/en/docs/testing/). Query signatures and control semantics in the [API and CLI reference](/en/docs/api-reference/).

The optional repository [original support journey (Chinese)](repo:docs/support-journey.md) covers this same source file. Temporal/Coding composition and production service integration are outside this Local tutorial's verification.
