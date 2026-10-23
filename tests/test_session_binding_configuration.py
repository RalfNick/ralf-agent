"""Session bindings assemble through the existing profile and client lifecycle."""

import asyncio
import json
from contextlib import closing

import pytest

from relf_agent import InMemoryMemory, RuntimeBuilder, RuntimeProfile, Scope
from relf_agent.cli import main
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import ComponentRegistry
from relf_agent.runtime_config import load_catalog

from .test_session_binding_execution import session_agent


def declarations(backend=None):
    return [
        {
            "role": "session",
            "component_id": "history",
            "version": "1",
            "component": {
                "adapter": "session-resource",
                "config": {
                    "backend": backend or {"adapter": "sqlite"},
                    "namespaces": ["red", "blue"],
                    "default_namespace": "red",
                },
            },
        }
    ]


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_json_toml_cli_runs_and_resumes_namespaced_session(tmp_path, capsys, extension):
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [
                        {
                            "name": "app",
                            "version": "1",
                            "providers": {"default": {"adapter": "offline-echo"}},
                            "binding_components": declarations(),
                        }
                    ],
                }
            )
        )
    else:
        path.write_text("""schema_version = 2
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[[profiles.binding_components]]
role = "session"
component_id = "history"
version = "1"
[profiles.binding_components.component]
adapter = "session-resource"
[profiles.binding_components.component.config]
namespaces = ["red", "blue"]
default_namespace = "red"
[profiles.binding_components.component.config.backend]
adapter = "sqlite"
""")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(session_agent(namespace="blue").to_dict()))
    db = tmp_path / "run.sqlite"
    common = ["--config", str(path), "--db", str(db)]
    assert (
        main(
            [
                *common,
                "run",
                "--spec",
                str(spec),
                "--input",
                "q",
                "--session-id",
                "shared",
                "--command-id",
                "s",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "succeeded"
    assert main([*common, "resume", result["run_id"]]) == 0
    assert json.loads(capsys.readouterr().out) == result
    with RuntimeBuilder().build(load_catalog(path).default, db) as runtime:
        view, _ = runtime.binding_catalog.resolve(
            "session", session_agent(namespace="blue").bindings.session, Scope()
        )
        assert asyncio.run(view.read(Scope(), "shared"))[0] == 1
        assert runtime.sessions.read(Scope(), "shared") == (0, [])


def test_async_session_resource_factory_preserves_owned_cleanup(tmp_path):
    async def scenario():
        events = []

        class Backend(InMemoryMemory):
            async def aclose(self):
                events.append("closed")

        async def factory(config, context):
            return context.own_async(Backend(backend_id="async"))

        registry = ComponentRegistry()
        registry.register_async("session_store", "custom", factory)
        profile = RuntimeProfile(
            "app",
            "1",
            {"default": {"adapter": "offline-echo"}},
            binding_components=declarations({"adapter": "custom"}),
        )
        with pytest.raises(ValidationError):
            RuntimeBuilder(registry).build(profile, tmp_path / "refused.sqlite")
        async with await RuntimeBuilder(registry).abuild(
            profile, tmp_path / "async.sqlite"
        ) as runtime:
            h = runtime.submit(session_agent(), "q", command_id="s")
            assert (await runtime.drive(h.run_id)).state == "succeeded"
        assert events == ["closed"]

    asyncio.run(scenario())


def test_invalid_namespace_config_does_not_create_database(tmp_path):
    from relf_agent.errors import ValidationError

    values = declarations()
    values[0]["component"]["config"]["namespaces"] = [""]
    profile = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
    )
    db = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, db)
    assert not db.exists()


def test_session_resource_export_is_optional_dependency_safe():
    from relf_agent import SessionBindingResource

    assert (
        SessionBindingResource(InMemoryMemory(backend_id="test")).identity["backend_id"] == "test"
    )


def test_prepared_session_factory_freezes_default_namespace(tmp_path):
    from relf_agent import SQLiteStore
    from relf_agent.runtime_lifecycle import BuildContext

    registry = ComponentRegistry()
    declaration = declarations({"adapter": "in-memory", "config": {"backend_id": "memory"}})[0][
        "component"
    ]
    factory, config = registry.prepare("session_store", declaration)
    declaration["config"]["default_namespace"] = "blue"
    with closing(SQLiteStore(tmp_path / "factory.sqlite")) as store:
        resource = factory(
            config, BuildContext(store, tmp_path / "factory.sqlite", Scope(), tmp_path)
        )
        assert resource.default_namespace == "red"
