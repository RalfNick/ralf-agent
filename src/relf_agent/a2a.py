"""A2A 0.3.0 JSON-RPC polling subset over the native execution authority.

Supported: discovery, message/send, tasks/get, tasks/cancel. Text/data parts only;
no SSE, push, gRPC, files, task continuation or enterprise authentication. Hosts
supply authentication, scoped engines, durable inbox, specification and wakeup.

The advertised ``urn:ralf:a2a:message-receipts:v1`` extension supports read-only
recovery by original messageId through TaskQueryParams.metadata.ralfMessageId.
Not-found is absence of a durable receipt, not proof a submission had no effect.
"""

import asyncio
import copy
import json
import math
from dataclasses import asdict
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import AuthorizationDenied, IdempotencyConflict, NotFound, RalfError, ValidationError
from .handoff import _completed, call_inbox, validate_inbox
from .messaging import MessageEnvelope, _integer, _json, _text
from .ports import is_async_callable, is_sync_callable
from .service_audit import ServiceAudit
from .task_controls import TaskControlBridge
from .tool_sources import ToolDescriptor, ToolSourceError
from .types import Scope, canonical, digest, submission_request

PROTOCOL_VERSION = "0.3.0"
RECEIPT_EXTENSION = "urn:ralf:a2a:message-receipts:v1"
USER_INPUT_EXTENSION = "urn:ralf:a2a:user-input:v1"
_TASK_STATES = {
    "submitted",
    "working",
    "input-required",
    "completed",
    "canceled",
    "failed",
    "rejected",
    "auth-required",
    "unknown",
}
_NATIVE_STATES = {
    "queued": "submitted",
    "running": "working",
    "cancelling": "working",
    "waiting_approval": "input-required",
    "waiting_reconciliation": "input-required",
    "waiting_input": "input-required",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "canceled",
    "outcome_unknown": "unknown",
}


class A2AError(RalfError):
    code = "a2a_error"


class A2ARemoteError(A2AError):
    code = "a2a_remote_error"

    def __init__(self, rpc_code):
        self.rpc_code = rpc_code
        super().__init__(f"A2A remote request failed ({rpc_code})")


class _RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def _url(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("A2A URL requires nonempty text")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid endpoint")
        _ = parsed.port
    except ValueError as exc:
        raise ValidationError(
            "A2A URL requires HTTP(S) without credentials, query or fragment"
        ) from exc
    return value.rstrip("/")


def _timeout(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValidationError("A2A timeout must be finite and positive")
    return value


def _loads(raw):
    value = json.loads(raw)
    _json(value)
    return value


def _response_limit_error(request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32603, "message": "Response exceeds configured limit"},
    }


def _part(part):
    if not isinstance(part, dict):
        raise ValidationError("A2A parts require objects")
    if (
        part.get("kind") == "text"
        and set(part) <= {"kind", "text", "metadata"}
        and isinstance(part.get("text"), str)
    ):
        _json(part)
    elif (
        part.get("kind") == "data"
        and set(part) <= {"kind", "data", "metadata"}
        and isinstance(part.get("data"), dict)
    ):
        _json(part)
    else:
        raise ValidationError("A2A polling subset supports text/data parts")
    if "metadata" in part and not isinstance(part["metadata"], dict):
        raise ValidationError("A2A part metadata requires an object")


def _task(value):
    try:
        if not isinstance(value, dict) or value.get("kind") != "task":
            raise ValueError("invalid task")
        _text(value.get("id"), "Task identity")
        _text(value.get("contextId"), "Context identity")
        if (
            not isinstance(value.get("status"), dict)
            or value["status"].get("state") not in _TASK_STATES
        ):
            raise ValueError("invalid task state")
        for artifact in value.get("artifacts", []):
            if (
                not isinstance(artifact, dict)
                or not isinstance(artifact.get("parts"), list)
                or not artifact["parts"]
            ):
                raise ValueError("invalid artifact")
            _text(artifact.get("artifactId"), "Artifact identity")
            for part in artifact["parts"]:
                _part(part)
        _json(value)
        return value
    except Exception as exc:
        raise A2AError("A2A returned an invalid Task") from exc


def _agent_card(card, url):
    try:
        if (
            not isinstance(card, dict)
            or card.get("protocolVersion") != PROTOCOL_VERSION
            or card.get("preferredTransport", "JSONRPC") != "JSONRPC"
            or card.get("url") != url
        ):
            raise ValueError("unsupported card")
        if not isinstance(card.get("capabilities"), dict) or not isinstance(
            card.get("skills"), list
        ):
            raise ValueError("invalid card")
        for capability in ("streaming", "pushNotifications", "stateTransitionHistory"):
            if (
                capability in card["capabilities"]
                and type(card["capabilities"][capability]) is not bool
            ):
                raise ValueError("invalid capability")
        for skill in card["skills"]:
            if not isinstance(skill, dict):
                raise ValueError("invalid skill")
            for key in ("id", "name", "description"):
                _text(skill.get(key), key)
            if not isinstance(skill.get("tags"), list) or any(
                not isinstance(tag, str) for tag in skill["tags"]
            ):
                raise ValueError("invalid skill tags")
        for key in ("name", "description", "version"):
            _text(card.get(key), key)
        return json.loads(_json(card))
    except Exception as exc:
        raise A2AError("A2A Agent Card is invalid or unsupported") from exc


@runtime_checkable
class A2AClientPort(Protocol):
    """Replaceable native async client for this fixed JSON-RPC polling subset.

    identity is stable non-secret JSON containing kind, protocolVersion=0.3.0
    and url matching the configured endpoint. Methods return completed finite
    Agent Card/Task objects, never nested lazy work. get_by_message implements
    the advertised receipt extension; absence of receipt is not non-execution.
    A2AToolSource borrows this client unless owns_client is explicitly true.
    """

    url: str
    identity: dict

    async def discover(self) -> dict: ...
    async def send_message(self, message_id: str, input) -> dict: ...
    async def get_task(self, task_id: str) -> dict: ...
    async def get_by_message(self, message_id: str) -> dict: ...
    async def cancel_task(self, task_id: str, *, command_id: str) -> dict: ...
    async def aclose(self) -> None: ...


def validate_a2a_client(client):
    """Validate structural method modes and stable fixed-protocol identity."""
    url = _url(getattr(client, "url", None))
    identity = getattr(client, "identity", None)
    if (
        not isinstance(identity, dict)
        or identity.get("protocolVersion") != PROTOCOL_VERSION
        or identity.get("url") != url
    ):
        raise ValidationError("A2AClientPort requires a fixed protocol and endpoint identity")
    _text(identity.get("kind"), "A2A client identity kind")
    _json(identity)
    for method in (
        "discover",
        "send_message",
        "get_task",
        "get_by_message",
        "cancel_task",
        "aclose",
    ):
        if not is_async_callable(getattr(client, method, None)):
            raise ValidationError(f"A2AClientPort.{method} must be native async")
    return client


class A2AApplication:
    """Borrow a trusted native engine per authenticated Scope, not a task DB.

    ``authenticate(headers)`` is a native async host callback returning Scope.
    ``engine_for_scope(scope)`` is synchronous and must return an engine bound
    to exactly that Scope. ``wakeup(scope, run_id)`` is optional native async host
    scheduling; submission acceptance and drive remain distinct responsibilities.
    All resources are borrowed; host ASGI lifespan owns coordinator shutdown.
    """

    def __init__(
        self,
        *,
        engine_for_scope,
        spec,
        inbox,
        authenticate,
        url,
        name="Ralf Agent",
        description="Durable native Run polling",
        version="1",
        budget=32,
        wakeup=None,
        timeout=10,
        max_request_bytes=262144,
        max_response_bytes=262144,
        enable_user_input=False,
        enable_run_events=False,
        enable_run_controls=False,
        recovery_wakeup=None,
        audit=None,
    ):  # noqa: ASYNC109
        if not is_sync_callable(engine_for_scope) or not is_async_callable(authenticate):
            raise ValidationError("A2A requires trusted engine and async authentication callbacks")
        validate_inbox(inbox)
        if wakeup is not None and not is_async_callable(wakeup):
            raise ValidationError("A2A requires durable inbox and optional async wakeup")
        if type(enable_user_input) is not bool:
            raise ValidationError("A2A user input extension selection must be boolean")
        if type(enable_run_events) is not bool:
            raise ValidationError("A2A event extension selection must be boolean")
        if type(enable_run_controls) is not bool:
            raise ValidationError("A2A Run control selection must be boolean")
        if recovery_wakeup is not None and not is_async_callable(recovery_wakeup):
            raise ValidationError("Recovery wakeup must be a native async host callback")
        for value in (name, description, version):
            _text(value, "Agent Card text")
        _integer(budget, "A2A budget", 0, 1000000)
        _integer(max_request_bytes, "Request byte limit", 1024, 262144)
        _integer(max_response_bytes, "Response byte limit", 1024, 262144)
        if audit is not None and type(audit) is not ServiceAudit:
            raise ValidationError("Service audit requires ServiceAudit")
        self._audit = audit
        self._engine_for_scope = engine_for_scope
        self._authenticate = authenticate
        from .agent_harness import AgentHarness

        self._spec = AgentHarness(spec).definition
        self._input_composite = submission_request(self._spec, None)["definition"]["kind"] not in {
            "agent",
            "sequence",
            "bound_agent",
        }
        self._inbox = inbox
        self._url = _url(url)
        self._budget = budget
        self._wakeup = wakeup
        self._timeout = _timeout(timeout)
        self._max_request = max_request_bytes
        self._max_response = max_response_bytes
        self._user_input_enabled = enable_user_input
        self._run_events_enabled = enable_run_events
        self._run_controls_enabled = enable_run_controls
        self._recovery_wakeup = recovery_wakeup
        self._card = {
            "protocolVersion": PROTOCOL_VERSION,
            "name": name,
            "description": description,
            "url": self._url,
            "preferredTransport": "JSONRPC",
            "version": version,
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": False,
                "extensions": [
                    {
                        "uri": RECEIPT_EXTENSION,
                        "description": "Read-only lookup by metadata.ralfMessageId",
                        "required": False,
                    }
                ],
            },
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [
                {
                    "id": "run",
                    "name": name,
                    "description": description,
                    "tags": ["native-run", "polling"],
                }
            ],
            "securitySchemes": {"hostBearer": {"type": "http", "scheme": "bearer"}},
            "security": [{"hostBearer": []}],
            "supportsAuthenticatedExtendedCard": False,
        }
        if enable_user_input:
            self._card["capabilities"]["extensions"].append(
                {
                    "uri": USER_INPUT_EXTENSION,
                    "description": "Explicit original pending input reply via metadata.ralfInput",
                    "required": False,
                }
            )
        if enable_run_events:
            from .a2a_events import EXTENSION

            self._card["capabilities"]["extensions"].append(
                {
                    "uri": EXTENSION,
                    "description": "Read-only tasks/events cursor pages",
                    "required": False,
                }
            )
        if enable_run_controls:
            from .a2a_controls import EXTENSION

            self._card["capabilities"]["extensions"].append(
                {
                    "uri": EXTENSION,
                    "description": "Original Run controls; resume needs host recovery wakeup",
                    "required": False,
                }
            )

    def agent_card(self):
        return copy.deepcopy(self._card)

    def _engine(self, scope):
        engine = self._engine_for_scope(scope)
        if getattr(engine, "scope", None) != scope:
            raise AuthorizationDenied("Trusted engine Scope mismatch")
        controls = TaskControlBridge(engine, scope)
        if self._user_input_enabled:
            controls.require_input_discovery(composite=self._input_composite)
        return controls

    async def _task_snapshot(self, engine, snapshot):
        task = self._snapshot(snapshot)
        if self._user_input_enabled:
            inputs = await engine.pending_inputs(snapshot.run_id)
            engine.verify()
            pending = [item for item in snapshot.pending if item.get("kind") != "input"]
            pending.extend(
                {**question, "ownerTaskId": question["owner"]["run_id"]} for question in inputs
            )
            if pending:
                task["metadata"]["ralf"]["pending"] = pending
            else:
                task["metadata"]["ralf"].pop("pending", None)
        return _task(task)

    @staticmethod
    def _snapshot(snapshot):
        try:
            state = _NATIVE_STATES[snapshot.state]
        except (KeyError, AttributeError) as exc:
            raise A2AError("Native Run returned an unsupported state") from exc
        task = {
            "kind": "task",
            "id": snapshot.run_id,
            "contextId": snapshot.run_id,
            "status": {"state": state},
            "metadata": {
                "ralf": {
                    "state": snapshot.state,
                    "stateRevision": snapshot.state_revision,
                    "consistency": snapshot.consistency,
                }
            },
        }
        if snapshot.pending:
            task["metadata"]["ralf"]["pending"] = list(snapshot.pending)
        if snapshot.error:
            # Only the engine's typed code crosses the boundary.
            task["metadata"]["ralf"]["error"] = {"code": snapshot.error.get("code", "run_failed")}
        if state == "completed":
            task["artifacts"] = [
                {
                    "artifactId": snapshot.run_id + ":result",
                    "parts": [{"kind": "data", "data": {"result": snapshot.result}}],
                }
            ]
        return _task(task)

    def _message(self, params):
        if set(params) - {"message", "configuration", "metadata"} or not isinstance(
            params.get("message"), dict
        ):
            raise ValidationError("Invalid message/send parameters")
        message = params["message"]
        if (
            set(message) - {"kind", "role", "messageId", "parts", "metadata", "contextId", "taskId"}
            or message.get("kind") != "message"
            or message.get("role") != "user"
        ):
            raise ValidationError("Invalid A2A user Message")
        targeted = "taskId" in message or "contextId" in message
        if targeted and not (
            self._user_input_enabled
            and type(message.get("metadata")) is dict
            and "ralfInput" in message["metadata"]
        ):
            raise _RPCError(-32004, "Task continuation is unsupported")
        _text(message.get("messageId"), "Message identity")
        if not isinstance(message.get("parts"), list) or not 1 <= len(message["parts"]) <= 64:
            raise ValidationError("A2A Message requires bounded parts")
        for part in message["parts"]:
            _part(part)
        for owner in (message, params):
            if "metadata" in owner and not isinstance(owner["metadata"], dict):
                raise ValidationError("Message metadata requires an object")
        config = params.get("configuration", {})
        if not isinstance(config, dict) or set(config) - {
            "blocking",
            "acceptedOutputModes",
            "historyLength",
            "pushNotificationConfig",
        }:
            raise ValidationError("Invalid A2A send configuration")
        if "pushNotificationConfig" in config:
            raise _RPCError(-32003, "Push notifications are unsupported")
        if "blocking" in config and type(config["blocking"]) is not bool:
            raise ValidationError("Blocking must be a boolean")
        if config.get("blocking"):
            raise _RPCError(-32004, "Only polling submissions are supported")
        if "historyLength" in config and config["historyLength"] != 0:
            raise _RPCError(-32004, "Task history is unsupported")
        if "acceptedOutputModes" in config and config["acceptedOutputModes"] != [
            "application/json"
        ]:
            raise _RPCError(-32005, "Requested output modes are unsupported")
        _json(params)
        if targeted:
            self._input_message(message)
        elif type(message.get("metadata")) is dict and "ralfInput" in message["metadata"]:
            raise ValidationError("User input reply requires its original Task identity")
        return message

    @staticmethod
    def _input_message(message):
        from .user_input import input_reply_payload

        _text(message.get("taskId"), "Original input Task identity")
        if "contextId" in message and message["contextId"] != message["taskId"]:
            raise ValidationError("User input context differs from its original Task")
        target = message["metadata"]["ralfInput"]
        parts = message["parts"]
        if (
            type(target) is not dict
            or set(target) - {"pendingId", "targetDigest", "expectedStateRevision"}
            or {"pendingId", "targetDigest"} - set(target)
            or len(parts) != 1
            or set(parts[0]) != {"kind", "data"}
            or parts[0]["kind"] != "data"
            or type(parts[0]["data"]) is not dict
            or set(parts[0]["data"]) != {"value"}
        ):
            raise ValidationError("User input reply requires exact target metadata and JSON value")
        return input_reply_payload(
            message["taskId"],
            target["pendingId"],
            target["targetDigest"],
            parts[0]["data"]["value"],
            expected_state_revision=target.get("expectedStateRevision"),
        )

    async def _input_reply(self, scope, engine, params, message):
        payload = self._input_message(message)
        envelope = MessageEnvelope(message["messageId"], "a2a:user-input", params)
        previous = await call_inbox(self._inbox, "accept", scope, envelope)
        if previous is None:
            receipt = await engine.send_input(
                payload["run_id"],
                payload["pending_id"],
                payload["digest"],
                payload["value"],
                command_id=message["messageId"],
                expected_state_revision=payload.get("expected_state_revision"),
            )
            previous = {"run_id": payload["run_id"], "receipt": asdict(receipt)}
            await call_inbox(self._inbox, "complete", scope, envelope, previous)
        if self._wakeup is not None and previous["receipt"]["apply_state"] == "applied":
            engine.verify()
            if (
                await _completed(await self._wakeup(scope, previous["run_id"]), "A2A wakeup")
                is not None
            ):
                raise ValidationError("A2A wakeup must finish to None")
        task = await self._task_snapshot(engine, await engine.status(previous["run_id"]))
        task["metadata"]["ralf"]["inputReceipt"] = previous["receipt"]
        return _task(task)

    async def _rpc(self, scope, method, params, request_id):
        if not isinstance(params, dict):
            raise ValidationError("RPC parameters require an object")
        engine = self._engine(scope)
        if (
            method in {"tasks/approve", "tasks/reconcile", "tasks/resume"}
            and self._run_controls_enabled
        ):
            from .a2a_controls import apply_control, control_request

            control_request(method, params)
            if method == "tasks/resume":
                if self._recovery_wakeup is None:
                    raise _RPCError(-32004, "Host recovery wakeup is not configured")
                await engine.status(params["id"])
                engine.verify()
                completed = await _completed(
                    await self._recovery_wakeup(scope, params["id"]), "A2A recovery wakeup"
                )
                if completed is not None:
                    raise ValidationError("Recovery wakeup must finish to None")
                engine.verify()
                task = await self._task_snapshot(engine, await engine.status(params["id"]))
                task["metadata"]["ralf"]["recoveryHint"] = {"accepted": True, "durable": False}
                return _task(task)
            result = await apply_control(engine, method, params)
            receipt = result["receipt"]
            if (
                self._wakeup is not None
                and receipt["apply_state"] == "applied"
                and not receipt["outcome"].get("rejected")
            ):
                engine.verify()
                completed = await _completed(await self._wakeup(scope, params["id"]), "A2A wakeup")
                if completed is not None:
                    raise ValidationError("A2A wakeup must finish to None")
                engine.verify()
            return result
        if method == "tasks/events" and self._run_events_enabled:
            from .a2a_events import event_page

            return await event_page(
                engine, params, max_bytes=self._max_response, request_id=request_id
            )
        if method == "message/send":
            if self._user_input_enabled:
                engine.require_user_input_controls()
            message = self._message(params)
            if "taskId" in message:
                return await self._input_reply(scope, engine, params, message)
            envelope = MessageEnvelope(message["messageId"], "a2a:submissions", params)
            previous = await call_inbox(self._inbox, "accept", scope, envelope)
            if previous is None:
                # Full wire request remains in native command identity, so changes
                # to message metadata/configuration cannot reuse messageId.
                handle = await engine.submit(
                    self._spec,
                    {"a2a": params},
                    command_id=message["messageId"],
                    budget=self._budget,
                )
                previous = {"run_id": handle.run_id}
                await call_inbox(self._inbox, "complete", scope, envelope, previous)
            if self._wakeup is not None:
                engine.verify()
                completed = await _completed(
                    await self._wakeup(scope, previous["run_id"]), "A2A wakeup"
                )
                if completed is not None:
                    raise ValidationError("A2A wakeup must finish to None")
            return await self._task_snapshot(engine, await engine.status(previous["run_id"]))
        if method not in {"tasks/get", "tasks/cancel"}:
            raise _RPCError(-32601, "Method not found")
        allowed = (
            {"id", "metadata", "historyLength"} if method == "tasks/get" else {"id", "metadata"}
        )
        if set(params) - allowed:
            raise ValidationError("Invalid Task parameters")
        _text(params.get("id"), "Task identity")
        if params.get("historyLength", 0) != 0:
            raise _RPCError(-32004, "Task history is unsupported")
        metadata = params.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError("Task metadata requires an object")
        task_id = params["id"]
        if "ralfMessageId" in metadata:
            if method != "tasks/get":
                raise ValidationError("Message receipt lookup is read-only")
            _text(metadata["ralfMessageId"], "Message identity")
            receipt = await call_inbox(self._inbox, "result", scope, metadata["ralfMessageId"])
            if receipt is None:
                raise NotFound("No durable message receipt")
            task_id = receipt["run_id"]
        snapshot = await engine.status(task_id)
        if method == "tasks/cancel":
            if snapshot.state in {"succeeded", "failed", "cancelled"}:
                raise _RPCError(-32002, "Task cannot be canceled")
            command = metadata.get("ralfCommandId")
            if command is None:
                command = "a2a-cancel:" + digest({"id": request_id, "task": task_id})
            _text(command, "Cancellation command identity")
            receipt = await engine.cancel(task_id, command_id=command)
            if receipt.apply_state == "rejected" or receipt.outcome.get("rejected"):
                raise _RPCError(-32002, "Task cannot be canceled")
            snapshot = await engine.status(task_id)
        return await self._task_snapshot(engine, snapshot)

    async def _reply(self, send, status, value):
        encoded = canonical(value).encode("utf-8")
        if len(encoded) > self._max_response:
            status = 200
            encoded = canonical(_response_limit_error(value.get("id"))).encode("utf-8")
            if len(encoded) > self._max_response:
                encoded = canonical(_response_limit_error(None)).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": encoded})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        if scope["method"] == "GET" and scope["path"] == "/.well-known/agent-card.json":
            await self._reply(send, 200, self.agent_card())
            return
        endpoint_path = urlsplit(self._url).path or "/"
        if scope["method"] != "POST" or scope["path"] != endpoint_path:
            await self._reply(send, 404, {"error": "not_found"})
            return
        request_id = None
        trusted, method, task_id, message_id = None, None, None, None
        command_id = None
        outcome = "internal_error"
        try:
            async with asyncio.timeout(self._timeout):
                headers = {
                    key.decode("latin1").lower(): value.decode("latin1")
                    for key, value in scope.get("headers", [])
                }
                trusted = await self._authenticate(headers)
                if not isinstance(trusted, Scope):
                    raise AuthorizationDenied("Authentication did not bind Scope")
                body = bytearray()
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        outcome = "disconnected"
                        return
                    if event["type"] != "http.request":
                        raise ValidationError("Invalid HTTP request event")
                    body.extend(event.get("body", b""))
                    if len(body) > self._max_request:
                        raise _RPCError(-32600, "Request exceeds configured limit")
                    if not event.get("more_body", False):
                        break
                try:
                    request = _loads(body)
                except Exception as exc:
                    raise _RPCError(-32700, "Parse error") from exc
                if (
                    not isinstance(request, dict)
                    or set(request) - {"jsonrpc", "id", "method", "params"}
                    or request.get("jsonrpc") != "2.0"
                    or type(request.get("id")) not in (str, int)
                    or not isinstance(request.get("method"), str)
                ):
                    raise _RPCError(-32600, "Invalid request")
                if (
                    len(canonical(_response_limit_error(request["id"])).encode("utf-8"))
                    > self._max_response
                ):
                    raise _RPCError(-32600, "Request identity exceeds response limit")
                request_id = request["id"]
                method = request["method"]
                params = request.get("params", {})
                if self._audit is not None and isinstance(params, dict):
                    task_id = params.get("id") if type(params.get("id")) is str else None
                    command_id = params.get("commandId")
                    metadata = params.get("metadata", {})
                    if command_id is None and isinstance(metadata, dict):
                        command_id = metadata.get("ralfCommandId")
                    if type(command_id) is not str:
                        command_id = None
                    message = params.get("message", {})
                    if isinstance(message, dict):
                        message_id = message.get("messageId")
                        if type(message_id) is not str:
                            message_id = None
                result = await self._rpc(trusted, method, params, request_id)
                if self._audit is not None and isinstance(result, dict):
                    resolved_task = result.get("id", result.get("taskId"))
                    if type(resolved_task) is str:
                        task_id = resolved_task
                    receipt = result.get("receipt")
                    if isinstance(receipt, dict) and type(receipt.get("command_id")) is str:
                        command_id = receipt["command_id"]
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
                outcome = "rpc_ok"
        except AuthorizationDenied:
            outcome = "unauthorized"
            await self._reply(send, 401, {"error": "unauthorized"})
            return
        except _RPCError as exc:
            outcome = "invalid_request" if exc.code in {-32700, -32600, -32602} else "rpc_error"
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": exc.message},
            }
        except NotFound:
            outcome = "not_found"
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32001, "message": "Task not found"},
            }
        except (ValidationError, IdempotencyConflict):
            outcome = "invalid_request"
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "Invalid parameters or message identity conflict",
                },
            }
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                outcome = "timeout"
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": "Internal error"},
            }
        finally:
            if self._audit is not None:
                self._audit.record(
                    scope=trusted,
                    method=method,
                    outcome=outcome,
                    request_id=request_id,
                    task_id=task_id,
                    message_id=message_id,
                    command_id=command_id,
                )
        await self._reply(send, 200, response)


class A2AClient:
    def __init__(
        self,
        url,
        *,
        client=None,
        owns_client=False,
        headers=None,
        timeout=10,
        max_response_bytes=262144,
    ):  # noqa: ASYNC109
        self._url = _url(url)
        self._timeout = _timeout(timeout)
        _integer(max_response_bytes, "Response byte limit", 1024, 262144)
        if type(owns_client) is not bool:
            raise ValidationError("HTTP client ownership must be a boolean")
        if client is None:
            client, owns_client = (
                httpx.AsyncClient(timeout=self._timeout, follow_redirects=False),
                True,
            )
        if not is_async_callable(getattr(client, "send", None)) or not is_sync_callable(
            getattr(client, "build_request", None)
        ):
            raise ValidationError("A2A requires a native async HTTP client")
        if owns_client and not is_async_callable(getattr(client, "aclose", None)):
            raise ValidationError("Owned HTTP client requires async aclose")
        if headers is not None and (
            not isinstance(headers, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items())
        ):
            raise ValidationError("HTTP headers require a host-owned text mapping")
        self._client, self._owns_client = client, owns_client
        self._headers = dict(headers or {})
        self._max_response = max_response_bytes
        self._next_id = 0
        self._closed = False
        self._close_lock = asyncio.Lock()

    @property
    def url(self):
        return self._url

    @property
    def identity(self):
        return {"kind": "a2a-client", "protocolVersion": PROTOCOL_VERSION, "url": self.url}

    async def _request(self, method, url, payload=None):
        if self._closed:
            raise A2AError("A2A client is closed")
        response = None
        try:
            async with asyncio.timeout(self._timeout):
                request = self._client.build_request(
                    method, url, json=payload, headers=self._headers, timeout=self._timeout
                )
                response = await self._client.send(request, stream=True, follow_redirects=False)
                if response.status_code != 200:
                    raise A2AError("A2A HTTP request failed")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self._max_response:
                        raise A2AError("A2A response exceeds its byte limit")
                return _loads(content)
        except A2AError:
            raise
        except Exception as exc:
            raise A2AError(
                "A2A transport or response failed; submission outcome may be unknown"
            ) from exc
        finally:
            if response is not None:
                try:
                    async with asyncio.timeout(self._timeout):
                        await response.aclose()
                except Exception:
                    pass

    async def discover(self):
        parsed = urlsplit(self.url)
        url = urlunsplit((parsed.scheme, parsed.netloc, "/.well-known/agent-card.json", "", ""))
        card = await self._request("GET", url)
        return _agent_card(card, self.url)

    async def rpc(self, method, params):
        if method not in {
            "message/send",
            "tasks/get",
            "tasks/cancel",
            "tasks/events",
            "tasks/approve",
            "tasks/reconcile",
            "tasks/resume",
        }:
            raise ValidationError("Unsupported A2A polling method")
        _json(params)
        self._next_id += 1
        request_id = self._next_id
        value = await self._request(
            "POST",
            self.url,
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        if (
            not isinstance(value, dict)
            or value.get("jsonrpc") != "2.0"
            or type(value.get("id")) is not int
            or value["id"] != request_id
            or set(value) not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})
        ):
            raise A2AError("A2A returned an invalid RPC response")
        if "error" in value:
            error = value["error"]
            if (
                not isinstance(error, dict)
                or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str)
            ):
                raise A2AError("A2A returned an invalid RPC error")
            raise A2ARemoteError(error["code"])
        if method in {"tasks/approve", "tasks/reconcile"}:
            from .a2a_controls import validate_control_response

            try:
                return validate_control_response(value["result"], method, params)
            except Exception as exc:
                raise A2AError("A2A returned an invalid Run control receipt") from exc
        if method == "tasks/events":
            from .a2a_events import validate_event_page

            try:
                return validate_event_page(value["result"], params)
            except Exception as exc:
                raise A2AError("A2A returned an invalid event page") from exc
        return _task(value["result"])

    async def get_events(self, task_id, *, cursor=None, limit=100):
        from .a2a_events import event_request

        return await self.rpc("tasks/events", event_request(task_id, cursor, limit))

    async def approve_task(self, task_id, action_id, target_digest, *, command_id, approved=True):
        from .a2a_controls import control_request

        params = {
            "id": task_id,
            "actionId": action_id,
            "targetDigest": target_digest,
            "commandId": command_id,
            "approved": approved,
        }
        return await self.rpc("tasks/approve", control_request("tasks/approve", params))

    async def reconcile_task(self, task_id, action_id, result, *, command_id):
        from .a2a_controls import control_request

        params = {"id": task_id, "actionId": action_id, "result": result, "commandId": command_id}
        return await self.rpc("tasks/reconcile", control_request("tasks/reconcile", params))

    async def resume_task(self, task_id):
        _text(task_id, "Task identity")
        task = await self.rpc("tasks/resume", {"id": task_id})
        if task["id"] != task_id or task.get("metadata", {}).get("ralf", {}).get(
            "recoveryHint"
        ) != {"accepted": True, "durable": False}:
            raise A2AError("A2A returned an invalid recovery hint")
        return task

    async def send_message(self, message_id, input):
        _text(message_id, "Message identity")
        _json(input)
        return await self.rpc(
            "message/send",
            {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": message_id,
                    "parts": [{"kind": "data", "data": {"input": input}}],
                },
                "configuration": {"blocking": False},
            },
        )

    async def get_task(self, task_id):
        _text(task_id, "Task identity")
        task = await self.rpc("tasks/get", {"id": task_id})
        if task["id"] != task_id:
            raise A2AError("A2A returned a different Task identity")
        return task

    async def send_input(
        self,
        task_id,
        pending_id,
        target_digest,
        value,
        *,
        command_id,
        expected_state_revision=None,
    ):
        from .user_input import input_reply_payload

        _text(command_id, "Input command identity")
        payload = input_reply_payload(
            task_id,
            pending_id,
            target_digest,
            value,
            expected_state_revision=expected_state_revision,
        )
        target = {"pendingId": pending_id, "targetDigest": target_digest}
        if "expected_state_revision" in payload:
            target["expectedStateRevision"] = payload["expected_state_revision"]
        return await self.rpc(
            "message/send",
            {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": command_id,
                    "taskId": task_id,
                    "metadata": {"ralfInput": target},
                    "parts": [{"kind": "data", "data": {"value": payload["value"]}}],
                },
                "configuration": {"blocking": False},
            },
        )

    async def get_by_message(self, message_id):
        _text(message_id, "Message identity")
        return await self.rpc(
            "tasks/get", {"id": message_id, "metadata": {"ralfMessageId": message_id}}
        )

    async def cancel_task(self, task_id, *, command_id):
        _text(task_id, "Task identity")
        _text(command_id, "Command identity")
        task = await self.rpc(
            "tasks/cancel", {"id": task_id, "metadata": {"ralfCommandId": command_id}}
        )
        if task["id"] != task_id:
            raise A2AError("A2A returned a different Task identity")
        return task

    async def aclose(self):
        async with self._close_lock:
            if self._closed:
                return
            if self._owns_client:
                try:
                    async with asyncio.timeout(self._timeout):
                        await self._client.aclose()
                except Exception as exc:
                    raise A2AError("A2A HTTP close failed") from exc
            self._closed = True


class A2AToolSource:
    """Remote-agent tool discovered once and controlled by host ToolPolicy.

    Register ``message_id`` as policy.effect_key_argument to bind submission to
    the managed effect identity. ``reconcile`` performs read-only receipt lookup;
    it never resubmits. Completion proves remote Task completion, not local
    business exactly-once effects.
    """

    def __init__(
        self,
        client,
        *,
        name="remote_agent",
        description="Invoke the remote agent",
        poll_timeout=10,
        poll_interval=0.05,
        owns_client=False,
    ):
        validate_a2a_client(client)
        if type(owns_client) is not bool:
            raise ValidationError("A2A client ownership must be a boolean")
        _text(name, "Remote tool name")
        _text(description, "Remote tool description")
        self.client = client
        self._name, self._description = name, description
        self._poll_timeout = _timeout(poll_timeout)
        self._poll_interval = _timeout(poll_interval)
        self._owns_client = owns_client
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._card_digest = None
        self._descriptor = ToolDescriptor(
            name,
            description,
            {
                "type": "object",
                "properties": {"input": {}, "message_id": {"type": "string"}},
                "required": ["input", "message_id"],
                "additionalProperties": False,
            },
        )

    @property
    def identity(self):
        validate_a2a_client(self.client)
        return {
            "kind": "a2a",
            "protocolVersion": PROTOCOL_VERSION,
            "url": self.client.url,
            "tool": self._name,
            "client": json.loads(_json(self.client.identity)),
        }

    async def _client_call(self, method, *args, **kwargs):
        if self._closed:
            raise A2AError("A2A tool source is closed")
        validate_a2a_client(self.client)
        async with asyncio.timeout(self._poll_timeout):
            result = await _completed(
                await getattr(self.client, method)(*args, **kwargs), f"A2AClientPort.{method}"
            )
        if method == "discover":
            return _agent_card(result, self.client.url)
        task = _task(result)
        if method in {"get_task", "cancel_task"} and task["id"] != args[0]:
            raise A2AError("A2A returned a different Task identity")
        return task

    async def list_tools(self):
        card = await self._client_call("discover")
        current = digest(card)
        if self._card_digest is not None and self._card_digest != current:
            raise ToolSourceError("Remote Agent Card changed")
        self._card_digest = current
        return (self._descriptor,)

    @staticmethod
    def _result(task):
        if task["status"]["state"] != "completed":
            return None
        try:
            artifact = task["artifacts"][0]
            part = artifact["parts"][0]
            if part.get("kind") != "data" or set(part["data"]) != {"result"}:
                raise ValueError("invalid result")
            return {"task_id": task["id"], "state": "completed", "result": part["data"]["result"]}
        except Exception as exc:
            raise ToolSourceError("Remote completed Task has no supported result") from exc

    async def call_tool(self, descriptor, arguments, context):
        if descriptor.to_dict() != self._descriptor.to_dict() or self._card_digest is None:
            raise ToolSourceError("Remote tool was not discovered or selected")
        if arguments.get("message_id") != context.effect_key:
            raise ValidationError("A2A message identity must match the managed effect key")
        try:
            async with asyncio.timeout(self._poll_timeout):
                task = await self._client_call(
                    "send_message", arguments["message_id"], arguments["input"]
                )
                while True:
                    result = self._result(task)
                    if result is not None:
                        return result
                    if task["status"]["state"] not in {"submitted", "working"}:
                        raise ToolSourceError(
                            "Remote Task requires host attention; effect remains unknown"
                        )
                    await asyncio.sleep(self._poll_interval)
                    task = await self._client_call("get_task", task["id"])
        except ToolSourceError:
            raise
        except Exception as exc:
            raise ToolSourceError(
                "Remote A2A effect outcome is unknown; query its original message identity"
            ) from exc

    async def reconcile(self, arguments, context):
        try:
            task = await self._client_call("get_by_message", context.effect_key)
            return self._result(task)
        except A2ARemoteError as exc:
            if exc.rpc_code == -32001:
                return None
            raise ToolSourceError("Remote A2A reconciliation failed") from exc
        except A2AError as exc:
            raise ToolSourceError("Remote A2A reconciliation failed") from exc

    async def aclose(self):
        """Close only explicitly owned clients; failed cleanup remains retriable."""
        async with self._close_lock:
            if self._closed:
                return
            if self._owns_client:
                try:
                    validate_a2a_client(self.client)
                    async with asyncio.timeout(self._poll_timeout):
                        result = await _completed(
                            await self.client.aclose(), "A2AClientPort.aclose"
                        )
                    if result is not None:
                        raise ValidationError(
                            "A2AClientPort.aclose must return None after completion"
                        )
                except Exception as exc:
                    raise A2AError("A2A tool source client close failed") from exc
            self._closed = True
