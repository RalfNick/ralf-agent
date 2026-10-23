import json
import os
import subprocess
import sys

import pytest

from relf_agent import TemporalProfileCatalog


def test_catalog_example_is_offline_without_explicit_service(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "relf_agent.temporal_catalog_example", "--data-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    catalog = TemporalProfileCatalog.from_file(tmp_path / "temporal.json")
    assert len(catalog.profiles) == 2 and catalog.default_profile.version == "1"
    assert all(p.providers["default"]["adapter"] == "offline-echo" for p in catalog.profiles)
    assert set(p.name for p in tmp_path.iterdir()) == {"temporal.json"}


@pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)
def test_catalog_example_keeps_original_receipt_after_default_switch_and_restart(tmp_path):
    command = [
        sys.executable,
        "-m",
        "relf_agent.temporal_catalog_example",
        "--data-dir",
        str(tmp_path),
        "--address",
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
    ]
    answers = []
    for _ in range(2):
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        answer = json.loads(result.stdout.strip().splitlines()[-1])
        assert answer["original_profile"]["version"] == "1"
        assert answer["new_profile"]["version"] == "2"
        assert answer["duplicate_returns_original"] is True
        answers.append(answer)
    assert answers[0] == answers[1]
