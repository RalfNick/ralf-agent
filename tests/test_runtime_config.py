import importlib
import json

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError


def api():
    return importlib.import_module("ralf_agent.runtime_config")


def declaration(version="1", label="first"):
    return {
        "name": "app",
        "version": version,
        "providers": {"default": {"adapter": "offline-echo", "config": {"label": label}}},
    }


def test_profile_detaches_configuration_and_catalog_keeps_original_version():
    source = declaration()
    profile = api().RuntimeProfile(**source)
    original = profile.identity
    source["providers"]["default"]["config"]["label"] = "changed"
    profile.providers["default"]["config"]["label"] = "also changed"
    assert profile.identity == original
    catalog = api().RuntimeCatalog()
    catalog.register(profile, default=True)
    second = api().RuntimeProfile(**declaration("2", "second"))
    catalog.register(second, default=True)
    assert catalog.default.identity == second.identity
    assert catalog.resolve(original).providers["default"]["config"]["label"] == "first"


def test_catalog_refuses_same_version_with_different_configuration_or_digest():
    catalog = api().RuntimeCatalog()
    profile = api().RuntimeProfile(**declaration())
    catalog.register(profile, default=True)
    catalog.register(profile)
    with pytest.raises(DefinitionMismatch):
        catalog.register(api().RuntimeProfile(**declaration(label="changed")))
    wrong = {**profile.identity, "digest": "0" * 64}
    with pytest.raises(DefinitionMismatch):
        catalog.resolve(wrong)
    with pytest.raises(DefinitionMismatch):
        catalog.set_default("app", "missing")


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_catalog_can_load_both_formats_and_resolve_old_version(tmp_path, extension):
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "default": {"name": "app", "version": "2"},
                    "profiles": [declaration(), declaration("2", "second")],
                }
            )
        )
    else:
        path.write_text("""schema_version = 1
[default]
name = "app"
version = "2"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "first"
[[profiles]]
name = "app"
version = "2"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "second"
""")
    catalog = api().load_catalog(path)
    assert catalog.default.version == "2"
    assert catalog.resolve(api().RuntimeProfile(**declaration()).identity).version == "1"
    assert catalog.base_dir == path.parent.resolve()


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":1,"schema_version":2}',
        '{"schema_version":1,"default":{},"profiles":[],"import":"arbitrary.module"}',
        '{"schema_version":true,"default":{},"profiles":[]}',
        '{"schema_version":1,"default":{},"profiles":[NaN]}',
        "[]",
        "invalid-json",
    ],
)
def test_malformed_catalog_is_rejected_without_importing_code(tmp_path, payload):
    path = tmp_path / "runtime.json"
    path.write_text(payload)
    with pytest.raises(ValidationError):
        api().load_catalog(path)


@pytest.mark.parametrize(
    "change",
    [
        {"providers": {}},
        {"version": 1},
        {"providers": {"default": {"adapter": "x", "secret": "x"}}},
        {"components": {"unknown": {"adapter": "x"}}},
        {
            "components": {
                "recall_policy": {"adapter": "bounded-recall"},
                "recall_planner": {"adapter": "x"},
            }
        },
        {"providers": {"default": {"adapter": "x", "config": {"bad": float("nan")}}}},
    ],
)
def test_profile_errors_are_caught_before_component_construction(change):
    with pytest.raises(ValidationError):
        api().RuntimeProfile(**{**declaration(), **change})
