"""Real selected Artifact replacement and actual Local handler ownership."""

import asyncio
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

import relf_agent as r
from relf_agent.errors import CoordinatorBusy, NotFound, RalfError
from relf_agent.types import canonical, digest

from .test_artifact_binding_execution import Reader, definition
from .test_review_shutdown import cancel_all_tasks


class NativeAsyncArtifacts:
    """An async replacement with native coroutine storage, without a sync adapter."""

    backend_id = "alpha"
    identity = {"kind": "native-async-artifact-fixture", "version": "1", "backend_id": "alpha"}

    def __init__(self):
        self.values = {}
        self.puts = 0
        self.loops = []

    async def put(self, scope, namespace, value, *, expires_at=None):
        self.loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0)
        metadata = {
            "backend_id": self.backend_id,
            "workspace": scope.workspace,
            "principal": scope.principal,
            "namespace": namespace,
            "content_digest": digest(value),
            "byte_length": len(canonical(value).encode("utf-8")),
            "expires_at": expires_at,
        }
        reference = r.ArtifactReference(**metadata, artifact_id=digest(metadata))
        self.values[reference.artifact_id] = json.loads(canonical(value))
        self.puts += 1
        return reference

    async def get(self, scope, reference, *, max_bytes=None):
        self.loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0)
        if reference.artifact_id not in self.values:
            raise NotFound("Native async artifact has not been written")
        assert (scope.workspace, scope.principal) == (reference.workspace, reference.principal)
        assert reference.namespace == "alpha" and reference.backend_id == self.backend_id
        return json.loads(canonical(self.values[reference.artifact_id]))


def components(scope, target):
    catalog = r.BindingCatalog(scope=scope)
    resource = r.ArtifactBindingResource(
        target, version="1", namespaces=["alpha"], default_namespace="alpha"
    )
    catalog.register("artifacts", "alpha", "1", resource)
    tools, observed = r.ToolRegistry(), []

    def lookup(arguments, context):
        observed.append(context.run_id)
        return "EVIDENCE" * 1600

    tools.register(
        r.ToolSpec("lookup", "Read", {"type": "object"}, effect="read_only", cost=0),
        lookup,
    )
    original = r.InMemoryArtifactStore(backend_id="original")
    context = r.ManagedDataContext(original, scope=scope, tool_result_chars=1024, preview_chars=64)
    return catalog, resource, tools, context, observed


def local(path, scope, catalog, tools, context):
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": Reader()},
        tools=tools,
        scope=scope,
        binding_catalog=catalog,
        context_assembler=context,
    )


def test_local_native_async_replacement_uses_selected_receipt_and_completed_readback(tmp_path):
    scope = r.Scope("artifact-native-async", uuid.uuid4().hex)
    target = NativeAsyncArtifacts()
    catalog, resource, tools, context, observed = components(scope, target)

    async def run(runtime):
        handle = runtime.submit(definition("agent"), "read", command_id="s")
        done = await runtime.drive(handle.run_id)
        assert done.state == "succeeded", done.error
        record = runtime.context_artifacts(handle.run_id)[0]
        assert record["status"] == "verified"
        reference = r.ArtifactReference.from_dict(record["intent"]["reference"])
        assert reference.backend_id == reference.namespace == "alpha"
        assert (reference.workspace, reference.principal) == (scope.workspace, scope.principal)
        assert json.loads(await target.get(scope, reference)) == "EVIDENCE" * 1600
        assert observed == [handle.run_id] and target.puts == 1
        assert all(loop is asyncio.get_running_loop() for loop in target.loops)
        assert not resource._threads.has_active and not runtime._threads.has_active

    try:
        with local(tmp_path / "runs.sqlite", scope, catalog, tools, context) as runtime:
            asyncio.run(run(runtime))
        # Resource injection is borrowed; closing the Engine does not close the async port.
        receipt = asyncio.run(target.put(scope, "alpha", "still available"))
        assert asyncio.run(target.get(scope, receipt)) == "still available"
    finally:
        context.artifacts.close()


@pytest.mark.parametrize("operation", ["put", "get"])
def test_global_loop_cancel_keeps_selected_sync_handler_and_coordinator_owned(tmp_path, operation):
    started, release, finished = (threading.Event() for _ in range(3))

    class Held(r.InMemoryArtifactStore):
        def hold(self):
            started.set()
            try:
                assert release.wait(10)
            finally:
                finished.set()

        def put(self, *args, **kwargs):
            if operation == "put":
                self.hold()
            return super().put(*args, **kwargs)

        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            if operation == "get":
                self.hold()
            return value

    scope = r.Scope("artifact-global-cancel", uuid.uuid4().hex)
    target = Held(backend_id="alpha")
    catalog, _, tools, context, observed = components(scope, target)
    path = tmp_path / "runs.sqlite"
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.new_event_loop()
    loop.set_default_executor(executor)
    runtime = local(path, scope, catalog, tools, context)
    handle = runtime.submit(definition("agent"), "read", command_id="s")

    async def begin():
        asyncio.create_task(runtime.drive(handle.run_id))
        assert await asyncio.to_thread(started.wait, 3)

    try:
        loop.run_until_complete(begin())
        cancel_all_tasks(loop)
        loop.close()
        assert not finished.is_set() and runtime._threads.has_active_for(handle.run_id)
        with pytest.raises(RalfError):
            runtime.close()
        with r.SQLiteStore(path) as contender:
            with pytest.raises(CoordinatorBusy):
                r.LocalEngine(contender, providers={}, tools=r.ToolRegistry(), scope=scope)

        async def finish():
            waiting = asyncio.create_task(runtime.wait_for_threads())
            await asyncio.sleep(0)
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert not finished.is_set() and runtime._threads.has_active_for(handle.run_id)
            release.set()
            await runtime.wait_for_threads()

        asyncio.run(finish())
        executor.shutdown(wait=True)
        assert finished.is_set() and not runtime._threads.has_active
        assert observed == [handle.run_id]
        runtime.close()
        with local(path, scope, catalog, tools, context) as restored:
            assert restored.status(handle.run_id).state in {"cancelled", "cancelling"}
        target.put(scope, "alpha", "borrowed backend remains available")
    finally:
        release.set()
        executor.shutdown(wait=True)
        if not loop.is_closed():
            cancel_all_tasks(loop)
            loop.close()
        asyncio.run(runtime.wait_for_threads())
        runtime.close()
        target.close()
        context.artifacts.close()
