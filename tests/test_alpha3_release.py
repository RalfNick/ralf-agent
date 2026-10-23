"""Alpha 3 packaging must retain technical identity and work on PyPI."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_metadata_and_installed_entry_version_agree():
    import ralf_agent

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == ralf_agent.__version__ == "0.1.0a5"
    assert project["name"] == "relf-agent"
    assert project["scripts"]["ralf"] == "ralf_agent.cli:main"
    assert project["description"].startswith("Relf-Agent:")
    assert project["urls"]["Repository"] == "https://github.com/RalfNick/relf-agent"
    assert project["urls"]["Issues"] == "https://github.com/RalfNick/relf-agent/issues"


def test_package_long_description_document_links_resolve_outside_github():
    readme = (ROOT / "README.md").read_text()
    links = re.findall(r"\]\(([^)]+)\)", readme)
    relative = [url for url in links if not url.startswith(("https://", "http://", "#"))]
    assert relative == [], f"PyPI cannot resolve repository-relative links: {relative}"
    assert "0.1.0a5" in readme
    assert "Reliable and Extensible Lifecycle Framework for Intelligent Agents" in readme


def test_frozen_readme_does_not_turn_into_a_false_unpublished_notice_after_upload():
    readme = (ROOT / "README.md").read_text()
    for stale_status in ("尚未推送或发布", "尚未发布到PyPI", "PyPI 尚未发布", "本候选尚未公开发布"):
        assert stale_status not in readme


def test_gate_can_inspect_an_explicit_manifest_without_changing_historical_default(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"version":"0.1.0a3","artifacts":{}}\n')
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/release_gate.py"),
            "--plan",
            "--manifest",
            str(manifest),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0, run.stderr
    import json

    assert json.loads(run.stdout) == {"version": "0.1.0a3", "artifacts": {}}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]
