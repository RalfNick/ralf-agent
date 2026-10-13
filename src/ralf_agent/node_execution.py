"""Internal node views over one Run authority, never independent child Runs."""

import copy

from .engine import TERMINAL, LocalEngine
from .errors import ValidationError
from .types import RunSnapshot, digest
from .workflow import (
    ExecutionPlan,
    StaticWorkflowCompiler,
    StaticWorkflowInterpreter,
    ValueRef,
    encode_binding,
)
from .workflow_runtime import StaticWorkflowRuntime


def create_frame(engine, parent, node_id, input):
    node = copy.deepcopy(next(n for n in parent["plan"]["nodes"] if n["id"] == node_id))
    node.update(depends_on=[], when=None, input=encode_binding(ValueRef()))
    plan = ExecutionPlan(
        {
            "format": "ralf-static-plan",
            "schema_version": 2 if node.get("tool") is not None else 1,
            "name": parent["plan"]["name"],
            "version": parent["plan"]["version"],
            "nodes": [node],
            "output": encode_binding(ValueRef(node_id)),
            "output_schema": node["output_schema"],
        }
    ).to_dict()
    view = NodeEngine(engine, parent["id"], node_id)
    definition = {"kind": "graph", "steps": []}
    if "binding_definition" in parent["definition"]:
        from .binding_definitions import BoundDefinition
        from .binding_runtime import descriptor_for, unwrap_definition
        from .workflow import GraphWorkflowSpec

        index = next(i for i, n in enumerate(parent["plan"]["nodes"]) if n["id"] == node_id)
        bindings = (
            {}
            if node["agent"] is None
            else {
                f"graph/nodes/{node_id}": descriptor_for(
                    parent["definition"], index, parent["plan"]
                )
            }
        )
        definition = unwrap_definition(
            BoundDefinition(GraphWorkflowSpec.from_plan(ExecutionPlan(plan)), bindings).to_dict()
        )
        manifest = view._bindings.manifest(definition, plan=plan)
    else:
        manifest = view._workflow.manifest(plan)
    from .agent_limits import pin_projection_limits
    from .binding_manifests import step_manifest

    # Frames share the parent authority: recomputing a policy here must not
    # replace the caps accepted for that parent node.
    index = next(i for i, n in enumerate(parent["plan"]["nodes"]) if n["id"] == node_id)
    pin_projection_limits(manifest, parent["manifest"])
    pin_projection_limits(step_manifest(manifest, 0), engine._step_manifest(parent, index))
    return {
        "id": parent["id"],
        "revision": parent["revision"],
        "scope": parent["scope"],
        "state": "queued",
        "definition": definition,
        "manifest": manifest,
        "release_digest": digest({"definition": definition, "manifest": manifest}),
        "input": copy.deepcopy(input),
        "result": None,
        "error": None,
        "node": None,
        "decisions": 0,
        "messages": [],
        "session_id": f"{parent['session_id']}:node:{node_id}",
        "plan": plan,
        "workflow": {"current": None, "nodes": {node_id: {"state": "pending"}}},
    }


class NodeExecutionStore:
    def __init__(self, authority, run_id, node_id, *, engine=None):
        self.authority, self.run_id, self.node_id = authority, run_id, node_id
        self._parent_engine = engine

    def __getattr__(self, name):
        return getattr(self.authority, name)

    def _reservation_id(self, value):
        return (
            "node-context:" + digest([self.run_id, self.node_id, value])
            if value.startswith("context:")
            else value
        )

    def reserve(self, run_id, reservation_id, amount):
        return self.authority.reserve(run_id, self._reservation_id(reservation_id), amount)

    def settle(self, reservation_id, actual, usage):
        return self.authority.settle(self._reservation_id(reservation_id), actual, usage)

    def mark_unknown(self, reservation_id):
        return self.authority.mark_unknown(self._reservation_id(reservation_id))

    def managed_stage_reservation(self, run_id, reservation_id):
        proof = self.authority.managed_stage_reservation(
            run_id, self._reservation_id(reservation_id)
        )
        return None if proof is None else {**proof, "id": reservation_id}

    def _index(self, parent):
        return next(i for i, n in enumerate(parent["plan"]["nodes"]) if n["id"] == self.node_id)

    def run(self, run_id):
        if run_id != self.run_id:
            raise ValidationError("Node view can access only its parent Run")
        parent = self.authority.run(run_id)
        frame = copy.deepcopy(parent["workflow"]["nodes"][self.node_id]["execution"])
        frame["revision"] = parent["revision"]
        index = self._index(parent)
        frame["actions"] = [
            dict(copy.deepcopy(a), node=0) for a in parent["actions"] if a["node"] == index
        ]
        if parent["state"] in TERMINAL | {"cancelling"} and frame["state"] not in TERMINAL:
            frame["state"] = (
                "cancelling" if parent["state"] in {"failed", "cancelling"} else "cancelled"
            )
        return frame

    def save_run(self, frame):
        # Merge only this branch into the latest authority, even when a sibling
        # committed while its external call was suspended. No second action log.
        with self.authority.transaction():
            parent = self.authority.run(self.run_id)
            state = parent["workflow"]["nodes"][self.node_id]
            previous = state["state"]
            index = self._index(parent)
            owned = [dict(copy.deepcopy(a), node=index) for a in frame["actions"]]
            existing = {a["id"]: a for a in owned}
            parent["actions"] = [existing.pop(a["id"], a) for a in parent["actions"]]
            parent["actions"].extend(existing.values())
            execution = copy.deepcopy(frame)
            execution.pop("actions")
            state["execution"] = execution
            if frame["state"] == "succeeded":
                state.update(state="completed", result=copy.deepcopy(frame["result"]))
                if previous != "completed":
                    self.authority.emit(
                        self.run_id,
                        "workflow_node_completed",
                        {"node_id": self.node_id, "node": index},
                    )
            elif previous != "completed":
                state["state"] = "running" if frame["state"] == "queued" else frame["state"]
            if frame["state"] == "failed" and parent["state"] not in TERMINAL | {"cancelling"}:
                from .local_delegated_coding import delegated_stop_settled, request_cancel
                from .workflow_parallel import close_nodes

                parent["error"] = copy.deepcopy(frame["error"])
                from .binding_manifests import all_step_manifests

                coding = any(
                    m.get("delegated_coding_tools") for m in all_step_manifests(parent["manifest"])
                )
                workers = self._parent_engine is not None and (
                    any(
                        not task.done()
                        for task in self._parent_engine._parallel_tasks.get(self.run_id, ())
                    )
                    or self._parent_engine._threads.has_active_for(self.run_id)
                )
                if not delegated_stop_settled(parent) or (coding and workers):
                    parent["delegated_failure"] = {
                        "code": parent["error"]["code"],
                        "terminal": "failed",
                    }
                    request_cancel(parent, {"command": "failure", "code": parent["error"]["code"]})
                    parent["state"] = "cancelling"
                else:
                    parent["state"] = "failed"
                close_nodes(parent, index)
                self.authority.emit(
                    self.run_id,
                    "run_cancelling" if parent["state"] == "cancelling" else "run_failed",
                    {"code": parent["error"]["code"]},
                )
            self.authority.save_run(parent)
            frame["revision"] = parent["revision"]

    def emit(self, run_id, kind, data=None):
        # Native loop events retain their evidence, with an explicit node scope.
        # Only the parent owns public Workflow lifecycle transitions.
        if kind.startswith("workflow_node_") or kind in {
            "run_resumed",
            "run_succeeded",
            "run_cancelled",
            "run_failed",
        }:
            kind = "node_frame_" + kind
        self.authority.emit(run_id, kind, {**(data or {}), "workflow_node": self.node_id})


class NodeEngine(LocalEngine):
    """Reuse the native effect loop with a private projection and shared resources."""

    def __init__(self, parent, run_id, node_id):
        self.__dict__ = parent.__dict__.copy()
        self.parent, self.node_id = parent, node_id
        self.store = NodeExecutionStore(parent.store, run_id, node_id, engine=parent)
        from .task_controls import _binding

        self._coding_projection = (
            parent,
            parent.store,
            run_id,
            node_id,
            self.store,
            {name: _binding(getattr(self.store, name)) for name in ("run", "save_run")},
        )
        self._active, self._inflight, self._locks, self._drive_users = set(), {}, {}, {}
        self._parallel_tasks = {}
        self._quiescing_runs = set()
        self._workflow = StaticWorkflowRuntime(
            self, StaticWorkflowCompiler(), StaticWorkflowInterpreter(), parent.workflow_transforms
        )
        from .binding_runtime import AgentBindingResolver

        self._bindings = AgentBindingResolver(self)

    def _ensure_open(self):
        from .node_coding_projection import original_engine

        original_engine(self)._ensure_open()

    def _authorized(self, run_id, *, _cleanup_token=None):
        from .node_coding_projection import original_engine

        parent = original_engine(self)
        # This checks the live original permit, not the token copied at construction.
        parent._authorized(run_id, _cleanup_token=_cleanup_token)
        return self.store.run(run_id)

    def _check_release(self, run):
        from .node_coding_projection import original_engine

        parent = original_engine(self)
        parent._check_release(
            parent._authorized(run["id"], _cleanup_token=parent._coding_cleanup_token)
        )
        super()._check_release(run)

    def status(self, run_id):
        frame = self._authorized(run_id)
        if "input_requests" in frame:
            frame = {**frame, "release_digest": self.parent._authorized(run_id)["release_digest"]}
        return RunSnapshot.from_record(frame)

    def _operation_active(self, run_id):
        # The parent owns this Task and all real worker threads. Sibling threads
        # must not be mistaken for an abandoned operation in this node.
        return False

    async def _guarded(self, run_id, operation):
        return await operation
