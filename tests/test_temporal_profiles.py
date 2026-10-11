"""Temporal configuration is pure, versioned and separate from Local authority."""

import copy
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.runtime_config import RuntimeProfile, load_catalog
from ralf_agent.temporal_profile import TemporalProfile, TemporalProfileCatalog


def profile(version="1", **options):
    return TemporalProfile(
        "assistant", version, {"default": {"adapter": "offline-echo"}}, **options
    )


def document(*values):
    return {
        "kind": "temporal-profiles",
        "schema_version": 1,
        "default": {"name": "assistant", "version": "1"},
        "profiles": [v.to_dict() for v in values or (profile(),)],
    }


def test_profile_snapshots_declarations_and_flags():
    providers = {"default": {"adapter": "offline-echo", "config": {"label": "first"}}}
    components = {"session_store": {"adapter": "sqlite", "config": {"path": "sessions.sqlite"}}}
    flags = {
        "enable_sessions": True,
        "session_writes": True,
        "composite_sessions": True,
        "context_reads": True,
    }
    first = TemporalProfile("assistant", "1", providers, components, execution=flags)
    identity = first.identity
    providers["default"]["config"]["label"] = "changed"
    components["session_store"]["config"]["path"] = "changed.sqlite"
    flags["context_reads"] = False
    returned = first.to_dict()
    returned["providers"]["default"]["config"]["label"] = "caller"
    assert first.identity == identity
    assert first.providers["default"]["config"]["label"] == "first"
    assert first.components["session_store"]["config"]["path"] == "sessions.sqlite"
    assert first.execution["context_reads"] is True
    with pytest.raises(FrozenInstanceError):
        first.version = "2"


def test_explicit_default_flags_have_identical_identity_and_different_local_identity():
    first = profile()
    assert first.execution == {
        "enable_sessions": False,
        "session_writes": False,
        "composite_sessions": False,
        "context_reads": False,
    }
    assert first.identity == profile(execution=first.execution).identity
    assert first.identity != RuntimeProfile("assistant", "1", first.providers).identity
    assert first.identity != profile(execution={"context_reads": True}).identity
    assert first.identity["kind"] == "runtime-profile"


@pytest.mark.parametrize(
    "kind",
    [
        "coordinator",
        "conversation_resource",
        "workflow_compiler",
        "workflow_interpreter",
        "workflow_scheduler",
        "workflow_transforms",
    ],
)
def test_local_only_components_refuse_before_any_factory(kind):
    with pytest.raises(ValidationError):
        profile(components={kind: {"adapter": "unused"}})


@pytest.mark.parametrize(
    "execution",
    [
        {"context_reads": 1},
        {"enable_sessions": "yes"},
        {"session_writes": None},
        {"unknown": False},
        [],
    ],
)
def test_invalid_flags_are_explicit_errors(execution):
    with pytest.raises(ValidationError):
        profile(execution=execution)


@pytest.mark.parametrize(
    "execution",
    [
        {"composite_sessions": True},
        {"composite_sessions": True, "enable_sessions": True},
        {"session_writes": True},
        {"enable_sessions": True, "session_writes": True},
    ],
)
def test_external_save_flags_require_session_source_and_complete_host_grant(execution):
    with pytest.raises(ValidationError):
        profile(execution=execution)


def test_ten_binding_roles_are_retained_without_resolution():
    kinds = {
        "provider": "provider",
        "decision_policy": "harness",
        "context": "context_assembler",
        "session": "session_store",
        "facts": "memory_store",
        "knowledge": "knowledge",
        "tool_set": "tool_set",
        "verifier": "verifier",
        "limits": "limits",
        "stage_policy": "stage_policy",
    }
    declarations = [
        {
            "role": role,
            "component_id": role,
            "version": "1",
            "component": {"adapter": "custom-" + kind},
        }
        for role, kind in kinds.items()
    ]
    first = profile(binding_components=declarations)
    declarations[0]["component"]["adapter"] = "mutated"
    assert len(first.binding_components) == 10
    assert first.binding_components[0]["component"]["adapter"] == "custom-provider"
    assert first.to_dict()["binding_components"] == first.binding_components


def test_profile_size_is_bounded_before_registration():
    with pytest.raises(ValidationError):
        TemporalProfile(
            "assistant",
            "1",
            {"default": {"adapter": "offline-echo", "config": {"label": "x" * 1_000_001}}},
        )


def test_catalog_default_changes_preserve_original_resolution():
    catalog = TemporalProfileCatalog()
    first, second = profile(), profile("2", execution={"context_reads": True})
    catalog.register(first, default=True)
    catalog.register(second)
    catalog.set_default("assistant", "2")
    assert catalog.default_profile is second
    assert catalog.resolve(first.identity) is first
    with pytest.raises(DefinitionMismatch):
        catalog.register(profile(execution={"context_reads": True}))
    assert catalog.resolve(first.identity) is first
    assert catalog.default_profile is second
    with pytest.raises(ValidationError):
        catalog.register(RuntimeProfile("assistant", "1", first.providers))


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"name": "assistant", "version": "1"},
        {"kind": "runtime-profile", "name": "assistant", "version": "1", "digest": "a" * 64},
    ],
)
def test_unavailable_original_identity_never_falls_back_to_default(identity):
    catalog = TemporalProfileCatalog()
    catalog.register(profile(), default=True)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        catalog.resolve(identity)


def test_json_and_toml_catalogs_have_same_fixed_identity(tmp_path):
    json_path, toml_path = tmp_path / "runtime.json", tmp_path / "runtime.toml"
    json_path.write_text(json.dumps(document(profile(execution={"context_reads": True}))))
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
[profiles.execution]
context_reads = true
""")
    first, second = (TemporalProfileCatalog.from_file(p) for p in (json_path, toml_path))
    assert first.default_profile.identity == second.default_profile.identity
    assert first.base_dir == tmp_path.resolve()
    assert first.to_dict() == document(first.default_profile)
    for path in (json_path, toml_path):
        with pytest.raises(ValidationError):
            load_catalog(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "kind",
        "schema_bool",
        "extra",
        "null_flags",
        "null_components",
        "null_bindings",
        "unknown_profile",
        "missing_provider",
        "bad_default",
    ],
)
def test_invalid_catalogs_refuse_without_partial_registry(tmp_path, mutation):
    payload = copy.deepcopy(document())
    if mutation == "kind":
        payload["kind"] = "local"
    elif mutation == "schema_bool":
        payload["schema_version"] = True
    elif mutation == "extra":
        payload["extra"] = "ignored"
    elif mutation.startswith("null_"):
        payload["profiles"][0][
            {
                "null_flags": "execution",
                "null_components": "components",
                "null_bindings": "binding_components",
            }[mutation]
        ] = None
    elif mutation == "unknown_profile":
        payload["profiles"][0]["unknown"] = 1
    elif mutation == "missing_provider":
        payload["profiles"][0].pop("providers")
    else:
        payload["default"]["version"] = "unavailable"
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload))
    with pytest.raises((ValidationError, DefinitionMismatch)):
        TemporalProfileCatalog.from_file(path)


def test_duplicate_keys_and_conflicting_versions_refuse(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(document()).replace(
            '"context_reads": false', '"context_reads": false, "context_reads": true'
        )
    )
    with pytest.raises(ValidationError):
        TemporalProfileCatalog.from_file(path)
    path.write_text(json.dumps(document(profile(), profile(execution={"context_reads": True}))))
    with pytest.raises(DefinitionMismatch):
        TemporalProfileCatalog.from_file(path)


def test_pure_profile_import_does_not_load_optional_sdk(tmp_path):
    code = """import importlib.abc,sys
class RefuseSDK(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname == "temporalio" or fullname.startswith("temporalio."):
   raise AssertionError("pure configuration imported optional SDK")
sys.meta_path.insert(0,RefuseSDK())
from ralf_agent.temporal_profile import TemporalProfile
value=TemporalProfile("a","1",{"default":{"adapter":"offline-echo"}})
assert value.execution["context_reads"] is False
"""
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_public_profile_objects_are_available_without_optional_runtime():
    import ralf_agent

    assert ralf_agent.TemporalProfile is TemporalProfile
    assert ralf_agent.TemporalProfileCatalog is TemporalProfileCatalog


@pytest.mark.parametrize("name,version", [(None, "1"), ([], "1"), ("assistant", {}), ("", "1")])
def test_invalid_default_selection_is_typed_and_keeps_original_default(name, version):
    catalog = TemporalProfileCatalog()
    first = profile()
    catalog.register(first, default=True)
    with pytest.raises(ValidationError):
        catalog.set_default(name, version)
    assert catalog.default_profile is first
