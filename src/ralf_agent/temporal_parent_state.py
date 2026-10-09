"""Pure finite parent authority; child evidence is adopted by Workflow History."""

from .dag_planning import DAGProposal
from .errors import IdempotencyConflict, ValidationError
from .governance import TemporalExecutionPolicy
from .orchestration_types import ChildCall, TeamSelection
from .planning import PlanningRequest
from .spec_codec import decode_spec
from .temporal_state import (
    TERMINAL,
    TemporalRunState,
    detached,
    text,
    validate_manifest,
    validate_schema_references,
)
from .types import credits, digest, submission_request
from .workflow import (
    ExecutionPlan,
    GraphNode,
    GraphWorkflowSpec,
    StaticWorkflowCompiler,
    _choices,
    _resolve,
    validate_output,
)

PARENT_WORKFLOW_NAME = "ralf.temporal.parent.v1"
CONTROL_ACTIVITY = "ralf.temporal.control.v1"
SELECTION_ACTIVITY = "ralf.temporal.selection.v1"
CONTEXT_ACTIVITY = "ralf.temporal.context.v1"


def child_run_id(scope, command_id):
    return "ralf-temporal-" + digest([scope, command_id])


class TemporalParentState(TemporalRunState):
    def __init__(self, run_id, scope, command_id, request, manifest, epoch=None, depth=0):
        text(run_id, "Run ID")
        text(command_id, "Command ID")
        credits(request["budget"])
        validate_manifest(manifest)
        if request["definition"]["kind"] not in {"graph", "team", "dynamic"}:
            raise ValidationError("A distributed parent requires graph/team/dynamic")
        if request.get("session_id") is not None:
            raise ValidationError("Shared sessions unsupported")
        self.run_id, self.scope, self.request, self.manifest = (
            run_id,
            detached(scope),
            detached(request),
            detached(manifest),
        )
        self.epoch, self.depth = epoch or "history:" + run_id, depth
        self.policy = (
            TemporalExecutionPolicy.from_identity(manifest["execution_policy"])
            if "execution_policy" in manifest
            else TemporalExecutionPolicy()
        )
        if type(depth) is not int or not 0 <= depth < self.policy.max_depth:
            raise ValidationError("Distributed nesting depth exhausted")
        self.definition = self.request["definition"]
        self.kind = self.definition["kind"]
        self.max_concurrency = self.definition.get("max_concurrency", 1)
        if self.max_concurrency > self.policy.max_concurrency:
            raise ValidationError("Concurrency exceeds execution policy")
        self.child_cap = self.definition.get("child_budget", 8)
        self.release_digest = digest({"definition": self.definition, "manifest": self.manifest})
        self.state, self.revision, self.result, self.error = "queued", 0, None, None
        self.children, self.queue, self.event_log = [], [], []
        self.receipts, self.command_digests = {}, {}
        self.stage = "select" if self.kind == "team" else "plan"
        self.plan_revision, self.planning_revision = -1, 0
        self.dag = None
        self.results = {}
        self.selections = 0
        payload = {"kind": "submit", "scope": self.scope, "request": self.request}
        self.command_digests[command_id] = digest(payload)
        self.receipts[command_id] = self._receipt(command_id, "submit", {"state_revision": 0})
        self._emit("run_submitted", {"release_digest": self.release_digest}, bump=False)
        if self.kind == "graph":
            graph = GraphWorkflowSpec.from_dict(self.definition)
            if any(node.agent is None for node in graph.nodes):
                raise ValidationError("Temporal graph supports Agent nodes only")
            self._adopt_graph(graph)

    @property
    def quiescent(self):
        return all(call.get("settled", False) for call in self.children)

    @property
    def budget(self):
        held = sum(call["cap"] for call in self.children if not call.get("settled", False))
        unknown = sum(
            call["cap"]
            for call in self.children
            if not call.get("settled") and call.get("uncertain")
        )
        spent = sum(call.get("spent", 0) for call in self.children if call.get("settled", False))
        return {
            "allowance": self.request["budget"],
            "reserved": held - unknown,
            "unknown": unknown,
            "spent": spent,
            "remaining": self.request["budget"] - held - spent,
            "reservations": detached(
                [
                    {
                        "id": c["id"],
                        "amount": c["cap"],
                        "status": "settled"
                        if c.get("settled")
                        else ("unknown" if c.get("uncertain") else "reserved"),
                        "actual": c.get("spent", 0),
                    }
                    for c in self.children
                ]
            ),
        }

    def snapshot(self):
        pending = []
        for call in self.children:
            for item in call.get("snapshot", {}).get("pending", []):
                pending.append(
                    {
                        **item,
                        "run_id": item.get("run_id", call["run_id"]),
                        "call_id": item.get("call_id", call["id"]),
                    }
                )
        return {
            "run_id": self.run_id,
            "state": self.state,
            "state_revision": self.revision,
            "result": detached(self.result),
            "error": detached(self.error),
            "pending": detached(pending),
            "actions": [],
            "consistency": "authoritative",
        }

    def diagnostics(self):
        return {
            "snapshot": self.snapshot(),
            "manifest": detached(self.manifest),
            "release_digest": self.release_digest,
            "budget": self.budget,
            "workflow": {
                "backend": "temporal-parent",
                "kind": self.kind,
                "stage": self.stage,
                "quiescent": self.quiescent,
                "remote_stop_confirmed": self.quiescent,
                "unknown_remote_execution": any(
                    c.get("uncertain", False) for c in self.children if not c.get("settled")
                ),
                "reconciliation_pending": any(
                    c.get("observed_flow", {}).get("reconciliation_pending", False)
                    for c in self.children
                    if not c.get("settled")
                ),
                "evidence_ack_pending": any(
                    c.get("observed_flow", {}).get("evidence_ack_pending", False)
                    for c in self.children
                    if not c.get("settled")
                ),
                "children": detached(self.children),
                "plan_revision": self.plan_revision,
                "planning_revision": self.planning_revision,
                "dag": detached(self.dag),
                "depth": self.depth,
            },
        }

    def command(self, command_id, payload):
        self.authorize(payload.get("scope"))
        if payload.get("kind") == "patch":
            identity = digest(payload)
            if command_id in self.command_digests:
                if identity != self.command_digests[command_id]:
                    raise IdempotencyConflict("Patch command identity conflict")
                return detached(self.receipts[command_id])
            self._emit("command_recorded", {"command_id": command_id, "kind": "patch"})
            try:
                receipt = self._receipt(
                    command_id,
                    "patch",
                    self.patch(payload["proposal"], payload["expected_plan_revision"]),
                )
            except ValidationError as exc:
                receipt = self._receipt(
                    command_id, "patch", {"error": exc.code}, apply_state="rejected"
                )
            self.command_digests[command_id], self.receipts[command_id] = identity, receipt
            self._emit(
                "command_applied", {"command_id": command_id, "apply_state": receipt["apply_state"]}
            )
            return detached(receipt)
        if payload.get("kind") == "submit":
            if self.command_digests.get(command_id) != digest(payload):
                raise IdempotencyConflict("Submission identity conflict")
            return detached(self.receipts[command_id])
        return super().command(command_id, payload)

    def _apply(self, kind, payload, command_id):
        if kind == "drive":
            return {"state_revision": self.revision}
        if kind == "cancel":
            if self.state in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if self.state != "cancelled":
                self.state = "cancelled"
                self._emit("cancel_applied")
            return {"state_revision": self.revision, "remote_stop_confirmed": self.quiescent}
        if kind == "patch":
            return self.patch(payload["proposal"], payload["expected_plan_revision"])
        raise ValidationError("Use the actual child Run for approval/reconciliation")

    def _adopt_graph(self, graph, proposal=None):
        for node in graph.nodes:
            validate_schema_references(node.output_schema)
        validate_schema_references(graph.to_dict()["output_schema"])
        self.plan_revision += 1
        self.dag = {
            "plan": StaticWorkflowCompiler().compile(graph).to_dict(),
            "nodes": {node.id: {"state": "pending"} for node in graph.nodes},
            "proposal": proposal,
        }
        self.stage = "execute"
        self._emit("plan_revision_adopted", {"plan_revision": self.plan_revision})

    def accept_selection(self, value):
        if self.state in TERMINAL:
            raise ValidationError("Closed parent cannot adopt new selection")
        detached(value)
        if self.kind == "team":
            try:
                selection = TeamSelection(
                    [ChildCall(**call) for call in value["calls"]],
                    done=value["done"],
                    result=value.get("result"),
                )
            except (KeyError, TypeError) as exc:
                raise ValidationError("Invalid team selection") from exc
            self.selections += 1
            if self.selections > self.policy.max_children + 1:
                raise ValidationError("Team selection limit exceeded")
            if selection.done:
                if not self.quiescent:
                    raise ValidationError("Children still hold execution capacity")
                self.state, self.result = "succeeded", detached(selection.result)
                self._emit("run_succeeded")
                return
            for call in selection.calls:
                if call["member"] not in self.definition["members"]:
                    raise ValidationError("Unknown team member")
                prior = next((c for c in self.children if c["call_id"] == call["id"]), None)
                if prior is not None:
                    if prior["member"] != call["member"] or prior["input"] != call["input"]:
                        raise IdempotencyConflict("Child identity conflict")
                    raise ValidationError("Completed child cannot be dispatched again")
            if len({c["id"] for c in selection.calls}) != len(selection.calls):
                raise ValidationError("Duplicate child selection identity")
            self.queue = selection.calls
            self.stage = "execute"
        elif value.get("status") in {"refused", "needs_input"}:
            from .dag_planning import PlanningConclusion

            conclusion = PlanningConclusion(**value)
            self.state, self.result = "succeeded", conclusion.to_dict()
            self._emit("planning_conclusion_adopted")
            return
        else:
            if "steps" in value:
                from .dag_planning import DAGNode
                from .workflow import Literal

                steps = [ChildCall(**call) for call in value["steps"]]
                nodes = [
                    DAGNode(
                        call.id,
                        call.member,
                        depends_on=() if index == 0 else (steps[index - 1].id,),
                        input=Literal(call.input),
                    )
                    for index, call in enumerate(steps)
                ]
                proposal = DAGProposal(nodes)
            else:
                proposal = DAGProposal.from_dict(value)
            proposal.validate_members(self.definition["members"])
            if len(proposal.nodes) > min(
                self.definition["max_steps"], self.policy.max_children
            ) - len(self.children):
                raise ValidationError("Plan exceeds remaining child limit")
            self._emit("plan_proposal_received", {"proposal": proposal.to_dict()})
            self._adopt_graph(proposal.graph(), proposal.to_dict())
        self.state = "running"
        self._emit("selection_adopted")

    def _member(self, member):
        if member == "@planner":
            return self.manifest["orchestration"]["planners"][self.definition["planner"]]["agent"]
        return self.definition["members"][member]

    def delegate(self, call, *, graph_node=None):
        if self.state in TERMINAL:
            return None
        if len(self.children) >= min(
            self.policy.max_children, self.definition.get("max_steps", 256)
        ):
            raise ValidationError("Child limit exceeded")
        if self.child_cap > self.budget["remaining"]:
            raise ValidationError("Parent budget cannot reserve child cap")
        identity = f"{self.planning_revision}:{call.id}"
        command_id = "ralf-child:" + digest([self.scope, self.run_id, identity])
        if self.kind == "graph":
            node = next(
                node
                for node in [GraphNode.from_dict(n) for n in self.dag["plan"]["nodes"]]
                if node.id == call.member
            )
            member = node.agent
        else:
            member = decode_spec(self._member(call.member))
        request = submission_request(member, call.input, budget=self.child_cap)
        entry = {
            "id": identity,
            "call_id": call.id,
            "member": call.member,
            "input": call.input,
            "command_id": command_id,
            "run_id": child_run_id(self.scope, command_id),
            "request": request,
            "cap": self.child_cap,
            "settled": False,
            "spent": 0,
            "state": "queued",
            "depth": self.depth + 1,
            "started": False,
        }
        self.children.append(entry)
        self.state = "running"
        if graph_node is not None:
            self.dag["nodes"][graph_node].update(state="running", call_id=identity)
        self._emit(
            "child_intent_recorded",
            {"call_id": identity, "run_id": entry["run_id"], "cap": self.child_cap},
        )
        return detached(entry)

    def next_calls(self):
        if self.state in TERMINAL:
            return []
        pending = [call for call in self.children if not call.get("settled", False)]
        slots = self.max_concurrency - len(pending)
        if self.stage == "execute" and slots > 0:
            if self.dag is not None:
                plan = ExecutionPlan(self.dag["plan"])
                ready, skipped, settled, result = _choices(
                    plan, self.request["input"], self.dag["nodes"], parallel=True
                )
                for name in skipped:
                    self.dag["nodes"][name] = {"state": "skipped"}
                    self._emit("dag_node_skipped", {"node": name})
                for node in ready[:slots]:
                    self.delegate(
                        ChildCall(
                            node.id,
                            node.id
                            if self.kind == "graph"
                            else next(
                                n["member"]
                                for n in self.dag["proposal"]["nodes"]
                                if n["id"] == node.id
                            ),
                            _resolve(node.input, self.request["input"], settled),
                        ),
                        graph_node=node.id,
                    )
                if (
                    not ready
                    and not pending
                    and all(
                        n["state"] in {"completed", "skipped"} for n in self.dag["nodes"].values()
                    )
                ):
                    if self.kind == "graph":
                        self.state, self.result = "succeeded", result
                        self._emit("run_succeeded")
                    else:
                        self.stage = "verify"
                        self.dag["result"] = result
            else:
                for _ in range(min(slots, len(self.queue))):
                    call = self.queue.pop(0)
                    self.delegate(ChildCall(**call))
                if not self.queue and not pending:
                    self.stage = "select"
        return detached(
            [call for call in self.children if not call["started"] and not call.get("settled")]
        )

    def mark_started(self, run_id):
        call = next(c for c in self.children if c["run_id"] == run_id)
        if not call["started"]:
            call["started"] = True
            self._emit("child_started", {"run_id": run_id})

    def observe(self, run_id, value):
        detached(value)
        call = next((c for c in self.children if c["run_id"] == run_id), None)
        if call is None:
            raise ValidationError("Unknown child observation")
        try:
            snapshot, budget, flow = value["snapshot"], value["budget"], value["workflow"]
            revision = snapshot["state_revision"]
            spent = budget["spent"]
            amounts = [budget[name] for name in ("spent", "reserved", "unknown", "remaining")]
            if (
                value["scope"] != self.scope
                or snapshot["run_id"] != run_id
                or type(revision) is not int
                or revision < 0
                or snapshot["state"]
                not in TERMINAL
                | {
                    "queued",
                    "running",
                    "waiting_approval",
                    "waiting_reconciliation",
                    "outcome_unknown",
                    "cancelling",
                }
                or value["manifest"] != self.manifest
                or value["release_digest"]
                != digest({"definition": call["request"]["definition"], "manifest": self.manifest})
                or type(budget["allowance"]) is not int
                or budget["allowance"] != call["cap"]
                or any(type(amount) is not int or amount < 0 for amount in amounts)
                or sum(amounts) != call["cap"]
                or type(flow["quiescent"]) is not bool
                or type(flow["remote_stop_confirmed"]) is not bool
                or type(flow.get("evidence_ack_pending", False)) is not bool
                or type(flow.get("reconciliation_pending", False)) is not bool
                or not isinstance(snapshot.get("pending"), list)
            ):
                raise ValidationError("Invalid child evidence identity/capacity")
            if revision < call.get("observed_revision", -1):
                return
            if (
                flow["quiescent"]
                and flow["remote_stop_confirmed"]
                and snapshot["state"] in TERMINAL
                and (budget["reserved"] or budget["unknown"] or snapshot["pending"])
            ):
                raise ValidationError(
                    "Terminal quiescence contradicts pending credit/work evidence"
                )
            fingerprint = digest({"snapshot": snapshot, "budget": budget, "workflow": flow})
            if revision == call.get("observed_revision", -1) and fingerprint != call.get(
                "observation_digest"
            ):
                raise ValidationError("Same child revision has inconsistent evidence")
            if spent < call.get("spent", 0) or (
                call.get("settled")
                and (spent != call["spent"] or snapshot["state"] != call["state"])
            ):
                raise ValidationError("Child settlement or spent credits changed")
            if call.get("observation_digest") == fingerprint:
                return
            # Validate the output before adopting evidence or releasing capacity.
            node, normalized = None, snapshot["result"]
            if call["member"] != "@planner" and snapshot["state"] == "succeeded" and self.dag:
                node = next(
                    (n for n in self.dag["nodes"].values() if n.get("call_id") == call["id"]), None
                )
                if node is not None:
                    declared = next(
                        n
                        for n in [GraphNode.from_dict(n) for n in self.dag["plan"]["nodes"]]
                        if self.dag["nodes"][n.id] is node
                    )
                    normalized = validate_output(snapshot["result"], declared.output_schema)
            call.update(
                snapshot=detached(snapshot),
                observed_flow=detached(flow),
                observed_revision=revision,
                state=snapshot["state"],
                spent=spent,
                observation_digest=fingerprint,
                uncertain=budget["unknown"] > 0
                or flow.get("reconciliation_pending", False)
                or flow.get("unknown_remote_execution", False),
            )
            if (
                snapshot["state"] in TERMINAL
                and flow["quiescent"]
                and flow["remote_stop_confirmed"]
                and not flow.get("evidence_ack_pending")
                and not flow.get("reconciliation_pending")
                and budget["reserved"] == budget["unknown"] == 0
                and not snapshot["pending"]
            ):
                call["settled"] = True
            if call["member"] != "@planner" and call["state"] == "succeeded" and call["settled"]:
                self.results[call["member"]] = detached(normalized)
                if node is not None:
                    node.update(state="completed", result=detached(normalized))
            if self.state not in TERMINAL:
                if call["state"] in {"failed", "cancelled"}:
                    self.state, self.error = (
                        "failed",
                        {"code": "child_run_failed", "run_id": run_id},
                    )
                elif any(
                    c["state"] == "waiting_approval" for c in self.children if not c.get("settled")
                ):
                    self.state = "waiting_approval"
                elif any(
                    c["state"] in {"outcome_unknown", "waiting_reconciliation"}
                    for c in self.children
                    if not c.get("settled")
                ):
                    self.state = "outcome_unknown"
                else:
                    self.state = "running"
            self._emit(
                "child_observed",
                {"run_id": run_id, "state": call["state"], "settled": call["settled"]},
            )
        except (KeyError, TypeError, StopIteration) as exc:
            raise ValidationError("Malformed child observation") from exc

    def patch(self, value, expected_revision):
        if (
            self.kind != "dynamic"
            or self.definition.get("plan_mode") != "dag"
            or self.dag is None
            or self.state in TERMINAL
        ):
            raise ValidationError("Only active DAG parents accept patches")
        if type(expected_revision) is not int or expected_revision != self.plan_revision:
            raise ValidationError("DAG revision conflict")
        proposal = DAGProposal.from_dict(value)
        proposal.validate_members(self.definition["members"])
        old = {n["id"]: n for n in self.dag["proposal"]["nodes"]}
        new = {n["id"]: n for n in proposal.nodes}
        for name, node in self.dag["nodes"].items():
            if node["state"] != "pending" and new.get(name) != old[name]:
                raise ValidationError("Patch changes a dispatched or settled node")
        if len(proposal.nodes) > self.definition["max_steps"]:
            raise ValidationError("Patched DAG too large")
        pending = sum(
            node["id"] not in self.dag["nodes"]
            or self.dag["nodes"][node["id"]]["state"] == "pending"
            for node in proposal.nodes
        )
        if pending > min(self.policy.max_children, self.definition["max_steps"]) - len(
            self.children
        ):
            raise ValidationError("Patched DAG exceeds remaining children")
        prior = self.dag["nodes"]
        self._adopt_graph(proposal.graph(), proposal.to_dict())
        for name, node in prior.items():
            if node["state"] != "pending":
                self.dag["nodes"][name] = node
        return {"plan_revision": self.plan_revision, "state_revision": self.revision}

    def planning_request(self):
        results = [
            {"id": c["id"], "member": c["member"], "result": c["snapshot"]["result"]}
            for c in self.children
            if c["state"] == "succeeded" and c["member"] != "@planner"
        ]
        return PlanningRequest(
            self.request["input"],
            self.definition["members"],
            results,
            self.planning_revision,
            capabilities=detached(self.definition["members"]),
            constraints={
                "max_nodes": min(self.policy.max_children, self.definition.get("max_steps", 256))
                - len(self.children),
                "remaining_steps": min(
                    self.policy.max_children, self.definition.get("max_steps", 256)
                )
                - len(self.children),
                "remaining_revisions": self.definition.get("max_revisions", 1)
                - self.planning_revision,
                "max_concurrency": self.max_concurrency,
                "child_budget": self.child_cap,
                "parent_budget": self.budget,
                "remaining_depth": self.policy.max_depth - self.depth - 1,
            },
        ).to_dict()

    def accept_verification(self, value):
        from .planning import Verification

        verification = Verification(**value)
        self._emit("verification_received", verification.to_dict())
        if verification.status == "replan":
            if self.planning_revision + 1 >= self.definition["max_revisions"]:
                self.state, self.error = "failed", {"code": "plan_revision_limit"}
            else:
                self.planning_revision += 1
                self.stage, self.dag = "plan", None
                self.state = "running"
                self._emit("replanning_requested")
        elif verification.status == "failed":
            self.state, self.error = "failed", {"code": "verification_failed"}
        else:
            if not self.quiescent:
                raise ValidationError("Children still hold execution capacity")
            self.state, self.result = "succeeded", detached(verification.result)
            self._emit("run_succeeded")
