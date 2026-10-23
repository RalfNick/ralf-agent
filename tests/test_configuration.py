import pytest

from relf_agent import AgentSpec, Scope, WorkflowSpec
from relf_agent.errors import ValidationError
from relf_agent.types import credits


@pytest.mark.parametrize("field", ["name", "instructions", "provider", "version"])
@pytest.mark.parametrize("value", [None, 7, "   "])
def test_agent_text_configuration_is_validated_before_submit(field, value):
    arguments = {"name": "agent", "instructions": "Complete a task", field: value}
    with pytest.raises(ValidationError):
        AgentSpec(**arguments)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_decisions", True),
        ("max_decisions", 1.5),
        ("max_decisions", "8"),
        ("max_decisions", 0),
        ("max_context_chars", True),
        ("max_context_chars", 256.5),
        ("max_context_chars", "32000"),
        ("max_context_chars", 255),
    ],
)
def test_agent_limits_are_strict_integers(field, value):
    with pytest.raises(ValidationError):
        AgentSpec("agent", "Complete a task", **{field: value})


@pytest.mark.parametrize("tools", ["lookup", ["lookup", "lookup"], [""], [7], None])
def test_agent_tools_are_an_unambiguous_unique_sequence(tools):
    with pytest.raises(ValidationError):
        AgentSpec("agent", "Complete a task", tools=tools)


def test_agent_tool_lists_are_frozen_without_retaining_the_caller_list():
    names = ["lookup"]
    spec = AgentSpec("agent", "Complete a task", tools=names)
    names.append("write")
    assert spec.tools == ("lookup",)


@pytest.mark.parametrize("schema", [{"type": "not-a-schema-type"}, {"required": "field"}, 42])
def test_output_schema_is_validated_at_definition_time(schema):
    with pytest.raises(ValidationError):
        AgentSpec("agent", "Complete a task", output_schema=schema)


def test_output_schema_is_copied_from_caller_configuration():
    schema = {"type": "object", "required": ["answer"]}
    spec = AgentSpec("agent", "Complete a task", output_schema=schema)
    schema["required"].append("changed")
    assert spec.output_schema == {"type": "object", "required": ["answer"]}


@pytest.mark.parametrize("field", ["workspace", "principal"])
@pytest.mark.parametrize("value", [None, 7, "  "])
def test_scope_rejects_invalid_text(field, value):
    with pytest.raises(ValidationError):
        Scope(**{field: value})


def test_workflow_step_lists_are_frozen():
    first = AgentSpec("first", "Return evidence")
    steps = [first]
    flow = WorkflowSpec("flow", steps)
    steps.append(AgentSpec("second", "Summarize"))
    assert flow.steps == (first,)


@pytest.mark.parametrize(
    "arguments", [{"name": 7}, {"version": 7}, {"steps": "agent"}, {"steps": []}]
)
def test_workflow_configuration_errors_are_typed(arguments):
    parameters = {"name": "flow", "steps": [AgentSpec("agent", "Complete")], **arguments}
    with pytest.raises(ValidationError):
        WorkflowSpec(**parameters)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_credit_validation_has_a_public_error_and_keeps_valueerror_compatibility(value):
    with pytest.raises(ValidationError) as failure:
        credits(value)
    assert isinstance(failure.value, ValueError)
