"""Typed reference answers are explicit and validated before clients are created."""

import asyncio
import json

import pytest

from relf_agent.errors import ValidationError
from relf_agent.rag_evaluation_cli import arguments, main, run


def test_typed_answer_option_keeps_legacy_default():
    assert arguments([]).typed_answers is False
    assert arguments(["--typed-answers"]).typed_answers is True


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_invalid_typed_answers_are_refused_before_clients(value, monkeypatch, tmp_path):
    import relf_agent.rag_evaluation_cli as cli

    args = arguments(["--provider", "openai"])
    args.typed_answers = value
    args.evidence_dir = str(tmp_path / "evidence")

    def refuse(*args, **kwargs):
        pytest.fail("Invalid answer selection constructed a provider")

    monkeypatch.setattr(cli, "_http_provider", refuse)
    with pytest.raises(ValidationError):
        asyncio.run(run(args))
    assert not (tmp_path / "evidence").exists()


def test_offline_typed_answers_keep_fixture_quality_unknown(tmp_path, capsys):
    assert main(["--offline", "--typed-answers", "--evidence-dir", str(tmp_path / "evidence")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["typed_answers"] is True
    assert report["passed"] == report["total"] == 8
    assert report["model_quality"] is report["semantic_quality"] is None
