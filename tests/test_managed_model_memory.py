import importlib

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, MemoryAdmissionPolicy, ModelResponse
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.model_evidence import snapshot_model_response
from tests.test_managed_memory_stage import engine


def policy(memory=None, **kwargs):
    cls = importlib.import_module("ralf_agent.managed_model_memory").ManagedModelMemoryPolicy
    return cls(memory or InMemoryMemory(backend_id="model-facts"), **kwargs)


def test_model_only_selects_grounded_host_fields():
    stage = policy(
        admission=MemoryAdmissionPolicy(
            {"name": ("result", "name"), "transient": ("result", "temp")}
        )
    )
    source = {"result": {"name": "Alice", "temp": 1}}
    request = stage.request(source)
    assert request.tools == [] and "memory-field-selector:" in request.messages[0]["content"]
    proposals = stage.select(
        source, snapshot_model_response(ModelResponse(output={"keys": ["name"]}))
    )
    assert proposals[0].to_dict() == {
        "key": "name",
        "value": "Alice",
        "source_path": ["result", "name"],
    }
    assert stage.select(source, snapshot_model_response(ModelResponse(output={"keys": []}))) == []
    with pytest.raises(ValidationError):
        stage.propose(source)


@pytest.mark.parametrize(
    "output",
    [
        {"keys": ["unknown"]},
        {"keys": ["result", "result"]},
        {"keys": ["result"], "value": "invented"},
        None,
    ],
)
def test_untrusted_model_cannot_assign_values_or_unknown_fields(output):
    stage = policy()
    with pytest.raises(ValidationError):
        stage.select({"result": "source"}, snapshot_model_response(ModelResponse(output=output)))


def test_model_policy_limits_and_hooks_are_pinned():
    stage = policy(max_context_chars=1024)
    with pytest.raises(ValidationError):
        stage.request({"result": "x" * 3000})
    stage.select = lambda *args: []
    with pytest.raises(DefinitionMismatch):
        _ = stage.identity


def test_model_selector_admission_pins_host_provider_and_schema9(tmp_path):
    with engine(tmp_path / "run.sqlite", stage_policy=policy()) as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        m = local.diagnostics(h.run_id).manifest["managed_memory"]
        assert m["selector_provider"] == local.providers["default"].identity
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "9"


def test_missing_host_alias_refuses_without_schema_upgrade(tmp_path):
    with engine(tmp_path / "run.sqlite", stage_policy=policy(provider="missing")) as local:
        with pytest.raises(DefinitionMismatch):
            local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "1"


@pytest.mark.parametrize("limit", [True, 0, 100000000])
def test_selector_input_limit_is_bounded_integer(limit):
    with pytest.raises(ValidationError):
        policy(max_context_chars=limit)


def test_advanced_model_stages_are_refused_before_activation(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec

    with engine(tmp_path / "run.sqlite", stage_policy=policy()) as local:
        with pytest.raises(ValidationError):
            local.submit(
                GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
                "q",
                command_id="s",
            )
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "1"
