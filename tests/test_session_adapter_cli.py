import json

import pytest

from ralf_agent.adapter_contract_cli import main


@pytest.mark.parametrize("profile,count", [("core", 10), ("receipts", 14)])
def test_session_cli_without_fixture_is_explicit_and_has_no_io(
    profile, count, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "not-created"
    assert main(["--role", "session-store", "--profile", profile, "--evidence-dir", str(path)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert (value["role"], value["profile"], value["status"]) == (
        "session-store",
        profile,
        "not_run",
    )
    assert value["not_verified"] == value["total"] == count
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_knowledge_receipt_profile_without_importing_fixture(monkeypatch, capsys):
    import ralf_agent.adapter_contract_reference as reference

    def forbidden():
        pytest.fail("Invalid contract constructed a testing fixture")

    monkeypatch.setattr(reference, "offline_knowledge_fixture", forbidden)
    assert main(["--profile", "receipts", "--offline"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "invalid",
        "reason": "invalid_contract_configuration",
    }


@pytest.mark.parametrize(
    "name",
    [
        "SessionAdapterFixture",
        "SessionContractAddress",
        "SessionContractResource",
        "SessionContractPause",
        "SessionContractSession",
        "offline_session_fixture",
    ],
)
def test_session_contract_extension_is_public_sdk(name):
    import ralf_agent

    assert hasattr(ralf_agent, name), f"Missing public Session adapter type: {name}"


def test_explicit_offline_session_receipt_check(tmp_path, capsys):
    assert (
        main(
            [
                "--role",
                "session-store",
                "--profile",
                "receipts",
                "--offline",
                "--evidence-dir",
                str(tmp_path / "evidence"),
            ]
        )
        == 0
    )
    value = json.loads(capsys.readouterr().out)
    assert (value["status"], value["total"], value["passed"]) == ("passed", 14, 14)
    assert value["model_quality"] is value["semantic_quality"] is None


def test_session_contract_starter_public_template(tmp_path):
    from ralf_agent.starter import create_starter

    project = create_starter(tmp_path / "app", template="session-contracts")
    assert project.module == "agent_app"
    assert project.factory == "agent_app.runtime:create_engine"
    source = (tmp_path / "app" / "agent_app/adapter.py").read_text()
    assert "class ReferenceSQLiteSessionStore:" in source
    assert "ralf_agent.session_adapter_contract_reference" not in source
