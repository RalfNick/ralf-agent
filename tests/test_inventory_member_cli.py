"""Reference member verification is explicit and preflighted before model I/O."""

import asyncio
import json

import pytest

from relf_agent.errors import ValidationError
from relf_agent.orchestration_evaluation_cli import arguments, main, run


def test_cli_selects_member_verification_without_changing_legacy_default():
    assert arguments([]).member_verification is False
    selected = arguments(["--member-verification", "--completion-gate"])
    assert selected.member_verification is True
    assert selected.completion_gate is True


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_invalid_member_selection_refuses_before_provider_or_evidence(value, monkeypatch, tmp_path):
    import relf_agent.orchestration_evaluation_cli as cli

    args = arguments(["--provider", "openai", "--completion-gate"])
    args.member_verification = value
    args.evidence_dir = str(tmp_path / "evidence")

    def refuse(*args, **kwargs):
        pytest.fail("Invalid verification selection reached Provider construction")

    monkeypatch.setattr(cli, "_http_provider", refuse)
    with pytest.raises(ValidationError):
        asyncio.run(run(args))
    assert not (tmp_path / "evidence").exists()


def test_member_verification_requires_parent_gate_before_provider_construction(monkeypatch):
    import relf_agent.orchestration_evaluation_cli as cli

    args = arguments(["--provider", "openai", "--member-verification"])

    def refuse(*args, **kwargs):
        pytest.fail("Missing parent gate reached Provider construction")

    monkeypatch.setattr(cli, "_http_provider", refuse)
    with pytest.raises(ValidationError):
        asyncio.run(run(args))


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_original_offline_business_chain_selects_both_gates(kind, tmp_path, capsys):
    assert (
        main(
            [
                "--offline",
                "--kind",
                kind,
                "--member-verification",
                "--completion-gate",
                "--max-calls",
                "32",
                "--evidence-dir",
                str(tmp_path / "evidence"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["member_verification"] is True
    assert report["passed"] == report["total"] == 5
    assert report["model_quality"] is None
    assert all(row["checks"]["parent_completion"] for row in report["cases"])
