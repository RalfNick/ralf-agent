"""Selected original CREATE supervision preserves unselected defaults."""

import pytest

from ralf_agent.codex_environment import DockerCodingEnvironment
from ralf_agent.errors import ValidationError
from tests.test_codex_environment import resource as resource


def environment(resource, **options):
    root, cli = resource
    return DockerCodingEnvironment(
        root,
        "supervised",
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        retire_on_stop=True,
        expected_generation="a" * 32,
        create_recovery=True,
        **options,
    )


def test_selected_supervision_has_new_explicit_original_identity(resource):
    owner = environment(resource, create_supervision=True)
    assert owner.identity["create_operation_version"] == 2
    assert owner.identity["create_supervision_version"] == 1
    assert not tuple(resource[0].iterdir())


def test_disabled_supervision_preserves_previous_identity(resource):
    default = environment(resource)
    disabled = environment(resource, create_supervision=False)
    assert default.identity == disabled.identity
    assert default.identity["create_operation_version"] == 1
    assert "create_supervision_version" not in default.identity


@pytest.mark.parametrize("value", [1, None, "true", {}])
def test_supervision_requires_boolean(resource, value):
    with pytest.raises(ValidationError):
        environment(resource, create_supervision=value)
    assert not tuple(resource[0].iterdir())


def test_supervision_requires_recovery_and_original_fixed_generation(resource):
    root, cli = resource
    with pytest.raises(ValidationError):
        DockerCodingEnvironment(
            root,
            "supervised",
            docker_executable=str(cli),
            docker_host="unix:///fixture/docker.sock",
            create_supervision=True,
        )
    assert not tuple(root.iterdir())


def test_original_supervision_sources_cannot_move_before_preparation(resource, monkeypatch):
    import asyncio
    import os

    from ralf_agent import coding_create_inventory
    from ralf_agent.errors import DefinitionMismatch

    owner = environment(resource, create_supervision=True)
    original = coding_create_inventory.source_inventory()
    moved = {**original, "codex_create_gate": "f" * 64}
    monkeypatch.setattr(coding_create_inventory, "source_inventory", lambda: moved)
    try:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(owner.prepare())
        assert not (resource[0] / ".create-operation").exists()
        assert not (resource[1].parent / "docker.json").exists()
    finally:
        if owner._lease is not None:
            os.close(owner._lease)
            owner._lease = None
