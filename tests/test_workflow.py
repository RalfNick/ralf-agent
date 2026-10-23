"""Behavior contracts for the public static-plan boundary."""

import pytest

import relf_agent
from relf_agent import AgentSpec, WorkflowSpec
from relf_agent.errors import ValidationError


@pytest.fixture
def wf():
    class PublicAPI:
        def __getattr__(self, name):
            value = getattr(relf_agent, name, None)
            assert callable(value), f"Public static Workflow API is missing: {name}"
            return value

    return PublicAPI()


def graph(wf, nodes, **options):
    return wf.StaticWorkflowCompiler().compile(wf.GraphWorkflowSpec("flow", nodes, **options))


def pending(plan):
    return {node["id"]: {"state": "pending"} for node in plan.to_dict()["nodes"]}


def test_agent_and_sequence_compile_to_same_plan_format(wf):
    compiler = wf.StaticWorkflowCompiler()
    agent = AgentSpec("answer", "Return evidence.")
    solo = compiler.compile(agent)
    sequence = compiler.compile(WorkflowSpec("flow", (agent, agent)))
    assert solo.to_dict()["format"] == sequence.to_dict()["format"] == "ralf-static-plan"
    assert solo.to_dict()["schema_version"] == 1
    state = pending(sequence)
    selection = wf.StaticWorkflowInterpreter().select(sequence, "task", state)
    assert selection.node_id == "step-0" and selection.input == "task"
    state["step-0"] = {"state": "completed", "result": "evidence"}
    selection = wf.StaticWorkflowInterpreter().select(sequence, "task", state)
    assert selection.node_id == "step-1" and selection.input == "evidence"
    state["step-1"] = {"state": "completed", "result": "answer"}
    selection = wf.StaticWorkflowInterpreter().select(sequence, "task", state)
    assert selection.done and selection.result == "answer"


def test_out_of_order_graph_resolves_typed_input_mapping(wf):
    plan = graph(
        wf,
        [
            wf.GraphNode(
                "report",
                agent=AgentSpec("report", "Report"),
                depends_on=("read",),
                input=wf.InputMap(
                    {"value": wf.ValueRef("read", ("items", 0)), "constant": wf.Literal(False)}
                ),
            ),
            wf.GraphNode("read", transform="identity"),
        ],
    )
    state = pending(plan)
    first = wf.StaticWorkflowInterpreter().select(plan, {"items": [0]}, state)
    assert first.node_id == "read" and first.input == {"items": [0]}
    state["read"] = {"state": "completed", "result": {"items": [0]}}
    second = wf.StaticWorkflowInterpreter().select(plan, {}, state)
    assert second.node_id == "report" and second.input == {"value": 0, "constant": False}


def test_condition_skips_branch_and_required_dependents(wf):
    plan = graph(
        wf,
        [
            wf.GraphNode(
                "left", transform="identity", when=wf.BranchCondition(wf.ValueRef(), "left")
            ),
            wf.GraphNode("child", transform="identity", depends_on=("left",)),
            wf.GraphNode(
                "right",
                transform="identity",
                when=wf.BranchCondition(wf.ValueRef(), "left", negate=True),
            ),
        ],
    )
    selection = wf.StaticWorkflowInterpreter().select(plan, "right", pending(plan))
    assert selection.node_id == "right"
    assert selection.skipped == ("left", "child")


def test_optional_branch_join_preserves_null_and_declared_defaults(wf):
    plan = graph(
        wf,
        [
            wf.GraphNode("left", transform="identity"),
            wf.GraphNode("right", transform="identity"),
            wf.GraphNode(
                "join",
                transform="identity",
                depends_on=("left", "right"),
                allow_skipped_dependencies=True,
                input=wf.InputMap(
                    {
                        "left": wf.ValueRef("left", required=False, default="absent"),
                        "right": wf.ValueRef("right", required=False, default="absent"),
                    }
                ),
            ),
        ],
    )
    state = pending(plan)
    state["left"] = {"state": "skipped"}
    state["right"] = {"state": "completed", "result": None}
    result = wf.StaticWorkflowInterpreter().select(plan, "x", state)
    assert result.node_id == "join"
    assert result.input == {"left": "absent", "right": None}


@pytest.mark.parametrize(
    "value,equals,skipped", [(True, 1, True), (False, 0, True), (None, None, False), (1, 1, False)]
)
def test_conditions_use_json_types(wf, value, equals, skipped):
    plan = graph(
        wf,
        [wf.GraphNode("a", transform="identity", when=wf.BranchCondition(wf.ValueRef(), equals))],
    )
    selection = wf.StaticWorkflowInterpreter().select(plan, value, pending(plan))
    assert bool(selection.skipped) is skipped
    assert selection.done is skipped


@pytest.mark.parametrize(
    "data,path", [({}, ("missing",)), ({"x": None}, ("x", "child")), ([], (0,)), ({"0": "x"}, (0,))]
)
def test_required_binding_rejects_missing_or_wrong_container(wf, data, path):
    plan = graph(wf, [wf.GraphNode("a", transform="identity", input=wf.ValueRef(path=path))])
    with pytest.raises(ValidationError, match="reference"):
        wf.StaticWorkflowInterpreter().select(plan, data, pending(plan))


def test_optional_binding_has_detached_fallback(wf):
    fallback = {"values": []}
    plan = graph(
        wf,
        [
            wf.GraphNode(
                "a",
                transform="identity",
                input=wf.ValueRef(path=("missing",), required=False, default=fallback),
            )
        ],
    )
    fallback["values"].append(1)
    selection = wf.StaticWorkflowInterpreter().select(plan, {}, pending(plan))
    assert selection.input == {"values": []}
    selection.input["values"].append(2)
    assert wf.StaticWorkflowInterpreter().select(plan, {}, pending(plan)).input == {"values": []}


def test_plan_and_source_declarations_are_detached_snapshots(wf):
    source = {"field": wf.Literal({"nested": []})}
    spec = wf.GraphWorkflowSpec(
        "flow", [wf.GraphNode("a", transform="identity", input=wf.InputMap(source))]
    )
    source["field"].value["nested"].append(1)
    plan = wf.StaticWorkflowCompiler().compile(spec)
    encoded = plan.to_dict()
    encoded["nodes"][0]["input"]["fields"]["field"]["value"]["nested"].append(2)
    assert plan.to_dict()["nodes"][0]["input"]["fields"]["field"]["value"] == {"nested": []}
    assert wf.ExecutionPlan(plan.to_dict()).identity == plan.identity


@pytest.mark.parametrize(
    "case",
    ["duplicate", "unknown", "cycle", "self", "duplicate-dep", "non-ancestor", "unknown-ref"],
)
def test_invalid_graph_structure_rejects_before_execution(wf, case):
    node = wf.GraphNode
    cases = {
        "duplicate": [node("a", transform="identity"), node("a", transform="identity")],
        "unknown": [node("a", transform="identity", depends_on=("missing",))],
        "cycle": [
            node("a", transform="identity", depends_on=("b",)),
            node("b", transform="identity", depends_on=("a",)),
        ],
        "self": [node("a", transform="identity", depends_on=("a",))],
        "duplicate-dep": [
            node("a", transform="identity"),
            node("b", transform="identity", depends_on=("a", "a")),
        ],
        "non-ancestor": [
            node("a", transform="identity"),
            node("b", transform="identity", input=wf.ValueRef("a")),
        ],
        "unknown-ref": [node("a", transform="identity", input=wf.ValueRef("missing"))],
    }
    with pytest.raises(ValidationError):
        graph(wf, cases[case])


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"agent": AgentSpec("a", "x"), "transform": "identity"},
        {"transform": ""},
        {"transform": "identity", "allow_skipped_dependencies": 1},
        {"agent": AgentSpec("a", "x"), "config": {"x": 1}},
        {"transform": "identity", "output_schema": {"type": "invalid"}},
    ],
)
def test_node_configuration_is_strict(wf, options):
    with pytest.raises(ValidationError):
        wf.GraphNode("a", **options)


@pytest.mark.parametrize("node_id", ["", "input", "a b", "../a", "a" * 65, 12])
def test_node_ids_are_stable_identifiers(wf, node_id):
    with pytest.raises(ValidationError):
        wf.GraphNode(node_id, transform="identity")


@pytest.mark.parametrize("path", [(True,), (-1,), (1.5,), tuple("x" for _ in range(33))])
def test_reference_path_limits_are_strict(wf, path):
    with pytest.raises(ValidationError):
        wf.ValueRef(path=path)


def test_plan_limits_and_unknown_ir_fields_reject(wf):
    with pytest.raises(ValidationError):
        graph(wf, [wf.GraphNode(f"n{i}", transform="identity") for i in range(257)])
    with pytest.raises(ValidationError):
        graph(wf, [wf.GraphNode("a", transform="identity", input=wf.Literal("x" * 1048576))])
    plan = graph(wf, [wf.GraphNode("a", transform="identity")])
    encoded = plan.to_dict()
    encoded["schema_version"] = 2
    with pytest.raises(ValidationError):
        wf.ExecutionPlan(encoded)
    encoded = plan.to_dict()
    encoded["unexpected"] = True
    with pytest.raises(ValidationError):
        wf.ExecutionPlan(encoded)


def test_output_binding_and_default_result_map(wf):
    nodes = [wf.GraphNode("a", transform="identity"), wf.GraphNode("b", transform="identity")]
    state = {"a": {"state": "completed", "result": None}, "b": {"state": "skipped"}}
    default = wf.StaticWorkflowInterpreter().select(graph(wf, nodes), "task", state)
    assert default.done and default.result == {"a": None}
    explicit = wf.StaticWorkflowInterpreter().select(
        graph(wf, nodes, output=wf.ValueRef("a"), output_schema={"type": "null"}), "task", state
    )
    assert explicit.done and explicit.result is None
    with pytest.raises(ValidationError):
        wf.StaticWorkflowInterpreter().select(
            graph(wf, nodes, output=wf.ValueRef("a"), output_schema={"type": "string"}),
            "task",
            state,
        )


def test_incomplete_or_invalid_state_cannot_finish(wf):
    plan = graph(wf, [wf.GraphNode("a", transform="identity")])
    for state in [
        {},
        {"a": {"state": "completed"}},
        {"a": {"state": "invented"}},
        {"a": {"state": "running"}},
    ]:
        with pytest.raises(ValidationError):
            wf.StaticWorkflowInterpreter().select(plan, "task", state)


def test_identity_transform_only_accepts_empty_config(wf):
    source = {"x": []}
    value = wf.IdentityTransform().transform(source, {})
    value["x"].append(1)
    assert source == {"x": []}
    with pytest.raises(ValidationError):
        wf.IdentityTransform().transform(source, {"unknown": True})


def test_legacy_sequence_can_explicitly_opt_into_graph_ir(wf):
    sequence = WorkflowSpec("flow", (AgentSpec("first", "Read"), AgentSpec("second", "Report")))
    plan = wf.StaticWorkflowCompiler().compile(sequence)
    graph_spec = wf.GraphWorkflowSpec.from_plan(plan)
    assert graph_spec.name == "flow" and graph_spec.version == "1"
    assert graph_spec.nodes[1].depends_on == ("step-0",)
    assert wf.StaticWorkflowCompiler().compile(graph_spec).identity == plan.identity
