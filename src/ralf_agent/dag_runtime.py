"""Accepted DAG state and patches; only the parent Engine commits execution."""

import copy

from .dag_planning import DAGProposal, PlanningConclusion
from .errors import ValidationError
from .orchestration_types import ChildCall
from .types import canonical, digest
from .workflow import StaticWorkflowCompiler, _choices, _resolve, validate_output

CLOSED = {"succeeded", "failed", "cancelled", "cancelling"}


class DAGRuntime:
    def __init__(self, orchestration):
        self.orchestration = orchestration
        self.engine = orchestration.engine

    def _validate(self, run, proposal):
        proposal.validate_members(run["definition"]["members"])
        remaining = run["definition"]["max_steps"] - len(run["orchestration"]["children"])
        if len(proposal.nodes) > remaining:
            raise ValidationError("DAG exceeds the remaining child step allowance")

    def adopt(self, run):
        state = run["orchestration"]
        value = state["proposal"]
        if value.get("status") in {"refused", "needs_input"}:
            conclusion = PlanningConclusion(**value)
            state["revisions"].append(
                {
                    "revision": state["revision"],
                    "proposal": value,
                    "conclusion": conclusion.to_dict(),
                }
            )
            self.engine._commit(run, "planning_conclusion_adopted")
            return False
        proposal = DAGProposal.from_dict(value)
        self._validate(run, proposal)
        state["plan_revision"] = state.get("plan_revision", -1) + 1
        state["dag"] = {
            "proposal": proposal.to_dict(),
            "plan": StaticWorkflowCompiler().compile(proposal.graph()).to_dict(),
            "nodes": {node["id"]: {"state": "pending"} for node in proposal.nodes},
        }
        state["revisions"].append(
            {
                "revision": state["revision"],
                "plan_revision": state["plan_revision"],
                "proposal": proposal.to_dict(),
                "digest": digest(proposal.to_dict()),
            }
        )
        state["stage"] = "execute"
        self.engine._commit(run, "plan_revision_adopted")
        return True

    def _observe(self, run_id):
        run = self.orchestration.observe(run_id)
        if run["state"] in CLOSED:
            return run
        state, changed = run["orchestration"], False
        for record in state["dag"]["nodes"].values():
            if "call_id" not in record:
                continue
            call = next(c for c in state["children"] if c["id"] == record["call_id"])
            child = self.engine._authorized(call["run_id"])
            if child["state"] == "succeeded":
                proposal_node = next(
                    node
                    for node in state["dag"]["proposal"]["nodes"]
                    if state["dag"]["nodes"][node["id"]] is record
                )
                result = validate_output(child["result"], proposal_node["output_schema"])
                if record.get("state") != "completed":
                    record.update(state="completed", result=result)
                    changed = True
        if changed:
            with self.engine.store.transaction():
                self.engine._commit(run, "dag_nodes_completed")
        return run

    async def execute(self, run_id):
        from .orchestration import ChildRunFailed
        from .workflow import ExecutionPlan

        engine, attempted = self.engine, set()
        while True:
            run = self._observe(run_id)
            if run["state"] in CLOSED:
                return False
            state, dag = run["orchestration"], run["orchestration"]["dag"]
            if any(c["state"] in {"failed", "cancelled"} for c in state["children"]):
                raise ChildRunFailed("A DAG child did not succeed")
            pending = [
                c
                for c in state["children"]
                if c["state"] not in {"succeeded", "failed", "cancelled"}
            ]
            choices = copy.deepcopy(dag["nodes"])
            for record in choices.values():
                if record["state"] == "running":
                    call = next(c for c in pending if c["id"] == record["call_id"])
                    if call["state"] in {
                        "waiting_approval",
                        "waiting_reconciliation",
                        "outcome_unknown",
                    }:
                        record["state"] = (
                            "waiting_approval"
                            if call["state"] == "waiting_approval"
                            else "waiting_reconciliation"
                        )
            ready, skipped, settled, result = _choices(
                ExecutionPlan(dag["plan"]), run["input"], choices, parallel=True
            )
            if skipped:
                with engine.store.transaction():
                    latest = engine._authorized(run_id)
                    for node_id in skipped:
                        latest["orchestration"]["dag"]["nodes"][node_id] = {"state": "skipped"}
                    engine._commit(latest, "dag_nodes_skipped", {"nodes": list(skipped)})
                continue
            slots = run["definition"]["max_concurrency"] - len(pending)
            if ready and slots > 0:
                for graph_node in ready[:slots]:
                    declared = next(n for n in dag["proposal"]["nodes"] if n["id"] == graph_node.id)
                    bound = _resolve(graph_node.input, run["input"], settled)
                    with engine.store.transaction():
                        latest = engine._authorized(run_id)
                        if latest["state"] in CLOSED:
                            return False
                        latest_node = latest["orchestration"]["dag"]["nodes"].get(graph_node.id)
                        if latest_node is None or latest_node["state"] != "pending":
                            continue
                        call = self.orchestration.delegate(
                            run_id, ChildCall(graph_node.id, declared["member"], bound)
                        )
                        latest = engine._authorized(run_id)
                        latest["orchestration"]["dag"]["nodes"][graph_node.id].update(
                            state="running", input=bound, call_id=call["id"]
                        )
                        engine._commit(
                            latest,
                            "dag_node_dispatched",
                            {"node_id": graph_node.id, "call_id": call["id"]},
                        )
                continue
            unattempted = [call for call in pending if call["run_id"] not in attempted]
            if unattempted:
                attempted.update(call["run_id"] for call in unattempted)
                await self.orchestration._drive_children(run_id, unattempted)
                continue
            if pending:
                with engine.store.transaction():
                    latest = engine._authorized(run_id)
                    if latest["state"] not in CLOSED:
                        latest["state"] = (
                            "waiting_approval"
                            if any(c["state"] == "waiting_approval" for c in pending)
                            else "outcome_unknown"
                        )
                        engine._commit(latest, "children_waiting")
                return False
            if ready:
                raise ValidationError("DAG has no available execution capacity")
            with engine.store.transaction():
                latest = engine._authorized(run_id)
                latest["orchestration"]["dag"]["result"] = result
                engine._commit(latest, "dag_completed")
            return True

    def patch(self, run_id, proposal, expected_revision, command_id):
        if (
            not isinstance(proposal, DAGProposal)
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise ValidationError("DAG patch requires a typed proposal and non-negative revision")
        engine = self.engine
        payload = {
            "run_id": run_id,
            "proposal": proposal.to_dict(),
            "expected_plan_revision": expected_revision,
        }

        def apply():
            run = engine._authorized(run_id)
            engine._check_release(run)
            state = run.get("orchestration", {})
            if (
                run["definition"].get("plan_mode") != "dag"
                or state.get("stage") != "execute"
                or run["state"] in CLOSED
            ):
                raise ValidationError("Only an active accepted DAG may be patched")
            if state["plan_revision"] != expected_revision:
                raise ValidationError("Plan revision conflict")
            proposal.validate_members(run["definition"]["members"])
            old = {node["id"]: node for node in state["dag"]["proposal"]["nodes"]}
            new = {node["id"]: node for node in proposal.nodes}
            frozen = {
                key for key, record in state["dag"]["nodes"].items() if record["state"] != "pending"
            }
            if any(key not in new or canonical(old[key]) != canonical(new[key]) for key in frozen):
                raise ValidationError("A patch cannot alter dispatched or settled nodes")
            remaining = run["definition"]["max_steps"] - len(state["children"])
            if len(new.keys() - frozen) > remaining:
                raise ValidationError("DAG patch exceeds remaining steps")
            state["plan_revision"] += 1
            state["dag"] = {
                "proposal": proposal.to_dict(),
                "plan": StaticWorkflowCompiler().compile(proposal.graph()).to_dict(),
                "nodes": {
                    key: copy.deepcopy(state["dag"]["nodes"].get(key, {"state": "pending"}))
                    for key in new
                },
            }
            state["revisions"].append(
                {
                    "revision": state["revision"],
                    "plan_revision": state["plan_revision"],
                    "proposal": proposal.to_dict(),
                    "source": "patch",
                    "digest": digest(proposal.to_dict()),
                }
            )
            engine._commit(run, "plan_patched", {"plan_revision": state["plan_revision"]})
            return {"state_revision": run["revision"], "plan_revision": state["plan_revision"]}

        return engine.store.command(engine.scope, command_id, "patch_plan", payload, run_id, apply)
