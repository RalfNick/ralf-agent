"""Opt-in context stages: effects in Activities, acceptance in original History."""

import asyncio

from .artifacts import ArtifactReference
from .context_summaries import ContextSummary
from .data_context import ManagedDataContext
from .decisions import final_output
from .errors import AuthorizationDenied, DefinitionMismatch, NotFound, ValidationError
from .managed_context import ManagedContextPipeline
from .memory import memory_call
from .model_evidence import settlement_usage, snapshot_model_response, validate_received_response
from .temporal_state import TERMINAL, detached
from .types import ModelResponse, Scope, canonical, digest

ACTIVITY = "ralf.temporal.managed-context.v1"
ADMISSION_UPDATE = "admit_context_dispatch"


def capabilities(manifest):
    policy = manifest.get("managed_context", {}).get("policy", {})
    return {
        "automatic_context_compression": bool(policy),
        "large_tool_result_offload": policy.get("kind") == "managed-data-context",
    }


def artifact_records(state):
    records = {}
    for stage in getattr(state, "managed_context_stages", {}).values():
        for item in stage.get("prepared", {}).get("offloads", []):
            reference = item["reference"]
            key = reference["artifact_id"]
            if key in records:
                continue
            records[key] = {
                "intent": {
                    "run_id": state.run_id,
                    "release_digest": state.release_digest,
                    "scope": detached(state.scope),
                    "reference": detached(reference),
                    "policy": detached(
                        stage["policy"]
                        if "policy" in stage
                        else state.manifest["managed_context"]["policy"]
                    ),
                },
                "value": detached(item["value"]),
                "status": "verified"
                if key in state.context_artifact_receipts
                else "writing"
                if key in state.context_artifact_dispatches
                else "prepared",
                "dispatched": key in state.context_artifact_dispatches,
                "dispatch_digest": state.context_artifact_dispatches.get(key),
                "receipt_digest": state.context_artifact_receipts.get(key),
            }
    return list(records.values())


def registration(runtime):
    from .temporal_activities import component_identity

    context = runtime.context
    if not isinstance(context, ManagedContextPipeline):
        return None
    context.check()
    provider = runtime.providers.get(context.provider) if context.mode == "model" else None
    if context.mode == "model" and provider is None:
        raise DefinitionMismatch("Host summary provider is unavailable")
    return {
        "version": 1,
        "policy": context.identity,
        "provider": None if provider is None else component_identity(provider, ("complete",)),
        "summary_credits": 1,
        "dispatch_admission": "history-1",
    }


def check_scope(manifest, scope):
    policy = manifest.get("managed_context", {}).get("policy", {})
    if policy.get("kind") == "managed-data-context" and policy["scope"] != scope:
        raise AuthorizationDenied("Temporal data context belongs to another Scope")


def _check(runtime, request, context):
    runtime.validate_release(request["runtime_manifest"])
    check_scope(request["runtime_manifest"], request["scope"])
    if runtime.context is not context:
        raise DefinitionMismatch("Executing Temporal context changed during I/O")
    context.check()


async def _read(runtime, request, context, reference):
    value = await asyncio.wait_for(
        memory_call(context.artifacts.get, context.scope, reference), context.timeout
    )
    _check(runtime, request, context)
    if (
        digest(value) != reference.content_digest
        or len(canonical(value).encode("utf-8")) != reference.byte_length
    ):
        raise DefinitionMismatch("Artifact payload differs from fixed History reference")
    return value


async def validate_snapshot(runtime, request):
    if "managed_context" not in runtime.manifest:
        return
    context = runtime.context
    _check(runtime, request, context)
    if isinstance(context, ManagedDataContext):
        for item in request["context"]["context_identity"].get("artifact_projection", []):
            reference = ArtifactReference.from_dict(item["reference"])
            if (
                reference.backend_id != context.artifacts.backend_id
                or reference.namespace != context.namespace
                or (reference.workspace, reference.principal)
                != (context.scope.workspace, context.scope.principal)
            ):
                raise DefinitionMismatch("Context artifact lost original ownership")
            await _read(runtime, request, context, reference)
    _check(runtime, request, context)


async def admit_dispatch(request, guard):
    if (
        request["runtime_manifest"]["kernel"] != "temporal-3"
        and (
            request["runtime_manifest"].get("managed_context", {}).get("dispatch_admission")
            != "history-1"
        )
        and request["runtime_manifest"].get("dispatch_admission") != "history-1"
    ):
        return
    if guard is None:
        raise ValidationError("Managed dispatch requires its original History admission")
    proof = await guard(detached(request))
    expected = {k: request[k] for k in ("run_id", "action_id", "release_digest")}
    if (
        type(proof) is not dict
        or any(proof.get(k) != v for k, v in expected.items())
        or type(proof.get("allowed")) is not bool
    ):
        raise DefinitionMismatch("Dispatch grant differs from original History operation")
    if not proof["allowed"]:
        raise ValidationError("Original Run closed before external dispatch admission")


def admit_history(state, payload):
    from .temporal_context_read_state import admit, owns

    if owns(state, payload.get("action_id")):
        return admit(state, payload)
    if (
        state.manifest["kernel"] != "temporal-3"
        and state.manifest.get("managed_context", {}).get("dispatch_admission") != "history-1"
        and state.manifest.get("dispatch_admission") != "history-1"
    ) or payload.get("phase") not in {
        "model",
        "write",
        "summary",
        "select",
        "memory-write",
        "session-write",
        "session-root-read",
    }:
        raise ValidationError("Unsupported managed external dispatch admission")
    state.authorize(payload["scope"])
    if payload.get("release_digest") != state.release_digest:
        raise DefinitionMismatch("Dispatch admission lost original release")
    action = next(
        (a for a in getattr(state, "actions", []) if a["id"] == payload["action_id"]), None
    )
    if payload.get("phase") == "session-root-read" and (
        "session_tree_protocol" not in state.manifest
        or action is None
        or action["kind"] != "session_root_read"
    ):
        raise DefinitionMismatch("Root read admission requires its original Parent Action")
    proof = {
        "run_id": state.run_id,
        "action_id": payload["action_id"],
        "release_digest": state.release_digest,
        "allowed": False,
    }
    if (
        action is None
        or payload.get("phase") != ("model" if action["kind"] == "model" else action.get("phase"))
        or payload.get("request_digest")
        != action.get("dispatch_request_digest", action.get("request_digest"))
    ):
        raise DefinitionMismatch("Dispatch admission differs from original Activity intent")
    if "dispatch_grant" in action:
        return detached(action["dispatch_grant"])
    if (
        state.state not in TERMINAL
        and state.active_action == action["id"]
        and action["status"] == "executing"
    ):
        proof["allowed"] = True
        action["dispatch_grant"] = detached(proof)
        state._emit(
            "context_external_dispatch_admitted",
            {"action_id": action["id"], "phase": payload["phase"]},
        )
    return proof


async def execute(runtime, request, *, dispatch_guard=None):
    """Exactly one phase; never retries an optional model or artifact write."""
    from .temporal_activities import _code, _completed_none
    from .temporal_context import validate_context, validate_prepared

    context, dispatched = runtime.context, False
    try:
        _check(runtime, request, context)
        phase = request["phase"]
        if phase == "plan":
            from .temporal_session_state import validate_history

            validate_history(request, request["runtime_manifest"], request.get("scope"))
            if runtime.manifest.get("model_history_protocol") == 2:
                from .temporal_session_model_history import validate_request_frame

                validate_request_frame(request)
            scope = Scope(**request["scope"])
            references = (
                []
                if runtime.knowledge is None
                else await runtime.knowledge.references(
                    scope,
                    (
                        request.get("current_task")
                        if isinstance(request.get("current_task"), str)
                        else canonical(request["current_task"])
                        if "current_task" in request
                        else request["messages"][1]["content"]
                    ),
                )
            )
            _check(runtime, request, context)
            if (
                type(references) is not list
                or any(type(r) is not dict for r in references)
                or (
                    runtime.knowledge is not None
                    and (
                        len(references) > runtime.knowledge.limit
                        or len(canonical(references)) > runtime.knowledge.max_chars
                    )
                )
            ):
                raise ValidationError("Invalid or unbounded context references")
            references = detached(references)
            if runtime.knowledge is not None:
                _completed_none(
                    await runtime.knowledge.validate(scope, detached(references)),
                    "Knowledge validation",
                )
                _check(runtime, request, context)
            from .temporal_facts import load

            evidence = await load(runtime, request, references)
            from .temporal_session_state import context_evidence

            evidence.update(context_evidence(request))
            from .temporal_session_data import load as load_session

            evidence.update(await load_session(runtime, request))
            from .temporal_session_model_history import load_native

            evidence.update(await load_native(runtime, request))
            references = (
                evidence["references"]
                + evidence.get("session_references", [])
                + evidence.get("session_data_references", [])
            )
            history, limit = request["messages"], request["step"]["max_context_chars"]
            if runtime.model_history is not None:
                from .temporal_context import assemble_history

                messages, identity = assemble_history(
                    runtime, history, references, limit, frame=request.get("model_history_frame")
                )
                plan = None
            else:
                messages, identity = context.assemble(
                    detached(history), detached(references), limit
                )
                validate_context(messages, identity, limit)
                plan = context.prepare(detached(history), detached(references), limit)
            return {
                "ok": True,
                "plan": detached(plan),
                "fallback": {"messages": messages, "manifest": identity},
                **evidence,
                "offloads": context.offloads(history)
                if isinstance(context, ManagedDataContext)
                and (
                    runtime.model_history is None
                    or runtime.manifest["model_history"]["identity"].get(
                        "allow_tool_result_projection", False
                    )
                )
                else [],
                "source_digest": digest(history),
            }
        if phase in {"read", "verify"}:
            reference = ArtifactReference.from_dict(request["artifact"]["reference"])
            try:
                await _read(runtime, request, context, reference)
                return {"ok": True, "found": True, "reference": reference.to_dict()}
            except NotFound:
                _check(runtime, request, context)
                return {"ok": True, "found": False}
        if phase == "write":
            item = request["artifact"]
            reference = ArtifactReference.from_dict(item["reference"])
            if digest(item["value"]) != reference.content_digest:
                raise DefinitionMismatch("Artifact dispatch value changed")
            await admit_dispatch(request, dispatch_guard)
            _check(runtime, request, context)
            # Permission to put is the separate History dispatch, never a read-then-write retry.
            dispatched = True
            received = await asyncio.wait_for(
                memory_call(
                    context.artifacts.put, context.scope, context.namespace, detached(item["value"])
                ),
                context.timeout,
            )
            _check(runtime, request, context)
            if received != reference:
                raise DefinitionMismatch("Artifact receipt differs from History intent")
            return {"ok": True, "reference": received.to_dict(), "dispatched": True}
        if phase == "summary":
            provider = runtime.providers[context.provider]
            complete = provider.complete
            model_request = context.request(detached(request["plan"]))
            _check(runtime, request, context)
            await admit_dispatch(request, dispatch_guard)
            _check(runtime, request, context)
            if (
                runtime.providers.get(context.provider) is not provider
                or provider.complete != complete
            ):
                raise DefinitionMismatch("Executing summary provider changed before dispatch")
            dispatched = True
            response = await asyncio.wait_for(
                complete(model_request.messages, model_request.tools), context.timeout
            )
            if isinstance(response, ModelResponse):
                received = snapshot_model_response(response)
            else:
                from .model_evidence import _close_lazy

                _close_lazy(response)
                received = {
                    "output": None,
                    "tool_calls": [],
                    "usage": None,
                    "invalid_fields": ["response"],
                }
            # Return received evidence even when release validation after await rejects it.
            try:
                _check(runtime, request, context)
                if (
                    runtime.providers.get(context.provider) is not provider
                    or provider.complete != complete
                ):
                    raise DefinitionMismatch("Executing summary provider changed")
            except Exception as exc:
                return {
                    "ok": False,
                    "code": _code(exc, "summary_failed"),
                    "dispatched": True,
                    "received_response": received,
                }
            return {"ok": True, "received_response": received, "dispatched": True}
        if phase == "finalize":
            messages, identity = request["fallback"]["messages"], request["fallback"]["manifest"]
            plan, summary = request["plan"], None
            if plan is not None:
                if context.mode == "excerpt":
                    summary = context.excerpt(detached(plan))
                elif request.get("summary_response", {}).get("ok"):
                    received = request["summary_response"]["received_response"]
                    try:
                        validate_received_response(received)
                        if received["tool_calls"]:
                            raise ValidationError("Context summary cannot propose tools")
                        from .context_preparation import _schema

                        value = final_output(
                            received["output"], _schema(context.summary_max_chars)
                        )["text"]
                        summary = ContextSummary(value, plan["coverage"])
                    except ValidationError:
                        summary = None
                if summary is not None:
                    try:
                        messages, identity = context.finish(detached(plan), summary)
                    except ValidationError:
                        messages, identity = (
                            request["fallback"]["messages"],
                            request["fallback"]["manifest"],
                        )
            validate_context(messages, identity, request["step"]["max_context_chars"])
            validate_prepared(context, messages, request["step"]["max_context_chars"])
            _check(runtime, request, context)
            return {
                "ok": True,
                "messages": detached(messages),
                "references": detached(request["references"]),
                **(
                    {"native_history_snapshot": detached(request["native_history_snapshot"])}
                    if "native_history_snapshot" in request
                    else {}
                ),
                **(
                    {k: detached(request[k]) for k in ("session_data", "session_data_references")}
                    if "session_data" in request
                    else {}
                ),
                **(
                    {"session_references": detached(request["session_references"])}
                    if "session_references" in request
                    else {}
                ),
                **(
                    {"session_projection": detached(request["session_projection"])}
                    if "session_projection" in request
                    else {}
                ),
                **(
                    {
                        k: detached(request[k])
                        for k in ("facts", "knowledge_references", "facts_recall")
                    }
                    if "facts" in request
                    else {}
                ),
                "context_identity": detached(identity),
            }
        raise ValidationError("Unknown managed context phase")
    except Exception as exc:
        return {
            "ok": False,
            "code": _code(exc, "context_failed"),
            "dispatched": dispatched,
            "execution_uncertain": isinstance(exc, (TimeoutError, asyncio.CancelledError)),
        }


def next_stage(state):
    signature = state.context_cache_signature()
    if signature == state.context_signature:
        return None
    key = f"{state.node}:{state.decisions}"
    stage = state.managed_context_stages.setdefault(
        key,
        {
            "key": key,
            "source_digest": digest(state.messages),
            "status": "preparing",
            "phase": "plan",
            "operations": [],
            "index": 0,
            **(
                {
                    "policy": detached(state.step_manifest["managed_context"]["policy"]),
                    "step_bindings": state.step_bindings,
                }
                if state.manifest["kernel"] == "temporal-3"
                else {}
            ),
        },
    )
    if stage["phase"] == "summary" and state.budget["remaining"] < 1:
        stage["phase"] = "finalize"
        state._emit("context_summary_skipped", {"key": key, "code": "budget_exceeded"})
    phase = stage["phase"]
    action = {
        "id": f"{state.run_id}:managed-context:{key}:{len(stage['operations'])}",
        "kind": "managed_context",
        "phase": phase,
        "stage_key": key,
        "node": state.node,
        "status": "executing",
        "attempts": [],
    }
    state.actions.append(action)
    stage["operations"].append(action["id"])
    if phase == "summary":
        state._reserve(action, 1)
    else:
        state.active_action, state.state = action["id"], "running"
    request = {
        "phase": phase,
        "runtime_manifest": detached(state.manifest),
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "step": detached(state.step),
        **(
            {"step_bindings": state.step_bindings}
            if state.manifest["kernel"] == "temporal-3"
            else {}
        ),
    }
    if "session_data" in state.step_manifest:
        request["session_data_node"] = state.node
    request.update(state.session_context_fields())
    if "facts_context" in state.step_manifest:
        request["session_id"] = state.request.get("session_id") or state.run_id
    if state.step_manifest["managed_context"].get("dispatch_admission") == "history-1":
        request.update(action_id=action["id"], release_digest=state.release_digest)
    if phase == "plan":
        request["messages"] = detached(state.messages)
        if "session_history" in state.request:
            request["session_history"] = detached(state.request["session_history"])
    elif phase in {"read", "write", "verify"}:
        request["artifact"] = detached(stage["prepared"]["offloads"][stage["index"]])
        if phase == "write":
            reference = request["artifact"]["reference"]
            artifact_id = reference["artifact_id"]
            if (
                artifact_id in state.context_artifact_dispatches
                or artifact_id in state.context_artifact_receipts
            ):
                raise DefinitionMismatch(
                    "Artifact dispatch was already recorded in original History"
                )
            state.context_artifact_dispatches[artifact_id] = digest(reference)
    else:
        prepared = stage["prepared"]
        request.update({k: detached(prepared[k]) for k in ("plan", "fallback", "references")})
        if "native_history_snapshot" in prepared:
            request["native_history_snapshot"] = detached(prepared["native_history_snapshot"])
        if "session_data" in prepared:
            request.update(
                {k: detached(prepared[k]) for k in ("session_data", "session_data_references")}
            )
        if "session_references" in prepared:
            request["session_references"] = detached(prepared["session_references"])
        if "session_projection" in prepared:
            request["session_projection"] = detached(prepared["session_projection"])
        if "facts" in prepared:
            request.update(
                {
                    k: detached(prepared[k])
                    for k in ("facts", "knowledge_references", "facts_recall")
                }
            )
        request["summary_response"] = detached(stage.get("summary_response", {}))
    from .temporal_context_read_state import envelope as read_envelope

    request = read_envelope(state, action, request, phase)
    state._emit(
        "context_stage_intent_recorded",
        {"action_id": action["id"], "key": key, "phase": phase, "request_digest": digest(request)},
    )
    action["request_digest"] = digest(request)
    return action, request


def _after_artifacts(state, stage):
    prepared = stage["prepared"]
    if stage["index"] < len(prepared["offloads"]):
        stage["phase"] = "read"
    else:
        stage["phase"] = (
            "summary"
            if prepared["plan"] is not None
            and state.step_manifest["managed_context"]["policy"]["mode"] == "model"
            else "finalize"
        )


def accept_stage(state, action_id, response):

    response = detached(response)
    action = next(a for a in state.actions if a["id"] == action_id)
    stage, phase = state.managed_context_stages[action["stage_key"]], action["phase"]
    action["response"], action["status"] = response, "completed" if response.get("ok") else "failed"
    state.active_action = None
    if phase == "summary":
        received = response.get("received_response")
        if received is not None:
            action["received_response"] = detached(received)
            state._settle(action, settlement_usage(received.get("usage")))
            state._emit(
                "context_summary_response_recorded",
                {"action_id": action_id, "response_digest": digest(received)},
            )
        elif response.get("dispatched", True):
            action["status"], action["attempts"][0]["status"] = "outcome_unknown", "unknown"
            state.reservations[action["attempts"][0]["id"]]["status"] = "unknown"
            state.remote_uncertain = True
            state._emit("context_summary_outcome_unknown", {"action_id": action_id})
        else:
            state._settle(action, undispatched=True)
        stage["summary_response"], stage["phase"] = response, "finalize"
    elif phase == "write":
        stage["phase"] = "verify"
        if response.get("execution_uncertain"):
            action["status"] = "outcome_unknown"
            state.remote_uncertain = True
    if state.state in TERMINAL:
        stage["status"] = "closed"
        state._emit("late_context_evidence", {"action_id": action_id})
        return
    if phase == "write":
        # An observed receipt is still read-verified; a lost receipt never authorizes put again.
        return
    from .temporal_context_read_state import recreate_unadmitted

    if phase == "plan" and recreate_unadmitted(state, action, response):
        return
    if (
        phase in {"read", "verify"}
        and response.get("ok") is False
        and response.get("code") == "activity_outcome_unknown"
        and state.manifest.get("binding_protocol") in (5, 6, 7, 8, 9, 10, 11)
        and state.step_manifest["managed_context"]["policy"].get("artifact_binding", {}).get("mode")
        == "ref"
        and action_id in getattr(state, "context_read_stages", {})
        and action.get("dispatch_grant", {}).get("allowed") is not True
    ):
        # Original History can prove this Action never obtained permission for I/O.
        # observe() fences it atomically before the next, distinct read Action exists.
        reference = stage["prepared"]["offloads"][stage["index"]]["reference"]
        retry_key = phase + ":" + reference["artifact_id"]
        retries = stage.setdefault("undispatched_artifact_read_retries", {})
        if retries.get(retry_key, 0) == 0:
            retries[retry_key] = 1
            state._emit(
                "context_artifact_read_recreated", {"action_id": action_id, "reference": reference}
            )
            return
    if not response.get("ok") and phase != "summary":
        stage["status"] = "failed"
        state.state, state.error = "failed", {"code": response.get("code", "context_failed")}
        state._emit("context_failed", {"action_id": action_id})
        return
    if phase == "plan":
        if response["source_digest"] != stage["source_digest"]:
            raise DefinitionMismatch("Context plan changed original history")
        from .temporal_session_data_state import validate_snapshot as validate_session_snapshot

        validate_session_snapshot(
            response,
            state.step_manifest,
            {
                "scope": state.scope,
                "run_id": state.run_id,
                "session_data_node": state.node,
                "step": state.step,
                **state.session_context_fields(),
            },
        )
        from .temporal_session_tree_reads import adopt

        adopt(state, response)
        from .temporal_session_model_history import validate_native_snapshot

        validate_native_snapshot(
            response,
            state.step_manifest,
            {
                **state.request,
                "scope": state.scope,
                "messages": state.messages,
                **state.session_context_fields(),
            },
        )
        if "native_history_snapshot" in response:
            state.native_history_snapshots.setdefault(
                str(state.node), detached(response["native_history_snapshot"])
            )
        stage["prepared"] = response
        _after_artifacts(state, stage)
    elif phase in {"read", "verify"}:
        item = stage["prepared"]["offloads"][stage["index"]]
        if response["found"]:
            if response.get("reference") != item["reference"]:
                raise DefinitionMismatch("Artifact observation changed fixed reference")
            stage.setdefault("artifact_receipts", {})[item["reference"]["artifact_id"]] = digest(
                response
            )
            state.context_artifact_receipts[item["reference"]["artifact_id"]] = digest(response)
            state._emit(
                "context_artifact_verified", {"key": stage["key"], "reference": item["reference"]}
            )
            stage["index"] += 1
            _after_artifacts(state, stage)
        elif (
            phase == "read"
            and item["reference"]["artifact_id"] not in state.context_artifact_dispatches
            and item["reference"]["artifact_id"] not in state.context_artifact_receipts
        ):
            stage["phase"] = "write"
        else:
            stage["status"] = "failed"
            state.state, state.error = "failed", {"code": "context_artifact_unavailable"}
            state._emit(
                "context_failed", {"action_id": action_id, "code": "context_artifact_unavailable"}
            )
    elif phase == "finalize":
        if (
            response.get("references") != stage["prepared"]["references"]
            or any(
                response.get(k) != stage["prepared"].get(k)
                for k in (
                    "facts",
                    "knowledge_references",
                    "facts_recall",
                    "session_data",
                    "session_data_references",
                    "native_history_snapshot",
                )
            )
            or not isinstance(response.get("messages"), list)
            or len(canonical(response["messages"])) > state.step["max_context_chars"]
        ):
            raise ValidationError("Invalid adopted context snapshot")
        from .temporal_facts_state import validate_snapshot

        validate_snapshot(response, state.step_manifest)
        from .temporal_knowledge_state import validate_snapshot as validate_knowledge_snapshot

        validate_knowledge_snapshot(response, state.step_manifest, state.scope)
        from .temporal_session_state import validate_context_evidence

        validate_context_evidence(response, {**state.request, **state.session_context_fields()})
        from .temporal_session_data_state import validate_snapshot as validate_session_snapshot

        validate_session_snapshot(
            response,
            state.step_manifest,
            {
                "scope": state.scope,
                "run_id": state.run_id,
                "session_data_node": state.node,
                "step": state.step,
                **state.session_context_fields(),
            },
        )
        if state.step_manifest.get("model_history_protocol") == 2:
            from .session_model_history import validate_model_history_frame
            from .temporal_session_model_history import frame

            validate_model_history_frame(
                frame(state),
                response["messages"],
                allow_tool_result_projection=state.step_manifest["model_history"]["identity"].get(
                    "allow_tool_result_projection", False
                ),
            )
        elif state.step_manifest.get("model_history_protocol") == 1:
            from .model_history import validate_model_history

            validate_model_history(
                state.messages,
                response["messages"],
                allow_tool_result_projection=state.step_manifest["model_history"]["identity"].get(
                    "allow_tool_result_projection", False
                ),
            )
        stage["status"], stage["snapshot"] = "completed", response
        from .temporal_session_model_history import validate_native_snapshot

        validate_native_snapshot(
            response,
            state.step_manifest,
            {
                **state.request,
                "scope": state.scope,
                "messages": state.messages,
                **state.session_context_fields(),
            },
        )
        state.context_snapshot = response
        state.context_signature = state.context_cache_signature()
        state._emit(
            "context_snapshot_recorded", {"action_id": action_id, "digest": digest(response)}
        )
