"""Frozen artifact handoff checks run without importing or executing the SDK."""

import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def preflight(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "release_preflight", ROOT / "tools/release_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / "source"
    package = source / "src/ralf_agent"
    package.mkdir(parents=True)
    product = b'__version__ = "0.1.0a1"\n'
    (package / "__init__.py").write_bytes(product)
    (source / "pyproject.toml").write_text('[project]\nname="ralf-agent"\nversion="0.1.0a1"\n')
    for name in ["LICENSE", "NOTICE"]:
        (source / name).write_text(name + " original\n")
    wheel = tmp_path / "ralf_agent-0.1.0a1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("ralf_agent/__init__.py", product)
        z.writestr(
            "ralf_agent-0.1.0a1.dist-info/METADATA",
            "Name: ralf-agent\nVersion: 0.1.0a1\nLicense-Expression: Apache-2.0\n",
        )
        for name in ["LICENSE", "NOTICE"]:
            z.writestr(
                "ralf_agent-0.1.0a1.dist-info/licenses/" + name, (source / name).read_bytes()
            )
    sdist = tmp_path / "ralf_agent-0.1.0a1.tar.gz"
    tests = {
        "tests/context_crash_assertions.py": b"# helper",
        "tests/test_starter.py": b"# test",
        "examples/support_journey.py": b"# example",
    }
    with tarfile.open(sdist, "w:gz") as tar:
        for name, content in {
            **tests,
            **{n: (source / n).read_bytes() for n in ["LICENSE", "NOTICE"]},
        }.items():
            info = tarfile.TarInfo("ralf_agent-0.1.0a1/" + name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    import release_gate

    spec = {
        "version": "0.1.0a1",
        "artifact_source_commit": "original-source",
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [wheel, sdist]},
        "product_files": 1,
        "product_tree_sha256": release_gate.digest(
            {"__init__.py": hashlib.sha256(product).hexdigest()}
        ),
        "test_tree_sha256": release_gate.digest(
            {k: hashlib.sha256(v).hexdigest() for k, v in tests.items()}
        ),
        "deferred": ["function-fingerprint qualification", "S2"],
    }
    return source, wheel, sdist, spec


def test_handoff_copies_only_verified_original_artifacts(preflight, candidate, tmp_path):
    source, wheel, sdist, spec = candidate
    out = tmp_path / "handoff"
    result = preflight.prepare(wheel, sdist, source, spec, out)
    assert result["status"] == "passed_local_preflight"
    assert result["publication_ready"] is False
    assert result["deferred"] == ["function-fingerprint qualification", "S2"]
    assert {p.name for p in (out / "candidate").iterdir()} == {wheel.name, sdist.name}
    assert (out / "candidate" / wheel.name).read_bytes() == wheel.read_bytes()
    assert (out / "candidate" / sdist.name).read_bytes() == sdist.read_bytes()
    assert result["artifacts"] == spec["artifacts"]


@pytest.mark.parametrize("drift", ["source", "version", "wheel", "license", "notice"])
def test_preflight_rejects_drift_without_deliverable(preflight, candidate, tmp_path, drift):
    source, wheel, sdist, spec = candidate
    if drift == "source":
        (source / "src/ralf_agent/__init__.py").write_text(
            "raise RuntimeError('must never import')\n"
        )
    elif drift == "version":
        (source / "pyproject.toml").write_text('[project]\nname="ralf-agent"\nversion="0.2.0"\n')
    elif drift == "wheel":
        wheel.write_bytes(b"rebuilt package")
    else:
        (source / drift.upper()).write_text("changed")
    out = tmp_path / "rejected"
    with pytest.raises(RuntimeError):
        preflight.prepare(wheel, sdist, source, spec, out)
    assert not (out / "candidate").exists()
    assert json.loads((out / "preflight.json").read_text())["status"] == "failed"


def test_preflight_never_overwrites_old_evidence(preflight, candidate, tmp_path):
    source, wheel, sdist, spec = candidate
    out = tmp_path / "existing"
    out.mkdir()
    (out / "old-failure").write_text("retained")
    with pytest.raises(FileExistsError):
        preflight.prepare(wheel, sdist, source, spec, out)
    assert (out / "old-failure").read_text() == "retained"


def test_handoff_rechecks_copied_bytes_before_exposing_candidate(
    preflight, candidate, tmp_path, monkeypatch
):
    source, wheel, sdist, spec = candidate
    original = preflight.shutil.copyfile

    def corrupt_copy(src, dst):
        original(src, dst)
        if src == wheel:
            dst.write_bytes(b"changed during handoff")

    monkeypatch.setattr(preflight.shutil, "copyfile", corrupt_copy)
    out = tmp_path / "changed-copy"
    with pytest.raises(RuntimeError, match="copied_artifact_sha256_mismatch"):
        preflight.prepare(wheel, sdist, source, spec, out)
    assert not (out / "candidate").exists()
    assert json.loads((out / "preflight.json").read_text())["status"] == "failed"
