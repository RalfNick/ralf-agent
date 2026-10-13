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
    # Effective tool grants and exact resources are checked by recorded
    # manifests. Every existing Local definition composes the same authority.
    if definition.get("kind") not in {"agent", "sequence", "graph", "team", "dynamic"}:
        raise ValidationError("Unsupported Local Coding composition")


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
    from .node_coding_projection import original_engine

    engine = original_engine(engine)
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
    from .node_coding_projection import original_engine

    engine = original_engine(engine)
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
    from .local_coding_composition import mark_composition

    mark_composition(engine, manifest, definition, parent_call)
    declarations = any(item.get("delegated_coding_tools") for item in all_step_manifests(manifest))
    if not declarations:
        return
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
    from .node_coding_projection import original_engine

    original = original_engine(engine)
    if original is not engine:
        run = _original_run(original, run["id"])
        engine = original
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
        if (
            run["definition"]["kind"] == "graph"
            and run["plan"]["nodes"][action["node"]]["agent"] is None
        ):
            # Direct Tool nodes have a host grant, not an Agent binding role.
            recorded = engine._step_manifest(run, action["node"])
            if recorded.get("delegated_coding_tools", {}).get(action["tool"]) != handler.identity:
                raise DefinitionMismatch("Original direct Coding Tool grant changed")
            return
        components = engine._components(run, action["node"])
        if action["tool"] not in components.tools or components.runner is not handler.runner:
            raise DefinitionMismatch("Bound Coding Action replaced its original Runner resource")


class LocalCodingAuthority:
    """Single original approved and reserved Action; grants persist before RPC."""

    def __init__(self, engine, run_id, action_id):
        from .node_coding_projection import original_engine

        self._engine, self._run_id, self._action_id = original_engine(engine), run_id, action_id

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
            from .coding_execution_rules import grant as grant_native

            if self.cancelled():
                raise AuthorizationDenied("Delegated coding submission was cancelled or fenced")
            grant = grant_native(state, action, handler.identity, method, params, binding)
            if not grant["execute"]:
                return grant
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
            from .coding_execution_rules import adopt as adopt_native

            adopt_native(state, handler.identity, kind, evidence)
            self._engine._commit(
                run,
                "delegated_receipt_adopted",
                {"action_id": action["id"], "kind": kind, "evidence_digest": digest(evidence)},
            )


def _initial_state(engine, run, action, envelope, handler):
    from .node_coding_projection import original_action

    engine, run, action = original_action(engine, run, action)
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


async def _stop_original_work(engine, run_id):
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
    from .node_coding_projection import original_engine

    return engine._authorized(run_id, _cleanup_token=original_engine(engine)._coding_cleanup_token)


def stops_settled(engine, run):
    if not delegated_stop_settled(run):
        return False
    if run["manifest"].get("delegated_composition_protocol") != 1:
        return True
    from .local_coding_children import stops_settled as child_stops_settled

    return child_stops_settled(engine, run)


async def stop_work(engine, run_id):
    settled = await _stop_original_work(engine, run_id)
    run = _original_run(engine, run_id)
    if (
        run.get("orchestration") is not None
        and run["manifest"].get("delegated_composition_protocol") == 1
    ):
        from .local_coding_children import stop_children

        settled = await stop_children(engine, run_id) and settled
    return settled
