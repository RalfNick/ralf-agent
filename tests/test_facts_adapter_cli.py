"""Installed entry points explicitly select Facts and preserve old role routing."""

import json
from types import ModuleType

import pytest

from ralf_agent.adapter_contract_cli import main


@pytest.mark.parametrize(("profile", "count"), [("core", 10), ("managed", 16)])
def test_cli_without_facts_fixture_is_not_run(profile, count, capsys):
    assert main(["--role", "facts-store", "--profile", profile]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "not_run" and value["role"] == "facts-store"
    assert value["profile"] == profile and value["total"] == count
    assert value["semantic_quality"] is value["model_quality"] is None


def test_cli_invalid_facts_profile_is_safe(capsys):
    assert main(["--role", "facts-store", "--profile", "receipts"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "invalid",
        "reason": "invalid_contract_configuration",
    }


@pytest.mark.parametrize("profile", ["core", "managed"])
def test_explicit_offline_selects_facts_fixture_only(profile, monkeypatch, capsys):
    import sys

    import ralf_agent.adapter_contract_cli as module
    from ralf_agent import AdapterContractCaseResult, AdapterContractReport

    chosen = object()
    calls = []
    reference = ModuleType("ralf_agent.facts_adapter_contract_reference")

    def offline():
        calls.append("facts-fixture")
        return chosen

    reference.offline_facts_fixture = offline
    monkeypatch.setitem(sys.modules, reference.__name__, reference)

    class Suite:
        def __init__(self, *, role, contract_version, profile):
            assert role == "facts-store" and contract_version == "1"
            self.profile = profile

        async def run(self, *, fixture, evidence_dir):
            assert fixture is chosen and evidence_dir is None
            calls.append("run")
            count = 10 if self.profile == "core" else 16
            return AdapterContractReport(
                role="facts-store",
                profile=self.profile,
                cases=tuple(
                    AdapterContractCaseResult(f"F{n:02d}", "passed", "verified")
                    for n in range(1, count + 1)
                ),
            )

        async def aclose(self):
            calls.append("close")

    monkeypatch.setattr(module, "AdapterContractSuite", Suite)
    assert main(["--role", "facts-store", "--profile", profile, "--offline"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "passed" and value["profile"] == profile
    assert calls == ["facts-fixture", "run", "close"]
