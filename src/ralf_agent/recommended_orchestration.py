"""Starting definitions using existing policies and managed child execution."""

from .agent_harness import AgentHarness
from .binding_definitions import BoundDefinition
from .errors import ValidationError
from .orchestration_types import DynamicWorkflowSpec, TeamSpec
from .types import AgentSpec


def recommended_harness(
    kind, members=None, *, agent_bindings=None, name=None, version="1", **options
):
    """Freeze a customizable original Plan or Team definition.

    Rule planning and fixed supervisor order work offline. Explicit model
    planning needs a registered planner and a real configured model. Defaults
    provide instructions, not tools, autonomous research or business verification.
    Plan version 2 defaults to a DAG evidence chain: the first member receives
    the task and each later member receives the preceding member's result.
    Explicit planner or plan_mode options retain the original Spec defaults.
    Nested members and binding paths retain the original Spec contracts.
    """
    if kind not in {"plan-and-execute", "team"}:
        raise ValidationError("Recommended harness requires plan-and-execute or team")
    if members is None:
        members = {
            "researcher": AgentSpec(
                "researcher",
                "Analyze the task using available evidence. State missing evidence; do not invent facts.",
            ),
            **(
                {
                    "reviewer": AgentSpec(
                        "reviewer",
                        "Assess the task's constraints and risks using available evidence.",
                    )
                }
                if kind == "team"
                else {}
            ),
            ("synthesizer" if kind == "team" else "writer"): AgentSpec(
                "synthesizer" if kind == "team" else "writer",
                "Produce a clear answer from the task and supplied results. Identify unresolved questions.",
            ),
        }
    if not isinstance(members, dict) or not members:
        raise ValidationError("Recommended harness requires registered members")
    configured = dict(options)
    if kind == "team":
        configured.setdefault("strategy", "supervisor")
        if configured["strategy"] == "supervisor":
            configured.setdefault("strategy_config", {"supervisor": next(reversed(members))})
        spec = TeamSpec
    else:
        if version == "2" and not {"planner", "plan_mode"}.intersection(configured):
            configured["plan_mode"] = "dag"
        spec = DynamicWorkflowSpec
    try:
        definition = spec(
            "ralf." + kind if name is None else name, members, version=version, **configured
        )
    except TypeError as exc:
        raise ValidationError("Unknown recommended orchestration options") from exc
    if agent_bindings is not None:
        definition = BoundDefinition(definition, agent_bindings)
    return AgentHarness(definition)
