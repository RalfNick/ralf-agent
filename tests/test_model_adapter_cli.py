"""Model CLI selection is additive and never chooses a model implicitly."""

import json
import sys
from types import ModuleType

import pytest

from relf_agent.adapter_contract_cli import main


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("tools", 16)])
def test_unconfigured_model_cli_is_not_run(profile, count, tmp_path, capsys):
    destination = tmp_path / "not-allocated"
    assert (
        main(["--role", "model-provider", "--profile", profile, "--evidence-dir", str(destination)])
        == 0
    )
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "not_run" and value["role"] == "model-provider"
    assert value["profile"] == profile and value["total"] == value["not_verified"] == count
    assert value["model_quality"] is value["semantic_quality"] is None
    assert not destination.exists()


@pytest.mark.parametrize("profile", ["receipts", "managed", "stream", "native-history", ""])
def test_invalid_model_cli_profile_has_no_testing_io(profile, tmp_path, capsys):
    destination = tmp_path / "not-allocated"
    assert (
        main(
            [
                "--role",
                "model-provider",
                "--profile",
                profile,
                "--offline",
                "--evidence-dir",
                str(destination),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {
        "status": "invalid",
        "reason": "invalid_contract_configuration",
    }
    assert not destination.exists()


@pytest.mark.parametrize("profile", ["core", "tools"])
def test_explicit_model_offline_dispatches_only_model_fixture(profile, monkeypatch, capsys):
    import relf_agent.adapter_contract_cli as module
    from relf_agent import AdapterContractCaseResult, AdapterContractReport

    chosen, calls = object(), []
    reference = ModuleType("relf_agent.model_adapter_contract_reference")

    def offline():
        calls.append("model-fixture")
        return chosen

    reference.offline_model_fixture = offline
    monkeypatch.setitem(sys.modules, reference.__name__, reference)

    class Suite:
        def __init__(self, *, role, contract_version, profile):
            assert role == "model-provider" and contract_version == "1"
            self.profile = profile

        async def run(self, *, fixture, evidence_dir):
            assert fixture is chosen and evidence_dir is None
            calls.append("run")
            count = 10 if self.profile == "core" else 16
            return AdapterContractReport(
                role="model-provider",
                profile=self.profile,
                cases=tuple(
                    AdapterContractCaseResult(f"P{n:02d}", "passed", "verified")
                    for n in range(1, count + 1)
                ),
            )

        async def aclose(self):
            calls.append("close")

    monkeypatch.setattr(module, "AdapterContractSuite", Suite)
    assert main(["--role", "model-provider", "--profile", profile, "--offline"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert calls == ["model-fixture", "run", "close"]
