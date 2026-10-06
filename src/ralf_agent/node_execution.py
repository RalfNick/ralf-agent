"""Internal node views over one Run authority, never independent child Runs."""

import copy

from .engine import TERMINAL, LocalEngine
from .errors import ValidationError
from .types import digest
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
    manifest = view._workflow.manifest(plan)
    definition = {"kind": "graph", "steps": []}
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
    def __init__(self, authority, run_id, node_id):
        self.authority, self.run_id, self.node_id = authority, run_id, node_id

    def __getattr__(self, name):
        return getattr(self.authority, name)

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
                from .workflow_parallel import close_nodes

                parent["state"], parent["error"] = "failed", copy.deepcopy(frame["error"])
                close_nodes(parent, index)
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
        self.store = NodeExecutionStore(parent.store, run_id, node_id)
        self._active, self._inflight, self._locks, self._drive_users = set(), {}, {}, {}
        self._parallel_tasks = {}
        self._workflow = StaticWorkflowRuntime(
            self, StaticWorkflowCompiler(), StaticWorkflowInterpreter(), parent.workflow_transforms
        )

    def _check_release(self, run):
        self.parent._check_release(self.parent._authorized(run["id"]))
        super()._check_release(run)

    def _operation_active(self, run_id):
        # The parent owns this Task and all real worker threads. Sibling threads
        # must not be mistaken for an abandoned operation in this node.
        return False

    async def _guarded(self, run_id, operation):
        return await operation
