# Artifact binding examples

These examples require dev84, described in the
[Artifact binding guide](artifact-bindings.md); the scoped binding subset is accepted.
Each Python block is standalone. Agent/Profile examples use an offline Provider;
the store-port examples need no model. The Temporal block needs the package's
`temporal` extra dependencies. Profile assembly here does not start a Temporal Service,
connect a client or certify Worker recovery.

## Local Profile with a declared SQLite target

The original managed Context keeps its own memory store and projection settings.
The Artifact declaration owns a separate SQLite store through the default factory.
All paths resolve below `base_dir`; use a persistent host directory instead of the
temporary example directory when recovering accepted Runs.

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    RuntimeBuilder,
    RuntimeProfile,
)

with TemporaryDirectory() as directory:
    profile = RuntimeProfile(
        "artifact-demo",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "context_assembler": {
                "adapter": "managed-data",
                "config": {
                    "artifacts": {"adapter": "memory", "config": {"backend_id": "origin"}},
                    "tool_result_chars": 1024,
                    "preview_chars": 64,
                },
            }
        },
        binding_components=[
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
                            "config": {
                                "path": "data/evidence.sqlite",
                                "backend_id": "evidence",
                            },
                        },
                    },
                },
            }
        ],
    )
    agent = AgentDefinition(
        AgentSpec("researcher", "Reply briefly"),
        AgentBindingDescriptor(
            artifacts=BindingSelection.ref(
                "evidence",
                "1",
                selector={"namespace": "support"},
            )
        ),
    )
    with RuntimeBuilder(base_dir=directory).build(
        profile, Path(directory) / "runs.sqlite"
    ) as runtime:
        handle = runtime.submit(agent, "hello", command_id="hello")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
    assert (Path(directory) / "data/evidence.sqlite").is_file()
```

Use `backend={"adapter": "memory", "config": {"backend_id": "evidence"}}` for an
in-memory target. For POSIX file storage, set `adapter="file"` and
`config={"path": "data/evidence-files", "backend_id": "evidence"}`; `path` is a directory.
Omitting `backend` chooses memory. Neither an empty Profile nor an Artifact declaration
automatically enables managed Context offload: configure a compatible Context explicitly.

## Temporal Profile with a declared file target

The same binding declaration goes into `TemporalProfile`. `abuild` creates only the
declared data resources and the original runtime assembly; it creates no Local execution
database. This block checks publication of the joint protocol and declared file path
without connecting a server.

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from relf_agent import Scope, TemporalProfile, TemporalRuntimeBuilder


async def main():
    with TemporaryDirectory() as directory:
        scope = Scope("artifact-demo", "operator")
        profile = TemporalProfile(
            "artifact-demo",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components={
                "context_assembler": {
                    "adapter": "managed-data",
                    "config": {
                        "artifacts": {"adapter": "memory", "config": {"backend_id": "origin"}},
                        "tool_result_chars": 1024,
                        "preview_chars": 64,
                    },
                }
            },
            binding_components=[
                {
                    "role": "artifacts",
                    "component_id": "evidence",
                    "version": "1",
                    "component": {
                        "adapter": "scoped-store",
                        "config": {
                            "version": "1",
                            "namespaces": ["research"],
                            "default_namespace": "research",
                            "backend": {
                                "adapter": "file",
                                "config": {
                                    "path": "data/evidence-files",
                                    "backend_id": "evidence",
                                },
                            },
                        },
                    },
                }
            ],
        )
        assembly = await TemporalRuntimeBuilder(base_dir=directory).abuild(profile, scope=scope)
        try:
            assert assembly.release["binding_protocol"] == 5
            assert assembly.release["artifacts_binding_protocol"] == 1
        finally:
            await assembly.aclose()
        assert (Path(directory) / "data/evidence-files").is_dir()


asyncio.run(main())
```

To execute Agents, provide the host's Temporal SDK Client and use the original
`assembly.start_worker` / `assembly.create_engine` entry points, then submit the same
`AgentDefinition` selection as the Local example. Follow the
[Temporal Profile guide](temporal-profiles.md) for hosting and drain.
Preserve the accepted Scope, service namespace, queue, Profile, paths and release during
recovery. SQLite/file defaults are local physical stores; selecting them does not copy
payloads between Worker hosts or provide a shared remote Artifact service.

## Replace a sync store without transferring ownership

A structural store supplies a fixed ordinary identity with its actual `backend_id` and
completed `put/get` methods. This wrapper delegates storage to the existing memory default;
it demonstrates the port and borrowing behavior, not a remote storage implementation.

```python
import asyncio
from relf_agent import ArtifactBindingResource, InMemoryArtifactStore, Scope


class CustomSyncStore:
    def __init__(self):
        self.backend_id = "custom-sync"
        self.identity = {"kind": "example-artifacts", "version": "1", "backend_id": self.backend_id}
        self._store = InMemoryArtifactStore(backend_id=self.backend_id)

    def put(self, scope, namespace, value, *, expires_at=None):
        return self._store.put(scope, namespace, value, expires_at=expires_at)

    def get(self, scope, reference, *, max_bytes=None):
        return self._store.get(scope, reference, max_bytes=max_bytes)

    def close(self):
        self._store.close()


async def main():
    store = CustomSyncStore()
    resource = ArtifactBindingResource(store, version="1")
    scope = Scope()
    view = resource.select({}, scope)
    try:
        receipt = await view.put(scope, "context-results", {"value": "ready"})
        assert await view.get(scope, receipt) == {"value": "ready"}
        assert (
            store.put(scope, "context-results", "host still owns this").backend_id
            == store.backend_id
        )
    finally:
        await resource.wait_for_calls()
        store.close()


asyncio.run(main())
```

Sync delegation uses `sync_mode="thread"` by default. For a genuinely thread-affine
store, explicitly use `sync_mode="coordinator"`; it executes on the caller thread and
may block its event loop. The store still must honor original reference and Scope rules.

## Declare a native async store and own its lifecycle

Both methods below are native async. The factory registers cleanup with `own_async`,
so the assembly closes this store after draining its actual work. A factory that returns
an existing injected instance without `own_async` leaves it borrowed.

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from relf_agent import (
    BindingSelection,
    ComponentRegistry,
    InMemoryArtifactStore,
    RuntimeBuilder,
    RuntimeProfile,
    Scope,
)


class CustomAsyncStore:
    def __init__(self):
        self.backend_id = "custom-async"
        self.identity = {"kind": "example-artifacts", "version": "1", "backend_id": self.backend_id}
        self._store = InMemoryArtifactStore(backend_id=self.backend_id)
        self.closed = False

    async def put(self, scope, namespace, value, *, expires_at=None):
        await asyncio.sleep(0)
        return self._store.put(scope, namespace, value, expires_at=expires_at)

    async def get(self, scope, reference, *, max_bytes=None):
        await asyncio.sleep(0)
        return self._store.get(scope, reference, max_bytes=max_bytes)

    async def aclose(self):
        self.closed = True
        self._store.close()


async def main():
    allocated = []
    registry = ComponentRegistry()

    async def create(config, context):
        store = CustomAsyncStore()
        allocated.append(store)
        return context.own_async(store)

    registry.register_async("artifact_store", "custom-async", create)
    profile = RuntimeProfile(
        "async-artifacts",
        "1",
        {"default": {"adapter": "offline-echo"}},
        binding_components=[
            {
                "role": "artifacts",
                "component_id": "evidence",
                "version": "1",
                "component": {
                    "adapter": "scoped-store",
                    "config": {
                        "version": "1",
                        "backend": {"adapter": "custom-async"},
                    },
                },
            }
        ],
    )
    with TemporaryDirectory() as directory:
        runtime = await RuntimeBuilder(registry, base_dir=directory).abuild(
            profile,
            Path(directory) / "runs.sqlite",
        )
        try:
            view, _ = runtime.binding_catalog.resolve(
                "artifacts",
                BindingSelection.ref("evidence", "1"),
                Scope(),
            )
            receipt = await view.put(Scope(), "context-results", {"async": True})
            assert await view.get(Scope(), receipt) == {"async": True}
            assert not allocated[0].closed
        finally:
            await runtime.aclose()
        assert allocated[0].closed


asyncio.run(main())
```

Use `context.own` for a declared sync store with `close`; use the same registry in
`TemporalRuntimeBuilder(registry).abuild` for Temporal declarations. No synchronous
`build` implicitly connects an async store. Store replacements must return the exact
original `ArtifactReference`, fixed backend/Scope/namespace and bounded JSON value.
Mixed sync/async methods, lazy returns and identity/method drift are rejected.
The guide records the independent custom Context contract and acceptance limits.
