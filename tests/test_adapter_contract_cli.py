import importlib.util
import json

import pytest


def api():
    assert importlib.util.find_spec("ralf_agent.adapter_contract_cli"), (
        "Missing installed adapter CLI"
    )
    from ralf_agent.adapter_contract_cli import main

    return main


def test_unconfigured_cli_has_no_testing_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert api()([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run"
    assert report["reason"] == "adapter_not_configured"
    assert len(report["cases"]) == 12
    assert all(case["status"] == "not_verified" for case in report["cases"])
    assert list(tmp_path.iterdir()) == []
    assert report["model_quality"] is None
    assert report["semantic_quality"] is None


def test_unconfigured_cli_does_not_create_evidence_directory(tmp_path, capsys):
    path = tmp_path / "evidence"
    assert api()(["--evidence-dir", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_run"
    assert not path.exists()


def test_unknown_contract_is_public_validation_error(capsys):
    assert api()(["--contract-version", "unsupported"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report == {"status": "invalid", "reason": "invalid_contract_configuration"}


def test_explicit_offline_cli_runs_actual_required_cases(tmp_path, capsys):
    assert api()(["--offline", "--evidence-dir", str(tmp_path / "evidence")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed", report
    assert len(report["cases"]) == 12
    assert all(case["status"] == "passed" for case in report["cases"])
    assert report["model_quality"] is None
    assert report["semantic_quality"] is None


@pytest.mark.parametrize("name", ["AdapterContractSuite", "AdapterContractReport"])
def test_contract_sdk_types_exported(name):
    import ralf_agent

    assert hasattr(ralf_agent, name), f"Missing public SDK export {name}"


def test_public_starter_cli_generates_editable_external_adapter(tmp_path, capsys):
    from ralf_agent.cli import main

    destination = tmp_path / "external-adapter"
    assert main(["init", str(destination), "--template", "adapter-contracts"]) == 0
    project = json.loads(capsys.readouterr().out)
    assert project["template"] == "adapter-contracts"
    code = (destination / "agent_app/adapter.py").read_text()
    assert "class ReferenceSQLiteRetriever:" in code
    assert "from ralf_agent.adapter_contract_reference" not in code
    assert (destination / "runtime.json").is_file()
    assert (destination / "runtime.toml").is_file()


def test_cli_retries_original_owned_cleanup_without_rerunning_case(tmp_path, monkeypatch, capsys):
    import ralf_agent.adapter_contract_reference as reference

    delegate = reference.offline_knowledge_fixture()
    observed = {}

    class Fixture:
        def prepare(self, case_id, workspace):
            assert "case_id" not in observed, "CLI must not repeat a failed case"
            observed["case_id"] = case_id
            session = delegate.prepare(case_id, workspace)
            source = session.resources[0].resource
            close = source.close
            observed["source"] = source
            observed["attempts"] = 0

            def flaky_close():
                observed["attempts"] += 1
                if observed["attempts"] == 1:
                    raise RuntimeError("private cleanup detail")
                return close()

            source.close = flaky_close
            return session

    monkeypatch.setattr(reference, "offline_knowledge_fixture", lambda: Fixture())
    try:
        assert api()(["--offline", "--evidence-dir", str(tmp_path / "evidence")]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "failed"
        assert report["cases"][0]["code"] == "cleanup_failed"
        assert observed["attempts"] == 2
        assert "private cleanup detail" not in json.dumps(report)
        assert observed["source"].audit()["close_calls"] == 1
    finally:
        if "source" in observed:
            observed["source"].close()
