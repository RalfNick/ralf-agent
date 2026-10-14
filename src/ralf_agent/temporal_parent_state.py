"""Pure finite parent authority; child evidence is adopted by Workflow History."""

from .dag_planning import DAGNode, DAGProposal
from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .governance import TemporalExecutionPolicy
from .orchestration_types import ChildCall, TeamSelection
from .planning import PlanningRequest
from .spec_codec import decode_spec
from .temporal_bindings import request_release_digest
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
    Literal,
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
        from .temporal_session_state import validate_history

        validate_history(request, manifest, scope)
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
        self.observation_version = 1  # Workflow patch marker selects v2 for new histories.
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
        from .temporal_bindings import request_release_digest, validate_bindings

        validate_bindings(request, manifest, scope)
        self.release_digest = request_release_digest(request, manifest)
        from .temporal_user_input import initialize as initialize_inputs

        initialize_inputs(self)
        if self.definition.get("input_policy") is not None and (
            manifest.get("user_input_protocol") != 1
            or self.definition["input_policy"] not in manifest.get("user_input_policies", {})
        ):
            raise DefinitionMismatch("Original planner input policy unavailable")
        self.state, self.revision, self.result, self.error = "queued", 0, None, None
        self.children, self.queue, self.event_log = [], [], []
        self.receipts, self.command_digests = {}, {}
        self.stage = "select" if self.kind == "team" else "plan"
        self.plan_revision, self.planning_revision = -1, 0
        self.dag = None
        self.results = {}
        self.selections = 0
        self.memory_recovery_revision = 0
        self.actions, self.reservations = [], {}
        self.active_action, self.remote_uncertain = None, False
        self.session_stages, self.pending_session, self.session_recovery = {}, None, []
        payload = {"kind": "submit", "scope": self.scope, "request": self.request}
        self.command_digests[command_id] = digest(payload)
        self.receipts[command_id] = self._receipt(command_id, "submit", {"state_revision": 0})
        self._emit("run_submitted", {"release_digest": self.release_digest}, bump=False)
        from .temporal_parent_completion_state import initialize as initialize_completion

        initialize_completion(self)
        from .temporal_parent_session import initialize

        initialize(self)
        if self.kind == "graph":
            graph = GraphWorkflowSpec.from_dict(self.definition)
            if any(node.agent is None for node in graph.nodes):
                raise ValidationError("Temporal graph supports Agent nodes only")
            self._adopt_graph(graph)

    def _emit(self, kind, data=None, *, bump=True):
        from .temporal_coding_composition_state import enabled, request_parent_stop

        if (
            enabled(self.manifest)
            and hasattr(self, "composition_stop_intent")
            and self.composition_stop_intent is None
            and self.state in {"failed", "cancelled"}
        ):
            request_parent_stop(
                self, terminal_state=self.state, reason=self.error or {"code": kind}
            )
        return super()._emit(kind, data, bump=bump)

    @property
    def quiescent(self):
        return (
            self.children_quiescent
            and self.active_action is None
            and not self.remote_uncertain
            and all(r["status"] == "settled" for r in self.reservations.values())
            and all(
                s["status"] in {"completed", "failed", "closed", "closed_no_record"}
                for s in self.session_stages.values()
            )
        )

    @property
    def children_quiescent(self):
        from .temporal_coding_composition_state import (
            child_capacity_released,
            orchestration_enabled,
        )

        if orchestration_enabled(self.manifest):
            return all(
                call.get("settled") is True and child_capacity_released(call)
                for call in self.children
            )
        return all(call.get("settled", False) for call in self.children)

    def next_session_operation(self):
        if getattr(self, "composition_stop_intent", None) is not None:
            return None
        from .temporal_parent_session import next_operation

        operation = next_operation(self)
        from .temporal_coding_composition_state import enabled

        if (
            operation is not None
            and enabled(self.manifest)
            and operation[0]["kind"] == "session_root_read"
        ):
            action, request = operation
            request["execution_epoch"] = self.epoch
            action["request_digest"] = digest(request)
            self.root_read_request = detached(request)
        return operation

    def accept_session_root(self, action_id, response):
        from .temporal_parent_session import accept_read

        accept_read(self, action_id, response)

    def _complete_parent(self, result, *, verified=False):
        from .temporal_parent_session import prepare_result

        if self.parent_completion_enabled and not verified:
            self.prepare_parent_completion(result)
            return
        if not self._native_capacity():
            return
        if not prepare_result(self, result):
            self._complete_node(result)
        elif self.parent_completion_enabled:
            self.parent_completion_stages["r" + str(self.planning_revision)][
                "publication_intent_digest"
            ] = digest(self.session_stages["root"]["intent"])

    def _complete_node(self, result):
        from .temporal_parent_session import release_allowance

        if self.parent_completion_enabled:
            from .temporal_parent_completion_state import check_source

            try:
                stage = self.parent_completion_stages["r" + str(self.planning_revision)]
                if stage["status"] != "adopted" or stage["adopted_verdict"]["status"] != "accept":
                    raise DefinitionMismatch("Parent publication lacks original accepted verdict")
                check_source(self, stage, result, publication=True)
            except (
                KeyError,
                IndexError,
                StopIteration,
                TypeError,
                ValueError,
                ValidationError,
                DefinitionMismatch,
            ) as exc:
                self.state, self.error = (
                    "failed",
                    {"code": getattr(exc, "code", "validation_error")},
                )
                release_allowance(self)
                self._emit("run_failed", self.error)
                return
        release_allowance(self)
        if not self._native_capacity():
            return
        self.state, self.result = "succeeded", detached(result)
        self._emit("run_succeeded")

    def _native_capacity(self):
        from .temporal_parent_session import release_allowance
        from .temporal_session_model_history import parent_capacity

        try:
            parent_capacity(self)
            return True
        except ValidationError as exc:
            release_allowance(self)
            self.state, self.error = "failed", {"code": exc.code}
            self._emit("run_failed", self.error)
            return False

    def retry_blocked(self):
        from .temporal_session_save_state import request_recovery

        request_recovery(self)

    def prepare_parent_completion(self, result):
        from .temporal_parent_completion_state import prepare

        prepare(self, result)

    def next_parent_completion_operation(self):
        from .temporal_parent_completion_state import next_operation

        return next_operation(self)

    def accept_parent_completion(self, action_id, response):
        from .temporal_parent_completion_state import accept

        accept(self, action_id, response)

    @property
    def budget(self):
        own = TemporalRunState.budget.fget(self)
        held = sum(call["cap"] for call in self.children if not call.get("settled", False))
        unknown = sum(
            call["cap"]
            for call in self.children
            if not call.get("settled") and call.get("uncertain")
        )
        spent = sum(call.get("spent", 0) for call in self.children if call.get("settled", False))
        return {
            "allowance": self.request["budget"],
            "reserved": held - unknown + own["reserved"],
            "unknown": unknown + own["unknown"],
            "spent": spent + own["spent"],
            "remaining": self.request["budget"]
            - held
            - spent
            - own["reserved"]
            - own["unknown"]
            - own["spent"],
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
                + own["reservations"]
            ),
        }

    def snapshot(self):
        from .temporal_user_input import pending as pending_inputs

        pending = pending_inputs(self)
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
            "actions": detached(self.actions),
            "consistency": "authoritative",
        }

    def diagnostics(self):
        from .temporal_session_model_history import bundle

        return {
            "snapshot": self.snapshot(),
            "manifest": detached(self.manifest),
            "release_digest": self.release_digest,
            "budget": self.budget,
            **(
                {"input_requests": detached(self.input_requests)}
                if self.manifest.get("user_input_protocol") == 1
                else {}
            ),
            **(
                {"planning_input_sources": detached(self.planning_input_sources)}
                if self.manifest.get("user_input_protocol") == 1
                else {}
            ),
            **(
                {"parent_completion_stages": detached(self.parent_completion_stages)}
                if self.manifest.get("parent_completion_protocol") == 1
                else {}
            ),
            **(
                {"native_history_bundle": bundle(self)}
                if self.manifest.get("model_history_protocol") == 2
                else {}
            ),
            "workflow": {
                "backend": "temporal-parent",
                "kind": self.kind,
                "stage": self.stage,
                "quiescent": self.quiescent,
                "remote_stop_confirmed": self.quiescent,
                "unknown_remote_execution": self.remote_uncertain
                or any(c.get("uncertain", False) for c in self.children if not c.get("settled")),
                "reconciliation_pending": any(
                    s["status"] == "outcome_unknown" for s in self.session_stages.values()
                )
                or any(
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
        if kind == "send_input":
            from .temporal_user_input import apply_reply

            return apply_reply(self, payload, command_id)
        if kind == "drive":
            if self.manifest["kernel"] == "temporal-3":
                self.memory_recovery_revision += 1
            from .temporal_session_save_state import request_recovery

            request_recovery(self)
            return {"state_revision": self.revision}
        if kind == "cancel":
            from .temporal_coding_composition_state import enabled, request_parent_stop

            if enabled(self.manifest):
                if self.state == "succeeded" or (
                    self.state == "failed" and self.composition_stop_intent is None
                ):
                    return {"rejected": True, "reason": "too_late"}
                return request_parent_stop(
                    self, terminal_state="cancelled", reason={"code": "cancel_requested"}
                )
            if self.state in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if self.state != "cancelled":
                self.state = "cancelled"
                from .temporal_user_input import close_pending

                close_pending(self)
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
        self.planning_conclusion = None
        self.dag = {
            "plan": StaticWorkflowCompiler().compile(graph).to_dict(),
            "nodes": {node.id: {"state": "pending"} for node in graph.nodes},
            "proposal": proposal,
        }
        self.stage = "execute"
        self._emit("plan_revision_adopted", {"plan_revision": self.plan_revision})

    def accept_selection(self, value):
        from .temporal_coding_composition_state import orchestration_enabled

        if getattr(self, "composition_stop_intent", None) is not None or self.state in TERMINAL:
            raise ValidationError("Closed parent cannot adopt new selection")
        if orchestration_enabled(self.manifest) and not self.children_quiescent:
            raise ValidationError("Original children still own physical execution capacity")
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
                if not self.children_quiescent:
                    raise ValidationError("Children still hold execution capacity")
                self._complete_parent(selection.result)
                return
            for call in selection.calls:
                if call["member"] not in self.definition["members"]:
                    raise ValidationError("Unknown team member")
                if self.parent_completion_enabled and any(
                    c["member"] == call["member"] for c in self.children
                ):
                    raise ValidationError("Checked Team business member cannot execute twice")
                prior = next((c for c in self.children if c["call_id"] == call["id"]), None)
                if prior is not None:
                    if prior["member"] != call["member"] or prior["input"] != call["input"]:
                        raise IdempotencyConflict("Child identity conflict")
                    raise ValidationError("Completed child cannot be dispatched again")
            if len({c["id"] for c in selection.calls}) != len(selection.calls):
                raise ValidationError("Duplicate child selection identity")
            if self.parent_completion_enabled and len(
                {c["member"] for c in selection.calls}
            ) != len(selection.calls):
                raise ValidationError("Checked Team cannot select duplicate business members")
            self.queue = selection.calls
            self.stage = "execute"
        elif value.get("status") in {"refused", "needs_input"}:
            from .dag_planning import PlanningConclusion

            conclusion = PlanningConclusion(**value)
            from .temporal_user_input import adopt_planner

            if adopt_planner(self, conclusion.to_dict()):
                self._emit("planning_conclusion_adopted")
                return
            if self.parent_completion_enabled:
                self.planning_conclusion = conclusion.to_dict()
                self.dag = None
            if "session_tree_protocol" in self.manifest or self.parent_completion_enabled:
                self._complete_parent(conclusion.to_dict())
            else:
                self.state, self.result = "succeeded", conclusion.to_dict()
            self._emit("planning_conclusion_adopted")
            return
        else:
            if "steps" in value:
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
        if member == "@verifier":
            return self.manifest["parent_completion_policies"][
                self.definition["completion_policy"]
            ]["effective_agent_release"]["definition"]["steps"][0]
        if member == "@planner":
            return self.manifest["orchestration"]["planners"][self.definition["planner"]]["agent"]
        return self.definition["members"][member]

    def _project_call_request(self, call, cap, *, verifier=False):
        """Project the actual declared member before any child cap admission."""
        if call.member in {"@planner", "@verifier"}:
            member = decode_spec(self._member(call.member))
        elif self.kind == "graph":
            node = next(
                node
                for node in [GraphNode.from_dict(n) for n in self.dag["plan"]["nodes"]]
                if node.id == call.member
            )
            member = node.agent
        else:
            member = decode_spec(self._member(call.member))
        request = submission_request(member, call.input, budget=cap)
        if verifier:
            request["agent_bindings"] = detached(
                self.manifest["parent_completion_policies"][self.definition["completion_policy"]][
                    "effective_agent_release"
                ]["agent_bindings"]
            )
        from .temporal_bindings import project_child

        return project_child(self.request, call.member, request)

    def _call_runner_keys(self, call):
        from .temporal_coding_composition_state import coding_runner_keys

        return coding_runner_keys(self._project_call_request(call, self.child_cap), self.manifest)

    def delegate(self, call, *, graph_node=None, verifier=False):
        from .temporal_coding_composition_state import orchestration_enabled

        if getattr(self, "composition_stop_intent", None) is not None or self.state in TERMINAL:
            return None
        if (
            orchestration_enabled(self.manifest)
            and call.member == "@planner"
            and (
                self.kind != "dynamic"
                or call.id != "planner"
                or self.stage != "plan"
                or self.manifest["orchestration"]["planners"]
                .get(self.definition.get("planner"), {})
                .get("agent")
                is None
            )
        ):
            raise ValidationError("Planner child requires its original Dynamic planning slot")
        if verifier and (
            call.member != "@verifier"
            or call.id != "verdict"
            or not self.parent_completion_enabled
            or self.parent_completion_pending is None
        ):
            raise ValidationError("Verifier child requires original parent policy intent")
        if call.member == "@verifier" and not verifier:
            raise ValidationError("Ordinary callers cannot select parent verifier")
        limit = min(self.policy.max_children, self.definition.get("max_steps", 256))
        if len(self.children) >= limit:
            raise ValidationError("Child limit exceeded")
        cap = (
            self.manifest["parent_completion_policies"][self.definition["completion_policy"]][
                "identity"
            ]["verifier_budget"]
            if verifier
            else self.child_cap
        )
        if cap > self.budget["remaining"]:
            raise ValidationError("Parent budget cannot reserve child cap")
        identity = (
            f"r{self.planning_revision}.verifier.verdict"
            if verifier
            else f"{self.planning_revision}:{call.id}"
        )
        prior = next((c for c in self.children if c["id"] == identity), None)
        if prior is not None:
            if prior["input"] != call.input or prior["member"] != call.member:
                raise IdempotencyConflict("Original child intent changed")
            return detached(prior)
        command_id = "ralf-child:" + digest([self.scope, self.run_id, identity])
        request = self._project_call_request(call, cap, verifier=verifier)
        if "session_lineage" in self.request:
            from .temporal_session_tree import project_lineage

            request["session_lineage"] = project_lineage(
                self.request,
                self.run_id,
                call.member,
                call.id,
                request,
                proposal=self.dag["proposal"]
                if self.kind == "dynamic" and call.member not in {"@planner", "@verifier"}
                else None,
                planning_revision=self.planning_revision,
            )
            if self.root_session_snapshot is not None:
                request["session_root_snapshot"] = detached(self.root_session_snapshot)
        entry = {
            "id": identity,
            "call_id": call.id,
            "member": call.member,
            "input": call.input,
            "command_id": command_id,
            "run_id": child_run_id(self.scope, command_id),
            "request": request,
            "cap": cap,
            "settled": False,
            "spent": 0,
            "state": "queued",
            "depth": self.depth + 1,
            "started": False,
            **(
                {
                    "role": "verifier"
                    if verifier
                    else "planner"
                    if call.member == "@planner"
                    else "worker",
                    "planning_revision": self.planning_revision,
                }
                if self.manifest.get("parent_completion_protocol") == 1
                else {}
            ),
        }
        from .temporal_coding_composition_state import (
            enabled,
            orchestration_enabled,
            project_child_link,
        )

        if orchestration_enabled(self.manifest):
            entry["planning_revision"] = self.planning_revision
        if enabled(self.manifest):
            entry["request"] = project_child_link(self, entry, request)
            entry["child_request_digest"] = digest(entry["request"])
        self.children.append(entry)
        self.state = "running"
        if graph_node is not None:
            self.dag["nodes"][graph_node].update(state="running", call_id=identity)
        self._emit(
            "child_intent_recorded",
            {"call_id": identity, "run_id": entry["run_id"], "cap": cap},
        )
        return detached(entry)

    def next_calls(self):
        from .temporal_coding_composition_state import (
            child_capacity_released,
            enabled,
            occupied_runner_keys,
            orchestration_enabled,
        )

        if enabled(self.manifest) and (
            getattr(self, "composition_namespace", {}).get("id") is None
            or getattr(self, "composition_stop_intent", None) is not None
        ):
            return []
        if (
            self.state in TERMINAL
            or self.stage == "waiting_input"
            or not self.root_context_ready
            or self.pending_session is not None
            or self.root_aggregate is not None
        ):
            return []
        resource_aware = enabled(self.manifest) and (
            self.manifest.get("binding_protocol") in (13, 15)
            and self.kind == "graph"
            or orchestration_enabled(self.manifest)
        )
        pending = [
            call
            for call in self.children
            if (
                not child_capacity_released(call)
                if resource_aware
                else not call.get("settled", False)
            )
        ]
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
                occupied = set(occupied_runner_keys(self)) if resource_aware else set()
                for node in ready:
                    if slots <= 0:
                        break
                    call = ChildCall(
                        node.id,
                        node.id
                        if self.kind == "graph"
                        else next(
                            n["member"] for n in self.dag["proposal"]["nodes"] if n["id"] == node.id
                        ),
                        _resolve(node.input, self.request["input"], settled),
                    )
                    resources = frozenset()
                    if resource_aware:
                        resources = self._call_runner_keys(call)
                        if resources & occupied:
                            continue
                    self.delegate(call, graph_node=node.id)
                    occupied.update(resources)
                    slots -= 1
                if (
                    not ready
                    and not pending
                    and all(
                        n["state"] in {"completed", "skipped"} for n in self.dag["nodes"].values()
                    )
                ):
                    if self.kind == "graph":
                        self._complete_parent(result)
                    else:
                        self.stage = "verify"
                        self.dag["result"] = result
            else:
                occupied = set(occupied_runner_keys(self)) if resource_aware else set()
                waiting = []
                for value in self.queue:
                    if slots <= 0:
                        waiting.append(value)
                        continue
                    call = ChildCall(**value)
                    resources = self._call_runner_keys(call) if resource_aware else frozenset()
                    if resources & occupied:
                        waiting.append(value)
                        continue
                    self.delegate(call)
                    occupied.update(resources)
                    slots -= 1
                self.queue = waiting
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

    def _adopt_child_result(self, call):
        """Promote one original settled result after its selected physical stop."""
        from .temporal_coding_composition_state import (
            child_capacity_released,
            orchestration_enabled,
        )

        if (
            call["member"] in {"@planner", "@verifier"}
            or call["state"] != "succeeded"
            or not call.get("settled")
        ):
            return
        current = orchestration_enabled(self.manifest)
        if current and (
            not child_capacity_released(call)
            or call["planning_revision"] != self.planning_revision
            or getattr(self, "composition_stop_intent", None) is not None
        ):
            return
        node = (
            next((n for n in self.dag["nodes"].values() if n.get("call_id") == call["id"]), None)
            if self.dag
            else None
        )
        if current and self.kind == "dynamic" and node is None:
            return
        result = call.get("snapshot", {}).get("result")
        if node is not None:
            declared = next(
                n
                for n in [GraphNode.from_dict(n) for n in self.dag["plan"]["nodes"]]
                if self.dag["nodes"][n.id] is node
            )
            result = validate_output(result, declared.output_schema)
        if current:
            # Later diagnostics still update financial/physical evidence, but
            # cannot rewrite the original result already used by this parent.
            if "adopted_result" not in call:
                call["adopted_result"] = detached(result)
            result = call["adopted_result"]
        if node is not None:
            node.update(state="completed", result=detached(result))
        latest = next(
            (
                c
                for c in reversed(self.children)
                if c["member"] == call["member"]
                and c.get("planning_revision", 0) == self.planning_revision
            ),
            None,
        )
        if not current or latest is call:
            self.results[call["member"]] = detached(result)

    def observe(self, run_id, value):
        from .temporal_coding_composition_state import orchestration_enabled

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
                    "waiting_input",
                    "waiting_reconciliation",
                    "outcome_unknown",
                    "cancelling",
                }
                or value["manifest"] != self.manifest
                or value["release_digest"] != request_release_digest(call["request"], self.manifest)
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
            evidence_flow = flow
            if self.observation_version == 2:
                # A child's private cancellation/planning bookkeeping is not a
                # resource observation. Its snapshot/budget and stop/uncertainty
                # flags still must agree exactly at a given revision.
                evidence_flow = {
                    name: flow.get(name, False)
                    for name in (
                        "quiescent",
                        "remote_stop_confirmed",
                        "unknown_remote_execution",
                        "evidence_ack_pending",
                        "reconciliation_pending",
                    )
                }
            native = {}
            if self.manifest.get("user_input_protocol") == 1:
                from .temporal_user_input import observed_journal

                native["input_requests"] = observed_journal(value, call["request"])
                native["planning_input_sources"] = detached(value.get("planning_input_sources", {}))
            if self.manifest.get("model_history_protocol") == 2:
                from .temporal_session_model_history import observed_bundle

                native["native_history_bundle"] = observed_bundle(value)
            fingerprint = digest(
                {"snapshot": snapshot, "budget": budget, "workflow": evidence_flow, **native}
            )
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
            node = None
            if (
                call["member"] not in {"@planner", "@verifier"}
                and snapshot["state"] == "succeeded"
                and self.dag
            ):
                node = next(
                    (n for n in self.dag["nodes"].values() if n.get("call_id") == call["id"]), None
                )
                if node is not None:
                    declared = next(
                        n
                        for n in [GraphNode.from_dict(n) for n in self.dag["plan"]["nodes"]]
                        if self.dag["nodes"][n.id] is node
                    )
                    validate_output(snapshot["result"], declared.output_schema)
            call.update(
                **native,
                snapshot=detached(snapshot),
                observed_flow=detached(flow),
                observed_revision=revision,
                state=snapshot["state"],
                spent=spent,
                observation_digest=fingerprint,
                observed_release_digest=value["release_digest"],
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
            self._adopt_child_result(call)
            if call.get("role") == "verifier":
                from .temporal_parent_completion_state import observe_verifier

                observe_verifier(self, call)
            if (
                self.state not in TERMINAL
                and getattr(self, "composition_stop_intent", None) is None
                and (
                    not orchestration_enabled(self.manifest)
                    or call["planning_revision"] == self.planning_revision
                )
            ):
                if call["state"] in {"failed", "cancelled"}:
                    self.state, self.error = (
                        "failed",
                        {"code": "child_run_failed", "run_id": run_id},
                    )
                elif self.manifest.get("user_input_protocol") != 1 and any(
                    c["state"] == "waiting_approval" for c in self.children if not c.get("settled")
                ):
                    self.state = "waiting_approval"
                elif any(
                    c["state"] in {"outcome_unknown", "waiting_reconciliation"}
                    for c in self.children
                    if not c.get("settled")
                ):
                    self.state = "outcome_unknown"
                elif any(
                    c["state"] == "waiting_approval" for c in self.children if not c.get("settled")
                ):
                    self.state = "waiting_approval"
                elif (
                    any(
                        c["state"] == "waiting_input" for c in self.children if not c.get("settled")
                    )
                    or self.stage == "waiting_input"
                ):
                    self.state = "waiting_input"
                else:
                    self.state = "running"
            self._emit(
                "child_observed",
                {"run_id": run_id, "state": call["state"], "settled": call["settled"]},
            )
        except (KeyError, TypeError, StopIteration) as exc:
            raise ValidationError("Malformed child observation") from exc

    def patch(self, value, expected_revision):
        from .temporal_coding_composition_state import enabled, orchestration_enabled

        if enabled(self.manifest) and (
            not orchestration_enabled(self.manifest) or self.kind != "dynamic"
        ):
            raise DefinitionMismatch("Coding composition static graph patches are refused")
        if (
            self.kind != "dynamic"
            or self.definition.get("plan_mode") != "dag"
            or self.dag is None
            or self.state in TERMINAL
            or getattr(self, "composition_stop_intent", None) is not None
            or self.parent_completion_enabled
            and self.stage != "execute"
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
        from .temporal_coding_composition_state import orchestration_enabled
        from .temporal_user_input import clarifications

        fixed_results = orchestration_enabled(self.manifest)
        results = [
            {
                "id": c["id"],
                "member": c["member"],
                "result": c["adopted_result"] if fixed_results else c["snapshot"]["result"],
            }
            for c in self.children
            if c["state"] == "succeeded"
            and c["member"] not in {"@planner", "@verifier"}
            and (not fixed_results or "adopted_result" in c)
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
            **(
                {"verification_feedback": self.verification_feedback}
                if self.verification_feedback is not None
                else {}
            ),
            **({"clarifications": clarifications(self)} if clarifications(self) else {}),
        ).to_dict()

    def accept_verification(self, value):
        from .planning import Verification
        from .temporal_coding_composition_state import orchestration_enabled

        if orchestration_enabled(self.manifest) and (
            getattr(self, "composition_stop_intent", None) is not None
            or self.state in TERMINAL
            or self.stage != "verify"
            or not self.children_quiescent
        ):
            raise ValidationError("Original verification requires physically closed children")
        verification = Verification(**value)
        self._emit("verification_received", verification.to_dict())
        if verification.status == "replan":
            if self.planning_revision + 1 >= self.definition["max_revisions"]:
                self.state, self.error = "failed", {"code": "plan_revision_limit"}
            else:
                self.planning_revision += 1
                self.verification_feedback = None
                self.planning_conclusion = None
                self.stage, self.dag = "plan", None
                self.state = "running"
                self._emit("replanning_requested")
        elif verification.status == "failed":
            self.state, self.error = "failed", {"code": "verification_failed"}
        else:
            if not self.children_quiescent:
                raise ValidationError("Children still hold execution capacity")
            self._complete_parent(verification.result)
