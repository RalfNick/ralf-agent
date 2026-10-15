"""Exact factory-owned Session controls with independent mechanical end ACKs."""

from .errors import DefinitionMismatch
from .task_controls import _binding
from .temporal_session_deployment_verification import (
    REGISTRY_ACTIVITY,
    SessionControlValidation,
    _reject,
    registry_epoch,
    source_bindings,
    verify_registry_request,
)
from .temporal_session_state import SESSION_ACTIVITY
from .temporal_state import detached
from .types import digest


def _owner(runtime):
    from .temporal_context_execution import ContextExecutionOwner

    owner = getattr(runtime, "_deployment_execution_owner", None)
    if type(owner) is not ContextExecutionOwner or owner is not getattr(
        runtime, "_deployment_execution_owner_pin", None
    ):
        _reject()
    return owner


async def owned_control_body(validation, body):
    """Own actual body completion and its Session History ACK, outside Run debt."""
    import asyncio
    from uuid import uuid4

    from .errors import RalfError
    from .temporal_session_deployment_dto import (
        encode_control_body,
        validate_call_end,
        validate_call_identity,
    )

    await validation.validate()
    i, info = validation.intent, validation.info
    owner = _owner(validation.runtime)
    owner_execute = _binding(owner.execute)
    identity = validate_call_identity(
        {
            "version": 1,
            "scope": i["scope"],
            "namespace": i["namespace"],
            "coordinator_id": i["coordinator_id"],
            "coordinator_execution_epoch": i["coordinator_execution_epoch"],
            "session_command_id": i["session_command_id"],
            "turn_id": i["turn_id"],
            "intent_digest": i["intent_digest"],
            "mode": validation.value["mode"],
            "activity_id": info.activity_id,
            "activity_name": info.activity_type,
            "attempt": info.attempt,
            "invocation_id": uuid4().hex,
            "request_digest": digest(validation.value),
            "manifest_digest": digest(i["binding"]["manifest"]),
        },
        intent=i,
        deployment_id=validation.deployment_id,
        request_digest=digest(validation.value),
    )
    handle = validation.client.get_workflow_handle(
        i["coordinator_id"], run_id=i["coordinator_execution_epoch"]
    )
    proof = {
        "scope": i["scope"],
        "action_id": digest(identity),
        "release_digest": identity["manifest_digest"],
        "request_digest": identity["request_digest"],
        "execution_epoch": i["coordinator_execution_epoch"],
    }
    ack = asyncio.get_running_loop().create_future()
    # A failed start can leave this ACK unawaited while the actual owner drains.
    # Observe its exception; a caller awaiting the Future still receives it.
    ack.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    progress = {"body": None, "started": False, "requested": False, "refused": False}

    async def begin():
        progress["requested"] = True
        try:
            admitted = await handle.execute_update(
                "session_deployment_call_start",
                {"identity": identity},
                id="ralf-session-call:" + digest(identity),
            )
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, RalfError)
                else getattr(getattr(exc, "cause", None), "type", None)
            )
            if code in {
                "validation_error",
                "definition_mismatch",
                "authorization_denied",
                "idempotency_conflict",
            }:
                progress["refused"] = True
            raise
        validation._check()
        if admitted == {"identity": identity, "allowed": False}:
            progress["refused"] = True
            _reject()
        if admitted != {"identity": identity, "allowed": True}:
            _reject()
        progress["started"] = True

    async def operation():
        await validation.validate()
        await begin()
        try:
            await validation.validate()
            result = await body()
            await validation.validate()
            response = {"ok": True, "result": detached(result)}
        except Exception as exc:
            response = {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "session_control_failed",
            }
            if not isinstance(exc, RalfError):
                try:
                    import logging
                    from enum import Enum

                    kind = type(exc)
                    frames, trace = [], exc.__traceback__
                    while trace is not None and len(frames) < 16:
                        code = trace.tb_frame.f_code
                        frames.append(
                            {
                                "file": code.co_filename.replace("\\", "/").rsplit("/", 1)[-1][
                                    :128
                                ],
                                "function": code.co_name[:128],
                                "line": trace.tb_lineno,
                            }
                        )
                        trace = trace.tb_next
                    status = getattr(exc, "status", None)
                    detail = {
                        "exception_module": kind.__module__[:128],
                        "exception_type": kind.__name__[:128],
                        "rpc_status": status.name[:128] if isinstance(status, Enum) else None,
                        "frames": frames,
                    }
                    logging.getLogger(__name__).warning(
                        "Session control body failed: " + repr(detail),
                        extra={"session_control_failure": detail},
                    )
                except BaseException:
                    # Diagnostics cannot change the original response or its end ACK.
                    pass
        progress["body"] = response
        return response

    async def ended(received):
        if (
            received != proof
            or _owner(validation.runtime) is not owner
            or _binding(owner.execute) != owner_execute
        ):
            _reject()
        validation._check()
        if not progress["started"]:
            if progress["requested"] and not progress["refused"]:
                # Resolve a possibly applied start with this exact original identity
                # and SDK Update ID before releasing its actual-call owner.
                await validation.validate()
                await begin()
                progress["body"] = {"ok": False, "code": "session_control_start_unavailable"}
            else:
                if not ack.done():
                    ack.set_exception(
                        DefinitionMismatch("Session control start was not acknowledged")
                    )
                return
        if progress["body"] is None:
            # A cancelled/unended body is not a positive stopped result.
            _reject()
        await validation.validate()
        result = await handle.execute_update(
            "session_deployment_call_end",
            {
                "identity": identity,
                "body_result_digest": digest(progress["body"]),
                "body_result": encode_control_body(progress["body"], i["submission"]["manifest"]),
                "body_stopped": True,
            },
            id="ralf-session-call-end:" + digest([identity, progress["body"]]),
        )
        validation._check()
        await validation.validate()
        result = validate_call_end(result, identity=identity, body_result=progress["body"])
        if not ack.done():
            ack.set_result(result)

    response = await owner.execute(operation, proof=proof, on_end=ended)
    result = await asyncio.shield(ack)
    validation._check()
    return {**encode_control_body(response, i["submission"]["manifest"]), "call_end": result}


_REGISTRATIONS = {}


def _registration(runtime, client, function):
    from temporalio import activity

    definition = activity._Definition.from_callable(function)
    return (
        runtime,
        client,
        client.workflow_service,
        client.data_converter,
        _binding(runtime.validate_release),
        _binding(client.get_workflow_handle),
        _binding(client.workflow_service.describe_namespace),
        _binding(client.data_converter.decode),
        _binding(function),
        _binding(source_bindings),
        source_bindings(),
        _binding(_owner),
        _binding(_root_record),
        _binding(_business_identity),
        _binding(_registry_update),
        _binding(owned_control_body),
        _binding(_register),
        _binding(_observe),
        None if definition is None else definition.name,
    )


def is_registered_activity(runtime, client, function):
    """Object provenance and original endpoints; copied markers never suffice."""
    try:
        return _REGISTRATIONS.get(function) == _registration(runtime, client, function)
    except (AttributeError, TypeError):
        return False


def registered_session_deployment_activities(runtime, client):
    from temporalio import activity

    @activity.defn(name=SESSION_ACTIVITY)
    async def session_control(value: dict) -> dict:
        if not is_registered_activity(runtime, client, session_control):
            _reject()
        manifest = value.get("intent", {}).get("binding", {}).get("manifest", {})
        policy = manifest.get("deployment_admission_protocol", {}).get("policy", {})
        validation = SessionControlValidation(
            runtime,
            client,
            value,
            activity.info(),
            deployment_id=policy.get("deployment_id"),
        )

        async def body():
            if not is_registered_activity(runtime, client, session_control):
                _reject()
            return await (
                _register(validation) if value["mode"] == "register" else _observe(validation)
            )

        return await owned_control_body(validation, body)

    _REGISTRATIONS[session_control] = _registration(runtime, client, session_control)
    return [session_control]


async def _register(validation):
    from uuid import uuid4

    from .errors import CapacityExceeded
    from .temporal_session_deployment_dto import validate_start_view

    lifecycle = await validation.lifecycle()
    i = validation.intent
    handle, epoch, policy = await registry_epoch(
        validation.runtime,
        validation.client,
        manifest=i["submission"]["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        check=validation._check,
    )
    await validation.validate()
    saved = await _root_record(validation, handle, policy)
    barrier = lifecycle["refusal_barrier"]
    if saved is None and barrier is not None:
        if lifecycle["start_issued"] is not False:
            _reject()
        refusal = await _registry_update(
            handle,
            "session_never_claimed",
            {
                "scope": i["scope"],
                "admission_policy": policy,
                "namespace": i["namespace"],
                "intent": i,
                "barrier": barrier,
                "code": barrier["code"],
            },
            id="ralf-session-never-claimed:" + digest([i["intent_digest"], barrier]),
        )
        await validation.validate()
        start = _start_view(i, "start-refused", start_refusal=refusal)
        start = validate_start_view(
            start, intent=i, deployment_id=validation.deployment_id, registry_execution_epoch=epoch
        )
        return {"start": start, "registry_execution_epoch": epoch, "execution_epoch": None}
    if saved is None:
        if lifecycle["start_issued"]:
            _reject()
        verified = await validation.validate()
        request = {
            "scope": i["scope"],
            "admission_policy": policy,
            "namespace": i["namespace"],
            "command_id": i["run_command_id"],
            "kind": "submit",
            "target": i["run_id"],
            "payload_digest": digest(i["submission"]["request"]),
            "root_admission": {
                "version": 4,
                "manifest_digest": digest(i["submission"]["manifest"]),
                "submission": i["submission"],
                "session_origin": verified["session_origin"],
            },
        }
        try:
            await _registry_update(
                handle,
                "reserve_session_root",
                {"request": request, "intent": i},
                id="ralf-session-root:" + uuid4().hex,
            )
        except CapacityExceeded:
            await validation.validate()
            start = _start_view(i, "capacity-deferred")
            return {"start": start, "registry_execution_epoch": epoch, "execution_epoch": None}
        except Exception:
            # Uncertain RPC may have committed. Recover the original claim first.
            await validation.validate()
            saved = await _root_record(validation, handle, policy)
            if saved is None:
                raise
        await validation.validate()
        saved = await _root_record(validation, handle, policy)
        if saved is None:
            _reject()
    execution_epoch, receipt = saved["execution_epoch"], saved["run_receipt"]
    if lifecycle["start_issued"] and (execution_epoch is None or receipt is None):
        # Worker binding can precede the facade's original receipt-record ACK.
        # Recover that one SDK child; never issue another child start here.
        from temporalio.service import RPCError, RPCStatusCode

        from .errors import NotFound

        try:
            description = await validation.client.get_workflow_handle(i["run_id"]).describe()
        except NotFound:
            description = None
        except RPCError as exc:
            if exc.status is not RPCStatusCode.NOT_FOUND:
                raise
            description = None
        await validation.validate()
        if description is not None:
            original_epoch = description.run_id
            business = await _business_identity(
                validation, original_epoch, reservation=saved["reservation"]
            )
            original_receipt = await business.query(
                "view",
                {
                    "kind": "submission",
                    "scope": i["scope"],
                    "command_id": i["run_command_id"],
                    "request": i["submission"]["request"],
                },
            )
            await validation.validate()
            from .temporal_deployment_submissions import _receipt

            _receipt(original_receipt, command_id=i["run_command_id"], run_id=i["run_id"])
            root = saved["reservation"]["root_admission"]
            payload = {
                "scope": i["scope"],
                "admission_policy": policy,
                "namespace": i["namespace"],
                **{
                    k: root[k]
                    for k in (
                        "command_id",
                        "run_id",
                        "request_digest",
                        "manifest_digest",
                        "proof_digest",
                    )
                },
                "execution_epoch": original_epoch,
                "receipt": original_receipt,
            }
            try:
                await _registry_update(
                    handle,
                    "record_deployment_submission",
                    payload,
                    id="ralf-session-record:" + digest(payload),
                )
            except Exception:
                await validation.validate()
                recovered = await _root_record(validation, handle, policy)
                if (
                    recovered is None
                    or recovered["execution_epoch"] != original_epoch
                    or recovered["run_receipt"] != original_receipt
                ):
                    raise
            await validation.validate()
            saved = await _root_record(validation, handle, policy)
            if (
                saved is None
                or saved["execution_epoch"] != original_epoch
                or saved["run_receipt"] != original_receipt
            ):
                _reject()
            execution_epoch, receipt = original_epoch, original_receipt
    phase = "start-uncertain" if lifecycle["start_issued"] else "held-unbound"
    if execution_epoch is not None and receipt is not None:
        await _business_identity(validation, execution_epoch, reservation=saved["reservation"])
        phase = "started"
    else:
        execution_epoch, receipt = None, None
    start = _start_view(
        i,
        phase,
        reservation=saved["reservation"],
        execution_epoch=execution_epoch,
        run_receipt=receipt,
    )
    start = validate_start_view(
        start,
        intent=i,
        deployment_id=validation.deployment_id,
        registry_execution_epoch=epoch,
        execution_epoch=execution_epoch,
    )
    await registry_epoch(
        validation.runtime,
        validation.client,
        manifest=i["submission"]["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        expected=epoch,
        check=validation._check,
    )
    await validation.validate()
    return {"start": start, "registry_execution_epoch": epoch, "execution_epoch": execution_epoch}


def _start_view(intent, phase, **values):
    return {
        "version": 1,
        "intent": detached(intent),
        "phase": phase,
        "reservation": None,
        "execution_epoch": None,
        "run_receipt": None,
        "last_error": None,
        "start_refusal": None,
        **values,
    }


async def _root_record(validation, handle, policy):
    i = validation.intent
    result = await handle.query(
        "view",
        {
            "kind": "deployment_session_root",
            "scope": i["scope"],
            "admission_policy": policy,
            "namespace": i["namespace"],
            "command_id": i["run_command_id"],
            "payload_digest": digest(i["submission"]["request"]),
        },
    )
    await validation.validate()
    if result is None:
        return None
    if (
        type(result) is not dict
        or set(result)
        != {
            "reservation",
            "submission",
            "run_receipt",
            "execution_epoch",
            "intent",
            "session_origin",
        }
        or result["intent"] != i
        or result["submission"] != i["submission"]
        or result["session_origin"] != (await validation.validate())["session_origin"]
    ):
        _reject()
    return detached(result)


async def _business_identity(validation, epoch, *, reservation):
    from .temporal_parent_state import PARENT_WORKFLOW_NAME
    from .temporal_state import WORKFLOW_NAME

    i, client = validation.intent, validation.client
    await validation.validate()
    description = await client.get_workflow_handle(i["run_id"]).describe()
    await validation.validate()
    kind = (
        PARENT_WORKFLOW_NAME
        if i["submission"]["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}
        else WORKFLOW_NAME
    )
    if (
        description.id != i["run_id"]
        or description.run_id != epoch
        or description.namespace != i["namespace"]["name"]
        or description.workflow_type != kind
        or description.raw_info.first_run_id != epoch
        or description.parent_id != i["coordinator_id"]
        or description.parent_run_id != i["coordinator_execution_epoch"]
        or description.task_queue != i["submission"]["task_queue"]
    ):
        _reject()
    handle = client.get_workflow_handle(i["run_id"], run_id=epoch)
    events = handle.fetch_history_events(page_size=1)
    try:
        first = await anext(events)
    except StopAsyncIteration:
        _reject()
    await validation.validate()
    if first.event_id != 1 or not first.HasField("workflow_execution_started_event_attributes"):
        _reject()
    start = first.workflow_execution_started_event_attributes
    if (
        start.original_execution_run_id != epoch
        or start.first_execution_run_id != epoch
        or start.continued_execution_run_id
        or start.workflow_type.name != kind
        or start.task_queue.name != i["submission"]["task_queue"]
        or start.parent_workflow_namespace != i["namespace"]["name"]
        or start.parent_workflow_execution.workflow_id != i["coordinator_id"]
        or start.parent_workflow_execution.run_id != i["coordinator_execution_epoch"]
    ):
        _reject()
    accepted = await client.data_converter.decode(start.input.payloads)
    await validation.validate()
    if len(accepted) != 1 or type(accepted[0]) is not dict:
        _reject()
    accepted = accepted[0]
    metadata = {
        "version": 2,
        "root": reservation["root_admission"],
        "lineage": [],
        "session_origin": (await validation.validate())["session_origin"],
    }
    if accepted.get("deployment_admission") != metadata:
        _reject()
    if any(
        accepted.get(k) != expected
        for k, expected in {
            "scope": i["scope"],
            "command_id": i["run_command_id"],
            "request": i["submission"]["request"],
            "manifest": i["submission"]["manifest"],
            "activity_timeout": i["submission"]["activity_timeout"],
        }.items()
    ):
        _reject()
    last = await client.get_workflow_handle(i["run_id"]).describe()
    await validation.validate()
    if (
        last.run_id != epoch
        or last.raw_info.first_run_id != epoch
        or last.parent_id != i["coordinator_id"]
        or last.parent_run_id != i["coordinator_execution_epoch"]
    ):
        _reject()
    return handle


async def _observe(validation):
    from . import temporal_deployment_execution as execution
    from . import temporal_deployment_release as release
    from .temporal_session_deployment_dto import validate_start_view

    i = validation.intent
    await validation.validate()
    registry, registry_epoch_value, policy = await registry_epoch(
        validation.runtime,
        validation.client,
        manifest=i["submission"]["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        check=validation._check,
    )
    record = await _root_record(validation, registry, policy)
    if record is None or record["execution_epoch"] is None or record["run_receipt"] is None:
        _reject()
    epoch = record["execution_epoch"]
    validate_start_view(
        _start_view(
            i,
            "started",
            reservation=record["reservation"],
            execution_epoch=epoch,
            run_receipt=record["run_receipt"],
        ),
        intent=i,
        deployment_id=validation.deployment_id,
        registry_execution_epoch=registry_epoch_value,
        execution_epoch=epoch,
    )
    handle = await _business_identity(validation, epoch, reservation=record["reservation"])
    result = {
        "advance": None,
        "registry_execution_epoch": registry_epoch_value,
        "execution_epoch": epoch,
    }
    closure = await handle.query("view", {"kind": "deployment_closure", "scope": i["scope"]})
    await validation.validate()
    if type(closure) is not dict or type(closure.get("ready")) is not bool:
        _reject()
    if not closure["ready"] or closure.get("seal") is None:
        return result
    # These existing SDK proof readers validate the original Run/Parent and its
    # descendants. The observer itself has no business call-ledger entry.
    manifest = i["submission"]["manifest"]
    protocol = manifest.get("deployment_admission_protocol", {})
    readonly = _CheckedClient(
        validation,
        _aggregate=(
            type(protocol) is dict
            and type(protocol.get("version")) is int
            and protocol["version"] == 4
            and manifest.get("binding_protocol") in (22, 23)
            and "coding_execution_protocol" in manifest
        ),
    )
    proof = await execution._proof(
        validation.runtime, readonly, policy, i["scope"], i["run_id"], epoch, required=True
    )
    await validation.validate()
    if (
        proof["request"] != i["submission"]["request"]
        or proof["manifest"] != i["submission"]["manifest"]
        or proof["admission"]["lineage"] != []
        or proof["admission"].get("session_origin")
        != (await validation.validate())["session_origin"]
    ):
        _reject()
    closure = await release._closure(validation.runtime, readonly, policy, proof)
    await validation.validate()
    certificate = await release._tree(validation.runtime, readonly, policy, proof, seal=False)
    await validation.validate()
    if closure["seal"] != certificate:
        _reject()
    root = proof["admission_receipt"]["root"]
    retirement = await registry.query(
        "view", {"kind": "deployment_retirement", **release._binding(root, policy, certificate)}
    )
    await validation.validate()
    if retirement is None:
        return result
    if retirement != {"root": root, "certificate": certificate, "released": True}:
        _reject()
    run_proof = await handle.query("view", {"kind": "session_proof", "scope": i["scope"]})
    await validation.validate()
    descendants, pending, seen = [], list(proof["children"]), {i["run_id"]}
    while pending:
        child = pending.pop()
        if child.get("dispatch_started") is not True and child.get("started") is not True:
            continue
        child_id, child_epoch = child["run_id"], child.get("deployment_execution_epoch")
        if child_id in seen or len(seen) >= 4096 or type(child_epoch) is not str or not child_epoch:
            _reject()
        seen.add(child_id)
        physical = await execution._proof(
            validation.runtime, readonly, policy, i["scope"], child_id, child_epoch, required=True
        )
        await validation.validate()
        root_proof = await execution._ancestry(
            validation.runtime, readonly, policy, physical, read_only=True
        )
        await validation.validate()
        if root_proof["run_id"] != i["run_id"] or root_proof["execution_epoch"] != epoch:
            _reject()
        descendants.append(
            await readonly.get_workflow_handle(child_id, run_id=child_epoch).query(
                "view",
                {"kind": "session_proof", "scope": i["scope"]},
            )
        )
        pending.extend(physical["children"])
    await _business_identity(validation, epoch, reservation=record["reservation"])
    await registry_epoch(
        validation.runtime,
        validation.client,
        manifest=i["submission"]["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        expected=registry_epoch_value,
        check=validation._check,
    )
    await validation.validate()
    result["advance"] = {
        "version": 1,
        "intent_digest": i["intent_digest"],
        "run_proof": run_proof,
        "descendants": descendants,
        "closure": closure,
        "retirement": retirement,
    }
    return detached(result)


class _CheckedClient:
    """Read-only SDK ports; Coding observation groups retain explicit SDK exits."""

    def __init__(self, validation, *, _aggregate=False):
        if type(_aggregate) is not bool:
            _reject()
        if _aggregate:
            manifest = validation.intent["submission"]["manifest"]
            protocol = manifest.get("deployment_admission_protocol", {})
            if not (
                type(protocol) is dict
                and type(protocol.get("version")) is int
                and protocol["version"] == 4
                and manifest.get("binding_protocol") in (22, 23)
                and "coding_execution_protocol" in manifest
            ):
                _reject()
        self.validation = validation
        self._aggregate = _aggregate
        self._read_binding = validation, _aggregate
        self._service = _CheckedService(self)

    async def _after_read(self):
        if (
            type(self._aggregate) is not bool
            or self.validation is not self._read_binding[0]
            or self._aggregate is not self._read_binding[1]
        ):
            _reject()
        if self._aggregate:
            # The enclosing _observe verifies all seven live Session facts at
            # each group exit, before using or returning the collected proof.
            # Local pins and complete Runtime validation remain per SDK await.
            self.validation._check()
        else:
            await self.validation.validate()

    @property
    def namespace(self):
        return self.validation.client.namespace

    @property
    def workflow_service(self):
        return self._service

    @property
    def data_converter(self):
        return self.validation.client.data_converter

    def get_workflow_handle(self, *args, **kwargs):
        return _CheckedHandle(self, self.validation.client.get_workflow_handle(*args, **kwargs))


class _CheckedService:
    def __init__(self, client):
        self.client, self.validation = client, client.validation

    async def describe_namespace(self, request):
        self.validation._check()
        result = await self.validation.client.workflow_service.describe_namespace(request)
        await self.client._after_read()
        return result


class _CheckedHandle:
    def __init__(self, client, handle):
        self.client, self.validation, self.handle = client, client.validation, handle

    def fetch_history_events(self, **kwargs):
        async def events():
            self.validation._check()
            source = self.handle.fetch_history_events(**kwargs)
            while True:
                try:
                    item = await anext(source)
                except StopAsyncIteration:
                    return
                await self.client._after_read()
                yield item

        return events()

    async def query(self, *args, **kwargs):
        self.validation._check()
        result = await self.handle.query(*args, **kwargs)
        await self.client._after_read()
        return result

    async def describe(self):
        self.validation._check()
        result = await self.handle.describe()
        await self.client._after_read()
        return result


_REGISTRY_REGISTRATIONS = {}


def _registry_registration(runtime, client, function):
    from temporalio import activity

    definition = activity._Definition.from_callable(function)
    return (
        runtime,
        client,
        client.workflow_service,
        client.data_converter,
        _binding(runtime.validate_release),
        _binding(client.get_workflow_handle),
        _binding(client.workflow_service.describe_namespace),
        _binding(client.data_converter.decode),
        _binding(function),
        _binding(source_bindings),
        source_bindings(),
        _binding(verify_registry_request),
        None if definition is None else definition.name,
    )


def is_registered_registry_activity(runtime, client, function):
    try:
        return _REGISTRY_REGISTRATIONS.get(function) == _registry_registration(
            runtime, client, function
        )
    except (AttributeError, TypeError):
        return False


def registered_registry_session_activities(runtime, client):
    from temporalio import activity

    from .errors import RalfError

    @activity.defn(name=REGISTRY_ACTIVITY)
    async def verify(value: dict) -> dict:
        if not is_registered_registry_activity(runtime, client, verify):
            _reject()
        try:
            result = await verify_registry_request(runtime, client, value, info=activity.info())
            if not is_registered_registry_activity(runtime, client, verify):
                _reject()
            return result
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "session_verification_failed",
            }

    _REGISTRY_REGISTRATIONS[verify] = _registry_registration(runtime, client, verify)
    return [verify]


async def _registry_update(handle, name, value, **kwargs):
    from .temporal_deployment_submissions import _raise_sdk

    try:
        return await handle.execute_update(name, value, **kwargs)
    except Exception as exc:
        _raise_sdk(exc)
