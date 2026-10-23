"""Renamed artifacts must be verified without renaming their Python import tree."""

import hashlib
import json
import zipfile

import pytest

from tests import test_release_preflight, test_stage_alpha1_candidate

candidate = test_release_preflight.candidate
preflight = test_release_preflight.preflight
inputs = test_stage_alpha1_candidate.inputs
staging = test_stage_alpha1_candidate.staging


@pytest.mark.parametrize("candidate", [("0.1.0a5", "relf-agent")], indirect=True)
def test_renamed_archives_pass_real_preflight_with_legacy_imports(preflight, candidate, tmp_path):
    source, wheel, sdist, spec = candidate
    result = preflight.prepare(wheel, sdist, source, spec, tmp_path / "handoff")
    assert result["status"] == "passed_local_preflight"
    assert set(result["artifacts"]) == {
        "relf_agent-0.1.0a5-py3-none-any.whl",
        "relf_agent-0.1.0a5.tar.gz",
    }
    with zipfile.ZipFile(wheel) as archive:
        assert "ralf_agent/__init__.py" in archive.namelist()
    assert result["publication_ready"] is False


@pytest.mark.parametrize("candidate", [("0.1.0a5", "relf-agent")], indirect=True)
@pytest.mark.parametrize("drift", ["wheel_name", "source_name", "unsupported_name"])
def test_manifest_distribution_cannot_hide_metadata_or_source_mismatch(
    preflight, candidate, tmp_path, drift
):
    source, wheel, sdist, spec = candidate
    if drift == "wheel_name":
        with zipfile.ZipFile(wheel) as archive:
            contents = {n: archive.read(n) for n in archive.namelist()}
        metadata = "relf_agent-0.1.0a5.dist-info/METADATA"
        contents[metadata] = contents[metadata].replace(b"Name: relf-agent", b"Name: ralf-agent")
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        spec["artifacts"][wheel.name] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        expected = "package_version_mismatch"
    elif drift == "source_name":
        path = source / "pyproject.toml"
        path.write_text(path.read_text().replace('name="relf-agent"', 'name="ralf-agent"'))
        expected = "source_version_mismatch"
    else:
        spec["distribution_name"] = "../../other"
        expected = "unsupported_distribution_name"
    output = tmp_path / "rejected"
    with pytest.raises(RuntimeError, match=expected):
        preflight.prepare(wheel, sdist, source, spec, output)
    assert not (output / "candidate").exists()
    assert json.loads((output / "preflight.json").read_text())["status"] == "failed"


@pytest.mark.parametrize(
    "tag", ["relf-alpha5-private-stage-test", "ralf-alpha4-private-stage-test"]
)
def test_a5_staging_accepts_only_its_new_private_prefix(staging, inputs, tmp_path, tag):
    spec, release, blobs = inputs
    spec.update(version="0.1.0a5", distribution_name="relf-agent")
    release["tag_name"] = tag
    output = tmp_path / "stage"
    if tag.startswith("relf-alpha5-"):
        receipt = staging.stage(17, output, spec, lambda _: release, blobs.__getitem__)
        assert receipt["status"] == "verified_original_candidate"
        assert receipt["public_release"] is False
    else:
        with pytest.raises(RuntimeError, match="private_staging_release_mismatch"):
            staging.stage(17, output, spec, lambda _: release, blobs.__getitem__)
        assert not (output / "candidate").exists()
