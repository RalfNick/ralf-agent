"""Private draft transport cannot silently publish or substitute Alpha inputs."""

import hashlib
import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def staging(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "stage_alpha1_candidate", ROOT / "tools/stage_alpha1_candidate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs():
    content = {"original.whl": b"wheel", "original.tar.gz": b"sdist"}
    spec = {
        "version": "0.1.0a1",
        "artifacts": {n: hashlib.sha256(v).hexdigest() for n, v in content.items()},
    }
    release = {
        "id": 17,
        "draft": True,
        "published_at": None,
        "tag_name": "ralf-alpha1-private-stage-test",
        "assets": [
            {"id": i, "name": n, "size": len(v), "state": "uploaded"}
            for i, (n, v) in enumerate(content.items(), 1)
        ],
    }
    blobs = {a["id"]: content[a["name"]] for a in release["assets"]}
    return spec, release, blobs


def test_private_stage_accepts_only_exact_original_bytes(staging, inputs, tmp_path):
    spec, release, blobs = inputs
    out = tmp_path / "new"
    receipt = staging.stage(17, out, spec, lambda _: release, blobs.__getitem__)
    assert receipt["status"] == "verified_original_candidate"
    assert receipt["draft"] is True
    assert receipt["artifacts"] == spec["artifacts"]
    assert {p.name for p in (out / "candidate").iterdir()} == set(spec["artifacts"])


@pytest.mark.parametrize(
    "drift",
    [
        "published",
        "publication_date",
        "release_id",
        "foreign_tag",
        "extra_asset",
        "duplicate",
        "size",
        "bytes",
        "not_uploaded",
    ],
)
def test_private_stage_rejects_wrong_source_without_exposing_candidate(
    staging, inputs, tmp_path, drift
):
    spec, release, blobs = inputs
    if drift == "published":
        release["draft"] = False
    elif drift == "publication_date":
        release["published_at"] = "2026-10-20"
    elif drift == "release_id":
        release["id"] = 18
    elif drift == "foreign_tag":
        release["tag_name"] = "0.1.0a1"
    elif drift == "extra_asset":
        release["assets"].append({"id": 3, "name": "extra"})
    elif drift == "duplicate":
        release["assets"][1]["name"] = release["assets"][0]["name"]
    elif drift == "size":
        release["assets"][0]["size"] += 1
    elif drift == "bytes":
        blobs[1] = b"wrong"
    else:
        release["assets"][0]["state"] = "new"
    out = tmp_path / drift
    with pytest.raises(RuntimeError):
        staging.stage(17, out, spec, lambda _: release, blobs.__getitem__)
    assert not (out / "candidate").exists()
    assert json.loads((out / "proof.json").read_text())["status"] == "failed"


def test_asset_redirect_strips_authorization(staging):
    request = urllib.request.Request(
        "https://api.github.com/repos/RalfNick/ralf-agent/releases/assets/1",
        headers={"Authorization": "Bearer private"},
    )
    redirected = staging.AssetRedirect().redirect_request(
        request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/asset"
    )
    assert redirected.get_header("Authorization") is None
    with pytest.raises(RuntimeError, match="unsafe_asset_redirect"):
        staging.AssetRedirect().redirect_request(
            request, None, 302, "Found", {}, "http://example.com/asset"
        )


def test_alpha2_stage_accepts_its_exact_private_draft(staging, inputs, tmp_path):
    spec, release, blobs = inputs
    spec["version"] = "0.1.0a2"
    release["tag_name"] = "ralf-alpha2-private-stage-test"
    receipt = staging.stage(17, tmp_path / "a2", spec, lambda _: release, blobs.__getitem__)
    assert receipt["status"] == "verified_original_candidate"
    assert receipt["artifacts"] == spec["artifacts"]


def test_alpha3_stage_accepts_its_own_frozen_bytes(staging, inputs, tmp_path):
    spec, release, blobs = inputs
    spec["version"] = "0.1.0a3"
    release["tag_name"] = "ralf-alpha3-private-stage-test"
    receipt = staging.stage(17, tmp_path / "a3", spec, lambda _: release, blobs.__getitem__)
    assert receipt["status"] == "verified_original_candidate"
    assert receipt["artifacts"] == spec["artifacts"]


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.1.0a2", "ralf-alpha1-private-stage-test"),
        ("0.1.0a1", "ralf-alpha2-private-stage-test"),
        ("0.1.0a3", "ralf-alpha1-private-stage-test"),
    ],
)
def test_private_stage_rejects_cross_version_or_unknown_alpha(
    staging, inputs, tmp_path, version, tag
):
    spec, release, blobs = inputs
    spec["version"] = version
    release["tag_name"] = tag
    output = tmp_path / "rejected"
    with pytest.raises(RuntimeError, match="private_staging_release_mismatch"):
        staging.stage(17, output, spec, lambda _: release, blobs.__getitem__)
    assert not (output / "candidate").exists()
    assert json.loads((output / "proof.json").read_text())["status"] == "failed"
