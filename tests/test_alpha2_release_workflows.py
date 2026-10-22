"""The current Alpha gate must not run historical inputs or publish by itself."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_COMMIT = "dfb066e111b2ca9cbace7b4c29fb4abdacd04e9b"


@pytest.mark.parametrize("name", ["alpha2-release-gate.yml", "alpha2-stage-candidate.yml"])
def test_alpha2_workflows_are_manual_and_pin_accepted_tools(name):
    path = ROOT / ".github/workflows" / name
    assert path.is_file(), "a2 requires an independent manual workflow"
    text = path.read_text()
    assert '"on":\n  workflow_dispatch:' in text
    assert "pull_request:" not in text and "\n  push:" not in text
    assert f"ref: {TOOLS_COMMIT}" in text
    checkout_ref = next(line.strip().split()[1] for line in text.splitlines() if "ref: " in line)
    assert len(checkout_ref) == 40 and checkout_ref.startswith(TOOLS_COMMIT)
    assert "persist-credentials: false" in text
    assert "github.repository == 'RalfNick/ralf-agent'" in text
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "ralf-alpha2-original-candidate" in text
    assert "ralf-alpha1-original-candidate" not in text
    assert "0.1.0a1" not in text


def test_alpha2_native_gate_keeps_original_resource_and_install_contract():
    path = ROOT / ".github/workflows/alpha2-release-gate.yml"
    assert path.is_file()
    text = path.read_text()
    for required in [
        "contents: read",
        "actions: read",
        "runs-on: ubuntu-24.04",
        "cancel-in-progress: false",
        "request['RUNNER_OS'] == 'Linux' and request['RUNNER_ARCH'] == 'X64'",
        "for minor in 3.11 3.12 3.13; do",
        "--only-binary=:all: --no-deps --require-hashes",
        "-r tools/release_gate_requirements.lock",
        "tools/run_release_gate_linux.py --platform linux/amd64 --require-native",
        "ralf_agent-0.1.0a2-py3-none-any.whl",
        "ralf_agent-0.1.0a2.tar.gz",
        '--output "$RUNNER_TEMP/alpha2-evidence/native-amd64"',
        "if: always()",
    ]:
        assert required in text
    assert "contents: write" not in text
    assert "releases" not in text
    assert "pip install ralf-agent" not in text
    assert "matrix:" not in text
