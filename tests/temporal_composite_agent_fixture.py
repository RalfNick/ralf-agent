"""Network-only composite fixture using production parent/child authorities."""

from relf_agent.temporal_control_activities import select
from relf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME, TemporalParentState
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import digest

from .temporal_agent_fixture import AlreadyStarted, StateClient, worker_runtime


class CompositeClient(StateClient):
    def __init__(self):
        super().__init__()
        self.worker_runtime = worker_runtime()
        self.pumping = False

    async def start_workflow(self, name, accepted, *, id, **options):
        if name != PARENT_WORKFLOW_NAME:
            return await super().start_workflow(name, accepted, id=id, **options)
        if id in self.states or id in self.registries:
            raise AlreadyStarted()
        self.states[id] = TemporalParentState(
            id, accepted["scope"], accepted["command_id"], accepted["request"], accepted["manifest"]
        )
        self.states[id].observation_version = 2
        self.start_entered.set()
        await self.start_gate.wait()
        await self.pump()

    async def advance(self, run_id):
        if not isinstance(self.states[run_id], TemporalParentState):
            await super().advance(run_id)
            # Acknowledgement activities run after manual evidence even when the
            # business Run is cancelled; these fixture tools are all read-only.
            self.states[run_id].pending_acks.clear()
        await self.pump()

    async def pump(self):
        if self.hold_execution or self.pumping:
            return
        self.pumping = True
        try:
            for _ in range(60):
                before = digest([s.diagnostics() for s in self.states.values()])
                for parent in tuple(self.states.values()):
                    if not isinstance(parent, TemporalParentState):
                        continue
                    if parent.state in {"succeeded", "failed", "cancelled"}:
                        for call in parent.children:
                            if call["started"] and not call["settled"]:
                                child = self.states[call["run_id"]]
                                child.command(
                                    "stop:" + parent.run_id + ":" + child.run_id,
                                    {"kind": "cancel", "scope": parent.scope},
                                )
                                if not isinstance(child, TemporalParentState):
                                    await super().advance(child.run_id)
                    elif parent.quiescent and parent.stage in {"select", "plan", "verify"}:
                        kind = "team" if parent.stage == "select" else parent.stage
                        value = await select(
                            self.worker_runtime,
                            {
                                "runtime_manifest": parent.manifest,
                                "definition": parent.definition,
                                "kind": kind,
                                "input": parent.request["input"],
                                "results": parent.results,
                                "planning_request": parent.planning_request()
                                if parent.kind == "dynamic"
                                else None,
                                "planner_snapshot": None,
                            },
                        )
                        if kind == "verify":
                            parent.accept_verification(value)
                        else:
                            parent.accept_selection(value)
                    for call in parent.next_calls():
                        request = call["request"]
                        cls = (
                            TemporalParentState
                            if request["definition"]["kind"] in {"graph", "team", "dynamic"}
                            else TemporalRunState
                        )
                        kwargs = {"depth": call["depth"]} if cls is TemporalParentState else {}
                        self.states[call["run_id"]] = cls(
                            call["run_id"],
                            parent.scope,
                            call["command_id"],
                            request,
                            parent.manifest,
                            **kwargs,
                        )
                        if cls is TemporalParentState:
                            self.states[call["run_id"]].observation_version = 2
                        parent.mark_started(call["run_id"])
                        if cls is TemporalRunState:
                            await super().advance(call["run_id"])
                    for call in parent.children:
                        if call["started"] and not call["settled"]:
                            parent.observe(
                                call["run_id"],
                                {
                                    **self.states[call["run_id"]].diagnostics(),
                                    "scope": parent.scope,
                                },
                            )
                if before == digest([s.diagnostics() for s in self.states.values()]):
                    return
            raise AssertionError("Fixture composite execution did not converge")
        finally:
            self.pumping = False


def definitions():
    import relf_agent as r

    agent = r.AgentSpec("a", "Answer", ("lookup",))
    graph = r.GraphWorkflowSpec("graph", [r.GraphNode("a", agent=agent)])
    return {
        "graph": graph,
        "team": r.TeamSpec("team", {"a": agent}),
        "dynamic": r.DynamicWorkflowSpec(
            "dynamic", {"a": agent}, planner="dag-rule", plan_mode="dag"
        ),
        "plan": r.DynamicWorkflowSpec("plan", {"a": agent}),
        "nested": r.TeamSpec("outer", {"inner": graph}, child_budget=24),
    }
