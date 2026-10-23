import subprocess
import sys

from relf_agent import TemporalProfileCatalog


def test_installed_module_writes_offline_configuration_without_sdk_or_service(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "relf_agent.temporal_profile_example", "--data-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    profile = TemporalProfileCatalog.from_file(tmp_path / "temporal.toml").default_profile
    assert profile.providers["default"]["adapter"] == "offline-echo"
    assert profile.execution["context_reads"] and profile.execution["composite_sessions"]
    assert set(path.name for path in tmp_path.iterdir()) == {"temporal.toml"}
