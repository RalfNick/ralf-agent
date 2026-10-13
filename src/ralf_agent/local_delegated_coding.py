"""Original Local ToolAction authority for a bounded delegated coding Turn.

The runner owns native receipts; this module owns permission and the independent
stop/effect journal in the original Run transaction. A DispatchEnvelope is data,
never a permission to launch a process or native Turn.
"""

from __future__ import annotations

import copy
from dataclasses import asdict

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .executors import DispatchEnvelope, EffectObservation
from .types import InvocationContext, canonical, digest


def pending_delegated_work(run):
    return tuple(
        a
        for a in run.get("actions", ())
        if (d := a.get("delegated_execution")) is not None
        and (d.get("pending_stop") is not False or d.get("fenced") is not True)
    )


def delegated_stop_settled(run):
    return not pending_delegated_work(run)


def request_cancel(run, reason):
    for action in pending_delegated_work(run):
        state = action["delegated_execution"]
        state.setdefault("cancel", copy.deepcopy(reason))


def manifest_tools(engine, names):
    from .delegated_coding import registered_coding_tool

    result = {}
    for name in names:
        handler = registered_coding_tool(engine.tools.get(name))
        if handler is not None:
            handler.check()
            # Concrete physical pins are checked before model dispatch as well
            # as native work. Use class methods, never replaceable instance hooks.
            from .codex_runner import CodexCodingRunner

            runner = handler.runner
            if type(runner) is CodexCodingRunner:
                from .runner_journal import RunnerJournal

                try:
                    CodexCodingRunner._check_root(runner)
                    RunnerJournal._check_physical(runner._journal)
                except (OSError, TypeError, ValueError) as exc:
                    raise DefinitionMismatch(
                        "Original Coding physical dependencies changed"
                    ) from exc
            result[name] = handler.identity
    return result


def validate_definition(engine, definition, parent_call=None):
    def contains(value):
        # Follow only serialized definition nodes. Schemas, Literal inputs,
        # argument defaults and component config are caller data, not selections.
        kind = value.get("kind", "agent")
        if kind in {"bound_agent", "bound_definition"}:
            from .binding_runtime import unwrap_definition

            return contains(unwrap_definition(value))
        if kind in {"agent", "sequence"}:
            steps = value.get("steps", [value])
            if "binding_definition" in value:
                from .binding_runtime import descriptor_for

                steps = [
                    {
                        **step,
                        "tools": engine._bindings.resolve(step, descriptor_for(value, i))[0].tools,
                    }
                    for i, step in enumerate(steps)
                ]
            return any(bool(manifest_tools(engine, step.get("tools", ()))) for step in steps)
        if kind == "graph":
            return any(
                (node.get("tool") is not None and bool(manifest_tools(engine, (node["tool"],))))
                or (node.get("agent") is not None and contains(node["agent"]))
                for node in value["nodes"]
            )
        if kind in {"team", "dynamic"}:
            return any(contains(member) for member in value["members"].values())
        return False

    wrapper = definition.get("binding_definition", {})
    descriptors = (
        [wrapper["bindings"]]
        if wrapper.get("kind") == "bound_agent"
        else wrapper.get("agent_bindings", {}).values()
    )
    explicit = any("runner" in descriptor for descriptor in descriptors)
    if (explicit or contains(definition)) and (
        definition.get("kind") not in {"agent", "sequence"} or parent_call is not None
    ):
        raise ValidationError(
            "Delegated coding supports root unbound or explicitly runner-bound Local Agents and sequences only"
        )


_STORE_METHODS = (
    "prepare_delegated_execution",
    "delegated_execution_reservation",
    "delegated_pending",
)


def store_registration(store):
    from .ports import is_sync_callable
    from .task_controls import _binding

    version = getattr(store, "delegated_execution_version", None)
    if version is None:
        return None
    if (
        type(version) is not int
        or version != 1
        or any(not is_sync_callable(getattr(store, name, None)) for name in _STORE_METHODS)
    ):
        raise ValidationError(
            "Delegated execution requires its completed public optional Store capability"
        )
    return {
        "store": store,
        "backend_id": store.backend_id,
        "methods": {name: _binding(getattr(store, name)) for name in _STORE_METHODS},
    }


def check_store(engine):
    from .binding_artifacts import _same_binding

    current = store_registration(engine.store)
    original = engine._delegated_store_registration
    if (
        current is None
        or original is None
        or current["store"] is not original["store"]
        or current["backend_id"] != original["backend_id"]
        or any(
            not _same_binding(current["methods"][name], original["methods"][name])
            for name in _STORE_METHODS
        )
    ):
        raise ValidationError(
            "Delegated execution Store differs from its original optional capability"
        )


def delegated_pending(engine):
    import inspect

    check_store(engine)
    value = engine.store.delegated_pending(engine.scope)
    if (
        type(value) is not tuple
        or len(value) > 10000
        or any(type(item) is not str or not item.strip() or len(item) > 1024 for item in value)
        or len(set(value)) != len(value)
    ):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError(
            "Delegated pending query must return completed finite original Run IDs"
        )
    check_store(engine)
    return value


def activate(engine, manifest, definition, parent_call=None):
    from .binding_manifests import all_step_manifests

    declarations = any(item.get("delegated_coding_tools") for item in all_step_manifests(manifest))
    if not declarations:
        return
    if definition.get("kind") not in {"agent", "sequence"} or parent_call is not None:
        raise ValidationError(
            "Delegated coding supports root unbound or explicitly runner-bound Local Agents and sequences only"
        )
    check_store(engine)
    from .ports import _invoke_sync_none

    _invoke_sync_none(engine.store.prepare_delegated_execution, "Delegated execution preparation")
    check_store(engine)


def _dispatch(envelope):
    return {
        **asdict(envelope.context),
        "tool_manifest": envelope.tool_manifest,
        "arguments": envelope.arguments,
        "operation_digest": envelope.operation_digest,
    }


def _envelope(state):
    dispatch = state["request"]["dispatch"]
    from .types import Scope

    return DispatchEnvelope(
        InvocationContext(
            Scope(**dispatch["scope"]),
            *[
                dispatch[k]
                for k in ("run_id", "action_id", "attempt_id", "effect_key", "execution_epoch")
            ],
        ),
        dispatch["tool_manifest"],
        dispatch["arguments"],
        dispatch["operation_digest"],
    )


def validate_journal(engine, run):
    from .binding_manifests import all_step_manifests, step_manifest

    if any(item.get("delegated_coding_tools") for item in all_step_manifests(run["manifest"])):
        delegated_pending(engine)
    from .delegated_coding import registered_coding_tool
    from .runner_journal_state import _json

    for action in run.get("actions", ()):
        state = action.get("delegated_execution")
        if state is None:
            continue
        try:
            _json(state, "Delegated execution", limit=1048576)
            handler = registered_coding_tool(engine.tools.get(action["tool"]))
            recorded = step_manifest(run["manifest"], action["node"])
            check_action_runner(engine, run, action, handler)
            request = state["request"]
            dispatch = request["dispatch"]
            expected = {
                "scope": run["scope"],
                "run_id": run["id"],
                "action_id": action["id"],
                "attempt_id": action["attempts"][0]["id"],
                "effect_key": action["effect_key"],
                "execution_epoch": dispatch["execution_epoch"],
                "tool_manifest": recorded["tools"][action["tool"]],
                "arguments": action["arguments"],
                "operation_digest": action["digest"],
            }
            if (
                state["version"] != 1
                or type(state["version"]) is not int
                or handler is None
                or state["runner"] != handler.identity
                or len(action["attempts"]) != 1
                or action["approved"] is not True
                or set(request)
                != {
                    "dispatch",
                    "release_digest",
                    "reservation",
                    "definition_digest",
                    "deadline",
                    "request_digest",
                }
                or dispatch != expected
                or not isinstance(dispatch["execution_epoch"], str)
                or not dispatch["execution_epoch"]
                or request["request_digest"]
                != digest({k: v for k, v in request.items() if k != "request_digest"})
                or request["release_digest"] != run["release_digest"]
                or request["definition_digest"] != digest(run["definition"])
                or request["reservation"]
                != {
                    "id": action["attempts"][0]["id"],
                    "amount": recorded["tools"][action["tool"]]["cost"],
                }
                or request["deadline"] is not None
                or type(state["pending_stop"]) is not bool
                or type(state["fenced"]) is not bool
                or type(state["grants"]) is not dict
                or set(state["grants"]) - {"prepare", "thread/start", "turn/start"}
                or state["effect_case"] not in {"pending", "unknown", "confirmed"}
            ):
                raise DefinitionMismatch("Original delegated execution journal changed")
            for method, grant in state["grants"].items():
                if (
                    grant["method"] != method
                    or grant["request"] != request
                    or grant["execute"] is not False
                    or grant["binding"]["request"] != request
                    or grant["binding"]["runner"] != handler.identity
                    or grant["binding"]["dispatch"] != dispatch
                ):
                    raise DefinitionMismatch("Original delegated phase grant changed")
        except (KeyError, IndexError, TypeError, ValidationError) as exc:
            raise DefinitionMismatch("Original delegated execution journal is invalid") from exc


def check_action_runner(engine, run, action, handler):
    """The effective bound step and registered tool borrow the same pinned resource."""
    if handler is None:
        raise DefinitionMismatch("Original delegated Coding handler is unavailable")
    handler.check()
    if "binding_definition" in run["definition"]:
        components = engine._components(run, action["node"])
        if action["tool"] not in components.tools or components.runner is not handler.runner:
            raise DefinitionMismatch("Bound Coding Action replaced its original Runner resource")


class LocalCodingAuthority:
    """Single original approved and reserved Action; grants persist before RPC."""

    def __init__(self, engine, run_id, action_id):
        self._engine, self._run_id, self._action_id = engine, run_id, action_id

    def _current(self):
        engine = self._engine
        check_store(engine)
        run = _original_run(engine, self._run_id)
        engine._check_release(run)
        action = next((a for a in run["actions"] if a["id"] == self._action_id), None)
        if action is None or action.get("kind") != "tool" or not action.get("approved"):
            raise AuthorizationDenied("Delegated coding requires the original approved ToolAction")
        from .delegated_coding import registered_coding_tool

        handler = registered_coding_tool(engine.tools.get(action["tool"]))
        if handler is None:
            raise AuthorizationDenied("The original ToolAction has no registered coding resource")
        handler.check()
        check_action_runner(engine, run, action, handler)
        state = action.get("delegated_execution")
        if state is None or state.get("version") != 1 or len(action["attempts"]) != 1:
            raise AuthorizationDenied("Delegated coding requires one original reserved execution")
        reservation = engine.store.delegated_execution_reservation(
            run["id"], action["attempts"][0]["id"]
        )
        if (
            type(reservation) is not dict
            or set(reservation) != {"id", "amount", "state"}
            or reservation["id"] != action["attempts"][0]["id"]
            or type(reservation["amount"]) is not int
            or reservation["amount"] != engine.tools.get(action["tool"]).spec.cost
            or reservation["state"] not in {"reserved", "unknown", "settled"}
        ):
            raise AuthorizationDenied("Original delegated execution reservation is unavailable")
        if (
            reservation["state"] == "settled"
            and action["status"] != "completed"
            and state.get("effect_case") != "confirmed"
        ):
            raise AuthorizationDenied("Delegated execution reservation was released")
        return run, action, state, handler

    def check(self, envelope, runneridentity):
        if type(envelope) is not DispatchEnvelope:
            raise AuthorizationDenied("Delegated coding requires an original DispatchEnvelope")
        run, action, state, handler = self._current()
        if canonical(handler.identity) != canonical(runneridentity) or canonical(
            _dispatch(envelope)
        ) != canonical(state["request"]["dispatch"]):
            raise DefinitionMismatch("Delegated coding original dispatch or resource changed")
        request = state["request"]
        if (
            request["release_digest"] != run["release_digest"]
            or request["definition_digest"] != digest(run["definition"])
            or request["dispatch"]["operation_digest"] != action["digest"]
            or request["dispatch"]["arguments"] != action["arguments"]
            or request["dispatch"]["tool_manifest"]
            != self._engine.tools.get(action["tool"]).manifest
            or request["dispatch"]["scope"] != run["scope"]
        ):
            raise DefinitionMismatch("Delegated coding original request changed")
        unsigned = {k: v for k, v in request.items() if k != "request_digest"}
        if request["request_digest"] != digest(unsigned):
            raise DefinitionMismatch("Delegated coding original intent digest changed")
        return copy.deepcopy(request)

    def resource_state(self, envelope, runneridentity):
        """Read original grants/locators for cold stop; never permits new work."""
        self.check(envelope, runneridentity)
        _, _, state, _ = self._current()
        return copy.deepcopy(
            {
                "prepare_grant": state["grants"].get("prepare"),
                **{kind: state.get(kind) for kind in ("prepared", "binding", "thread", "turn")},
            }
        )

    def cancelled(self):
        run, _, state, _ = self._current()
        return run["state"] in {"cancelling", "cancelled", "failed"} or "cancel" in state

    def authorize(self, method, params, binding):
        if self._engine._coding_cleanup_token is not None:
            raise AuthorizationDenied("Coding cleanup cannot submit new native work")
        canonical(params)
        canonical(binding)
        with self._engine.store.transaction():
            run, action, state, handler = self._current()
            self.check(_envelope(state), handler.identity)
            if (
                run["id"] not in self._engine._active
                or run["state"] != "running"
                or action["status"] != "executing"
                or state["request"]["dispatch"]["execution_epoch"] != self._engine.owner
            ):
                raise AuthorizationDenied(
                    "Native submission requires its active original coordinator epoch"
                )
            if method not in {"prepare", "thread/start", "turn/start"}:
                raise AuthorizationDenied("Native method has no original coding grant")
            if (
                self.cancelled()
                or run["state"] in {"succeeded", "failed", "cancelled"}
                or (state.get("fenced") and state["grants"])
            ):
                raise AuthorizationDenied("Delegated coding submission was cancelled or fenced")
            if (
                binding.get("request") != state["request"]
                or binding.get("runner") != handler.identity
                or binding.get("dispatch") != state["request"]["dispatch"]
            ):
                raise DefinitionMismatch("Native grant binding differs from original intent")
            if method == "prepare":
                environment = binding.get("environment")
                generation = digest(
                    {"dispatch": state["request"]["dispatch"], "runner": handler.identity}
                )[:32]
                if (
                    type(environment) is not dict
                    or environment.get("expected_generation") != generation
                ):
                    raise DefinitionMismatch(
                        "Preparation grant requires its original namespace generation"
                    )
                if handler.identity.get("kind") == "codex-coding-runner":
                    from pathlib import Path

                    dispatch = state["request"]["dispatch"]
                    resource_key = digest(
                        {"scope": dispatch["scope"], "effect_key": dispatch["effect_key"]}
                    )
                    expected_path = str(Path(handler.identity["root"]["path"]) / resource_key)
                    if (
                        environment.get("root", {}).get("path") != expected_path
                        or environment.get("docker_host") != handler.identity["docker_host"]
                        or environment.get("profile") != handler.identity["profile"]
                        or environment.get("retire_on_stop") is not True
                    ):
                        raise DefinitionMismatch(
                            "Preparation grant replaced original namespace dependencies"
                        )
                expected = {}
            else:
                prepared = state.get("prepared")
                if prepared is None or state.get("binding") != binding:
                    raise AuthorizationDenied(
                        "Native grant requires its adopted original environment"
                    )
                expected = {
                    "cwd": "/workspace",
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                }
                if method == "thread/start":
                    expected["ephemeral"] = False
                else:
                    if not state.get("thread"):
                        raise AuthorizationDenied(
                            "Native Turn requires its adopted original Thread"
                        )
                    expected.update(
                        threadId=state["thread"]["thread_id"],
                        input=[
                            {
                                "type": "text",
                                "text": action["arguments"]["task"],
                                "text_elements": [],
                            }
                        ],
                    )
            if params != expected:
                raise AuthorizationDenied("Native request differs from its bounded original grant")
            grant = {
                "request": copy.deepcopy(state["request"]),
                "method": method,
                "params": copy.deepcopy(params),
                "binding": copy.deepcopy(binding),
                "execute": False,
            }
            prior = state["grants"].get(method)
            if prior is not None:
                if any(prior[k] != grant[k] for k in ("method", "params", "binding", "request")):
                    raise DefinitionMismatch("Native phase cannot replace its original submission")
                return grant
            state["grants"][method] = copy.deepcopy(grant)
            state["pending_stop"] = True
            state["fenced"] = False
            state["phase"] = method + "_submitted"
            self._engine._commit(
                run, "delegated_phase_granted", {"action_id": action["id"], "method": method}
            )
            grant["execute"] = True
            return grant

    def adopt(self, kind, evidence):
        canonical(evidence)
        if (
            kind
            not in {
                "prepared",
                "thread",
                "turn",
                "observation",
                "stop",
                "result_candidate",
                "error",
            }
            or type(evidence) is not dict
        ):
            raise ValidationError("Invalid delegated receipt")
        with self._engine.store.transaction():
            run, action, state, handler = self._current()
            self.check(_envelope(state), handler.identity)
            if kind == "prepared":
                if "prepare" not in state["grants"]:
                    raise AuthorizationDenied(
                        "Environment receipt has no original preparation grant"
                    )
                original = state["grants"]["prepare"]["binding"]["environment"]
                if (
                    evidence.get("identity") != original
                    or evidence.get("generation") != original.get("expected_generation")
                    or type(evidence.get("container_id")) is not str
                    or len(evidence["container_id"]) != 64
                    or set(evidence["container_id"]) - set("0123456789abcdef")
                ):
                    raise DefinitionMismatch(
                        "Environment receipt replaced its granted original namespace"
                    )
                if "prepared" in state and any(
                    state["prepared"].get(k) != evidence.get(k)
                    for k in ("identity", "container_id", "generation")
                ):
                    raise DefinitionMismatch("Original environment receipt changed")
                state["prepared"] = copy.deepcopy(evidence)
                state["binding"] = {
                    "request": copy.deepcopy(state["request"]),
                    "runner": handler.identity,
                    "dispatch": copy.deepcopy(state["request"]["dispatch"]),
                    "environment": {
                        "identity": evidence["identity"],
                        "container_id": evidence["container_id"],
                        "generation": evidence["generation"],
                    },
                }
            elif kind in {"thread", "turn"}:
                required = {"thread_id"} if kind == "thread" else {"thread_id", "turn_id"}
                if set(evidence) != required or any(
                    type(evidence[key]) is not str
                    or not evidence[key].strip()
                    or len(evidence[key]) > 1024
                    for key in required
                ):
                    raise ValidationError("Native receipt requires bounded original locators")
                if f"{kind}/start" not in state["grants"]:
                    raise AuthorizationDenied("Native receipt has no original submission grant")
                if kind == "turn" and evidence.get("thread_id") != state.get("thread", {}).get(
                    "thread_id"
                ):
                    raise DefinitionMismatch("Native Turn receipt changed its original Thread")
                if kind in state and state[kind] != evidence:
                    raise DefinitionMismatch("Native handle receipt changed")
                state[kind] = copy.deepcopy(evidence)
            elif kind == "stop":
                preparation = state["grants"].get("prepare")
                if preparation is None:
                    raise AuthorizationDenied(
                        "Stop receipt has no original namespace preparation grant"
                    )
                namespace = preparation["binding"]["environment"]
                if (
                    evidence.get("identity") != namespace
                    or evidence.get("generation") != namespace.get("expected_generation")
                    or type(evidence.get("container_id")) is not str
                    or len(evidence["container_id"]) != 64
                    or set(evidence["container_id"]) - set("0123456789abcdef")
                ):
                    raise DefinitionMismatch("Stop receipt replaced the granted original namespace")
                prepared = state.get("prepared")
                if prepared is not None and any(
                    evidence.get(k) != prepared.get(k)
                    for k in ("container_id", "generation", "identity")
                ):
                    raise DefinitionMismatch("Stop receipt belongs to another original environment")
                state["stop"] = copy.deepcopy(evidence)
                if (
                    evidence.get("fenced") is True
                    and evidence.get("stopped") is True
                    and evidence.get("retired") is True
                    and evidence.get("container_present") is False
                    and evidence.get("running") is False
                ):
                    state["pending_stop"] = False
                    state["fenced"] = True
            elif kind == "result_candidate":
                candidate = evidence.get("result", {})
                native = candidate.get("native", {})
                observation = state.get("observation", {})
                stopped = state.get("stop", {})
                if (
                    native.get("status") != "completed"
                    or observation.get("native_status") != "completed"
                    or observation.get("final_thread_read") is not True
                    or any(
                        native.get(k) != state.get("turn", {}).get(k)
                        for k in ("thread_id", "turn_id")
                    )
                    or state["pending_stop"]
                    or not state["fenced"]
                    or candidate.get("stop")
                    != {k: stopped.get(k) for k in ("container_id", "generation", "fenced")}
                ):
                    raise ValidationError(
                        "Native result candidate requires original completion, read and fencing receipts"
                    )
                if "result_candidate" in state and state["result_candidate"] != candidate:
                    raise DefinitionMismatch("Original native result candidate changed")
                state["result_candidate"] = copy.deepcopy(candidate)
            elif kind == "observation":
                if any(
                    evidence.get(k) != state.get("turn", {}).get(k)
                    for k in ("thread_id", "turn_id")
                ):
                    raise DefinitionMismatch("Native observation belongs to another original Turn")
                state["observation"] = copy.deepcopy(evidence)
            else:
                state["error"] = copy.deepcopy(evidence)
            state["phase"] = kind
            self._engine._commit(
                run,
                "delegated_receipt_adopted",
                {"action_id": action["id"], "kind": kind, "evidence_digest": digest(evidence)},
            )


def _initial_state(engine, run, action, envelope, handler):
    request = {
        "dispatch": _dispatch(envelope),
        "release_digest": run["release_digest"],
        "reservation": {
            "id": envelope.context.attempt_id,
            "amount": engine.tools.get(action["tool"]).spec.cost,
        },
        "definition_digest": digest(run["definition"]),
        "deadline": None,
    }
    request["request_digest"] = digest(request)
    return {
        "version": 1,
        "request": request,
        "runner": handler.identity,
        "phase": "intent",
        "grants": {},
        "pending_stop": False,
        "fenced": True,
        "native_unknown": False,
        "effect_case": "pending",
    }


async def tool(engine, run_id, action_id):
    from .delegated_coding import registered_coding_tool

    run = engine._authorized(run_id)
    action = next(a for a in run["actions"] if a["id"] == action_id)
    handler = registered_coding_tool(engine.tools.get(action["tool"]))
    if handler is None:
        raise AuthorizationDenied("Original delegated resource is unavailable")
    engine._check_release(run)
    check_action_runner(engine, run, action, handler)
    recorded = engine._step_manifest(run, action["node"])["tools"][action["tool"]]
    cold = "delegated_execution" in action
    if not cold:
        with engine.store.transaction():
            run = engine._authorized(run_id)
            action = next(a for a in run["actions"] if a["id"] == action_id)
            if run["state"] == "cancelling":
                return False
            attempt_id = action["id"] + ":1"
            engine.store.reserve(run_id, attempt_id, recorded["cost"])
            action["attempts"].append({"id": attempt_id, "status": "executing"})
            action["status"] = "executing"
            context = InvocationContext(
                engine.scope, run_id, action_id, attempt_id, action["effect_key"], engine.owner
            )
            envelope = DispatchEnvelope(
                context,
                recorded,
                action["arguments"],
                action["digest"],
            )
            action["delegated_execution"] = _initial_state(engine, run, action, envelope, handler)
            engine._commit(
                run,
                "tool_dispatch_intent",
                {
                    "action_id": action_id,
                    "attempt_id": attempt_id,
                    "digest": action["digest"],
                    "effect_key": action["effect_key"],
                },
            )
    state = engine._authorized(run_id)["actions"]
    state = next(a["delegated_execution"] for a in state if a["id"] == action_id)
    envelope = _envelope(state)
    authority = LocalCodingAuthority(engine, run_id, action_id)
    try:
        observation = await (
            handler.runner.reconcile(envelope, authority=authority)
            if cold
            else handler.runner.execute(envelope, authority=authority)
        )
        handler.check()
        run = engine._authorized(run_id)
        action = next(a for a in run["actions"] if a["id"] == action_id)
        if observation is not None:
            engine._component_result(observation, EffectObservation, "CodingRunner")
            if (
                pending_delegated_work(run)
                or "result_candidate" not in action["delegated_execution"]
                or observation.result != action["delegated_execution"]["result_candidate"]
            ):
                raise ValidationError(
                    "Native result lacks original stopped and fenced candidate evidence"
                )
            if run["state"] != "cancelling" and "cancel" not in action["delegated_execution"]:
                with engine.store.transaction():
                    run = engine._authorized(run_id)
                    action = next(a for a in run["actions"] if a["id"] == action_id)
                    action["delegated_execution"]["effect_case"] = "confirmed"
                    engine._commit(run, "delegated_effect_confirmed", {"action_id": action_id})
                engine._record_tool_observation(
                    run_id,
                    action_id,
                    observation,
                    {"source": observation.source, "attempt_id": envelope.context.attempt_id},
                )
                engine._adopt_tool_observation(run_id, action_id)
                return True
    except Exception as exc:
        with engine.store.transaction():
            run = engine._authorized(run_id)
            action = next(a for a in run["actions"] if a["id"] == action_id)
            action["delegated_execution"]["error"] = {
                "code": getattr(exc, "code", "delegated_execution_unknown")
            }
            engine._commit(run, "delegated_execution_error", {"action_id": action_id})
    await stop_work(engine, run_id)
    with engine.store.transaction():
        run = engine._authorized(run_id)
        action = next(a for a in run["actions"] if a["id"] == action_id)
        action["status"] = "outcome_unknown"
        action["attempts"][0]["status"] = "unknown"
        action["delegated_execution"]["effect_case"] = "unknown"
        action["delegated_execution"]["native_unknown"] = True
        engine.store.mark_unknown(envelope.context.attempt_id)
        if run["state"] != "cancelling":
            run["state"] = "waiting_reconciliation"
        engine._commit(run, "effect_unknown", {"action_id": action_id})
    return False


async def stop_work(engine, run_id):
    from .delegated_coding import registered_coding_tool

    for action in pending_delegated_work(_original_run(engine, run_id)):
        run = _original_run(engine, run_id)
        engine._check_release(run)
        handler = registered_coding_tool(engine.tools.get(action["tool"]))
        check_action_runner(engine, run, action, handler)
        authority = LocalCodingAuthority(engine, run_id, action["id"])
        try:
            evidence = await handler.runner.stop_existing(
                _envelope(action["delegated_execution"]), authority=authority
            )
            handler.check()
            if evidence is not None:
                authority.adopt("stop", evidence)
        except Exception as exc:
            authority.adopt("error", {"code": getattr(exc, "code", "delegated_stop_unknown")})
    return delegated_stop_settled(_original_run(engine, run_id))


def _original_run(engine, run_id):
    """Private receipt/stop permit; public business operations remain closed."""
    return engine._authorized(run_id, _cleanup_token=engine._coding_cleanup_token)
