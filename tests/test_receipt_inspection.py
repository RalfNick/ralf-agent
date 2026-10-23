import json

import pytest

from relf_agent import SQLiteStore

from .receipt_runtime import create_engine
from .test_cli import cli
from .test_receipt_process_recovery import crash_at, evidence, read_run


@pytest.mark.parametrize(
    "scenario,event,status",
    [
        ("final", "model_response_recorded", "response_received"),
        ("queryable_write", "tool_receipt_recorded", "receipt_received"),
        ("unqueryable_write", "tool_receipt_recorded", "receipt_received"),
    ],
)
@pytest.mark.parametrize("cancel", [False, True])
def test_inspect_explains_saved_evidence_without_querying_or_dispatching(
    tmp_path, scenario, event, status, cancel
):
    database = tmp_path / "recorded.sqlite"
    run_id = crash_at(database, scenario, event)
    if cancel:
        with create_engine(database, scenario) as engine:
            engine.cancel(run_id, command_id="cancel-before-inspect")
    before = read_run(database, run_id)
    business = evidence(database)
    report = json.loads(cli(database, "inspect", run_id).stdout)
    assert len(report["recorded_evidence"]) == 1
    item = report["recorded_evidence"][0]
    assert item["status"] == status and item["evidence_digest"]
    assert report["unresolved_effects"] == []
    assert report["resume_command"]
    text = cli(database, "--format", "text", "inspect", run_id).stdout
    assert "Saved evidence awaiting adoption" in text
    assert "No external request is needed to adopt this saved evidence" in text
    assert read_run(database, run_id) == before and evidence(database) == business
    with SQLiteStore(database, readonly=True) as store:
        assert store.run(run_id)["state"] == ("cancelled" if cancel else "running")
