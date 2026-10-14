"""Policy declarations preserve authority and validate before factory I/O."""

import asyncio
import json
from pathlib import Path

import pytest

from ralf_agent import ComponentRegistry, TemporalProfile, TemporalProfileCatalog
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.governance import TemporalExecutionPolicy
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.runtime_config import RuntimeProfile
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.types import canonical


def profile(config=None, *, adapter="bounded", provider="offline-echo", version="1"):
    return TemporalProfile(
        "assistant",
        version,
        {"default": {"adapter": provider}},
        components={
            "execution_policy": {"adapter": adapter, "config": {} if config is None else config}
        },
    )


def document(selected):
    return {
        "kind": "temporal-profiles",
        "schema_version": 1,
        "default": {"name": selected.name, "version": selected.version},
        "profiles": [selected.to_dict()],
    }


def test_omitted_policy_retains_original_profile_bytes_and_release(tmp_path):
    selected = TemporalProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    assert canonical(selected.to_dict()) == (
        '{"components":{},"execution":{"composite_sessions":false,"context_reads":false,'
        '"enable_sessions":false,"session_writes":false},"name":"assistant",'
        '"providers":{"default":{"adapter":"offline-echo","config":{}}},"version":"1"}'
    )
    assert selected.identity["digest"] == (
        "12ee838512cf7b6085d7222210e262f4084f8f1581e171c79ceda89058c41ead"
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        try:
            assert "execution_policy" not in assembly.release
        finally:
            await assembly.aclose()
        assert not any(tmp_path.iterdir())

    asyncio.run(run())


@pytest.mark.parametrize(
    "config",
    [
        {},
        {
            "version": "limited-1",
            "run_timeout_seconds": 60,
            "approval_timeout_seconds": 15.5,
            "max_children": 4,
            "max_concurrency": 2,
            "max_depth": 3,
            "allowed_tools": ["lookup", "apply"],
        },
        {
            "run_timeout_seconds": 86400,
            "approval_timeout_seconds": 86400,
            "max_children": 256,
            "max_concurrency": 32,
            "max_depth": 8,
            "allowed_tools": [],
        },
    ],
)
def test_builtin_policy_is_assembled_and_pinned_in_release(tmp_path, config):
    async def run():
        selected = profile(config)
        expected = TemporalExecutionPolicy(**config)
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        runtime, cleanup = assembly.detach_components()
        try:
            assert runtime.execution_policy == expected
            assert runtime.manifest["execution_policy"] == expected.identity
            assert runtime.orchestration_release["execution_policy"] == expected.identity
            assert runtime.manifest["runtime_profile"] == selected.identity
            assert not any(tmp_path.iterdir())
        finally:
            await cleanup.cleanup_async()
            await assembly.aclose()

    asyncio.run(run())


def test_explicit_empty_policy_is_distinct_from_omission():
    omitted = TemporalProfile("assistant", "1", {"default": {"adapter": "offline-echo"}})
    explicit = profile()
    assert explicit.identity != omitted.identity
    assert explicit.components["execution_policy"] == {"adapter": "bounded", "config": {}}


def test_policy_declaration_snapshots_and_immutable_catalog_resolution():
    config = {"run_timeout_seconds": 60, "allowed_tools": ["lookup"]}
    selected = profile(config)
    original = selected.identity
    config["run_timeout_seconds"] = 120
    config["allowed_tools"].append("write")
    returned = selected.components
    returned["execution_policy"]["config"]["allowed_tools"].append("caller")
    assert selected.identity == original
    assert selected.components["execution_policy"]["config"] == {
        "run_timeout_seconds": 60,
        "allowed_tools": ["lookup"],
    }
    catalog = TemporalProfileCatalog()
    catalog.register(selected, default=True)
    newer = profile({"run_timeout_seconds": 120}, version="2")
    catalog.register(newer)
    catalog.set_default("assistant", "2")
    assert catalog.resolve(original).identity == original
    with pytest.raises(DefinitionMismatch):
        catalog.register(profile({"run_timeout_seconds": 120}))


def test_json_and_toml_policy_have_same_identity_and_runtime(tmp_path):
    selected = profile(
        {
            "version": "limits-1",
            "run_timeout_seconds": 90,
            "approval_timeout_seconds": 20,
            "max_children": 4,
            "max_concurrency": 2,
            "max_depth": 3,
            "allowed_tools": ["lookup"],
        }
    )
    json_path, toml_path = tmp_path / "policy.json", tmp_path / "policy.toml"
    json_path.write_text(json.dumps(document(selected)))
    toml_path.write_text("""kind = "temporal-profiles"
schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.execution_policy]
adapter = "bounded"
[profiles.components.execution_policy.config]
version = "limits-1"
run_timeout_seconds = 90
approval_timeout_seconds = 20
max_children = 4
max_concurrency = 2
max_depth = 3
allowed_tools = ["lookup"]
""")
    catalogs = [TemporalProfileCatalog.from_file(path) for path in (json_path, toml_path)]
    assert all(catalog.default_profile.identity == selected.identity for catalog in catalogs)
    assert all(catalog.to_dict() == document(selected) for catalog in catalogs)

    async def run():
        for catalog in catalogs:
            assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
                catalog.default_profile
            )
            try:
                assert (
                    assembly.release["execution_policy"]
                    == TemporalExecutionPolicy(
                        **selected.components["execution_policy"]["config"]
                    ).identity
                )
            finally:
                await assembly.aclose()

    asyncio.run(run())


def test_custom_synchronous_policy_factory_can_replace_builtin(tmp_path):
    calls = []
    expected = TemporalExecutionPolicy(version="business-1", run_timeout_seconds=25)

    def custom(config, context):
        calls.append((config, context.scope, context.store))
        return expected

    registry = ComponentRegistry()
    registry.register("execution_policy", "business", custom)

    async def run():
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile({"service_class": "interactive"}, adapter="business")
        )
        runtime, cleanup = assembly.detach_components()
        try:
            assert runtime.execution_policy is expected
            assert runtime.manifest["execution_policy"] == expected.identity
            assert calls == [({"service_class": "interactive"}, assembly.scope, None)]
        finally:
            await cleanup.cleanup_async()
            await assembly.aclose()

    asyncio.run(run())


def test_local_profile_refuses_temporal_policy():
    with pytest.raises(ValidationError):
        RuntimeProfile(
            "assistant",
            "1",
            {"default": {"adapter": "offline-echo"}},
            {"execution_policy": {"adapter": "bounded"}},
        )


INVALID_CONFIGS = [
    {"run_timeout_seconds": True},
    {"approval_timeout_seconds": False},
    {"run_timeout_seconds": float("nan")},
    {"approval_timeout_seconds": float("inf")},
    {"run_timeout_seconds": 0},
    {"approval_timeout_seconds": -1},
    {"run_timeout_seconds": 86401},
    {"approval_timeout_seconds": "15"},
    {"max_children": True},
    {"max_children": 0},
    {"max_children": 257},
    {"max_concurrency": 33},
    {"max_concurrency": 1.0},
    {"max_depth": 9},
    {"max_depth": -1},
    {"version": ""},
    {"allowed_tools": "lookup"},
    {"allowed_tools": [""]},
    {"allowed_tools": [123]},
    {"kind": "temporal-execution-policy"},
    {"unexpected": "must-not-be-ignored"},
]


@pytest.mark.parametrize("config", INVALID_CONFIGS)
@pytest.mark.parametrize("catalog_mode", [False, True], ids=["single", "catalog-valid-first"])
def test_invalid_builtin_policy_refuses_before_any_factory_io(tmp_path, config, catalog_mode):
    calls = []

    def provider(config, context):
        calls.append("provider-io")
        Path(context.db_path).write_text("unexpected resource construction")
        return EchoProvider("side-effect")

    registry = ComponentRegistry()
    registry.register("provider", "observed", provider)

    async def run():
        builder = TemporalRuntimeBuilder(registry, base_dir=tmp_path)
        with pytest.raises(ValidationError):
            invalid = profile(config, provider="observed", version="2")
            if catalog_mode:
                catalog = TemporalProfileCatalog()
                catalog.register(profile(provider="observed"), default=True)
                catalog.register(invalid)
                await builder.abuild_catalog(catalog)
            else:
                await builder.abuild(invalid)
        assert calls == []
        assert not any(tmp_path.iterdir())

    asyncio.run(run())


@pytest.mark.parametrize("catalog_mode", [False, True], ids=["single", "catalog-valid-first"])
def test_unknown_policy_adapter_refuses_before_any_provider_io(tmp_path, catalog_mode):
    calls = []
    registry = ComponentRegistry()
    registry.register("provider", "observed", lambda c, ctx: calls.append("provider-io"))

    async def run():
        builder = TemporalRuntimeBuilder(registry, base_dir=tmp_path)
        selected = profile(adapter="unregistered", provider="observed", version="2")
        with pytest.raises(ValidationError):
            if catalog_mode:
                catalog = TemporalProfileCatalog()
                catalog.register(profile(provider="observed"), default=True)
                catalog.register(selected)
                await builder.abuild_catalog(catalog)
            else:
                await builder.abuild(selected)
        assert calls == []
        assert not any(tmp_path.iterdir())

    asyncio.run(run())


@pytest.mark.parametrize("result_kind", ["none", "identity-dict", "awaitable"])
@pytest.mark.parametrize("async_factory", [False, True], ids=["sync-factory", "async-factory"])
def test_invalid_custom_policy_result_closes_owned_provider_before_return(
    tmp_path, result_kind, async_factory
):
    events = []
    returned_coroutines = []

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
        return TemporalExecutionPolicy()

    def policy_factory(config, context):
        events.append("policy-created")
        if result_kind == "none":
            return None
        if result_kind == "identity-dict":
            return TemporalExecutionPolicy().identity
        result = lazy_policy()
        returned_coroutines.append(result)
        return result

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider)
    if async_factory:

        async def asynchronous_policy_factory(config, context):
            await asyncio.sleep(0)
            return policy_factory(config, context)

        registry.register_async("execution_policy", "invalid-result", asynchronous_policy_factory)
    else:
        registry.register("execution_policy", "invalid-result", policy_factory)

    async def run():
        assembled = None
        try:
            with pytest.raises(ValidationError):
                assembled = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                    profile(adapter="invalid-result", provider="owned")
                )
            assert events == [
                "provider-created",
                "policy-created",
                "close-started",
                "close-finished",
            ]
            assert all(value.cr_frame is None for value in returned_coroutines)
        finally:
            if assembled is not None:
                await assembled.aclose()

    asyncio.run(run())


def test_async_policy_replacement_preflights_then_awaits_factory_and_closes_provider(tmp_path):
    events = []
    expected = TemporalExecutionPolicy(
        version="remote-configuration-1", approval_timeout_seconds=12
    )

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
        assert context.store is None
        events.append("policy-started")
        await asyncio.sleep(0)
        events.append("policy-finished")
        return expected

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider)
    registry.register_async("execution_policy", "remote-config", policy_factory, validator=validate)

    async def run():
        assembled = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile({"tier": "interactive"}, adapter="remote-config", provider="owned")
        )
        try:
            assert assembled.release["execution_policy"] == expected.identity
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
