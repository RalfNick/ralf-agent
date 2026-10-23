# Per-Agent Artifact stores

Dev84 implements independent `artifacts` bindings in Local and Temporal.
Dev83 can use an Artifact store through a whole managed Context, but rejects this
independent role. The examples below require the accepted dev84 subset.
This subset does not complete R01/R18, H1/H3 or the Harness roadmap.

Use this binding when Agents share summary/context policy but store large tool results
in different host-approved physical stores or namespaces. The original Local Engine or
Temporal History owns write intents, read-back verification and result adoption.
The selected view borrows its store and has no close/delete permission.

## Select a Context and an Artifact target independently

`AgentBindingDescriptor.context` selects the summary, assembler, projection and excerpt
policy. `AgentBindingDescriptor.artifacts` then derives a compatible effective Context:

| Artifact selection | Behavior |
| --- | --- |
| `BindingSelection.inherit()` | Preserve the selected Context object and identity, including its original store. |
| `BindingSelection.ref("evidence", "1")` | Use a registered store and its default namespace. `selector={"namespace": "support"}` narrows that choice to an allowed namespace. |
| `BindingSelection.disabled()` | Disable large tool-result offload while retaining history summaries and reference excerpts. No replacement store or successful write receipt is fabricated. |

Explicit `ref` or `disabled` requires a managed Context with both pure binding ports;
an incompatible Context fails before Run acceptance. The standard `ManagedDataContext`
provides these ports. Disabling offload can leave raw tool evidence too large for the
model context budget, in which case the existing budget check can fail the Run.

All six actual Agent compositions use the existing member paths: native, sequence,
graph, Team, dynamic and nested. For a composite, put the same descriptors in
`BoundDefinition.agent_bindings`; the selected namespace and resource stay fixed in
the accepted release and original child calls.

## Run an offline Local example

This example actually offloads a large read-only tool result, then checks that the model
received a reference to the selected SQLite store. The memory store belongs to the
original Context; the two choices remain independent.

```python
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    ArtifactBindingResource,
    BindingCatalog,
    BindingSelection,
    InMemoryArtifactStore,
    LocalEngine,
    ManagedDataContext,
    ModelResponse,
    Scope,
    SQLiteArtifactStore,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)


class Model:
    identity = {"kind": "offline-artifact-example", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [message for message in messages if message["role"] == "tool"]
        if evidence:
            return ModelResponse(output=json.loads(evidence[-1]["content"]))
        return ModelResponse(tool_calls=[ToolCall("lookup", {}, call_id="read")])


def lookup(args, context):
    return "EVIDENCE" * 1600


with TemporaryDirectory() as directory:
    scope = Scope("artifact-demo", "operator")
    original = InMemoryArtifactStore(backend_id="original-context")
    selected = SQLiteArtifactStore(Path(directory) / "evidence.sqlite", backend_id="evidence")
    context = ManagedDataContext(original, scope=scope, tool_result_chars=1024, preview_chars=64)
    catalog = BindingCatalog(scope=scope)
    catalog.register("context", "brief", "1", context)
    catalog.register(
        "artifacts",
        "evidence",
        "1",
        ArtifactBindingResource(
            selected, version="1", namespaces=["research", "support"], default_namespace="research"
        ),
    )
    tools = ToolRegistry()
    tools.register(
        ToolSpec("lookup", "Read evidence", {"type": "object"}, effect="read_only", cost=0), lookup
    )
    agent = AgentDefinition(
        AgentSpec("researcher", "Answer using evidence", tools=["lookup"], max_context_chars=4000),
        AgentBindingDescriptor(
            context=BindingSelection.ref("brief", "1"),
            artifacts=BindingSelection.ref("evidence", "1", selector={"namespace": "support"}),
        ),
    )
    try:
        with LocalEngine(
            SQLiteStore(Path(directory) / "runs.sqlite"),
            scope=scope,
            providers={"default": Model()},
            tools=tools,
            binding_catalog=catalog,
            context_assembler=context,
        ) as engine:
            handle = engine.submit(agent, "read", command_id="read")
            result = asyncio.run(engine.drive(handle.run_id))
            assert result.state == "succeeded", result.error
            reference = result.result["artifact"]
            assert reference["backend_id"] == "evidence" and reference["namespace"] == "support"
    finally:
        selected.close()
        original.close()
```

An offline Provider verifies execution and storage routing; it does not establish model
answer quality. For runnable Profile and custom-store examples, see
[Artifact binding examples](artifact-binding-examples.md).

## Defaults, declarations and ownership

Declare `role="artifacts"`, `adapter="scoped-store"` in the existing Local Profile v2
or Temporal Profile. The nested `backend` uses the existing `artifact_store` registry:

| Store | SDK implementation | Nested adapter and host configuration |
| --- | --- | --- |
| Memory | `InMemoryArtifactStore` | `memory`; omitted `backend` selects memory. Data lasts only for that store instance. |
| SQLite | `SQLiteArtifactStore` | `sqlite`, with an explicit `path` and stable `backend_id`. |
| POSIX file | `FileArtifactStore` | `file`, with an explicit directory `path` and stable `backend_id`; JSON payloads and SQLite receipts. |
| Custom | Completed sync or async `put/get` port | Register an `artifact_store` factory and keep a fixed physical identity. |

The binding configuration requires a nonblank `version`. The default namespace is
`context-results`; an explicit allowlist must contain its `default_namespace`.
Allow at most 256 unique namespaces, each ordinary nonblank UTF-8 text up to 512 bytes
without NUL. The resource behavior version is bounded to 256 UTF-8 bytes. Catalog
registration versions identify the host declaration; keep them explicit as well.

Relative paths resolve against `RuntimeBuilder.base_dir` or `TemporalRuntimeBuilder.base_dir`.
An Artifact file directory is a host storage location, not an Agent Workspace grant.
The trusted Catalog Scope must match the managed Context Scope. The selector accepts
only `namespace`; it cannot choose a path, backend ID, URI or credentials. References
retain the actual backend ID, Scope and namespace. For recovery, preserve the original
paths, physical identities, versions, Context and published release.

SDK-injected stores and Catalog resources are borrowed. A factory calls `context.own`
or `context.own_async` to transfer declared-resource cleanup to the assembly; simply
returning an injected store leaves it borrowed. Partial assembly closes owned resources
in reverse order. Closing one borrowed Agent/Engine does not close the shared store.
The host must drain actual work before closing its borrowed stores.

Sync stores default to `sync_mode="thread"` and must be thread-safe; all three defaults
are. `sync_mode="coordinator"` supports a thread-affine custom store on the caller thread
and can block that loop. Sync methods must return completed values. Native async methods
must both be async and return completed values; their factories require `abuild`, with
the original client/event-loop lifetime retained. Standalone resources expose
`wait_for_calls()` for their actual sync threads; Engine calls use its original tracker.

## Custom Context contract

Implement both synchronous, pure methods when replacing the managed Context:

- `artifact_binding_identity(resource_metadata_or_none)` predicts a bounded ordinary
  JSON dictionary without creating clients, reading/writing storage or calling a model.
- `bind_artifacts(view_or_none)` returns a completed `ManagedContextPipeline` whose
  identity exactly equals that prediction. It preserves original policy and provider
  settings and checks its original Context/resource on use.

The selected metadata is the original `ArtifactView.identity`: exactly `kind`, `version`,
`backend_id`, `target`, `scope` and `namespace`. `kind` is `artifact-binding-view`, version
is the string `"1"`, `target` contains the fixed resource identity, and `scope` contains
the trusted `workspace`/`principal`. `None` means disabled, not inherit. Do not invent a
second resource schema or hide credentials/clients in this metadata.

The predicted Context identity contains an `artifact_binding` dictionary with exactly
`version` (integer `1`), `mode` (`"ref"` or `"disabled"`), `origin` (the original Context
identity) and `resource` (selected metadata or `None`). Temporal requires the same
binding proof, original managed provider and policy identity
in its fixed registration templates. Host publication predicts all approved namespaces
and disabled choices before I/O; History selects only these bounded JSON templates.
The complete Artifact template registration is capped at one MiB. Actual realization
must match before dispatch. A subclass overriding managed projection/summary hooks must
implement its own two binding ports; inheriting the default ports is insufficient.

## Explicit Temporal disabled-only support

When no independent Artifact target is needed, pass `artifact_bindings=True` with an
empty trusted `BindingCatalog` to `TemporalRuntime`. A `TemporalProfile` uses
`execution={"artifact_bindings": True}`; the builder creates its empty scoped Catalog
without allocating an unused store. Configure a compatible managed Context, then use
`artifacts=BindingSelection.disabled()`. Joint5/artifacts1 publishes only the fixed
disabled choices. The flag defaultsFalse and is omitted from legacy Profile identity;
registration of a real Artifact resource still opts in automatically.

Pure binding ports receive detached target metadata. The runtime validates the exact
origin/target/mode proof and preserved policy, pins original receivers/implementations
before invocation and cache reuse, and rejects a custom port that ignores the choice.
An unused Context with custom managed hooks but inherited default binding ports remains
registered without Artifact templates; explicit selection refuses before accepting a Run.
A genuine custom predictor failure is surfaced rather than silently treated as unsupported.
The view checks `max_bytes` before delegation and closes rejected lazy coroutine/generator
returns without executing them. Backend custom equality cannot replace original resources.

## Protocol and acceptance boundary

Explicit Local selection uses `local-bindings-15`. Temporal Artifact registration uses
joint `binding_protocol=5` and `artifacts_binding_protocol=1`, including the original
effective Context proof. Only this joint release advertises the Artifact role and its
namespace selector. Older protocols 1–4 and inherited releases retain their routes
and do not advertise independent Artifact selection.
Dev83 pure admission rejects the new joint release. An actual old83 Worker also refuses
it before scheduling any Activity: History records WorkflowTask failure, without a
queryable RALF Run state.

Evidence currently includes Local focused regressions and real six-composition
SQLite/file routing, plus Temporal pure contracts and twelve actual SQLite/file composition
cases with approval restart, lost write ACK/read-back, accepted-result recovery and History
replay. The integrated 155-test gate also passes independent process crashes, actual
async/cancellation cases and old83 two-way compatibility, including all22 starters.
The sole review findings are fixed; full/fresh-install/frozen-package gates pass.
See the [acceptance record](../architecture/reviews/2026-10-12-artifact-bindings.md).

Worker-crash recovery has a narrow rule: only a new joint-protocol release
with `artifacts=ref` may rebuild a managed Artifact `read` or `verify` whose outcome is
`activity_outcome_unknown` and which never received `allowed` from its original History
dispatch grant. The original durable phase/artifact allows this rebuild once. History
atomically fences the old Action before rebuilding; a late grant for it is denied.
Reads that already received a grant are not retried. Legacy protocols 1–4 keep their
original behavior. Unit contracts and actual SQLite/file Worker-crash recovery pass;
the final installed-service gate also passes.

A lost writer ACK may later be verified from the immutable content and allow a successful
result, while `unknown_remote_execution` still makes the Run nonquiescent. Content
verification is not handler-end proof. Keep the actual-work ownership and capacity until
the original History receives the required end evidence; waiting for a local PID to exit
does not fabricate a History end acknowledgement.

Artifact values remain JSON-only and bounded to one MiB. Remote Artifact services,
binary transfer, retention/GC/cache, workspace import/export, global disk quota and
cross-host ownership need separate contracts and evidence. See the
[design](superpowers/specs/2026-10-12-artifact-bindings-design.md) and
[remaining capability list](remaining-work.md).
