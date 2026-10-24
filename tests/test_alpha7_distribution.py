"""New module/CLI identity is explicit; older archives retain their defaults."""

import hashlib
import json
import zipfile

import pytest

from tests import test_release_gate, test_release_preflight, test_stage_alpha1_candidate

candidate = test_release_preflight.candidate
preflight = test_release_preflight.preflight
gate = test_release_gate.gate
staging = test_stage_alpha1_candidate.staging
inputs = test_stage_alpha1_candidate.inputs


@pytest.mark.parametrize("candidate", [("0.1.0a7", "relf-agent", "relf_agent")], indirect=True)
def test_new_module_archives_pass_the_real_source_handoff(preflight, candidate, tmp_path):
    source, wheel, sdist, spec = candidate
    result = preflight.prepare(wheel, sdist, source, spec, tmp_path / "handoff")
    assert result["status"] == "passed_local_preflight"
    assert (tmp_path / "handoff/candidate" / wheel.name).read_bytes() == wheel.read_bytes()
    assert result["publication_ready"] is False


@pytest.mark.parametrize("candidate", [("0.1.0a7", "relf-agent", "relf_agent")], indirect=True)
@pytest.mark.parametrize(
    "field,value", [("python_module", "../relf_agent"), ("cli_name", "../relf")]
)
def test_unsafe_entrypoint_identity_is_rejected_before_handoff(
    preflight, candidate, tmp_path, field, value
):
    source, wheel, sdist, spec = candidate
    spec[field] = value
    out = tmp_path / "refused"
    with pytest.raises(RuntimeError, match="unsupported_" + field):
        preflight.prepare(wheel, sdist, source, spec, out)
    assert not (out / "candidate").exists()
    assert json.loads((out / "preflight.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("entrypoint", ["new", "old_module", "old_cli", "old_prefix"])
def test_a7_staging_requires_its_full_entrypoint_identity(staging, inputs, tmp_path, entrypoint):
    spec, release, blobs = inputs
    spec.update(
        version="0.1.0a7",
        distribution_name="relf-agent",
        python_module="relf_agent",
        cli_name="relf",
    )
    release["tag_name"] = "relf-alpha7-private-stage-test"
    if entrypoint == "old_module":
        spec["python_module"] = "ralf_agent"
    elif entrypoint == "old_cli":
        spec["cli_name"] = "ralf"
    elif entrypoint == "old_prefix":
        release["tag_name"] = "relf-alpha5-private-stage-test"
    output = tmp_path / "stage"
    if entrypoint == "new":
        assert (
            staging.stage(17, output, spec, lambda _: release, blobs.__getitem__)["status"]
            == "verified_original_candidate"
        )
    else:
        with pytest.raises(RuntimeError, match="private_staging_release_mismatch"):
            staging.stage(17, output, spec, lambda _: release, blobs.__getitem__)
        assert not (output / "candidate").exists()


def test_legacy_identity_defaults_do_not_follow_the_new_distribution_name(gate):
    assert (
        gate.python_module({"distribution_name": "relf-agent", "version": "0.1.0a5"})
        == "ralf_agent"
    )
    assert gate.cli_name({"distribution_name": "relf-agent", "version": "0.1.0a5"}) == "ralf"


@pytest.mark.parametrize("candidate", [("0.1.0a7", "relf-agent", "relf_agent")], indirect=True)
@pytest.mark.parametrize(
    "drift", ["old_cli", "old_alias", "extra_module", "auxiliary_old_module", "foreign_command"]
)
def test_mixed_or_incorrect_public_entrypoints_are_not_handed_off(
    preflight, candidate, tmp_path, drift
):
    source, wheel, sdist, spec = candidate
    if drift == "old_cli":
        spec["cli_name"] = "ralf"
        expected = "cli_entrypoint_mismatch"
    else:
        with zipfile.ZipFile(wheel) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        if drift in {"old_alias", "auxiliary_old_module", "foreign_command"}:
            name = "relf_agent-0.1.0a7.dist-info/entry_points.txt"
            entries[name] += {
                "old_alias": b"ralf = relf_agent.cli:main\n",
                "auxiliary_old_module": b"relf-check-model = ralf_agent.model_check_cli:main\n",
                "foreign_command": b"foreign = relf_agent.cli:main\n",
            }[drift]
            expected = "cli_entrypoint_mismatch"
        else:
            entries["ralf_agent/__init__.py"] = b"# unwanted alias"
            expected = "unexpected_python_module"
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        spec["artifacts"][wheel.name] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    out = tmp_path / "rejected"
    with pytest.raises(RuntimeError, match=expected):
        preflight.prepare(wheel, sdist, source, spec, out)
    assert not (out / "candidate").exists()
