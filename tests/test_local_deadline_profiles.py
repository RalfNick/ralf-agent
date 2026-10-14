"""Local deadline configuration preserves defaults and rejects policy confusion."""

import asyncio
import importlib
import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, LocalEngine, SQLiteStore, TemporalProfile
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.governance import TemporalExecutionPolicy
from ralf_agent.runtime_builder import EchoProvider, RuntimeBuilder
from ralf_agent.runtime_config import RuntimeCatalog, RuntimeProfile, load_catalog
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import canonical


def policy_type():
    return importlib.import_module("ralf_agent.governance").LocalExecutionPolicy


def profile(config=None, *, adapter="local-bounded", provider="offline-echo", version="1"):
    return RuntimeProfile(
        "assistant",
        version,
        {"default": {"adapter": provider}},
        {"execution_policy": {"adapter": adapter, "config": {} if config is None else config}},
    )


def declaration(selected):
    return {
        "name": selected.name,
        "version": selected.version,
        "providers": selected.providers,
        "components": selected.components,
    }


def document(selected):
    return {
        "schema_version": 1,
        "default": {"name": selected.name, "version": selected.version},
        "profiles": [declaration(selected)],
    }


def test_local_policy_value_is_immutable_and_round_trips_its_identity():
    policy = policy_type()(
        version="interactive-1", run_timeout_seconds=45, approval_timeout_seconds=12
    )
    assert policy.identity == {
        "kind": "local-execution-policy",
        "version": "interactive-1",
        "run_timeout_seconds": 45,
        "approval_timeout_seconds": 12,
    }
    assert policy_type().from_identity(policy.identity) == policy
    returned = policy.identity
    returned["run_timeout_seconds"] = 100
    assert policy.run_timeout_seconds == 45
    with pytest.raises(FrozenInstanceError):
        policy.run_timeout_seconds = 100


@pytest.mark.parametrize(
    "config",
    [
        {"run_timeout_seconds": True},
        {"approval_timeout_seconds": False},
        {"run_timeout_seconds": float("nan")},
        {"approval_timeout_seconds": float("inf")},
        {"run_timeout_seconds": float("-inf")},
        {"run_timeout_seconds": 0},
        {"approval_timeout_seconds": -1},
        {"run_timeout_seconds": 86401},
        {"approval_timeout_seconds": "15"},
        {"version": ""},
        {"version": 1},
    ],
)
def test_local_policy_rejects_invalid_deadline_values(config):
    with pytest.raises(ValidationError):
        policy_type()(**config)


@pytest.mark.parametrize(
    "identity",
    [
        None,
        {},
        TemporalExecutionPolicy().identity,
        {"kind": "local-execution-policy", "unexpected": 1},
        {"kind": "local-execution-policy", "run_timeout_seconds": True},
    ],
)
def test_local_policy_refuses_wrong_or_malformed_identity(identity):
    with pytest.raises(ValidationError):
        policy_type().from_identity(identity)


def test_omitted_local_policy_preserves_original_profile_and_manifest_bytes(tmp_path):
    selected = RuntimeProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    assert canonical(declaration(selected)) == (
        '{"components":{},"name":"assistant",'
        '"providers":{"default":{"adapter":"offline-echo","config":{}}},"version":"1"}'
    )
    assert selected.identity["digest"] == (
        "0ce02f668d161c2059d1f5fc37b668d93b97370294993bdc1baee566b58ce4c7"
    )
    with RuntimeBuilder().build(selected, tmp_path / "default.sqlite") as assembled:
        handle = assembled.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
        manifest = assembled.diagnostics(handle.run_id).manifest
        assert "execution_policy" not in manifest
        assert "local_deadline_protocol" not in manifest
        assert manifest["runtime_profile"] == selected.identity
        assert asyncio.run(assembled.drive(handle.run_id)).state == "succeeded"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"version": "interactive-1", "run_timeout_seconds": 60, "approval_timeout_seconds": 15.5},
        {"run_timeout_seconds": 86400, "approval_timeout_seconds": 86400},
    ],
)
def test_local_sdk_and_builtin_profile_pin_same_policy_in_original_release(tmp_path, config):
    expected = policy_type()(**config)
    with SQLiteStore(tmp_path / "sdk.sqlite") as store:
        with LocalEngine(
            store,
            providers={"default": EchoProvider("sdk")},
            tools=ToolRegistry(),
            execution_policy=expected,
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
            manifest = engine.diagnostics(handle.run_id).manifest
            assert manifest["execution_policy"] == expected.identity
            assert manifest["local_deadline_protocol"] == 1
            assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
    selected = profile(config)
    with RuntimeBuilder().build(selected, tmp_path / "profile.sqlite") as assembled:
        handle = assembled.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
        manifest = assembled.diagnostics(handle.run_id).manifest
        assert manifest["execution_policy"] == expected.identity
        assert manifest["local_deadline_protocol"] == 1
        assert manifest["runtime_profile"] == selected.identity
        assert asyncio.run(assembled.drive(handle.run_id)).state == "succeeded"


def test_policy_declaration_detaches_inputs_and_catalog_keeps_old_version():
    config = {"run_timeout_seconds": 60}
    selected = profile(config)
    original = selected.identity
    config["run_timeout_seconds"] = 120
    selected.components["execution_policy"]["config"]["run_timeout_seconds"] = 240
    assert selected.identity == original
    assert selected.components["execution_policy"]["config"] == {"run_timeout_seconds": 60}
    omitted = RuntimeProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    assert profile().identity != omitted.identity
    catalog = RuntimeCatalog()
    catalog.register(selected, default=True)
    catalog.register(profile({"run_timeout_seconds": 120}, version="2"), default=True)
    assert catalog.resolve(original).identity == original
    with pytest.raises(DefinitionMismatch):
        catalog.register(profile({"run_timeout_seconds": 120}))


def test_json_and_toml_select_same_local_policy_and_runtime(tmp_path):
    selected = profile(
        {"version": "interactive-1", "run_timeout_seconds": 90, "approval_timeout_seconds": 20}
    )
    json_path, toml_path = tmp_path / "policy.json", tmp_path / "policy.toml"
    json_path.write_text(json.dumps(document(selected)))
    toml_path.write_text("""schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.execution_policy]
adapter = "local-bounded"
[profiles.components.execution_policy.config]
version = "interactive-1"
run_timeout_seconds = 90
approval_timeout_seconds = 20
""")
    for index, path in enumerate((json_path, toml_path)):
        catalog = load_catalog(path)
        assert catalog.default.identity == selected.identity
        with RuntimeBuilder(base_dir=catalog.base_dir).build(
            catalog.default, tmp_path / f"catalog-{index}.sqlite"
        ) as assembled:
            handle = assembled.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
            assert (
                assembled.diagnostics(handle.run_id).manifest["execution_policy"]
                == policy_type()(**selected.components["execution_policy"]["config"]).identity
            )


@pytest.mark.parametrize(
    "config",
    [
        {"run_timeout_seconds": True},
        {"approval_timeout_seconds": False},
        {"run_timeout_seconds": float("nan")},
        {"approval_timeout_seconds": float("inf")},
        {"run_timeout_seconds": 0},
        {"approval_timeout_seconds": -1},
        {"run_timeout_seconds": 86401},
        {"approval_timeout_seconds": "15"},
        {"version": ""},
        {"version": 1},
        {"max_children": 4},
        {"allowed_tools": []},
        {"kind": "local-execution-policy"},
        {"unexpected": "must-not-be-ignored"},
    ],
)
@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
def test_invalid_builtin_policy_is_refused_before_provider_or_store_io(
    tmp_path, config, async_build
):
    events = []
    registry = ComponentRegistry()
    registry.register("provider", "observed", lambda c, ctx: events.append("provider-io"))

    def store_factory(path):
        events.append("store-io")
        return SQLiteStore(path)

    builder = RuntimeBuilder(registry, store_factory=store_factory)
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(ValidationError):
        selected = profile(config, provider="observed")
        if async_build:
            asyncio.run(builder.abuild(selected, path))
        else:
            builder.build(selected, path)
    assert events == []
    assert not path.exists()


@pytest.mark.parametrize("async_build", [False, True], ids=["build", "abuild"])
def test_unknown_local_policy_adapter_is_refused_before_any_factory_io(tmp_path, async_build):
    events = []
    registry = ComponentRegistry()
    registry.register("provider", "observed", lambda c, ctx: events.append("provider-io"))
    selected = profile(adapter="unregistered", provider="observed")
    builder = RuntimeBuilder(registry, store_factory=lambda path: events.append("store-io"))
    with pytest.raises(ValidationError):
        if async_build:
            asyncio.run(builder.abuild(selected, tmp_path / "absent.sqlite"))
        else:
            builder.build(selected, tmp_path / "absent.sqlite")
    assert events == []


def test_registered_sync_local_policy_replaces_builtin(tmp_path):
    events = []
    expected = policy_type()(version="business-1", run_timeout_seconds=25)

    def factory(config, context):
        events.append((config, context.db_path, context.scope))
        return expected

    registry = ComponentRegistry()
    registry.register("execution_policy", "business", factory)
    selected = profile({"tier": "interactive"}, adapter="business")
    path = tmp_path / "custom.sqlite"
    with RuntimeBuilder(registry).build(selected, path) as assembled:
        handle = assembled.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
        assert (
            assembled.diagnostics(handle.run_id).manifest["execution_policy"] == expected.identity
        )
        assert len(events) == 1 and events[0][0] == {"tier": "interactive"}
        assert Path(events[0][1]) == path.resolve()


def test_async_local_policy_factory_preflights_and_closes_owned_provider(tmp_path):
    events = []
    expected = policy_type()(version="remote-configuration-1", approval_timeout_seconds=12)

    class Client:
        async def aclose(self):
            events.append("close-started")
            await asyncio.sleep(0)
            events.append("close-finished")

    def validate(config):
        assert config == {"tier": "interactive"}
        events.append("policy-preflight")

    def provider(config, context):
        context.own_async(Client())
        events.append("provider-created")
        return EchoProvider("owned")

    async def policy_factory(config, context):
        assert config == {"tier": "interactive"}
        assert context.store is not None
        events.append("policy-started")
        await asyncio.sleep(0)
        events.append("policy-finished")
        return expected

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider)
    registry.register_async("execution_policy", "remote-config", policy_factory, validator=validate)

    async def run():
        assembled = await RuntimeBuilder(registry).abuild(
            profile({"tier": "interactive"}, adapter="remote-config", provider="owned"),
            tmp_path / "async.sqlite",
        )
        try:
            handle = assembled.submit(AgentSpec("a", "Answer"), "q", command_id="submit")
            assert (
                assembled.diagnostics(handle.run_id).manifest["execution_policy"]
                == expected.identity
            )
            assert events == [
                "policy-preflight",
                "provider-created",
                "policy-started",
                "policy-finished",
            ]
        finally:
            await assembled.aclose()
        assert events[-2:] == ["close-started", "close-finished"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "result_kind",
    [
        "none",
        "identity-dict",
        "awaitable",
        "context-manager",
        "async-context-manager",
        "temporal-policy",
    ],
)
@pytest.mark.parametrize("async_factory", [False, True], ids=["sync-factory", "async-factory"])
def test_invalid_custom_local_policy_closes_owned_provider_before_return(
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

    async def lazy_policy():
        events.append("unexpected-policy-execution")
        return policy_type()()

    @contextmanager
    def lazy_context():
        events.append("unexpected-policy-execution")
        yield policy_type()()

    @asynccontextmanager
    async def lazy_async_context():
        events.append("unexpected-policy-execution")
        yield policy_type()()

    def factory(config, context):
        events.append("policy-created")
        if result_kind == "none":
            return None
        if result_kind == "identity-dict":
            return {"kind": "local-execution-policy", "version": "1"}
        if result_kind == "temporal-policy":
            return TemporalExecutionPolicy()
        if result_kind == "context-manager":
            return lazy_context()
        if result_kind == "async-context-manager":
            return lazy_async_context()
        value = lazy_policy()
        coroutines.append(value)
        return value

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider)
    if async_factory:

        async def async_policy_factory(config, context):
            await asyncio.sleep(0)
            return factory(config, context)

        registry.register_async("execution_policy", "invalid-result", async_policy_factory)
    else:
        registry.register("execution_policy", "invalid-result", factory)

    async def run():
        assembled = None
        path = tmp_path / "invalid-result.sqlite"
        try:
            with pytest.raises(ValidationError):
                assembled = await RuntimeBuilder(registry).abuild(
                    profile(adapter="invalid-result", provider="owned"), path
                )
            assert events == [
                "provider-created",
                "policy-created",
                "close-started",
                "close-finished",
            ]
            assert all(value.cr_frame is None for value in coroutines)
            with SQLiteStore(path) as store:
                coordinator = store.create_coordinator()
                coordinator.acquire()
                coordinator.release()
        finally:
            if assembled is not None:
                await assembled.aclose()

    asyncio.run(run())


def test_local_assembly_refuses_builtin_temporal_policy_and_releases_store(tmp_path):
    path = tmp_path / "temporal-policy.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile(adapter="bounded"), path)
    if path.exists():
        with SQLiteStore(path) as store:
            coordinator = store.create_coordinator()
            coordinator.acquire()
            coordinator.release()


@pytest.mark.parametrize("custom_factory", [False, True], ids=["builtin", "custom"])
def test_temporal_assembly_refuses_local_policy_before_worker_use(tmp_path, custom_factory):
    registry = ComponentRegistry()
    adapter = "local-bounded"
    if custom_factory:
        adapter = "local-custom"
        registry.register("execution_policy", adapter, lambda config, context: policy_type()())
    selected = TemporalProfile(
        "assistant",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"execution_policy": {"adapter": adapter}},
    )

    async def run():
        assembled = None
        try:
            with pytest.raises(ValidationError):
                assembled = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                    selected
                )
            assert not any(tmp_path.iterdir())
        finally:
            if assembled is not None:
                await assembled.aclose()

    asyncio.run(run())
