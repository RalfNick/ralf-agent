# Context budgets, historical excerpts and explicit artifacts

dev20 adds opt-in context and artifact defaults. The original ContextAssembler,
canonical character limit, native local-4 identity and old sixteen starters are
unchanged. New runs can use BudgetedContextAssembler; accepted runs retain their
original builder/configuration. This is D3a, not completed intelligent memory or
enterprise data governance.

## Quick start without a checkout

Install the preview wheel, then create an editable standalone application:

```shell
relf init my-context-agent --template context
cd my-context-agent
python -m agent_app --input 'pool timeout' --command-id first
python -m agent_app --input 'pool timeout' --command-id queued --submit-only
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

The first explicit application tool stores 256 offline evidence rows and returns
a reference/preview. The second reads a bounded sample through ArtifactStore.
The offline Provider copies those rows; this verifies integration, not semantic
quality. The application owns a separate SQLite artifact database and closes it
after Engine shutdown. Keep code, configuration and both databases for recovery.

## Pure context assembly

```python
from relf_agent import (
    BudgetedContextAssembler,
    ExcerptContextSummarizer,
    UTF8TokenEstimator,
)

builder = BudgetedContextAssembler(
    counter=UTF8TokenEstimator(),
    max_units=1000,
    summarizer=ExcerptContextSummarizer(excerpt_chars=128),
    summary_max_chars=500,
)
history = [
    {"role": "system", "content": "Use evidence; obtain approval for business writes."},
    {"role": "user", "content": "Diagnose a pool timeout."},
    {"role": "assistant", "content": "old diagnosis evidence " * 300},
    {
        "role": "assistant",
        "tool_calls": [
            {"id": "c1", "function": {"name": "read", "arguments": "{}"}},
        ],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "Current pool is saturated."},
]
messages, manifest = builder.assemble(history, [], 2000)
assert messages[:2] == history[:2] and messages[-2:] == history[-2:]
assert manifest["measurement"]["estimated"]
assert manifest["summary"]["included"]
```

Pass the same builder as LocalEngine(context_assembler=builder). It measures
assembly and the actual request after Harness.prepare; both must satisfy the
original character limit and the configured measurement budget before dispatch.
Snapshots and measurement/provenance manifests are retained on model Actions.
Already-received model responses still adopt without another Provider call.

The required system/task and complete latest assistant/tool group survive
selection. Earlier groups are selected as complete units, preserving order.
Unmatched/missing/duplicate tool results are rejected rather than repaired.
If required/latest evidence is too large, fail explicitly. Optional references
and excerpts cannot displace protected evidence. No raw tool result is silently
truncated or stored elsewhere by the builder.

| Extension port | Completed return | Default |
| --- | --- | --- |
| MessageCounter.count(messages) | ContextMeasure(units, unit, estimated) | CanonicalCharacterCounter, exact canonical JSON characters |
| ContextBudgeter.select(head, groups, measure=..., max_chars=..., max_units=...) | Ordered unique tuple/list of existing group indexes, including latest | WholeGroupBudgeter, remove oldest groups until both budgets fit |
| ContextSummarizer.summarize(groups, max_chars=...) | ContextSummary(text, group_digests) | Explicit ExcerptContextSummarizer; disabled by default |
| ContextRequestValidator.validate_request(messages, max_chars) | ContextMeasure | BudgetedContextAssembler validates the actual prepared request |

Supply structural Python objects with nonempty stable JSON identity and the
documented synchronous methods; inheritance is optional. Inputs are detached;
proposal bodies, coverage and final budgets are independently validated.
Configuration/method bindings are fixed on builder construction, checked after
calls, and included in its release identity. Construct a new builder for changes.
Async/generator methods, coroutine/context-manager returns and untyped counts
are rejected. Pure components must not call models/tools, access a database or
schedule work. Python extensions are trusted host code, not a sandbox.

UTF8TokenEstimator counts ceil(canonical UTF-8 bytes/4). Its measurement is an
estimate and includes JSON serialization; it is not a model tokenizer, exact
context-window promise, provider usage or monetary cap. Tool descriptors and
provider-added framing are outside this message measurement. Implement
MessageCounter with your explicitly installed tokenizer/model identity for a
closer bound, and leave room for tool/protocol overhead.

```python
from relf_agent import ContextMeasure


class MyCounter:
    identity = {"kind": "my-tokenizer", "model": "chosen-model", "version": "1"}

    def count(self, messages):
        # Inject your tokenizer explicitly. No package downloads/model calls.
        units = my_tokenizer.count_messages(messages)
        return ContextMeasure(units, "my-model-tokens", False)
```

Excerpt summaries retain ordered digests for all omitted groups. Bounded
excerpts may sample only the earliest groups and never imply complete semantic
coverage. The summary is a marked untrusted historical-evidence user message;
it does not become a system instruction, authorization or confirmed business
fact. It never overwrites Sessions, approvals, actions, effect receipts or
execution events. An empty/oversized optional excerpt is omitted and recorded.
Input hard bounds are 4096 messages/1024 groups/256 references/8MiB UTF-8; summary
text is at most 32768 characters. Character and measurement limits are strict
integers, not bool/float/coerced strings.

## Declarative default

Use a versioned RuntimeProfile with this additive component; sync build and
async abuild both support it:

```json
{"context_assembler":{"adapter":"budgeted","config":{
  "counter":"utf8-estimate","max_units":2000,
  "summarizer":"excerpt","summary_max_chars":512,
  "excerpt_chars":128,"max_excerpts":16
}}}
```

Other defaults are counter=canonical-chars, summarizer=none; max_units defaults
to the Agent character limit. Unknown fields/adapters and invalid limits fail
before creating execution storage. Custom ports are assembled through the SDK
or your explicitly registered factory. There is no automatic model summarizer,
hot reload, optional tokenizer import or live configuration migration.

## Explicit scoped artifact storage

```python
from relf_agent import Scope, SQLiteArtifactStore, ArtifactReference

scope = Scope("project", "alice")  # derive from the trusted host
with SQLiteArtifactStore(".ralf/artifacts.sqlite", max_bytes=65536, capacity=128) as artifacts:
    reference = artifacts.put(scope, "tool-results", {"rows": [1, 2, 3]})
    wire = reference.to_dict()
    restored = ArtifactReference.from_dict(wire)
    assert artifacts.get(scope, restored, max_bytes=65536) == {"rows": [1, 2, 3]}
```

ArtifactStore exposes put/get/delete/close; AsyncArtifactStore exposes native
async equivalents and aclose for user adapters. InMemoryArtifactStore and
SQLiteArtifactStore implement the sync port with thread-safe operations. A tool
may use these stores explicitly through InvocationContext.scope. A remote
implementation must enforce the same Scope, immutable reference/content,
bounded reads, atomic duplicate/capacity and completed lifecycle contract.
Redis/PostgreSQL/vector adapters implement other data ports; they are not
ArtifactStore adapters. S3/object storage and automatic thread adapters are
pending.

References bind backend, workspace, principal, namespace, SHA256 content, UTF-8
byte length and finite optional expiry. Identical content/metadata returns the
same reference; changing TTL creates a different reference. JSON values are
serialized once and detached; invalid Unicode/NaN/oversized payloads are refused.
Reads check Scope/backend/expiry/metadata/content and byte limits before
disclosure, with bounded SQLite payload projection and expiry recheck afterward.
The hard per-payload cap is 1MiB; defaults are 1MiB and 1024 retained entries per
Scope/namespace. Configuration may lower either limit; capacity is at most
100000. SQLite uses one fixed resolved file, rejects unsafe aliases/replacement,
serializes capacity and immutable writes with BEGIN IMMEDIATE and synchronous
FULL WAL, and rejects externally uncommitted transactions.

Content/metadata IDs provide integrity, not authentication or enterprise IAM.
A trusted host must establish Scope; do not accept arbitrary caller Scope.
Capacity is per namespace and not a global disk quota. Expired entries remain
until explicit delete; deletion can break historical Run recovery. Deletion
success means the logical entry was removed, not secure erasure/backups cleanup.
No automatic GC, cross-store transaction, model/tool result transformation or
execution-authority ownership is provided. A tool returning references defines
which full data it keeps externally and which result/preview the Action retains.

## Remaining boundaries

dev20 delivered deterministic context defaults and explicit artifacts. dev21
subsequently added opt-in source-grounded extraction, explicit managed model
summaries and registered pure custom Temporal ContextBuilder implementations;
see [managed memory](managed-memory.md) and [Temporal custom context](temporal-custom-context.md).
Automatic in-Run compression/offload, semantic conflict/retraction, remote
artifacts and complete semantic quality remain pending. Temporal shared Session
support remains unsupported. The [dev25 gap audit](remaining-work.md) records the
current boundaries; the [dev20 review](../architecture/reviews/2026-10-07-context-artifacts.md)
preserves that increment's original evidence.


dev54 增加[TextTokenizer／TokenizerMessageCounter](tokenization.md)，用于显式词表计量及同单位输出预留；纯与受管理 context 工厂支持字节基线声明，原字符／UTF8 estimate 默认身份保留。该计量不覆盖供应商 framing 或实际账单。
