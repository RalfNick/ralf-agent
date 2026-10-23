"""Declared Artifact resources reuse owned stores and allocation-free preflight."""

import asyncio
import json

import pytest

import relf_agent as r
from relf_agent.errors import ValidationError
from relf_agent.runtime_config import load_catalog


def declaration(config=None):
    return {
        "role": "artifacts",
        "component_id": "evidence",
        "version": "1",
        "component": {
            "adapter": "scoped-store",
            "config": {
                "version": "1",
                "namespaces": ["evidence"],
                "default_namespace": "evidence",
                "backend": {
                    "adapter": "sqlite",
                    "config": {"path": "evidence.sqlite", "backend_id": "evidence"},
                },
                **(config or {}),
            },
        },
    }


def profile(bindings):
    return r.RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=bindings
    )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("adapter", ["memory", "sqlite", "file"])
def test_declared_default_store_has_borrowed_view_and_owned_lifecycle(
    tmp_path, adapter, asynchronous
):
    config = {"adapter": adapter, "config": {"backend_id": "evidence"}}
    if adapter != "memory":
        config["config"]["path"] = "evidence." + adapter
    declaration_value = declaration({"backend": config})
    selected_profile = profile([declaration_value])
    builder = r.RuntimeBuilder(base_dir=tmp_path)

    async def run():
        runtime = (
            await builder.abuild(selected_profile, tmp_path / "run.sqlite")
            if asynchronous
            else builder.build(selected_profile, tmp_path / "run.sqlite")
        )
        try:
            view, _ = runtime.binding_catalog.resolve(
                "artifacts", r.BindingSelection.ref("evidence", "1"), r.Scope()
            )
            receipt = await view.put(r.Scope(), "evidence", {"value": "data"})
            assert await view.get(r.Scope(), receipt) == {"value": "data"}
            assert view.backend_id == "evidence"
            return view._target._backend
        finally:
            if asynchronous:
                await runtime.aclose()
            else:
                runtime.close()

    backend = asyncio.run(run())
    # Declared original is closed by BuildContext; view itself has no close grant.
    if adapter == "file":
        assert backend._root_fd is None
    else:
        assert backend._closed


@pytest.mark.parametrize(
    "config",
    [
        {"version": ""},
        {"namespaces": []},
        {"namespaces": ["evidence", "evidence"]},
        {"default_namespace": "foreign"},
        {"sync_mode": "auto"},
        {"secret": "unused"},
        {"backend": {"adapter": "missing"}},
    ],
)
def test_invalid_preflight_never_allocates_execution_or_artifact_storage(tmp_path, config):
    selected_profile = profile([declaration(config)])
    with pytest.raises(ValidationError):
        r.RuntimeBuilder(base_dir=tmp_path).build(selected_profile, tmp_path / "run.sqlite")
    assert not (tmp_path / "run.sqlite").exists() and not (tmp_path / "evidence.sqlite").exists()


def test_async_backend_factory_requires_abuild_before_store_creation(tmp_path):
    registry = r.ComponentRegistry()

    async def create(config, context):
        raise AssertionError("sync preflight constructed async client")

    registry.register_async("artifact_store", "remote", create)

    selected_profile = profile([declaration({"backend": {"adapter": "remote"}})])
    with pytest.raises(ValidationError):
        r.RuntimeBuilder(registry).build(selected_profile, tmp_path / "run.sqlite")
    assert not (tmp_path / "run.sqlite").exists()


def test_json_declaration_resolves_existing_nested_factory(tmp_path):
    value = {
        "schema_version": 2,
        "default": {"name": "app", "version": "1"},
        "profiles": [
            {
                "name": "app",
                "version": "1",
                "providers": {"default": {"adapter": "offline-echo"}},
                "binding_components": [declaration()],
            }
        ],
    }
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value))
    selected = load_catalog(path).default
    with r.RuntimeBuilder(base_dir=tmp_path).build(selected, tmp_path / "run.sqlite") as runtime:
        view, _ = runtime.binding_catalog.resolve(
            "artifacts", r.BindingSelection.ref("evidence", "1"), r.Scope()
        )
        assert view.backend_id == "evidence" and view.namespace == "evidence"


def test_native_async_store_replacement_and_owned_rollback(tmp_path):
    allocated = []

    class Remote:
        def __init__(self):
            self.base = r.InMemoryArtifactStore(backend_id="remote")
            self.backend_id, self.identity = self.base.backend_id, self.base.identity
            self.closed = False

        async def put(self, *args, **kwargs):
            await asyncio.sleep(0)
            return self.base.put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            await asyncio.sleep(0)
            return self.base.get(*args, **kwargs)

        async def aclose(self):
            self.closed = True
            self.base.close()

    registry = r.ComponentRegistry()

    async def create(config, context):
        store = Remote()
        allocated.append(store)
        return context.own_async(store)

    registry.register_async("artifact_store", "remote", create)

    async def exercise():
        async def broken(config, context):
            await create(config, context)
            raise ValidationError("remote initialization failed after allocation")

        registry.register_async("artifact_store", "broken", broken)
        selected = profile([declaration({"backend": {"adapter": "remote"}})])
        runtime = await r.RuntimeBuilder(registry).abuild(selected, tmp_path / "good.sqlite")
        view, _ = runtime.binding_catalog.resolve(
            "artifacts", r.BindingSelection.ref("evidence", "1"), r.Scope()
        )
        receipt = await view.put(r.Scope(), "evidence", {"remote": True})
        assert await view.get(r.Scope(), receipt) == {"remote": True}
        assert not allocated[0].closed
        await runtime.aclose()
        assert allocated[0].closed
        # The second factory fails after allocation; original ownership rolls
        # both clients back before returning the build error.
        from relf_agent.errors import RalfError

        with pytest.raises(RalfError):
            failed = declaration({"backend": {"adapter": "broken"}})
            failed["component_id"] = "second"
            await r.RuntimeBuilder(registry).abuild(
                profile(
                    [
                        declaration({"backend": {"adapter": "remote"}}),
                        failed,
                    ]
                ),
                tmp_path / "bad.sqlite",
            )
        assert len(allocated) == 3 and all(store.closed for store in allocated)

    asyncio.run(exercise())
