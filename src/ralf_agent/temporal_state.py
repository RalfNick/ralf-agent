"""Deterministic Temporal Run state. Only a Workflow may persist this value.

The PostgreSQL journal is deliberately absent here: commands, credits, Actions,
and terminal decisions are replayed exclusively from Temporal History.
"""

import copy

from jsonschema import Draft202012Validator

from .decisions import final_output, validate_call_ids, validate_decision
from .errors import (
    AgentLimitExceeded,
    AuthorizationDenied,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from .governance import TemporalExecutionPolicy
from .harness import DecisionProposal
from .model_evidence import settlement_usage, validate_model_usage, validate_received_response
from .temporal_artifact_bindings import validate_protocol as validate_artifacts
from .temporal_facts_state import validate_protocol as validate_facts_protocol
from .temporal_facts_state import validate_snapshot as validate_facts_snapshot
from .temporal_knowledge_state import validate_protocol as validate_knowledge_protocol
from .temporal_knowledge_state import validate_snapshot as validate_knowledge_snapshot
from .temporal_session_data_state import validate_protocol as validate_session_data_protocol
from .temporal_session_data_state import validate_snapshot as validate_session_snapshot
from .temporal_session_model_history import freeze as freeze_native_history
from .temporal_session_save_state import validate_protocol as validate_session_save_protocol
from .temporal_session_state import validate_history as validate_session_history
from .temporal_session_state import validate_protocol as validate_session_protocol
from .tools import ToolSpec
from .types import AgentSpec, ToolCall, canonical, credits, digest

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
KERNEL = "temporal-1"
WORKFLOW_NAME = "ralf.temporal.run.v1"
MODEL_ACTIVITY = "ralf.temporal.model.v1"
MODEL_ADOPTION_ACTIVITY = "ralf.temporal.model-adoption.v1"
TOOL_ACTIVITY = "ralf.temporal.tool.v1"
RECONCILE_ACTIVITY = "ralf.temporal.reconcile.v1"
ACK_ACTIVITY = "ralf.temporal.evidence.v1"
CONTEXT_ACTIVITY = "ralf.temporal.context.v1"


def detached(value):
    canonical(value)
    return copy.deepcopy(value)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")


def validate_schema_references(schema):
    """Keep every Workflow Schema check deterministic and free of network I/O."""
    if not isinstance(schema, dict):
        return
    for key in ("$ref", "$dynamicRef", "$recursiveRef"):
        reference = schema.get(key)
        if isinstance(reference, str) and not reference.startswith("#"):
            raise ValidationError("Temporal requires local Schema references")
    for key in (
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "additionalItems",
        "unevaluatedItems",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    ):
        validate_schema_references(schema.get(key))
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for value in schema.get(key, ()):
            validate_schema_references(value)
    items = schema.get("items")
    for value in items if isinstance(items, list) else (items,):
        validate_schema_references(value)
    for key in (
        "$defs",
        "definitions",
        "properties",
        "patternProperties",
        "dependentSchemas",
        "dependencies",
    ):
        values = schema.get(key, {})
        if isinstance(values, dict):
            for value in values.values():
                validate_schema_references(value)


def validate_manifest(manifest):
    if isinstance(manifest, dict) and "runtime_profile" in manifest:
        from .types import runtime_profile_identity

        runtime_profile_identity(manifest["runtime_profile"])
    if not isinstance(manifest, dict) or manifest.get("kernel") not in {
        KERNEL,
        "temporal-2",
        "temporal-3",
    }:
        raise DefinitionMismatch("Unsupported Temporal runtime release")
    if manifest["kernel"] == "temporal-3":
        if (
            type(manifest.get("binding_protocol")) is not int
            or manifest.get("binding_protocol") not in (1, 2, 3, 4, 5, 6, 7, 8)
            or manifest.get("dispatch_admission") != "history-1"
        ):
            raise DefinitionMismatch("Unsupported Temporal binding/memory protocol")
    if manifest["kernel"] == "temporal-2" or (
        manifest["kernel"] == "temporal-3" and "managed_context" in manifest
    ):
        managed = manifest.get("managed_context", {})
        if (
            managed.get("version") != 1
            or managed.get("summary_credits") != 1
            or managed.get("policy") != manifest.get("context_builder")
        ):
            raise DefinitionMismatch("Unsupported managed Temporal context release")
    elif "managed_context" in manifest:
        raise DefinitionMismatch("Managed context requires an explicit Temporal protocol")
    from .temporal_context_read_protocol import validate_protocol as validate_context_reads

    validate_context_reads(manifest)
    from .temporal_tool_execution import validate_protocol as validate_tool_execution

    validate_tool_execution(manifest)
    from .binding_sandbox import validate_sandbox_protocol

    validate_sandbox_protocol(manifest)
    validate_artifacts(manifest)
    validate_facts_protocol(manifest)
    validate_knowledge_protocol(manifest)
    validate_session_protocol(manifest)
    validate_session_data_protocol(manifest)
    validate_session_save_protocol(manifest)
    from .temporal_limits_state import validate_protocol as validate_limits_protocol

    validate_limits_protocol(manifest)
    from .temporal_completion_state import validate_protocol as validate_completion_protocol

    validate_completion_protocol(manifest)
    from .temporal_decision_state import validate_protocol as validate_decision_protocol

    validate_decision_protocol(manifest)
    from .temporal_decision_state import validate_continuation_protocol

    validate_continuation_protocol(manifest)
    from .temporal_decision_state import validate_model_history_protocol

    validate_model_history_protocol(manifest)
    if "workspace_binding_protocol" in manifest:
        if type(manifest["workspace_binding_protocol"]) is not int or manifest[
            "workspace_binding_protocol"
        ] not in {1, 2}:
            raise DefinitionMismatch("Unsupported Temporal Workspace binding protocol")
        from .binding_workspace import _record, has_writable_workspace

        writable = has_writable_workspace(manifest.get("tools", {}))
        if writable != (manifest["workspace_binding_protocol"] == 2):
            raise DefinitionMismatch(
                "Workspace protocol differs from native published capabilities"
            )

        for record in manifest.get("binding_catalog", {}).get("records", {}).values():
            if record["role"] == "workspace":
                _record(record["identity"])
    if "skills_binding_protocol" in manifest:
        if (
            type(manifest["skills_binding_protocol"]) is not int
            or manifest["skills_binding_protocol"] != 1
        ):
            raise DefinitionMismatch("Unsupported Temporal Skills binding protocol")
        from .binding_skills import _record

        for record in manifest.get("binding_catalog", {}).get("records", {}).values():
            if record["role"] == "skills":
                _record(record["identity"])
    for key in ("tools", "providers", "harness", "context_builder", "tool_executor", "policy"):
        if not isinstance(manifest.get(key), dict):
            raise ValidationError(f"Temporal runtime release requires {key}")
    if not manifest["providers"]:
        raise ValidationError("Temporal runtime requires explicit providers")
    for name, identity in manifest["providers"].items():
        text(name, "Provider name")
        if not isinstance(identity, dict) or not identity:
            raise ValidationError("Temporal requires non-empty provider identities")
    for name, value in manifest["tools"].items():
        try:
            implementation = value["implementation_digest"]
            if not isinstance(implementation, str) or len(implementation) != 64:
                raise ValidationError("Invalid Temporal tool manifest implementation identity")
            spec = ToolSpec(
                **{key: item for key, item in value.items() if key != "implementation_digest"}
            )
            if spec.name != name:
                raise ValidationError("Invalid Temporal tool manifest name")
            validate_schema_references(spec.input_schema)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Invalid Temporal tool manifest") from exc
    canonical(manifest)
    return detached(manifest)


def validate_request(request, manifest):
    validate_session_history(request, manifest)
    credits(request["budget"])
    if request.get("session_id") is not None:
        raise ValidationError("Temporal shared sessions are not supported")
    definition = request["definition"]
    policy = (
        TemporalExecutionPolicy.from_identity(manifest["execution_policy"])
        if "execution_policy" in manifest
        else TemporalExecutionPolicy()
    )
    if definition.get("kind") in {"graph", "team", "dynamic"}:
        if "orchestration" not in manifest:
            raise ValidationError(
                "Temporal supports native AgentSpec or sequential WorkflowSpec; registered orchestration release required"
            )
        from .spec_codec import agent_steps, decode_spec, validate_definition_tree
        from .workflow import GraphWorkflowSpec

        value = validate_definition_tree(definition)
        decode_spec(value)
        stack = [(definition, 0)]
        planner_agents = []
        while stack:
            current, depth = stack.pop()
            if depth >= policy.max_depth:
                raise ValidationError("Distributed definition exceeds registered depth")
            if current.get("max_concurrency", 1) > policy.max_concurrency:
                raise ValidationError("Concurrency exceeds execution policy")
            kind = current.get("kind", "agent")
            if kind == "graph":
                graph = GraphWorkflowSpec.from_dict(current)
                if any(node.agent is None for node in graph.nodes):
                    raise ValidationError("Temporal graph supports Agent nodes only")
                for node in graph.nodes:
                    validate_schema_references(node.output_schema)
                validate_schema_references(graph.to_dict()["output_schema"])
            elif kind in {"team", "dynamic"}:
                registries = manifest["orchestration"]
                fields = (
                    [("strategy", "teams")]
                    if kind == "team"
                    else [("planner", "planners"), ("verifier", "verifiers")]
                )
                for field, registry in fields:
                    if current[field] not in registries[registry]:
                        raise DefinitionMismatch("Orchestration component unavailable")
                if kind == "dynamic":
                    planner = registries["planners"][current["planner"]]
                    if planner.get("agent") is not None:
                        planner_agents.append(planner["agent"])
                stack.extend((member, depth + 1) for member in current["members"].values())
        steps = agent_steps(definition) + planner_agents
    else:
        if definition.get("kind") not in {"agent", "sequence"}:
            raise ValidationError("Temporal supports native AgentSpec or sequential WorkflowSpec")
        if not isinstance(definition.get("steps"), list) or not definition["steps"]:
            raise ValidationError("Temporal requires at least one native Agent step")
        steps = definition["steps"]
    if request.get("agent_bindings"):
        from .binding_paths import agent_paths
        from .binding_types import AgentBindingDescriptor
        from .temporal_bindings import effective_step, validate_bindings

        validate_bindings(request, manifest)
        steps = [
            effective_step(
                value,
                manifest,
                request["agent_bindings"].get(path, AgentBindingDescriptor().to_dict()),
            )
            for path, value in agent_paths(definition).items()
        ] + (planner_agents if definition["kind"] in {"graph", "team", "dynamic"} else [])
    for value in steps:
        spec = AgentSpec(**value)
        validate_schema_references(spec.output_schema)
        if spec.provider not in manifest["providers"]:
            raise DefinitionMismatch(f"Model provider not configured: {spec.provider}")
        for name in spec.tools:
            if policy.allowed_tools is not None and name not in policy.allowed_tools:
                raise ValidationError("Tool forbidden by execution policy")
            if name not in manifest["tools"]:
                raise DefinitionMismatch(f"Tool not registered: {name}")
    from .temporal_bindings import validate_bindings

    validate_bindings(request, manifest)
    from .binding_paths import agent_paths
    from .temporal_bindings import effective_step

    for path, descriptor in request.get("agent_bindings", {}).items():
        effective_step(agent_paths(definition)[path], manifest, descriptor)
    canonical(request)


class TemporalRunState:
    """One bounded Agent/sequence. No clocks, generated IDs, I/O, or hidden retry."""

    def __init__(self, run_id, scope, command_id, request, manifest, execution_epoch=None):
        text(run_id, "Run ID")
        text(command_id, "Command ID")
        manifest = validate_manifest(manifest)
        validate_request(request, manifest)
        self.run_id, self.scope = run_id, detached(scope)
        self.request, self.manifest = detached(request), manifest
        validate_session_history(request, manifest, scope)
        from .temporal_bindings import request_release_digest, validate_bindings

        validate_bindings(request, manifest, scope)
        self.release_digest = request_release_digest(request, manifest)
        self.epoch = execution_epoch or f"history:{run_id}"
        if "context_read_protocol" in manifest and (
            execution_epoch is not None
            and (
                type(execution_epoch) is not str
                or not execution_epoch.strip()
                or len(execution_epoch) > 1024
            )
        ):
            raise ValidationError("Context reads require a bounded original execution epoch")
        self.state, self.revision, self.result, self.error = "queued", 0, None, None
        self.node, self.decisions, self.actions = 0, 0, []
        self.limits_stages = {}
        self.completion_stages, self.pending_verification = {}, None
        self.completion_task = detached(request["input"])
        self.current_task = detached(request["input"])
        self.native_history_episodes = []
        self.native_history_snapshots = {}
        self.messages = self._turn_messages(self.step, request["input"])
        self.receipts, self.command_digests, self.event_log = {}, {}, []
        self.reservations, self.pending_acks = {}, []
        self.active_action, self.remote_uncertain = None, False
        self.reconcile_requests = []
        self.active_reconciliation = None
        self.active_evidence_ack = None
        self.deferred_acks = []
        self.context_snapshot = None
        self.session_private_snapshots = {}
        self.context_signature = None
        self.memory_stages, self.pending_completion, self.memory_recovery = {}, None, []
        self.session_stages, self.pending_session, self.session_recovery = {}, None, []
        self.managed_context_stages = {}
        self.context_read_stages = {}
        self.tool_executions = {}
        self.context_artifact_dispatches = {}
        self.context_artifact_receipts = {}
        from .temporal_managed_context import check_scope

        check_scope(manifest, self.scope)
        payload = {"kind": "submit", "scope": self.scope, "request": self.request}
        self.command_digests[command_id] = digest(payload)
        self.receipts[command_id] = self._receipt(command_id, "submit", {"state_revision": 0})
        self._emit("run_submitted", {"release_digest": self.release_digest}, bump=False)

    @property
    def step(self):
        from .temporal_bindings import effective_step

        step = effective_step(
            self.request["definition"]["steps"][self.node], self.manifest, self.step_bindings
        )
        from .temporal_limits_state import effective_step as limited_step

        return limited_step(self, step)

    @property
    def step_bindings(self):
        from .temporal_bindings import step_descriptor

        return step_descriptor(self.request, self.node)

    @property
    def step_manifest(self):
        from .temporal_bindings import effective_manifest

        return effective_manifest(self.manifest, self.step_bindings)

    def context_cache_signature(self):
        source = [self.step, self.messages]
        if "session_history" in self.request:
            source.append(self.request["session_history"])
        if self.manifest["kernel"] == "temporal-3":
            source.extend([self.node, self.step_bindings])
        return digest(source)

    @staticmethod
    def _messages(step, value):
        return [
            {"role": "system", "content": step["instructions"]},
            {"role": "user", "content": value if isinstance(value, str) else canonical(value)},
        ]

    def _turn_messages(self, step, value):
        return self._messages(step, value)

    @property
    def budget(self):
        reserved = sum(v["amount"] for v in self.reservations.values() if v["status"] == "reserved")
        unknown = sum(v["amount"] for v in self.reservations.values() if v["status"] == "unknown")
        spent = sum(
            v.get("actual", 0) for v in self.reservations.values() if v["status"] == "settled"
        )
        return {
            "allowance": self.request["budget"],
            "reserved": reserved,
            "unknown": unknown,
            "spent": spent,
            "remaining": self.request["budget"] - reserved - unknown - spent,
            "reservations": detached(list(self.reservations.values())),
        }

    def _emit(self, kind, data=None, *, bump=True):
        if bump:
            self.revision += 1
        self.event_log.append(
            {
                "run_id": self.run_id,
                "seq": len(self.event_log) + 1,
                "kind": kind,
                "data": detached(data or {}),
            }
        )

    def _receipt(self, command_id, kind, outcome, *, apply_state="applied"):
        return {
            "command_id": command_id,
            "run_id": self.run_id,
            "kind": kind,
            "record_state": "durably_recorded",
            "apply_state": apply_state,
            "outcome": detached(outcome),
        }

    def authorize(self, scope):
        if scope != self.scope:
            raise AuthorizationDenied("Run belongs to another workspace or principal")

    def command(self, command_id, payload):
        text(command_id, "Command ID")
        self.authorize(payload.get("scope"))
        identity = digest(payload)
        if command_id in self.command_digests:
            if identity != self.command_digests[command_id]:
                raise IdempotencyConflict("Command ID already identifies different content")
            return detached(self.receipts[command_id])
        kind = payload.get("kind")
        if kind not in {"approve", "cancel", "reconcile", "drive"}:
            raise ValidationError("Unknown Temporal command")
        self._emit("command_recorded", {"command_id": command_id, "kind": kind})
        try:
            outcome = self._apply(kind, payload, command_id)
            receipt = self._receipt(command_id, kind, outcome)
        except (ValidationError, DefinitionMismatch) as exc:
            receipt = self._receipt(command_id, kind, {"error": exc.code}, apply_state="rejected")
        self.command_digests[command_id] = identity
        self.receipts[command_id] = receipt
        self._emit(
            "command_applied",
            {"command_id": command_id, "kind": kind, "apply_state": receipt["apply_state"]},
        )
        return detached(receipt)

    def _apply(self, kind, payload, command_id):
        if kind == "cancel":
            if self.state in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if self.state == "cancelled":
                return {"reason": "already_terminal"}
            self.state = "cancelled"
            from .temporal_completion_state import close_pending

            close_pending(self)
            self._emit(
                "cancel_applied", {"state": self.state, "remote_stop_confirmed": self.quiescent}
            )
            return {"state_revision": self.revision, "remote_stop_confirmed": self.quiescent}
        if kind == "drive":
            return {"state_revision": self.revision}
        action = next((a for a in self.actions if a["id"] == payload.get("action_id")), None)
        if kind == "approve":
            if self.state in TERMINAL:
                return {"rejected": True, "reason": "target_closed"}
            if (
                action is None
                or action["status"] != "waiting_approval"
                or action["digest"] != payload.get("digest")
                or type(payload.get("approved")) is not bool
            ):
                raise ValidationError("Approval does not match the pending operation")
            action["approved"] = payload["approved"]
            action["status"] = "ready" if payload["approved"] else "failed"
            self.state = "running" if payload["approved"] else "failed"
            if not payload["approved"]:
                self.error = {"code": "approval_rejected"}
            self._emit(
                "approval_applied", {"action_id": action["id"], "approved": action["approved"]}
            )
            return {"state_revision": self.revision}
        if (
            action is None
            or action["kind"] != "tool"
            or action["status"] not in {"outcome_unknown", "completed"}
        ):
            raise ValidationError("No unknown tool effect to reconcile")
        if payload.get("query", False):
            if action["status"] == "completed":
                return {"reason": "already_confirmed", "state_revision": self.revision}
            if any(a["id"] == action["id"] for a in self.reconcile_requests):
                return {"reason": "query_pending", "state_revision": self.revision}
            self.reconcile_requests.append(detached(action))
            self._emit("reconciliation_requested", {"action_id": action["id"]})
            return {"state_revision": self.revision, "evidence_pending": True}
        if "result" not in payload:
            raise ValidationError("Manual reconciliation requires explicit evidence")
        self.accept_tool(
            action["id"],
            {
                "ok": True,
                "result": payload["result"],
                "source": "operator",
                "command_id": command_id,
            },
            reconciled=True,
        )
        return {"state_revision": self.revision}

    @property
    def quiescent(self):
        return (
            self.active_action is None
            and not self.remote_uncertain
            and all(value["execution_stopped"] for value in self.tool_executions.values())
            and (
                self.manifest["kernel"] != "temporal-3"
                or self.budget["reserved"] == self.budget["unknown"] == 0
            )
        )

    def snapshot(self):
        return {
            "run_id": self.run_id,
            "state": self.state,
            "state_revision": self.revision,
            "result": detached(self.result),
            "error": detached(self.error),
            "pending": [
                {
                    "action_id": a["id"],
                    "digest": a["digest"],
                    "tool": a["tool"],
                    "arguments": detached(a["arguments"]),
                }
                for a in self.actions
                if a["status"] == "waiting_approval" and self.state not in TERMINAL
            ],
            "actions": detached(self.actions),
            "consistency": "authoritative",
        }

    def diagnostics(self):
        return {
            "snapshot": self.snapshot(),
            "manifest": detached(self.manifest),
            "release_digest": self.release_digest,
            "budget": self.budget,
            **(
                {"native_history_episodes": detached(self.native_history_episodes)}
                if self.manifest.get("model_history_protocol") == 2
                else {}
            ),
            **(
                {"completion_stages": detached(list(self.completion_stages.values()))}
                if self.manifest.get("completion_protocol") == 1
                else {}
            ),
            **(
                {"limits_stages": detached(list(self.limits_stages.values()))}
                if self.manifest.get("limits_protocol") == 1
                else {}
            ),
            **(
                {"memory_stages": detached(list(self.memory_stages.values()))}
                if self.manifest["kernel"] == "temporal-3"
                else {}
            ),
            **(
                {"session_stages": detached(list(self.session_stages.values()))}
                if "session_save_protocol" in self.manifest
                else {}
            ),
            **(
                {"context_stages": detached(list(self.managed_context_stages.values()))}
                if "managed_context" in self.manifest or self.managed_context_stages
                else {}
            ),
            **(
                {"context_reads": detached(list(self.context_read_stages.values()))}
                if "context_read_protocol" in self.manifest
                else {}
            ),
            "workflow": {
                "backend": "temporal",
                "node": self.node,
                "steps": len(self.request["definition"]["steps"]),
                "quiescent": self.quiescent,
                "remote_stop_confirmed": self.quiescent,
                "active_action": self.active_action,
                "unknown_remote_execution": self.remote_uncertain,
                "reconciliation_pending": bool(
                    self.reconcile_requests or self.active_reconciliation
                ),
                "evidence_ack_pending": bool(self.pending_acks or self.active_evidence_ack),
                "deferred_evidence_acks": len(self.deferred_acks),
                **(
                    {"tool_executions": detached(list(self.tool_executions.values()))}
                    if "tool_execution_protocol" in self.manifest
                    else {}
                ),
            },
        }

    def _reserve(self, action, amount):
        if amount > self.budget["remaining"]:
            self.state, self.error = "failed", {"code": "budget_exceeded"}
            self._emit("run_failed", self.error)
            return False
        attempt_id = f"{action['id']}:attempt:1"
        action["attempts"] = [{"id": attempt_id, "status": "executing"}]
        self.reservations[attempt_id] = {"id": attempt_id, "amount": amount, "status": "reserved"}
        action["status"] = "executing"
        self.active_action, self.state = action["id"], "running"
        self._emit(
            "dispatch_intent_recorded",
            {
                "action_id": action["id"],
                "attempt_id": attempt_id,
                "effect_key": action.get("effect_key"),
                "credits": amount,
            },
        )
        return True

    def _settle(self, action, usage=None, *, undispatched=False):
        if action["attempts"]:
            attempt = action["attempts"][0]
            attempt["status"] = "not_dispatched" if undispatched else "completed"
            reservation = self.reservations[attempt["id"]]
            reservation.update(
                status="settled",
                actual=0 if undispatched else reservation["amount"],
                usage=usage or {},
            )
        if self.active_action == action["id"]:
            self.active_action = None

    def envelope(self, action):
        return {
            "runtime_manifest": detached(self.manifest),
            "scope": self.scope,
            "run_id": self.run_id,
            "action_id": action["id"],
            "attempt_id": action["attempts"][0]["id"],
            "effect_key": action["effect_key"],
            "execution_epoch": self.epoch,
            "tool": action["tool"],
            "tool_manifest": self.manifest["tools"][action["tool"]],
            "arguments": detached(action["arguments"]),
            "operation_digest": action["digest"],
            **(
                {"release_digest": self.release_digest}
                if "tool_execution_protocol" in self.manifest
                else {}
            ),
        }

    def next_operation(self):
        if self.active_action is not None:
            return None
        if self.pending_session is not None or self.session_recovery:
            from .temporal_session_save_state import next_stage as next_session

            operation = next_session(self)
            if operation is not None:
                return operation
        if self.manifest["kernel"] == "temporal-3" and (
            self.pending_completion is not None or self.memory_recovery
        ):
            from .temporal_memory_state import next_stage

            operation = next_stage(self)
            if operation is not None:
                return operation
        if self.state in TERMINAL:
            return None
        if any(not value["execution_stopped"] for value in self.tool_executions.values()):
            return None
        if str(self.node) in self.session_stages:
            # An accepted completion already owns this node. A held save may
            # only resume through its original recovery phases, never a model.
            return None
        if self.manifest.get("model_continuation_protocol") == 1:
            from .temporal_decision_state import next_adoption

            operation = next_adoption(self)
            if operation is not None:
                return operation
        from .temporal_completion_state import next_stage as next_completion

        operation = next_completion(self)
        if operation is not None:
            return operation
        from .temporal_limits_state import next_stage as next_limits

        operation = next_limits(self)
        if operation is not None:
            return operation
        pending = [
            a
            for a in self.actions
            if a["node"] == self.node and a["kind"] == "tool" and a["status"] != "completed"
        ]
        if pending:
            action = pending[0]
            if action["status"] in {"outcome_unknown", "waiting_approval", "blocked"}:
                return None
            manifest = self.step_manifest["tools"][action["tool"]]
            if manifest["requires_approval"] and not action["approved"]:
                action["status"], self.state = "waiting_approval", "waiting_approval"
                self._emit(
                    "approval_requested", {"action_id": action["id"], "digest": action["digest"]}
                )
                return None
            if not self._reserve(action, manifest["cost"]):
                return None
            from .temporal_tool_execution_state import prepare

            return action, prepare(self, action, self.envelope(action))
        if self.decisions >= self.step["max_decisions"]:
            self.state, self.error = "failed", {"code": "decision_limit"}
            self._emit("run_failed", self.error)
            return None
        if "managed_context" in self.step_manifest:
            from .temporal_managed_context import next_stage

            operation = next_stage(self)
            if operation is not None or self.state in TERMINAL:
                return operation
        if ("managed_context" not in self.step_manifest) and (
            self.step_manifest.get("session_data") is not None
            or self.step_manifest.get("facts_context") is not None
            or self.step_manifest.get("knowledge_context") is not None
            or self.step_manifest.get("context_registration") is not None
            or bool(self.request.get("session_history"))
            or self.step_manifest.get("model_history_protocol") == 2
            or self.request.get("session_root_snapshot") is not None
        ):
            signature = self.context_cache_signature()
            if signature != self.context_signature:
                context_id = f"{self.run_id}:context:{self.node}:{self.decisions + 1}"
                retry = getattr(self, "unadmitted_context_retries", {}).get(
                    f"{self.node}:{self.decisions}:context", 0
                )
                if retry:
                    context_id += f":retry:{retry}"
                action = {
                    "id": context_id,
                    "kind": "context",
                    "node": self.node,
                    "status": "executing",
                    "attempts": [],
                }
                self.actions.append(action)
                self.active_action, self.state = action["id"], "running"
                self._emit("context_dispatch_intent_recorded", {"action_id": action["id"]})
                request = {
                    "runtime_manifest": detached(self.manifest),
                    "scope": self.scope,
                    "run_id": self.run_id,
                    "step": detached(self.step),
                    **self.session_context_fields(),
                    **(
                        {"session_data_node": self.node}
                        if "session_data" in self.step_manifest
                        else {}
                    ),
                    **(
                        {"step_bindings": self.step_bindings}
                        if self.manifest["kernel"] == "temporal-3"
                        else {}
                    ),
                    "messages": detached(self.messages),
                    **(
                        {"session_history": detached(self.request["session_history"])}
                        if "session_history" in self.request
                        else {}
                    ),
                    **(
                        {"session_id": self.request.get("session_id") or self.run_id}
                        if "facts_context" in self.step_manifest
                        else {}
                    ),
                }
                from .temporal_context_read_state import envelope as read_envelope

                return action, read_envelope(self, action, request, "context")
        self.decisions += 1
        action = {
            "id": f"{self.run_id}:model:{self.node}:{self.decisions}",
            "kind": "model",
            "node": self.node,
            "status": "ready",
            "attempts": [],
        }
        self.actions.append(action)
        if not self._reserve(action, self.step["model_credits"]):
            return None
        request = {
            "runtime_manifest": detached(self.manifest),
            "step": detached(self.step),
            "messages": detached(self.messages),
        }
        if "session_data" in self.step_manifest:
            request["session_data_node"] = self.node
        if "session_history" in self.request:
            request["session_history"] = detached(self.request["session_history"])
        request.update(self.session_context_fields())
        if self.manifest.get("session_protocol") == 1 or "runtime_profile" in self.manifest:
            request["scope"] = self.scope
        if self.manifest["kernel"] == "temporal-3":
            request.update(step_bindings=self.step_bindings, scope=self.scope)
        if self.context_snapshot is not None and (
            self.step_manifest.get("session_data") is not None
            or self.step_manifest.get("facts_context") is not None
            or self.step_manifest.get("knowledge_context") is not None
            or self.step_manifest.get("context_registration") is not None
            or bool(self.request.get("session_history"))
            or self.step_manifest.get("model_history_protocol") == 2
            or self.request.get("session_root_snapshot") is not None
        ):
            request.update(context=detached(self.context_snapshot), scope=self.scope)
        if (
            self.manifest["kernel"] == "temporal-3"
            or self.manifest.get("dispatch_admission") == "history-1"
            or self.step_manifest.get("managed_context", {}).get("dispatch_admission")
            == "history-1"
        ):
            request.update(
                run_id=self.run_id,
                action_id=action["id"],
                release_digest=self.release_digest,
                scope=self.scope,
            )
            action["dispatch_request_digest"] = digest(request)
        if self.manifest.get("model_continuation_protocol") == 1:
            action["dispatch_request"] = detached(request)
        return action, request

    def session_context_fields(self):
        from .temporal_session_model_history import request_fields as native_fields
        from .temporal_session_tree_reads import request_fields

        return {**request_fields(self), **native_fields(self)}

    def accept_context(self, action_id, response):
        from .temporal_context_read_state import observe, owns

        if owns(self, action_id):
            return observe(self, action_id, response, TemporalRunState._accept_context)
        return self._accept_context(action_id, response)

    def _accept_context(self, action_id, response):
        action = next(a for a in self.actions if a["id"] == action_id)
        self.active_action = None
        if not response.get("ok"):
            from .temporal_context_read_state import recreate_unadmitted

            if recreate_unadmitted(self, action, response):
                return
            action["status"] = "failed"
            if self.state not in TERMINAL:
                self.state, self.error = "failed", {"code": response.get("code", "context_failed")}
            self._emit("context_failed", {"action_id": action_id})
            return
        canonical(response)
        if (
            not isinstance(response.get("references"), list)
            or not isinstance(response.get("messages"), list)
            or len(canonical(response["messages"])) > self.step["max_context_chars"]
        ):
            raise ValidationError("Invalid received model context")
        validate_facts_snapshot(response, self.step_manifest)
        validate_knowledge_snapshot(response, self.step_manifest, self.scope)
        from .temporal_session_state import validate_context_evidence

        validate_context_evidence(response, {**self.request, **self.session_context_fields()})
        validate_session_snapshot(
            response,
            self.step_manifest,
            {
                "scope": self.scope,
                "run_id": self.run_id,
                "session_data_node": self.node,
                "step": self.step,
                **self.session_context_fields(),
            },
        )
        from .temporal_session_tree_reads import adopt

        adopt(self, response)
        if self.step_manifest.get("model_history_protocol") == 2:
            from .session_model_history import validate_model_history_frame
            from .temporal_session_model_history import frame

            validate_model_history_frame(
                frame(self),
                response["messages"],
                allow_tool_result_projection=self.step_manifest["model_history"]["identity"].get(
                    "allow_tool_result_projection", False
                ),
            )
        elif self.step_manifest.get("model_history_protocol") == 1:
            from .model_history import validate_model_history

            validate_model_history(
                self.messages,
                response["messages"],
                allow_tool_result_projection=self.step_manifest["model_history"]["identity"].get(
                    "allow_tool_result_projection", False
                ),
            )
        from .temporal_session_model_history import validate_native_snapshot

        validate_native_snapshot(
            response,
            self.step_manifest,
            {
                **self.request,
                "scope": self.scope,
                "messages": self.messages,
                **self.session_context_fields(),
            },
        )
        if "native_history_snapshot" in response:
            self.native_history_snapshots.setdefault(
                str(self.node), detached(response["native_history_snapshot"])
            )
        self.context_snapshot = detached(response)
        self.context_signature = self.context_cache_signature()
        action["status"], action["response"] = "completed", detached(response)
        self._emit(
            "context_snapshot_recorded", {"action_id": action_id, "digest": digest(response)}
        )

    def accept_managed_context(self, action_id, response):
        from .temporal_context_read_state import observe, owns
        from .temporal_managed_context import accept_stage

        if owns(self, action_id):
            return observe(self, action_id, response, accept_stage)
        accept_stage(self, action_id, response)

    def context_execution_ended(self, payload):
        from .temporal_context_read_state import ended

        return ended(self, payload)

    def accept_limits(self, action_id, response):
        from .temporal_limits_state import accept_stage

        accept_stage(self, action_id, response)

    def admit_context_dispatch(self, payload):
        from .temporal_managed_context import admit_history

        return admit_history(self, payload)

    def operation_unknown(self, action_id, code):
        action = next(a for a in self.actions if a["id"] == action_id)
        from .temporal_tool_execution_state import unknown

        unknown(self, action_id)
        action["status"], action["attempts"][0]["status"] = "outcome_unknown", "unknown"
        self.reservations[action["attempts"][0]["id"]]["status"] = "unknown"
        self.active_action, self.remote_uncertain = None, True
        if action_id in self.tool_executions:
            from .temporal_tool_execution_state import refresh

            refresh(self)
        if self.state not in TERMINAL:
            self.state = "waiting_reconciliation" if action["kind"] == "tool" else "failed"
            self.error = {"code": code, "action_id": action_id}
        self._emit("action_outcome_unknown", {"action_id": action_id, "code": code})

    def admit_tool_dispatch(self, payload):
        from .temporal_tool_execution_state import admit

        return admit(self, payload)

    def tool_execution_ended(self, payload):
        from .temporal_tool_execution_state import ended

        return ended(self, payload)

    def accept_failure(self, action_id, response):
        if response.get("dispatched", True):
            self.operation_unknown(action_id, response.get("code", "activity_failed"))
            return
        action = next(a for a in self.actions if a["id"] == action_id)
        self._settle(action, undispatched=True)
        if response.get("blocked"):
            action["status"] = "blocked"
            if self.state not in TERMINAL:
                self.state, self.error = "waiting_reconciliation", {"code": "prior_effect_unknown"}
            self._emit(
                "prior_effect_blocks_write",
                {"action_id": action_id, "prior": response.get("prior")},
            )
            return
        action["status"] = "failed"
        if self.state not in TERMINAL:
            self.state, self.error = "failed", {"code": response.get("code", "activity_failed")}
        self._emit("run_failed", {"code": response.get("code", "activity_failed")})

    def accept_model(self, action_id, response):
        if self.manifest.get("model_continuation_protocol") == 1:
            from .temporal_decision_state import accept_receipt

            return accept_receipt(self, action_id, response)
        return self._accept_model_decision(action_id, response)

    def accept_model_adoption(self, action_id, response):
        from .temporal_decision_state import accept_adoption

        return accept_adoption(self, action_id, response)

    def _accept_model_decision(self, action_id, response, *, already_received=False):
        decision_required = self.manifest.get("decision_protocol") == 1
        received_v2 = response.get("model_evidence_version") == 2 or (
            decision_required and "received_response" in response
        )
        if not received_v2 and not response["ok"]:
            # Recorded legacy Activity failures must replay their original History.
            self.accept_failure(action_id, response)
            return
        action = next(a for a in self.actions if a["id"] == action_id)
        if received_v2:
            received = detached(response["received_response"])
            action["received_response"] = received
            if not already_received:
                self._settle(action, settlement_usage(received.get("usage")))
        else:
            self._settle(action, response.get("usage"))
        action["status"], action["response"] = "completed", detached(response)
        if not already_received:
            self._emit("model_response_recorded", {"action_id": action_id})
        if self.state in TERMINAL:
            self._emit("late_model_evidence", {"action_id": action_id})
            return
        try:
            if decision_required and not received_v2:
                raise ValidationError("DecisionPolicy requires original received model evidence")
            if received_v2:
                validate_received_response(received)
                validate_model_usage(received["usage"])
                if not response["ok"]:
                    self._reject_model(action, response.get("code", "validation_error"))
                    return
                if response.get("usage") != received["usage"]:
                    raise ValidationError("Model evidence usage disagrees with its proposal")
                if self.manifest.get("decision_protocol") == 1:
                    from .temporal_decision_state import valid_adoption

                    if not valid_adoption(self, action, response):
                        raise ValidationError(
                            "Decision evidence differs from original request or registration"
                        )
                proposal = validate_decision(
                    AgentSpec(**self.step),
                    DecisionProposal(
                        response["output"],
                        tuple(ToolCall(**call) for call in response["tool_calls"]),
                    ),
                    self.manifest["tools"],
                )
                response = {
                    **response,
                    "output": proposal.output,
                    "tool_calls": [
                        {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                        for call in proposal.tool_calls
                    ],
                }
            from .temporal_decision_state import continuation_adoption

            continuation = continuation_adoption(self, response, received if received_v2 else None)
            from .temporal_decision_state import model_history_proposal

            history_proposal = model_history_proposal(self, response)
            calls = response["tool_calls"]
            proposals = []
            for i, call in enumerate(calls):
                if call["name"] not in self.step["tools"]:
                    raise ValidationError("Model proposed an undeclared tool")
                manifest = self.manifest["tools"][call["name"]]
                if not isinstance(call["arguments"], dict) or not Draft202012Validator(
                    manifest["input_schema"]
                ).is_valid(call["arguments"]):
                    raise ValidationError("Model tool arguments do not match Schema")
                identity = f"{self.run_id}:tool:{self.node}:{self.decisions}:{i}"
                operation = {
                    "run_id": self.run_id,
                    "action_id": identity,
                    "scope": self.scope,
                    "tool": manifest,
                    "arguments": call["arguments"],
                }
                proposals.append(
                    {
                        "id": identity,
                        "kind": "tool",
                        "node": self.node,
                        "tool": call["name"],
                        "arguments": detached(call["arguments"]),
                        "digest": digest(operation),
                        "effect_key": "ralf-temporal:"
                        + digest([self.scope, self.run_id, identity]),
                        "call_id": call.get("call_id") or identity,
                        "approved": False,
                        "status": "ready",
                        "attempts": [],
                    }
                )
            if received_v2:
                validate_call_ids([item["call_id"] for item in proposals])
            from .temporal_limits_state import tool_batch_allowed

            if not tool_batch_allowed(self, proposals):
                raise AgentLimitExceeded("Agent tool action limit exceeded")
            if proposals:
                self.actions.extend(proposals)
                from .model_continuation import assistant_message

                native_proposals = proposals
                if history_proposal is not None:
                    native_proposals = [
                        {
                            "tool": raw["name"],
                            "arguments": raw["arguments"],
                            "call_id": actual["call_id"],
                        }
                        for raw, actual in zip(
                            history_proposal["tool_calls"], proposals, strict=True
                        )
                    ]
                message = assistant_message(
                    response["output"],
                    native_proposals,
                    received=received if received_v2 else None,
                    continuation=continuation,
                )
                if (
                    history_proposal is not None
                    and response["output"] is not None
                    and not isinstance(response["output"], str)
                ):
                    message["content"] = canonical(response["output"])
                if self.step_manifest.get("model_history_protocol") == 2:
                    action["native_history_message"] = {
                        "order": len(self.messages),
                        "message": detached(message),
                    }
                self.messages.append(message)
                self._emit(
                    "decision_adopted",
                    {"action_id": action_id, "proposed_actions": [a["id"] for a in proposals]},
                )
            else:
                result = final_output(response["output"], self.step["output_schema"])
                if self.step_manifest.get("model_history_protocol") in (1, 2):
                    from .model_continuation import assistant_message

                    message = assistant_message(
                        response["output"],
                        [],
                        received=received if received_v2 else None,
                        continuation=continuation,
                    )
                    # Preserve raw text/null; map finite non-text JSON to chat content.
                    # The original received/proposed DTO keeps its JSON value type.
                    if response["output"] is not None and not isinstance(response["output"], str):
                        message["content"] = canonical(response["output"])
                    if self.step_manifest.get("model_history_protocol") == 2:
                        action["native_history_message"] = {
                            "order": len(self.messages),
                            "message": detached(message),
                        }
                    self.messages.append(message)
                    self._emit("decision_adopted", {"action_id": action_id, "proposed_actions": []})
                from .temporal_completion_state import prepare as prepare_completion

                if not prepare_completion(self, action, result):
                    self.finish_output(action, result)
        except (ValidationError, AuthorizationDenied, AgentLimitExceeded) as exc:
            if received_v2:
                self._reject_model(action, exc.code)
            else:
                self.state, self.error = "failed", {"code": exc.code}
                self._emit("run_failed", self.error)

    def finish_output(self, action, result):
        from .temporal_memory_state import prepare

        if not prepare(self, action, result):
            self.complete_node(result)

    def accept_completion(self, action_id, response):
        from .temporal_completion_state import accept_stage

        accept_stage(self, action_id, response)

    def complete_node(self, result):
        if not self._freeze_native_history():
            return
        from .temporal_session_save_state import prepare as prepare_session

        if not prepare_session(self, result):
            self._complete_node(result)

    def _complete_node(self, result):
        if not self._freeze_native_history():
            return
        self._emit("node_completed", {"node": self.node, "result_digest": digest(result)})
        if self.node + 1 < len(self.request["definition"]["steps"]):
            self.node += 1
            self.completion_task = detached(result)
            self.current_task = detached(result)
            self.decisions, self.messages = 0, self._turn_messages(self.step, result)
        else:
            self.state, self.result = "succeeded", detached(result)
            self._emit("run_succeeded", {"result_digest": digest(result)})

    def _freeze_native_history(self):
        try:
            freeze_native_history(self)
            return True
        except (DefinitionMismatch, ValidationError) as exc:
            self.state, self.error = "failed", {"code": exc.code}
            self._emit("run_failed", self.error)
            return False

    def accept_memory(self, action_id, response):
        from .temporal_memory_state import accept_stage

        accept_stage(self, action_id, response)

    def accept_session(self, action_id, response):
        from .temporal_session_save_state import accept_stage

        accept_stage(self, action_id, response)

    def session_execution_ended(self, proof):
        self.authorize(proof.get("scope"))
        action = next((a for a in self.actions if a["id"] == proof.get("action_id")), None)
        if (
            set(proof) != {"scope", "action_id", "request_digest", "release_digest"}
            or proof["release_digest"] != self.release_digest
            or action is None
            or (action["kind"], action.get("phase"))
            not in {
                ("managed_session", "session-write"),
                ("session_root_read", "session-root-read"),
            }
            or proof["request_digest"] != action["request_digest"]
            or not action.get("dispatch_grant", {}).get("allowed")
        ):
            raise DefinitionMismatch("Session execution end lost original admitted identity")
        if action["kind"] == "session_root_read":
            from .temporal_parent_session import end_read

            return end_read(self, action, proof)
        stage = self.session_stages[action["stage_key"]]
        if "execution_end_proof" in action:
            return {"action_id": action["id"], "execution_stopped": True}
        if stage.get("write_action") != action["id"]:
            if action["status"] != "completed_no_record":
                raise DefinitionMismatch("Session execution end targets another original attempt")
            # A settled, definitively unwritten attempt still owns its actual
            # end notification. ACK it without stopping a newer writer.
            action["execution_end_proof"] = detached(proof)
            self._emit("session_execution_ended", {"action_id": action["id"]})
            return {"action_id": action["id"], "execution_stopped": True}
        if "execution_end_proof" not in action:
            action["execution_end_proof"] = detached(proof)
            stage["execution_stopped"] = True
            if stage.get("owns_remote_uncertainty"):
                self.remote_uncertain = stage["prior_remote_uncertain"] or any(
                    "write_action" in s
                    and s["status"] == "outcome_unknown"
                    and not s["execution_stopped"]
                    for s in self.session_stages.values()
                )
                stage["owns_remote_uncertainty"] = False
            self._emit("session_execution_ended", {"action_id": action["id"]})
        return {"action_id": action["id"], "execution_stopped": True}

    def _reject_model(self, action, code):
        action.update(status="rejected", decision_error={"code": code})
        self._emit("decision_rejected", {"action_id": action["id"], "code": code})
        self.state, self.error = "failed", {"code": code}
        self._emit("run_failed", self.error)

    def accept_tool(self, action_id, response, *, reconciled=False):
        if not response["ok"]:
            self.accept_failure(action_id, response)
            return
        action = next(a for a in self.actions if a["id"] == action_id)
        result = detached(response["result"])
        if action["status"] == "completed":
            self._emit(
                "late_effect_evidence",
                {
                    "action_id": action_id,
                    "matches_committed_result": digest(result) == digest(action["result"]),
                    "result_digest": digest(result),
                },
            )
            return
        self._settle(action, {"effect": "confirmed"})
        action.update(
            status="completed",
            result=result,
            receipt={"source": response.get("source", "tool-handler")},
        )
        self.pending_acks.append(
            {
                **self.envelope(action),
                "result": result,
                "source": response.get("source", "tool-handler"),
            }
        )
        if "tool_execution_protocol" in self.manifest:
            from .temporal_tool_execution_state import refresh

            refresh(self)
        elif not reconciled:
            # A real completed Activity proves its awaited handler returned. A
            # query/operator receipt alone never proves a lost handler stopped.
            self.remote_uncertain = any(a["status"] == "outcome_unknown" for a in self.actions)
        self._emit(
            "effect_reconciled" if reconciled else "tool_result_committed",
            {"action_id": action_id, "source": response.get("source", "tool-handler")},
        )
        if self.state not in TERMINAL:
            self.state, self.error = "running", None
            message = {
                "role": "tool",
                "tool_call_id": action["call_id"],
                "content": canonical(result),
            }
            if self.step_manifest.get("model_history_protocol") == 2:
                action["native_history_message"] = {
                    "order": len(self.messages),
                    "message": detached(message),
                }
            self.messages.append(message)

    def retry_blocked(self):
        self.pending_acks.extend(self.deferred_acks)
        self.deferred_acks = []
        # Retrying a journal acknowledgement is safe after business terminal;
        # dispatching a blocked operation is not. No control may reopen a Run.
        if self.manifest["kernel"] == "temporal-3":
            from .temporal_memory_state import request_recovery

            request_recovery(self)
            from .temporal_session_save_state import request_recovery as session_recovery

            session_recovery(self)
        if self.state in TERMINAL:
            return
        for action in self.actions:
            if action["status"] == "blocked":
                # No handler was dispatched. A fresh attempt after journal
                # reconciliation is safe, with unchanged action/effect identity.
                action["status"] = "ready"
                self.state, self.error = "running", None
                self._emit("blocked_write_rechecked", {"action_id": action["id"]})


COMMAND_REGISTRY_NAME = "ralf.temporal.commands.v1"
COMMAND_REGISTRY_CAPACITY = 4096


class TemporalCommandRegistryState:
    """Scoped identity guard only. It never stores Run state or applied outcomes."""

    def __init__(self, scope, *, capacity=COMMAND_REGISTRY_CAPACITY):
        if type(capacity) is not int or not 1 <= capacity <= COMMAND_REGISTRY_CAPACITY:
            raise ValidationError("Invalid Temporal command registry capacity")
        self.scope, self.capacity, self.identities = detached(scope), capacity, {}

    def reserve(self, request):
        if request.get("scope") != self.scope:
            raise AuthorizationDenied("Command registry belongs to another trusted scope")
        for key in ("command_id", "kind", "target", "payload_digest"):
            text(request.get(key), f"Command {key}")
        identity = detached({key: request[key] for key in ("kind", "target", "payload_digest")})
        command_id = request["command_id"]
        previous = self.identities.get(command_id)
        if previous is not None and previous != identity:
            raise IdempotencyConflict(
                "Scoped command ID already identifies different content or target"
            )
        if previous is None:
            if len(self.identities) >= self.capacity:
                raise ValidationError("Temporal scoped command registry capacity exhausted")
            self.identities[command_id] = identity
        return {
            "command_id": command_id,
            "target": identity["target"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
        }


def temporal_capabilities():
    return {
        "native_agent": True,
        "sequence": True,
        "history_context": True,
        "durable_approvals": True,
        "history_replay": True,
        "scoped_command_identity": True,
        "queryable_effect_reconciliation": True,
        "graph": False,
        "team": False,
        "dag": False,
        "nesting": False,
        "shared_session": False,
        "remote_memory": False,
        "rag": False,
        "custom_harness": False,
        "custom_context_builder": True,
        "async_runtime_catalog": False,
    }
