"""Deployment admission configuration does not change per-Run policy contracts."""

import asyncio
import importlib
import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import FrozenInstanceError

import pytest

import ralf_agent as r
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.governance import LocalExecutionPolicy, TemporalExecutionPolicy
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.runtime_config import RuntimeCatalog, RuntimeProfile, load_catalog
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.types import canonical


def policy_type():
    return importlib.import_module("ralf_agent.governance").DeploymentAdmissionPolicy


def profile(config=None, *, adapter="bounded", provider="offline-echo", version="1"):
    return RuntimeProfile(
        "assistant",
        version,
        {"default": {"adapter": provider}},
        {
            "admission_policy": {
                "adapter": adapter,
                "config": {"deployment_id": "business"} if config is None else config,
            }
        },
    )


def declaration(selected):
    return {
        "name": selected.name,
        "version": selected.version,
        "providers": selected.providers,
        "components": selected.components,
    }


def test_portable_admission_policy_identity_is_immutable_and_distinct_from_execution_policy():
    policy = policy_type()(
        "business", version="capacity-1", max_active_root_runs=4, max_active_root_runs_per_scope=2
    )
    assert policy.identity == {
        "kind": "deployment-admission-policy",
        "deployment_id": "business",
        "version": "capacity-1",
        "max_active_root_runs": 4,
        "max_active_root_runs_per_scope": 2,
    }
    assert policy_type().from_identity(policy.identity) == policy
    detached = policy.identity
    detached["max_active_root_runs"] = 100
    assert policy.max_active_root_runs == 4
    with pytest.raises(FrozenInstanceError):
        policy.max_active_root_runs = 100
    assert LocalExecutionPolicy().identity == {
        "kind": "local-execution-policy",
        "version": "1",
        "run_timeout_seconds": None,
        "approval_timeout_seconds": None,
    }
    assert TemporalExecutionPolicy().identity == {
        "kind": "temporal-execution-policy",
        "version": "1",
        "max_children": 256,
        "max_concurrency": 32,
        "max_depth": 8,
        "run_timeout_seconds": None,
        "approval_timeout_seconds": None,
        "allowed_tools": None,
    }


@pytest.mark.parametrize(
    "identity",
    [
        None,
        {},
        LocalExecutionPolicy().identity,
        TemporalExecutionPolicy().identity,
        {"kind": "deployment-admission-policy", "deployment_id": "business", "extra": 1},
    ],
)
def test_admission_policy_rejects_wrong_or_unknown_identity(identity):
    with pytest.raises(ValidationError):
        policy_type().from_identity(identity)


def test_default_profile_and_unconfigured_store_keep_original_bytes_and_schema(tmp_path):
    selected = RuntimeProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    assert (
        canonical(declaration(selected))
        == '{"components":{},"name":"assistant","providers":{"default":{"adapter":"offline-echo","config":{}}},"version":"1"}'
    )
    assert (
        selected.identity["digest"]
        == "0ce02f668d161c2059d1f5fc37b668d93b97370294993bdc1baee566b58ce4c7"
    )
    with r.RuntimeBuilder().build(selected, tmp_path / "default.sqlite") as runtime:
        handle = runtime.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        run = runtime.store.run(handle.run_id)
        assert "local_admission" not in run
        assert "admission_policy" not in run["manifest"]
        assert "local_admission_protocol" not in run["manifest"]
        assert (
            runtime.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "1"
        )
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


@pytest.mark.parametrize(
    "config",
    [
        {"deployment_id": "business"},
        {
            "deployment_id": "business",
            "version": "capacity-1",
            "max_active_root_runs": 4,
            "max_active_root_runs_per_scope": 2,
        },
        {
            "deployment_id": "business",
            "max_active_root_runs": 10000,
            "max_active_root_runs_per_scope": 10000,
        },
    ],
)
def test_sdk_and_builtin_profile_activate_and_pin_same_admission_policy(tmp_path, config):
    expected = policy_type()(**config)
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "sdk.sqlite"),
        providers={"default": EchoProvider("sdk")},
        tools=r.ToolRegistry(),
        admission_policy=expected,
    ) as engine:
        assert engine.store.local_capacity_policy() == expected.identity
        handle = engine.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert engine.diagnostics(handle.run_id).manifest["admission_policy"] == expected.identity
        assert engine.diagnostics(handle.run_id).manifest["local_admission_protocol"] == 1
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
    selected = profile(config)
    with r.RuntimeBuilder().build(selected, tmp_path / "profile.sqlite") as runtime:
        assert runtime.store.local_capacity_policy() == expected.identity
        handle = runtime.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
        assert runtime.diagnostics(handle.run_id).manifest["admission_policy"] == expected.identity
        assert runtime.diagnostics(handle.run_id).manifest["runtime_profile"] == selected.identity
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_declaration_is_detached_and_catalog_keeps_original_admission_policy():
    config = {"deployment_id": "business", "max_active_root_runs": 4}
    selected = profile(config)
    original = selected.identity
    config["max_active_root_runs"] = 8
    selected.components["admission_policy"]["config"]["deployment_id"] = "replacement"
    assert selected.identity == original
    assert selected.components["admission_policy"]["config"] == {
        "deployment_id": "business",
        "max_active_root_runs": 4,
    }
    catalog = RuntimeCatalog()
    catalog.register(selected, default=True)
    catalog.register(
        profile({"deployment_id": "business", "max_active_root_runs": 8}, version="2"), default=True
    )
    assert catalog.resolve(original).identity == original
    with pytest.raises(DefinitionMismatch):
        catalog.register(profile({"deployment_id": "replacement"}))


def test_json_and_toml_pin_same_admission_policy(tmp_path):
    selected = profile(
        {
            "deployment_id": "business",
            "version": "capacity-1",
            "max_active_root_runs": 4,
            "max_active_root_runs_per_scope": 2,
        }
    )
    json_path, toml_path = tmp_path / "policy.json", tmp_path / "policy.toml"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": "assistant", "version": "1"},
                "profiles": [declaration(selected)],
            }
        )
    )
    toml_path.write_text("""schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.admission_policy]
adapter = "bounded"
[profiles.components.admission_policy.config]
deployment_id = "business"
version = "capacity-1"
max_active_root_runs = 4
max_active_root_runs_per_scope = 2
""")
    for index, path in enumerate((json_path, toml_path)):
        catalog = load_catalog(path)
        assert catalog.default.identity == selected.identity
        with r.RuntimeBuilder(base_dir=catalog.base_dir).build(
            catalog.default, tmp_path / f"catalog-{index}.sqlite"
        ) as runtime:
            assert (
                runtime.store.local_capacity_policy()
                == policy_type()(**selected.components["admission_policy"]["config"]).identity
            )


INVALID_CONFIGS = [
    {},
    {"deployment_id": ""},
    {"deployment_id": 1},
    {"deployment_id": "business", "version": ""},
    {"deployment_id": "business", "max_active_root_runs": True},
    {"deployment_id": "business", "max_active_root_runs": 0},
    {"deployment_id": "business", "max_active_root_runs": 10001},
    {"deployment_id": "business", "max_active_root_runs": 1.0},
    {"deployment_id": "business", "max_active_root_runs_per_scope": False},
    {"deployment_id": "business", "max_active_root_runs_per_scope": 0},
    {"deployment_id": "business", "max_active_root_runs_per_scope": float("nan")},
    {"deployment_id": "business", "max_active_root_runs_per_scope": float("inf")},
    {"deployment_id": "business", "max_active_root_runs": 2, "max_active_root_runs_per_scope": 3},
    {"deployment_id": "business", "kind": "deployment-admission-policy"},
    {"deployment_id": "business", "run_timeout_seconds": 30},
]


@pytest.mark.parametrize("config", INVALID_CONFIGS)
@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
def test_invalid_admission_configuration_is_refused_before_store_or_provider_io(
    tmp_path, config, async_build
):
    events = []
    registry = r.ComponentRegistry()
    registry.register("provider", "observed", lambda config, context: events.append("provider-io"))
    builder = r.RuntimeBuilder(registry, store_factory=lambda path: events.append("store-io"))
    with pytest.raises(ValidationError):
        selected = profile(config, provider="observed")
        if async_build:
            asyncio.run(builder.abuild(selected, tmp_path / "absent.sqlite"))
        else:
            builder.build(selected, tmp_path / "absent.sqlite")
    assert events == []
    assert not (tmp_path / "absent.sqlite").exists()


@pytest.mark.parametrize("async_factory", [False, True], ids=["sync-factory", "async-factory"])
def test_custom_admission_policy_replacement_and_owned_client_lifecycle(tmp_path, async_factory):
    expected = policy_type()("business", version="business-1", max_active_root_runs=2)
    events = []

    class Client:
        async def aclose(self):
            events.append("close-started")
            await asyncio.sleep(0)
            events.append("close-finished")

    def provider(config, context):
        context.own_async(Client())
        events.append("provider-created")
        return EchoProvider("owned")

    def validate(config):
        assert config == {"tier": "interactive"}
        events.append("preflight")

    def custom(config, context):
        assert config == {"tier": "interactive"}
        assert context.store is not None
        events.append("policy-created")
        return expected

    registry = r.ComponentRegistry()
    registry.register("provider", "owned", provider)
    if async_factory:

        async def asynchronous(config, context):
            await asyncio.sleep(0)
            return custom(config, context)

        registry.register_async("admission_policy", "business", asynchronous, validator=validate)
    else:
        registry.register("admission_policy", "business", custom, validator=validate)

    async def scenario():
        runtime = await r.RuntimeBuilder(registry).abuild(
            profile({"tier": "interactive"}, adapter="business", provider="owned"),
            tmp_path / "custom.sqlite",
        )
        try:
            assert runtime.store.local_capacity_policy() == expected.identity
            assert events == ["preflight", "provider-created", "policy-created"]
        finally:
            await runtime.aclose()
        assert events[-2:] == ["close-started", "close-finished"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "result_kind",
    [
        "none",
        "identity-dict",
        "awaitable",
        "context-manager",
        "async-context-manager",
        "execution-policy",
        "subclass",
    ],
)
@pytest.mark.parametrize("async_factory", [False, True], ids=["sync-factory", "async-factory"])
def test_invalid_custom_admission_result_rolls_back_owned_assembly(
    tmp_path, result_kind, async_factory
):
    events, coroutines = [], []

    class Client:
        async def aclose(self):
            events.append("close-started")
            await asyncio.sleep(0)
            events.append("close-finished")

    def provider(config, context):
        context.own_async(Client())
        events.append("provider-created")
        return EchoProvider("owned")

    async def lazy():
        events.append("unexpected-policy-execution")
        return policy_type()("business")

    @contextmanager
    def context_value():
        events.append("unexpected-policy-execution")
        yield policy_type()("business")

    @asynccontextmanager
    async def async_context_value():
        events.append("unexpected-policy-execution")
        yield policy_type()("business")

    def factory(config, context):
        events.append("policy-created")
        if result_kind == "none":
            return None
        if result_kind == "identity-dict":
            return {"kind": "deployment-admission-policy", "deployment_id": "business"}
        if result_kind == "execution-policy":
            return LocalExecutionPolicy()
        if result_kind == "context-manager":
            return context_value()
        if result_kind == "async-context-manager":
            return async_context_value()
        if result_kind == "subclass":

            class Subclass(policy_type()):
                pass

            return Subclass("business")
        value = lazy()
        coroutines.append(value)
        return value

    registry = r.ComponentRegistry()
    registry.register("provider", "owned", provider)
    if async_factory:

        async def asynchronous(config, context):
            await asyncio.sleep(0)
            return factory(config, context)

        registry.register_async("admission_policy", "invalid-result", asynchronous)
    else:
        registry.register("admission_policy", "invalid-result", factory)

    async def scenario():
        runtime = None
        path = tmp_path / "invalid.sqlite"
        try:
            with pytest.raises(ValidationError):
                runtime = await r.RuntimeBuilder(registry).abuild(
                    profile(adapter="invalid-result", provider="owned"), path
                )
            assert events == [
                "provider-created",
                "policy-created",
                "close-started",
                "close-finished",
            ]
            assert all(value.cr_frame is None for value in coroutines)
            with r.SQLiteStore(path) as store:
                coordinator = store.create_coordinator()
                coordinator.acquire()
                coordinator.release()
        finally:
            if runtime is not None:
                await runtime.aclose()

    asyncio.run(scenario())


def test_explicit_policy_with_legacy_store_refuses_and_closes_owned_resources(tmp_path):
    events = []

    class LegacyStore:
        local_admission_version = None

        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            if name.startswith("local_capacity_") or name == "prepare_local_capacity":
                raise AttributeError(name)
            return getattr(self.inner, name)

    class Client:
        def close(self):
            events.append("client-closed")

    def provider(config, context):
        context.own(Client())
        return EchoProvider("owned")

    registry = r.ComponentRegistry()
    registry.register("provider", "owned", provider)
    path = tmp_path / "legacy.sqlite"
    with pytest.raises(ValidationError):
        r.RuntimeBuilder(
            registry, store_factory=lambda path: LegacyStore(r.SQLiteStore(path))
        ).build(profile(provider="owned"), path)
    assert events == ["client-closed"]
    with r.SQLiteStore(path) as store:
        coordinator = store.create_coordinator()
        coordinator.acquire()
        coordinator.release()


@pytest.mark.parametrize("adapter", ["bounded", "custom"])
def test_temporal_dual_admission_sources_refuse_before_any_component_io(tmp_path, adapter):
    events = []
    registry = r.ComponentRegistry()
    registry.register("provider", "observed", lambda config, context: events.append("provider-io"))
    if adapter == "custom":
        registry.register(
            "admission_policy", "custom", lambda config, context: events.append("policy-io")
        )

    async def scenario():
        with pytest.raises(ValidationError):
            selected = r.TemporalProfile(
                "assistant",
                "1",
                {"default": {"adapter": "observed"}},
                {"admission_policy": {"adapter": adapter, "config": {"deployment_id": "business"}}},
            )
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                selected, admission_policy=policy_type()("host")
            )
        assert events == [] and not any(tmp_path.iterdir())

    asyncio.run(scenario())


@pytest.mark.parametrize("adapter", ["bounded", "custom"])
def test_temporal_admission_declaration_publishes_and_closes_unused_assembly(tmp_path, adapter):
    events = []
    config = {"deployment_id": "business", "max_active_root_runs": 2}
    expected = policy_type()(**config)
    registry = r.ComponentRegistry()

    class OwnedClient:
        async def aclose(self):
            await asyncio.sleep(0)
            events.append("client-closed")

    def provider(config, context):
        events.append("provider-created")
        context.own_async(OwnedClient())
        return EchoProvider("temporal")

    def policy(declaration, context):
        assert declaration == config
        events.append("policy-created")
        return expected

    registry.register("provider", "observed", provider)
    if adapter == "custom":
        registry.register("admission_policy", "custom", policy)
    selected = r.TemporalProfile(
        "assistant",
        "1",
        {"default": {"adapter": "observed"}},
        {"admission_policy": {"adapter": adapter, "config": config}},
    )
    original_profile = canonical(selected.identity)

    async def scenario():
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(selected)
        try:
            publication = assembly.release["deployment_admission_protocol"]
            assert publication["version"] == 2 and publication["policy"] == expected.identity
            assert canonical(assembly.release["runtime_profile"]) == original_profile
            assert canonical(selected.identity) == original_profile
            assert events == ["provider-created"] + (
                ["policy-created"] if adapter == "custom" else []
            )
            assert assembly._client is assembly._worker is None and assembly._engines == []
        finally:
            await assembly.aclose()
        assert assembly._closed and assembly._context._resources == []
        assert events[-1] == "client-closed"
        assert canonical(selected.identity) == original_profile
        assert not any(tmp_path.iterdir())

    asyncio.run(scenario())


@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
def test_host_admission_policy_restores_original_profile_without_rewriting_legacy_release(
    tmp_path, async_build
):
    selected = RuntimeProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    original_profile = selected.identity
    path = tmp_path / "legacy-profile.sqlite"
    spec = r.AgentSpec("a", "Answer")
    with r.RuntimeBuilder().build(selected, path) as original:
        handle = original.submit(spec, "original task", command_id="original-submit")
        original_run = original.store.run(handle.run_id)
    expected = policy_type()("business", max_active_root_runs=1)

    async def scenario():
        builder = r.RuntimeBuilder()
        runtime = (
            await builder.abuild(selected, path, admission_policy=expected)
            if async_build
            else builder.build(selected, path, admission_policy=expected)
        )
        try:
            assert selected.identity == original_profile
            assert runtime.store.local_capacity_policy() == expected.identity
            assert runtime.store.local_capacity_holders(runtime.scope) == (handle.run_id,)
            assert runtime.submit(spec, "original task", command_id="original-submit") == handle
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            restored = runtime.store.run(handle.run_id)
            assert restored["manifest"] == original_run["manifest"]
            assert restored["release_digest"] == original_run["release_digest"]
            assert "local_admission" not in restored
            assert restored["manifest"]["runtime_profile"] == original_profile
            fresh = runtime.submit(spec, "new task", command_id="new-submit")
            accepted = runtime.store.run(fresh.run_id)
            assert accepted["manifest"]["runtime_profile"] == original_profile
            assert accepted["manifest"]["admission_policy"] == expected.identity
            assert accepted["local_admission"]["root_run_id"] == fresh.run_id
            assert (await runtime.drive(fresh.run_id)).state == "succeeded"
        finally:
            await runtime.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
@pytest.mark.parametrize(
    "invalid", [{"deployment_id": "business"}, LocalExecutionPolicy(), TemporalExecutionPolicy()]
)
def test_invalid_host_admission_policy_refuses_before_any_factory_io(
    tmp_path, async_build, invalid
):
    events = []
    registry = r.ComponentRegistry()
    registry.register("provider", "observed", lambda config, context: events.append("provider-io"))
    selected = RuntimeProfile("assistant", "1", {"default": {"adapter": "observed"}})
    builder = r.RuntimeBuilder(registry, store_factory=lambda path: events.append("store-io"))
    with pytest.raises(ValidationError):
        if async_build:
            asyncio.run(
                builder.abuild(selected, tmp_path / "absent.sqlite", admission_policy=invalid)
            )
        else:
            builder.build(selected, tmp_path / "absent.sqlite", admission_policy=invalid)
    assert events == []


@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
def test_host_and_profile_admission_policy_sources_refuse_even_when_identical(
    tmp_path, async_build
):
    events = []
    expected = policy_type()("business")
    registry = r.ComponentRegistry()
    registry.register("provider", "observed", lambda config, context: events.append("provider-io"))
    builder = r.RuntimeBuilder(registry, store_factory=lambda path: events.append("store-io"))
    with pytest.raises(ValidationError):
        selected = profile(provider="observed")
        if async_build:
            asyncio.run(
                builder.abuild(selected, tmp_path / "absent.sqlite", admission_policy=expected)
            )
        else:
            builder.build(selected, tmp_path / "absent.sqlite", admission_policy=expected)
    assert events == []
