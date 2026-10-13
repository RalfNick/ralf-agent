"""The opt-in native chain is reachable from the installed public entry points."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent import ComponentRegistry, RuntimeBuilder, RuntimeProfile
from ralf_agent.errors import ValidationError
from ralf_agent.starter import create_starter


def test_public_sdk_exports_match_the_selected_implementations():
    sdk = importlib.import_module("ralf_agent")
    for module, names in (
        ("fact_index_generation", ("GenerationIndexedMemoryStore", "GenerationSourceChanged")),
        ("fact_index_maintenance_tools", ("FactIndexMaintenanceToolSource",)),
        (
            "fact_index_maintenance_factories",
            (
                "create_fact_index_maintenance_owner",
                "fact_index_maintenance_components",
                "maintained_agent_workflow",
            ),
        ),
    ):
        implementation = importlib.import_module("ralf_agent." + module)
        for name in names:
            assert getattr(sdk, name, None) is getattr(implementation, name)


def test_default_registry_admits_paired_configuration_but_sync_build_allocates_nothing(tmp_path):
    factories = importlib.import_module("ralf_agent.fact_index_maintenance_factories")
    components = factories.fact_index_maintenance_components(
        {"resource_id": "personal", "namespace": "reader"}
    )
    registry = ComponentRegistry()
    for kind, declaration in components.items():
        registry.prepare(kind, declaration)
    profile = RuntimeProfile(
        name="maintained",
        version="1",
        providers={"default": {"adapter": "echo"}},
        components=components,
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry, base_dir=tmp_path).build(profile, tmp_path / "runs.sqlite")
    assert list(tmp_path.iterdir()) == []


def test_cli_can_publish_the_complete_editable_memory_index_application(tmp_path):
    target = tmp_path / "app"
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path.cwd() / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "ralf_agent", "init", str(target), "--template", "memory-index"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    published = json.loads(completed.stdout)
    assert published["template"] == "memory-index"
    assert (target / "agent_app/runtime.py").is_file()
    assert (target / "README.md").is_file()
    assert not (target / ".ralf").exists()
    project = create_starter(tmp_path / "sdk-app", template="memory-index")
    assert project.factory == "agent_app.runtime:create_engine"
    assert set(project.files) == set(published["files"])
