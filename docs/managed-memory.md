# Automatic memory and managed model summaries

dev21 adds an explicit application pipeline over the existing execution and
memory ports. Business success and memory completion have separate receipts.
Importing the SDK or using a normal LocalEngine does not enable model extraction.

```bash
ralf init my-memory-app --template memory
cd my-memory-app
python -m agent_app
python -m agent_app  # same task, duplicate observations after process restart
```

This installed starter uses an offline provider and rule extraction. Edit its
provider and result fields to fit your application. The previous 17 templates
retain their original contents.

```python
from ralf_agent import (
    AgentSpec,
    LocalEngine,
    MemoryAdmissionPolicy,
    MemoryPipeline,
    ModelMemoryExtractor,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.providers import DeepSeekChatProvider

provider = DeepSeekChatProvider(
    "deepseek-flash",
    max_output_tokens=1024,
    timeout=60,
    json_mode=True,
)  # reads the application's DEEPSEEK_API_KEY; never put a key in source
spec = AgentSpec(
    "preferences",
    "Return observed language and project preferences as JSON.",
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["language", "project"],
        "properties": {"language": {"type": "string"}, "project": {"type": "string"}},
    },
)
policy = MemoryAdmissionPolicy(
    {
        "language": ("result", "language"),
        "project": ("result", "project"),
    }
)
with LocalEngine(
    SQLiteStore(".ralf/runs.sqlite"), providers={"default": provider}, tools=ToolRegistry()
) as engine:
    pipeline = MemoryPipeline(
        engine,
        policy=policy,
        namespace=spec.name,
        extractor=ModelMemoryExtractor(policy),  # omit for deterministic extraction
    )
    result = await pipeline.run(
        spec,
        {"language": "zh-CN", "project": "RALF"},
        command_id="preferences-1",
    )
    print(result["task"]["state"], result["memory"]["status"])
```

Run the async portion inside your application's event loop. The model extractor
uses one tool-free Agent Run with one execution credit. It selects allowlisted
keys; the host takes each value from its configured JSON source path and rejects
fabricated values. The durable extraction Run contains usage and response evidence.
Credits are not currency or token ceilings; configure your Provider's token and
timeout limits separately.

Rule extraction is the default and calls no model. A successful source Run is
captured under the Engine's trusted Scope and rechecked around awaited operations.
Unsuccessful or non-authoritative sources cannot produce observations. Facts carry
source Run, source digest, field path, extraction Run and release digest. They are
marked `source-observation`; an Agent result or tool claim is not proven truth and
cannot confer permissions. Choose paths that your host permits to become memory.

The default namespace is `auto-memory`. Set `namespace=spec.name` to let the
ordinary LocalEngine recall these observations for that Agent, preferably with a
bounded MemoryRecallPolicy. Temporal shared memory recall remains a separate,
unimplemented feature; consolidation can use explicit external memory adapters.

Inject `memory=` to use existing InMemoryMemory, SQLiteMemory, RedisMemory or
PostgresMemory, or your CAS/recall/validate_facts implementation. Initialize and
close remote adapters in the application. Resources are borrowed. Immutable command
bindings live in `<namespace>:commands`; observation keys are derived from source
Run and logical field, leaving curated keys untouched. Reusing a command for
another source/configuration fails. A crash between individual fact writes can
leave partial admission; call `consolidate(source_run_id, command_id=...)` again.
Duplicate current observations keep version 1. Conflicting, expired or unavailable
duplicates fail instead of being recreated. Duplicate lookup is bounded to 32
pages of at most 256 candidates; long-term retention/compaction is still host work.

Model failures are retained as extraction Run failures. `run()` preserves the
successful business result and reports `memory.status=failed`; it does not undo
business effects. `consolidate()` raises a typed error so a service can arrange
recovery explicitly. A successful Run with an empty model selection is valid.
Automatic semantic deduplication, belief revision, retraction and atomic multi-fact
transactions are not implemented.

For model summaries, prepare one managed proposal explicitly:

```python
from ralf_agent import (
    BudgetedContextAssembler,
    FrozenContextSummarizer,
    ManagedModelSummarizer,
)

groups = [[{"role": "assistant", "content": "zh-CN; INC-POOL remains unresolved."}]]
proposal = await ManagedModelSummarizer().summarize(
    engine,
    groups,
    command_id="summary-1",
    max_chars=384,
)
builder = BudgetedContextAssembler(
    summarizer=FrozenContextSummarizer(proposal),
    summary_max_chars=384,
)
```

The summarizer uses a separate one-credit, tool-free managed Run and strict text
schema. The host computes complete assistant/tool group coverage. Frozen summaries
are pure ContextSummarizers: assembly does not access a model or storage. Their
coverage must exactly match the omitted groups; changing history requires explicit
preparation with a new command. The budgeter may omit a summary if it cannot fit
the protected current task and newest group. Text is marked untrusted historical
evidence. Summaries do not rewrite Session, approvals, Actions or effect receipts.
This is explicit preparation, not automatic in-Run model compression. Excerpt
summaries remain the offline option.

Both managed summary and model extraction work with synchronous LocalEngine
controls or asynchronous TemporalEngine controls. Temporal custom context is
registered separately; see [Temporal custom context](temporal-custom-context.md).

## In-Run rule stage

Dev40 additionally provides optional Local native/sequence [managed rule-memory stages](managed-memory-stages.md), selected through host stage_policy bindings. These freeze verified result observations before terminal submission; this explicit MemoryPipeline continues to require an authoritative succeeded Run. Automatic model extraction and advanced/Temporal stage combinations remain pending.
