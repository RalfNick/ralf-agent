import asyncio
import importlib

import pytest

from ralf_agent import AgentSpec, ModelResponse, SQLiteStore
from ralf_agent.errors import CoordinatorBusy, ValidationError

from .test_runtime_config import declaration


def api():
    return importlib.import_module("ralf_agent.runtime_builder")


def profile(**changes):
    module = importlib.import_module("ralf_agent.runtime_config")
    return module.RuntimeProfile(**{**declaration(), **changes})


def test_defaults_build_and_execute_with_a_saved_profile(tmp_path):
    selected = profile()
    with api().RuntimeBuilder().build(selected, tmp_path / "default.sqlite") as runtime:
        handle = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == {"echo": "question", "label": "first"}
        assert runtime.diagnostics(handle.run_id).manifest["runtime_profile"] == selected.identity


def test_unknown_adapter_is_rejected_before_creating_the_database(tmp_path):
    selected = profile(providers={"default": {"adapter": "module:dangerous_factory"}})
    database = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        api().RuntimeBuilder().build(selected, database)
    assert not database.exists()


def test_explicit_provider_factory_receives_detached_configuration_and_context(tmp_path):
    calls = []

    class Provider:
        identity = {"kind": "registered-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output="custom")

    registry = api().ComponentRegistry()

    def factory(configuration, context):
        calls.append((configuration.copy(), context.db_path))
        configuration["change"] = "only factory input"
        return Provider()

    registry.register("provider", "custom", factory)
    selected = profile(providers={"default": {"adapter": "custom", "config": {"model": "fixture"}}})
    with api().RuntimeBuilder(registry).build(selected, tmp_path / "custom.sqlite") as runtime:
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).result == "custom"
    assert selected.providers["default"]["config"] == {"model": "fixture"}
    assert calls[0][0] == {"model": "fixture"}


def test_owned_resources_close_after_engine_and_retry_failed_resource_cleanup(tmp_path):
    events = []

    class Client:
        tries = 0

        def close(self):
            events.append("client")
            self.tries += 1
            if self.tries == 1:
                raise RuntimeError("close failed")

    class Provider:
        identity = {"kind": "owned-provider", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output="done")

    def factory(configuration, context):
        client = context.own(Client())
        context.own(client)
        return Provider()

    registry = api().ComponentRegistry()
    registry.register("provider", "owned", factory)
    selected = profile(providers={"default": {"adapter": "owned"}})
    runtime = api().RuntimeBuilder(registry).build(selected, tmp_path / "owned.sqlite")
    with pytest.raises(RuntimeError):
        runtime.close()
    with pytest.raises(ValidationError):
        runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
    runtime.close()
    runtime.close()
    assert events == ["client", "client"]


def test_construction_failure_closes_declared_resources_and_store(tmp_path):
    closed = []

    class Client:
        def close(self):
            closed.append("client")

    def factory(configuration, context):
        context.own(Client())
        raise RuntimeError("factory failed")

    registry = api().ComponentRegistry()
    registry.register("provider", "broken", factory)
    selected = profile(providers={"default": {"adapter": "broken"}})
    with pytest.raises(ValidationError):
        api().RuntimeBuilder(registry).build(selected, tmp_path / "failed.sqlite")
    assert closed == ["client"]
    with SQLiteStore(tmp_path / "failed.sqlite") as store:
        coordinator = store.create_coordinator()
        coordinator.acquire()
        coordinator.release()


def test_chat_adapter_rejects_inline_secrets_and_uses_explicit_environment_reference(
    tmp_path, monkeypatch
):
    database = tmp_path / "secret.sqlite"
    with pytest.raises(ValidationError):
        api().RuntimeBuilder().build(
            profile(
                providers={
                    "default": {
                        "adapter": "chat-completions",
                        "config": {"model": "fixture", "api_key": "not-persistable"},
                    }
                }
            ),
            database,
        )
    monkeypatch.setenv("RALF_FIXTURE_KEY", "fixture-key")
    with (
        api()
        .RuntimeBuilder()
        .build(
            profile(
                providers={
                    "default": {
                        "adapter": "chat-completions",
                        "config": {"model": "fixture", "api_key_env": "RALF_FIXTURE_KEY"},
                    }
                }
            ),
            tmp_path / "env.sqlite",
        ) as runtime
    ):
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert "fixture-key" not in str(runtime.diagnostics(handle.run_id).manifest)


def test_incomplete_engine_close_cannot_mark_runtime_closed_or_release_resources(tmp_path):
    from ralf_agent import LocalEngine

    resources = []

    class Client:
        def close(self):
            resources.append("closed")

    class Proxy:
        tries = 0

        def __init__(self, runtime):
            self.runtime = runtime

        def __getattr__(self, name):
            return getattr(self.runtime, name)

        def close(self):
            self.tries += 1
            if self.tries == 1:
                return False
            self.runtime.close()

    def owned_provider(config, context):
        context.own(Client())
        return api().EchoProvider("first")

    registry = api().ComponentRegistry()
    registry.register("provider", "owned", owned_provider)
    path = tmp_path / "incomplete-close.sqlite"
    runtime = (
        api()
        .RuntimeBuilder(
            registry, engine_factory=lambda store, **options: Proxy(LocalEngine(store, **options))
        )
        .build(
            profile(providers={"default": {"adapter": "owned"}}),
            path,
        )
    )
    try:
        with pytest.raises(ValidationError):
            runtime.close()
        assert resources == []
        with SQLiteStore(path) as other:
            with pytest.raises(CoordinatorBusy):
                other.create_coordinator().acquire()
    finally:
        runtime.close()
    assert resources == ["closed"]


def test_authority_construction_errors_are_typed_and_do_not_expose_backend_text(tmp_path):
    def failed_store(path):
        raise RuntimeError("SECRET_BACKEND_CONNECTION")

    with pytest.raises(ValidationError) as failure:
        api().RuntimeBuilder(store_factory=failed_store).build(
            profile(), tmp_path / "unused.sqlite"
        )
    assert "SECRET_BACKEND_CONNECTION" not in str(failure.value)


def test_failed_construction_cleanup_retains_a_retriable_resource_handle(tmp_path):
    closed = []

    class Client:
        def close(self):
            closed.append("client")
            if len(closed) == 1:
                raise RuntimeError("cleanup temporarily unavailable")

    def broken(config, context):
        context.own(Client())
        raise RuntimeError("construction unavailable")

    registry = api().ComponentRegistry()
    registry.register("provider", "broken-cleanup", broken)
    with pytest.raises(api().RuntimeBuildError) as failure:
        api().RuntimeBuilder(registry).build(
            profile(providers={"default": {"adapter": "broken-cleanup"}}),
            tmp_path / "cleanup.sqlite",
        )
    failure.value.cleanup.close()
    failure.value.cleanup.close()
    assert closed == ["client", "client"]


def test_existing_execution_owner_keeps_its_typed_coordinator_conflict(tmp_path):
    path = tmp_path / "owned-authority.sqlite"
    builder = api().RuntimeBuilder()
    with builder.build(profile(), path):
        with pytest.raises(CoordinatorBusy):
            builder.build(profile(), path)
