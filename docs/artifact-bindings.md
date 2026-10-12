# Per-Agent Artifact stores

This feature is under development for dev84; dev83 accepts Artifact stores through a
whole managed Context but does not accept the independent artifacts binding role.
Local integration is implemented and being verified. Temporal and release acceptance
remain pending. It does not complete R01/R18 or the entire Harness roadmap.

Use an independent binding when Agents share summary/context policy while storing large
tool results in different host-approved physical stores or namespaces. The original
Engine/Temporal History retains write intent, receipt verification and result adoption.
The selected view is borrowed and has no close/delete permission.

## SDK

```python
import asyncio
from ralf_agent import (
    AgentBindingDescriptor, AgentDefinition, AgentSpec, ArtifactBindingResource,
    BindingCatalog, BindingSelection, InMemoryArtifactStore, LocalEngine,
    ManagedDataContext, ModelResponse, Scope, SQLiteStore, ToolRegistry,
)

class Model:
    identity = {"kind": "offline-artifact-example", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="ready")

original = InMemoryArtifactStore(backend_id="original-context")
selected = InMemoryArtifactStore(backend_id="team-evidence")
catalog = BindingCatalog(scope=Scope())
catalog.register(
    "artifacts", "evidence", "1",
    ArtifactBindingResource(
        selected, version="1", namespaces=["research", "support"],
        default_namespace="research",
    ),
)
agent = AgentDefinition(
    AgentSpec("researcher", "Answer using evidence"),
    AgentBindingDescriptor(
        artifacts=BindingSelection.ref(
            "evidence", "1", selector={"namespace": "support"},
        ),
    ),
)
try:
    with LocalEngine(
        SQLiteStore("runs.sqlite"), providers={"default": Model()},
        tools=ToolRegistry(), binding_catalog=catalog,
        context_assembler=ManagedDataContext(original),
    ) as engine:
        handle = engine.submit(agent, "hello", command_id="hello")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
finally:
    selected.close()
    original.close()
```

The same descriptors use the existing member paths in BoundDefinition for sequence,
graph, Team, dynamic and nested definitions. Selection only narrows the registered
namespace allowlist; it never changes host Scope, grants a path or selects a model-provided
backend. References retain the original physical backend_id/Scope/namespace.

`inherit` preserves the original Context object and identity. `disabled` removes large
result offload while retaining summaries and reference excerpts. Large raw evidence may
then exceed the model context budget; no store or successful receipt is fabricated.
An explicit selection requires a compatible managed Context and fails before Run creation
otherwise. Summary provider, assembler, limits and excerpt settings remain those of the
selected Context. Custom Context authors implement both pure `artifact_binding_identity`
and `bind_artifacts`; prediction must match the actual managed Context identity.

## Profile declarations

Declare a binding component in the existing schema-version2 Runtime Profile. The original
managed-data Context declaration still supplies summary/projection settings.

```json
{
  "role": "artifacts",
  "component_id": "evidence",
  "version": "1",
  "component": {
    "adapter": "scoped-store",
    "config": {
      "version": "1",
      "namespaces": ["research", "support"],
      "default_namespace": "research",
      "backend": {
        "adapter": "sqlite",
        "config": {"path": "data/evidence.sqlite", "backend_id": "evidence"}
      }
    }
  }
}
```

The nested backend uses the existing `artifact_store` registry. Defaults are `memory`,
`sqlite` and POSIX `file`; custom factories implement completed put/get plus fixed physical
identity. Explicit relative paths resolve against RuntimeBuilder.base_dir. A declaration
owns only resources explicitly recorded by its factory in BuildContext; a factory returning
an injected store borrows it. Failed builds close owned clients in reverse order.

Sync backends default to `sync_mode="thread"` and must be thread-safe. Existing defaults
are thread-safe. `sync_mode="coordinator"` supports thread-affine custom stores on the
caller thread and can block that loop. Neither mode executes lazy sync return values.
Native async stores require `abuild`; pure preflight allocates no connection or execution
store. Native async clients can register their original `aclose` through `own_async`.
Standalone borrowed resources expose `wait_for_calls` to drain their actual sync threads;
Engine calls reuse its original tracker and cannot release the coordinator while active.

JSON values remain bounded to one MiB. Remote Artifact services, binary transfer,
retention/GC/cache, workspace import/export and cross-host ownership are separate roadmap
items. See the [design](superpowers/specs/2026-10-12-artifact-bindings-design.md) and
[remaining capability list](remaining-work.md).
