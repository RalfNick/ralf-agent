"""Selected physical Artifact stores retain original Local adoption authority."""

import asyncio
import gc
import json
import weakref

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError

from .test_workspace_binding_execution import definition as workspace_definition
from .test_workspace_binding_execution import finish


class Reader:
    identity = {"kind": "artifact-binding-reader", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [m for m in messages if m["role"] == "tool"]
        if evidence:
            return r.ModelResponse(output={"evidence": json.loads(evidence[-1]["content"])})
        return r.ModelResponse(tool_calls=[r.ToolCall("lookup", {}, call_id="read")])


def definition(kind, mode="ref"):
    value = workspace_definition(kind).to_dict()

    def patch(agent):
        agent["tools"] = ["lookup"]
        agent["max_context_chars"] = 4000

    def walk(value):
        if isinstance(value, dict):
            if value.get("kind") == "agent" or {"name", "instructions", "tools"} <= set(value):
                patch(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(value)
    bindings = [value["bindings"]] if kind == "agent" else value["agent_bindings"].values()
    for binding in bindings:
        name = binding["workspace"]["component_id"]
        binding["workspace"] = r.BindingSelection.inherit().to_dict()
        binding["artifacts"] = (
            r.BindingSelection.ref(name, "1", selector={"namespace": name}).to_dict()
            if mode == "ref"
            else r.BindingSelection.disabled().to_dict()
        )
    from relf_agent.binding_definitions import decode_definition

    return decode_definition(value)


def host(tmp_path, backend_kind="sqlite"):
    catalog, backends, observed = r.BindingCatalog(scope=r.Scope()), {}, []
    for name in ("alpha", "beta"):
        cls = r.SQLiteArtifactStore if backend_kind == "sqlite" else r.FileArtifactStore
        backends[name] = cls(tmp_path / (name + ".artifacts"), backend_id=name)
        catalog.register(
            "artifacts",
            name,
            "1",
            r.ArtifactBindingResource(
                backends[name], version="1", namespaces=[name], default_namespace=name
            ),
        )
    tools = r.ToolRegistry()

    def lookup(args, context):
        observed.append(context.run_id)
        return "EVIDENCE" * 1600

    tools.register(
        r.ToolSpec(
            "lookup",
            "Read evidence",
            {"type": "object"},
            requires_approval=True,
            effect="read_only",
            cost=0,
        ),
        lookup,
    )
    original = r.InMemoryArtifactStore(backend_id="original")
    context = r.ManagedDataContext(original, tool_result_chars=1024, preview_chars=64)
    return catalog, backends, tools, context, observed


def engine(path, catalog, tools, context):
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": Reader()},
        tools=tools,
        binding_catalog=catalog,
        context_assembler=context,
    )


def references(runtime, run_id):
    root = runtime.store.run(run_id)
    values = list(root.get("context_artifacts", {}).values())
    for node in root.get("workflow", {}).get("nodes", {}).values():
        values.extend(node.get("execution", {}).get("context_artifacts", {}).values())
    for child in (runtime.diagnostics(run_id).workflow or {}).get("children", []):
        values.extend(references(runtime, child["run_id"]))
    return values


@pytest.mark.parametrize("backend_kind", ["sqlite", "file"])
@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_six_compositions_offload_into_selected_physical_namespaces(
    tmp_path, kind, backend_kind
):
    catalog, backends, tools, context, observed = host(tmp_path, backend_kind)
    try:
        with engine(tmp_path / "runs.sqlite", catalog, tools, context) as runtime:
            handle = runtime.submit(definition(kind), "read", command_id="submit", budget=32)
            done = asyncio.run(finish(runtime, handle.run_id))
            assert done.state == "succeeded", done.error
            stored = references(runtime, handle.run_id)
            assert len(stored) == (1 if kind == "agent" else 2)
            assert sorted(v["intent"]["reference"]["backend_id"] for v in stored) == (
                ["alpha"] if kind == "agent" else ["alpha", "beta"]
            )
            for item in stored:
                raw = item["intent"]["reference"]
                assert raw["namespace"] == raw["backend_id"] and item["status"] == "verified"
                assert (
                    json.loads(
                        backends[raw["backend_id"]].get(
                            r.Scope(), r.ArtifactReference.from_dict(raw)
                        )
                    )
                    == "EVIDENCE" * 1600
                )
            assert runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-15"
        assert len(observed) == (1 if kind == "agent" else 2)
        # Catalog targets are borrowed and usable after closing the Engine.
        backends["alpha"].put(r.Scope(), "alpha", "still borrowed")
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_disabled_offload_is_explicit_and_does_not_write_original_store(tmp_path):
    catalog, backends, tools, context, observed = host(tmp_path)
    try:
        with engine(tmp_path / "disabled.sqlite", catalog, tools, context) as runtime:
            handle = runtime.submit(definition("agent", "disabled"), "read", command_id="s")
            run = runtime.store.run(handle.run_id)
            selected = runtime._components(run).context
            assert selected is not context and not hasattr(selected, "artifacts")
            assert selected.mode == context.mode
            # Oversize raw evidence cannot fit after disabling projection; original tool
            # executes once and no fake artifact receipt is produced.
            done = asyncio.run(finish(runtime, handle.run_id))
            assert done.state == "failed" and observed == [handle.run_id]
            assert not references(runtime, handle.run_id)
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_derived_context_is_stable_during_phase_and_weak_after_use(tmp_path):
    catalog, backends, tools, context, _ = host(tmp_path)
    try:
        with engine(tmp_path / "cache.sqlite", catalog, tools, context) as runtime:
            handle = runtime.submit(definition("agent"), "read", command_id="s")
            run = runtime.store.run(handle.run_id)
            first = runtime._components(run).context
            assert runtime._components(run).context is first
            reference = weakref.ref(first)
            del first
            gc.collect()
            assert reference() is None
            assert runtime._components(run).context.identity["artifact_binding"]["mode"] == "ref"
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_approval_restart_adopts_original_artifact_receipts_without_reexecution(tmp_path):
    catalog, backends, tools, context, observed = host(tmp_path)
    path = tmp_path / "restart.sqlite"
    try:
        with engine(path, catalog, tools, context) as runtime:
            handle = runtime.submit(definition("agent"), "read", command_id="s")
            waiting = asyncio.run(runtime.drive(handle.run_id))
            assert waiting.state == "waiting_approval" and not observed
        with engine(path, catalog, tools, context) as runtime:
            done = asyncio.run(finish(runtime, handle.run_id))
            assert done.state == "succeeded", done.error
            manifest = runtime.diagnostics(handle.run_id).manifest
        with engine(path, catalog, tools, context) as runtime:
            assert asyncio.run(runtime.drive(handle.run_id)) == done
            assert runtime.diagnostics(handle.run_id).manifest == manifest
            assert len(references(runtime, handle.run_id)) == 1
        assert observed == [handle.run_id]
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_missing_original_or_denied_namespace_refuses_before_run(tmp_path):
    catalog, backends, tools, context, observed = host(tmp_path)
    try:
        with engine(tmp_path / "denied.sqlite", catalog, tools, context) as runtime:
            wrapped = definition("agent").to_dict()
            wrapped["bindings"]["artifacts"]["selector"] = {"namespace": "beta"}
            from relf_agent.binding_definitions import decode_definition

            with pytest.raises(AuthorizationDenied):
                runtime.submit(decode_definition(wrapped), "read", command_id="s")
            catalog.unregister("artifacts", "alpha", "1")
            with pytest.raises(DefinitionMismatch):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            assert not observed
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


@pytest.mark.parametrize("backend_kind", ["sqlite", "file"])
@pytest.mark.parametrize(
    "event", ["context_artifact_intent", "context_artifact_dispatched", "context_artifact_verified"]
)
def test_selected_receipt_crash_recovers_without_repeating_tool(tmp_path, backend_kind, event):
    from .test_managed_data_context import crash_after_committed_event

    class Crash(BaseException):
        pass

    catalog, backends, tools, context, observed = host(tmp_path, backend_kind)
    path = tmp_path / "crash.sqlite"
    try:
        runtime = engine(path, catalog, tools, context)
        handle = runtime.submit(definition("agent"), "read", command_id="s")
        pending = asyncio.run(runtime.drive(handle.run_id)).pending[0]
        runtime.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="a")

        def lost_ack(run):
            if event == "context_artifact_dispatched":
                record = next(iter(run["context_artifacts"].values()))
                backends["alpha"].put(r.Scope(), "alpha", record["value"])

        crash_after_committed_event(runtime, event, Crash, lost_ack)
        try:
            with pytest.raises(Crash):
                asyncio.run(runtime.drive(handle.run_id))
        finally:
            runtime.close()
        with engine(path, catalog, tools, context) as restored:
            done = asyncio.run(restored.drive(handle.run_id))
            assert done.state == "succeeded", done.error
            assert observed == [handle.run_id]
            assert references(restored, handle.run_id)[0]["status"] == "verified"
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_binding_context_cannot_silently_ignore_explicit_selection(tmp_path):
    catalog, backends, tools, context, observed = host(tmp_path)
    try:
        with engine(
            tmp_path / "unsupported.sqlite", catalog, tools, r.ContextAssembler()
        ) as runtime:
            with pytest.raises(RalfError):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert (
                not observed
                and runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            )
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_custom_context_prediction_mismatch_is_rejected_before_run(tmp_path):
    class Wrong(r.ManagedDataContext):
        def artifact_binding_identity(self, metadata):
            return {"kind": "custom-claim", "version": "1"}

        def bind_artifacts(self, target):
            return self

    catalog, backends, tools, context, observed = host(tmp_path)
    original = Wrong(context.artifacts)
    try:
        with engine(tmp_path / "wrong.sqlite", catalog, tools, original) as runtime:
            with pytest.raises(DefinitionMismatch):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert (
                not observed
                and runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            )
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_cancelled_selected_sync_put_keeps_coordinator_until_real_thread_end(tmp_path):
    import threading

    class Blocked(r.InMemoryArtifactStore):
        def put(self, *args, **kwargs):
            self.entered.set()
            assert self.release.wait(5)
            return super().put(*args, **kwargs)

    catalog, backends, tools, context, observed = host(tmp_path)
    target = Blocked(backend_id="alpha")
    target.entered, target.release = threading.Event(), threading.Event()
    catalog.unregister("artifacts", "alpha", "1")
    catalog.register(
        "artifacts",
        "alpha",
        "1",
        r.ArtifactBindingResource(
            target, version="1", namespaces=["alpha"], default_namespace="alpha"
        ),
    )
    path = tmp_path / "cancel.sqlite"

    async def exercise():
        runtime = engine(path, catalog, tools, context)
        handle = runtime.submit(definition("agent"), "read", command_id="s")
        pending = (await runtime.drive(handle.run_id)).pending[0]
        runtime.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="a")
        drive = asyncio.create_task(runtime.drive(handle.run_id))
        try:
            assert await asyncio.to_thread(target.entered.wait, 2)
            drive.cancel()
            await asyncio.gather(drive, return_exceptions=True)
            assert runtime._threads.has_active_for(handle.run_id)
            with pytest.raises(RalfError):
                runtime.close()
        finally:
            target.release.set()
            await runtime._threads.drain(handle.run_id)
            await asyncio.gather(*tuple(runtime._inflight.values()), return_exceptions=True)
            await runtime.wait_for_threads()
            await asyncio.sleep(0)
            runtime.close()
        with engine(path, catalog, tools, context) as restored:
            assert restored.status(handle.run_id).state in {"cancelled", "cancelling"}

    try:
        asyncio.run(exercise())
    finally:
        target.release.set()
        target.close()
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_custom_port_cannot_return_unmanaged_context_with_matching_identity(tmp_path):
    class Unmanaged(r.ContextAssembler):
        identity = {"kind": "fake-managed", "version": "1"}

    class Custom(r.ManagedDataContext):
        def artifact_binding_identity(self, metadata):
            return Unmanaged.identity

        def bind_artifacts(self, target):
            return Unmanaged()

    catalog, backends, tools, context, _ = host(tmp_path)
    try:
        with engine(
            tmp_path / "unmanaged.sqlite", catalog, tools, Custom(context.artifacts)
        ) as runtime:
            with pytest.raises(RalfError):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()
