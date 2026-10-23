"""Graph transitions; execution authority and external effects stay in Engine."""

import copy
import inspect
from dataclasses import asdict

from .errors import DefinitionMismatch, RalfError, ValidationError
from .types import RunSnapshot, digest
from .workflow import (
    ExecutionPlan,
    GraphWorkflowSpec,
    IdentityTransform,
    StaticWorkflowCompiler,
    StaticWorkflowInterpreter,
    WorkflowSelection,
    validate_output,
    validate_selection,
)

CLOSED = {"succeeded", "failed", "cancelled", "cancelling"}


def is_graph(run):
    return run["definition"]["kind"] == "graph"


def agent_step(run, index=None):
    index = run["node"] if index is None else index
    if is_graph(run):
        try:
            step = run["plan"]["nodes"][index]["agent"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValidationError("Graph has no current Agent node") from exc
        if step is None:
            raise ValidationError("Current graph node is not an Agent")
        return step
    return run["definition"]["steps"][index]


def workflow_details(run, store=None):
    if run.get("orchestration") is not None:
        details = copy.deepcopy(run["orchestration"])
        if store is not None:
            for call in details["children"]:
                child = store.run(call["run_id"])
                if child["scope"] != run["scope"] or child.get("parent_id") != run["id"]:
                    raise DefinitionMismatch("Child diagnostics do not belong to this parent")
                call["snapshot"] = asdict(RunSnapshot.from_record(child))
        return details
    if not is_graph(run):
        return None
    details = copy.deepcopy({"plan": run["plan"], **run["workflow"]})
    for state in details["nodes"].values():
        frame = state.pop("execution", None)
        if frame is not None:
            state["session_id"] = frame["session_id"]
            if frame["error"] is not None:
                state["error"] = frame["error"]
    return details


class StaticWorkflowRuntime:
    def __init__(self, engine, compiler, interpreter, transforms):
        self.engine = engine
        engine.workflow_compiler = StaticWorkflowCompiler() if compiler is None else compiler
        engine.workflow_interpreter = (
            StaticWorkflowInterpreter() if interpreter is None else interpreter
        )
        if transforms is not None and (
            not isinstance(transforms, dict)
            or any(not isinstance(name, str) or not name.strip() for name in transforms)
        ):
            raise ValidationError("Register a mapping of named pure transforms")
        engine.workflow_transforms = {"identity": IdentityTransform(), **(transforms or {})}
        engine._component_identity(
            engine.workflow_compiler, ("compile",), True, "Workflow compiler"
        )
        engine._component_identity(
            engine.workflow_interpreter, ("select",), True, "Workflow interpreter"
        )
        for transform in engine.workflow_transforms.values():
            engine._component_identity(transform, ("transform",), True, "Node transform")

    def compile(self, definition):
        engine, compiler = self.engine, self.engine.workflow_compiler
        identity = engine._component_identity(compiler, ("compile",), True, "Workflow compiler")
        try:
            result = engine._component_result(
                compiler.compile(
                    GraphWorkflowSpec.from_dict(
                        definition.get("binding_definition", {}).get("definition", definition)
                    )
                ),
                ExecutionPlan,
                "WorkflowCompiler.compile",
            )
            plan = ExecutionPlan(result.to_dict()).to_dict()
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Workflow compiler failed") from exc
        if digest(identity) != digest(
            engine._component_identity(compiler, ("compile",), True, "Workflow compiler")
        ) or digest(identity) != digest(
            engine._component_identity(
                engine.workflow_compiler, ("compile",), True, "Workflow compiler"
            )
        ):
            raise DefinitionMismatch("The compiling Workflow component changed")
        return plan

    def manifest(self, plan, *, agent_manifests=None):
        from .binding_manifests import merge_coding_manifests

        engine = self.engine
        value = ExecutionPlan(plan).to_dict()
        transforms = {}
        for node in value["nodes"]:
            if node["transform"] is not None:
                name = node["transform"]
                if name not in engine.workflow_transforms:
                    raise DefinitionMismatch(f"Node transform is not configured: {name}")
                transforms[name] = engine._component_identity(
                    engine.workflow_transforms[name], ("transform",), True, "Node transform"
                )
        base = engine._manifest(
            [node["agent"] for node in value["nodes"] if node["agent"] is not None]
            if agent_manifests is None
            else []
        )
        if agent_manifests is not None:
            agent_manifests = tuple(agent_manifests)
            for manifest in agent_manifests:
                base["tools"].update(manifest["tools"])
            merge_coding_manifests(base, agent_manifests)
        tool_names = sorted(
            {node["tool"] for node in value["nodes"] if node.get("tool") is not None}
        )
        base["tools"].update(engine.tools.manifests(tool_names))
        from .local_delegated_coding import manifest_tools as coding_tools

        merge_coding_manifests(base, [{"delegated_coding_tools": coding_tools(engine, tool_names)}])
        from .local_user_input import manifest_tools

        input_tools = manifest_tools(engine, list(base["tools"]))
        if input_tools:
            base.update(kernel="local-9", user_input_protocol=1, user_input_tools=input_tools)
        manifest = {
            **base,
            "workflow": {
                "plan": ExecutionPlan(value).identity,
                "compiler": engine._component_identity(
                    engine.workflow_compiler, ("compile",), True, "Workflow compiler"
                ),
                "interpreter": engine._component_identity(
                    engine.workflow_interpreter, ("select",), True, "Workflow interpreter"
                ),
                "transforms": transforms,
                **(
                    {
                        "scheduler": engine._component_identity(
                            engine.workflow_scheduler, ("select",), True, "Workflow scheduler"
                        )
                    }
                    if value["schema_version"] == 3
                    else {}
                ),
            },
        }
        from .local_coding_composition import mark_composition

        return mark_composition(engine, manifest, {"kind": "graph", "nodes": value["nodes"]})

    async def prepare(self, run_id):
        engine = self.engine
        run = engine._authorized(run_id)
        if run["state"] in CLOSED:
            return False
        if run["node"] is not None:
            node_id = run["plan"]["nodes"][run["node"]]["id"]
            if (
                run["workflow"]["current"] != node_id
                or run["workflow"]["nodes"][node_id]["state"] != "running"
            ):
                raise ValidationError("Graph current node state is inconsistent")
            return True
        engine._check_release(run)
        interpreter = engine.workflow_interpreter
        try:
            selected = engine._component_result(
                interpreter.select(
                    ExecutionPlan(run["plan"]),
                    copy.deepcopy(run["input"]),
                    copy.deepcopy(run["workflow"]["nodes"]),
                ),
                WorkflowSelection,
                "WorkflowInterpreter.select",
            )
            selection = WorkflowSelection(
                selected.node_id, selected.input, selected.skipped, selected.done, selected.result
            )
            validate_selection(
                ExecutionPlan(run["plan"]), run["input"], run["workflow"]["nodes"], selection
            )
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Workflow interpreter failed") from exc
        current = engine._authorized(run_id)
        engine._check_release(current)
        if digest(
            engine._component_identity(interpreter, ("select",), True, "Workflow interpreter")
        ) != digest(run["manifest"]["workflow"]["interpreter"]):
            raise DefinitionMismatch("The selecting Workflow component changed")
        if current["state"] in CLOSED:
            return False
        if digest(current["workflow"]) != digest(run["workflow"]):
            raise ValidationError("Workflow changed during selection")
        messages = []
        index = None
        if not selection.done:
            index = next(
                i for i, node in enumerate(run["plan"]["nodes"]) if node["id"] == selection.node_id
            )
            step = run["plan"]["nodes"][index]["agent"]
            if step is not None:
                step = engine._agent_step(run, index)
                messages = engine._initial_messages(step, selection.input)
                engine._assemble_context(
                    messages,
                    [],
                    step["max_context_chars"],
                    context=engine._components(run, index).context,
                    components=engine._components(run, index),
                )
        if selection.done:
            from .remote_composite_saves import save_result

            if (
                await save_result(engine, run_id, selection.result, skipped=selection.skipped)
                is False
            ):
                return False
        with engine.store.transaction():
            current = engine._authorized(run_id)
            if current["state"] in CLOSED:
                return False
            engine._check_release(current)
            for node_id in selection.skipped:
                if current["workflow"]["nodes"][node_id]["state"] != "skipped":
                    current["workflow"]["nodes"][node_id] = {"state": "skipped"}
                    engine.store.emit(run_id, "workflow_node_skipped", {"node_id": node_id})
            if selection.done:
                from .session_composites import save_composite_turn_result

                save_composite_turn_result(engine, current, selection.result)
                current["state"], current["result"] = "succeeded", selection.result
                engine._commit(current, "run_succeeded")
                return False
            current["node"] = index
            current["workflow"]["current"] = selection.node_id
            current["workflow"]["nodes"][selection.node_id] = {
                "state": "running",
                "input": copy.deepcopy(selection.input),
            }
            current["messages"], current["decisions"] = messages, 0
            engine._commit(
                current, "workflow_node_started", {"node_id": selection.node_id, "node": index}
            )
        return True

    def complete(self, run, result):
        node = run["plan"]["nodes"][run["node"]]
        state = run["workflow"]["nodes"][node["id"]]
        if state["state"] != "running" or run["workflow"]["current"] != node["id"]:
            raise ValidationError("Cannot complete an inactive Workflow node")
        value = validate_output(result, node["output_schema"])
        state.update(state="completed", result=value)
        index = run["node"]
        run["node"], run["workflow"]["current"] = None, None
        run["messages"], run["decisions"] = [], 0
        self.engine._commit(run, "workflow_node_completed", {"node_id": node["id"], "node": index})

    async def transform(self, run_id):
        engine = self.engine
        run = engine._authorized(run_id)
        if run["state"] in CLOSED:
            return True
        engine._check_release(run)
        node = run["plan"]["nodes"][run["node"]]
        transform = engine.workflow_transforms[node["transform"]]
        try:
            value = transform.transform(
                copy.deepcopy(run["workflow"]["nodes"][node["id"]]["input"]),
                copy.deepcopy(node["config"]),
            )
            if (
                inspect.isawaitable(value)
                or inspect.isgenerator(value)
                or inspect.isasyncgen(value)
            ):
                if inspect.iscoroutine(value) or inspect.isgenerator(value):
                    value.close()
                raise ValidationError("Node transform must return completed JSON")
            result = validate_output(value, node["output_schema"])
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Node transform failed") from exc
        with engine.store.transaction():
            current = engine._authorized(run_id)
            engine._check_release(current)
            if digest(
                engine._component_identity(transform, ("transform",), True, "Node transform")
            ) != digest(run["manifest"]["workflow"]["transforms"][node["transform"]]):
                raise DefinitionMismatch("The executing node transform changed")
            if current["state"] not in CLOSED:
                self.complete(current, result)
        return True

    async def tool(self, run_id):
        engine = self.engine
        run = engine._authorized(run_id)
        if run["state"] in CLOSED:
            return True
        engine._check_release(run)
        node = run["plan"]["nodes"][run["node"]]
        action = next(
            (
                item
                for item in run["actions"]
                if item["node"] == run["node"] and item["kind"] == "tool"
            ),
            None,
        )
        if action is None:
            arguments = run["workflow"]["nodes"][node["id"]]["input"]
            proposal = engine._tool_proposal(run_id, run["node"], node["tool"], arguments)
            with engine.store.transaction():
                current = engine._authorized(run_id)
                engine._check_release(current)
                if current["state"] in CLOSED:
                    return True
                current["actions"].append(proposal)
                engine._commit(
                    current,
                    "workflow_tool_proposed",
                    {"node_id": node["id"], "action_id": proposal["id"]},
                )
            action = proposal
        if action["status"] != "completed":
            if not await engine._tool(run_id, action["id"]):
                return False
        with engine.store.transaction():
            current = engine._authorized(run_id)
            engine._check_release(current)
            completed = next(item for item in current["actions"] if item["id"] == action["id"])
            if current["state"] not in CLOSED and completed["status"] == "completed":
                self.complete(current, completed["result"])
        return True
