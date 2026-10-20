"""Fresh SDK identity for Session control; no Session coordinator root claim.

The pure DTO validators correlate bytes only. This module reads the original
SDK coordinator and its durable intent before allowing any control body.
"""

from .errors import DefinitionMismatch
from .task_controls import _binding
from .temporal_session_deployment_dto import validate_intent, validate_origin
from .temporal_session_state import SESSION_ACTIVITY, SESSION_WORKFLOW
from .temporal_state import detached
from .types import canonical, digest

REQUEST_FIELDS = {
    "version",
    "mode",
    "scope",
    "namespace",
    "coordinator_id",
    "coordinator_execution_epoch",
    "intent",
}
PERMANENT_REFUSAL_CODES = frozenset(
    {
        "validation_error",
        "definition_mismatch",
        "idempotency_conflict",
        "authorization_denied",
    }
)
_ACTIVITY_FIELDS = (
    "workflow_id",
    "workflow_run_id",
    "workflow_namespace",
    "activity_id",
    "activity_type",
    "attempt",
    "task_queue",
)


def _reject():
    raise DefinitionMismatch("Original Session control SDK identity changed")


class SessionControlValidation:
    """Invocation-local fresh reads, with immutable port and Activity pins."""

    def __init__(
        self,
        runtime,
        client,
        value,
        info,
        *,
        deployment_id,
        _coordinator_activity=True,
        _full_release=True,
    ):
        if type(_full_release) is not bool:
            _reject()
        if (
            type(value) is not dict
            or set(value) != REQUEST_FIELDS
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["mode"] not in {"register", "observe"}
        ):
            _reject()
        self.runtime, self.client, self.info = runtime, client, info
        self._coordinator_activity = _coordinator_activity
        self.value, self.deployment_id = detached(value), deployment_id
        self._digest = digest(self.value)
        self.intent = validate_intent(
            self.value["intent"],
            deployment_id=deployment_id,
            scope=self.value["scope"],
            namespace=self.value["namespace"],
            coordinator_execution_epoch=self.value["coordinator_execution_epoch"],
        )
        if self.intent["coordinator_id"] != self.value["coordinator_id"]:
            _reject()
        self._intent_digest = digest(self.intent)
        self._shared_intent = digest(self.value["intent"]) == self._intent_digest
        if self._shared_intent:
            self.value["intent"] = self.intent
        self._resources = runtime, client, client.workflow_service, client.data_converter
        self._claim = tuple(getattr(info, k, None) for k in _ACTIVITY_FIELDS)
        self._ports = [
            (runtime, "validate_release"),
            (client, "get_workflow_handle"),
            (client.workflow_service, "describe_namespace"),
            (client.data_converter, "decode"),
            (self, "_check"),
            (self, "validate"),
            (self, "_namespace"),
            (self, "_description"),
            (self, "_start"),
            (self, "lifecycle"),
        ]
        self._bindings = tuple(_binding(getattr(owner, name)) for owner, name in self._ports)
        self._source_bindings = source_bindings()
        self._source_function = _binding(source_bindings)
        self._check(full=_full_release)

    def _check(self, *, full=True):
        if type(full) is not bool or type(self._shared_intent) is not bool:
            _reject()
        runtime, client, service, converter = self._resources
        if (
            self.runtime is not runtime
            or self._source_function != _binding(source_bindings)
            or self._source_bindings != source_bindings()
            or self.client is not client
            or client.workflow_service is not service
            or client.data_converter is not converter
            or digest(self.value) != self._digest
            or (self._shared_intent and self.intent is not self.value.get("intent"))
            or (not self._shared_intent and digest(self.intent) != self._intent_digest)
            or self._bindings != tuple(_binding(getattr(o, n)) for o, n in self._ports)
            or tuple(getattr(self.info, k, None) for k in _ACTIVITY_FIELDS) != self._claim
        ):
            _reject()
        i, info = self.intent, self.info
        if client.namespace != i["namespace"]["name"]:
            _reject()
        if info is None:
            if self._coordinator_activity:
                _reject()
        else:
            if (
                info.workflow_namespace != client.namespace
                or self._coordinator_activity
                and (
                    info.workflow_id != i["coordinator_id"]
                    or info.workflow_run_id != i["coordinator_execution_epoch"]
                    or info.activity_type != SESSION_ACTIVITY
                )
                or type(info.attempt) is not int
                or info.attempt < 1
                or type(info.activity_id) is not str
                or not info.activity_id.strip()
                or self._coordinator_activity
                and info.task_queue != i["binding"]["task_queue"]
            ):
                _reject()
            from temporalio import activity

            try:
                live = activity.info()
            except RuntimeError:
                live = None
            if (
                live is not None
                and tuple(getattr(live, k, None) for k in _ACTIVITY_FIELDS) != self._claim
            ):
                _reject()
        if full:
            runtime.validate_release(i["binding"]["manifest"])

    async def _namespace(self):
        from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

        self._check(full=False)
        result = await self.client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=self.intent["namespace"]["name"])
        )
        self._check(full=False)
        if result.namespace_info.id != self.intent["namespace"]["id"]:
            _reject()

    def _description(self, description):
        i = self.intent
        if (
            description.id != i["coordinator_id"]
            or description.run_id != i["coordinator_execution_epoch"]
            or description.namespace != i["namespace"]["name"]
            or description.workflow_type != SESSION_WORKFLOW
            or description.parent_id is not None
            or description.parent_run_id is not None
            or getattr(description.raw_info, "first_run_id", None)
            != i["coordinator_execution_epoch"]
        ):
            _reject()

    async def _start(self, handle, description):
        events = handle.fetch_history_events(page_size=1)
        self._check(full=False)
        try:
            first = await anext(events)
        except StopAsyncIteration:
            _reject()
        self._check(full=False)
        if first.event_id != 1 or not first.HasField("workflow_execution_started_event_attributes"):
            _reject()
        start = first.workflow_execution_started_event_attributes
        epoch = self.intent["coordinator_execution_epoch"]
        if (
            start.workflow_type.name != SESSION_WORKFLOW
            or start.task_queue.name != description.task_queue
            or start.original_execution_run_id != epoch
            or start.first_execution_run_id != epoch
            or start.continued_execution_run_id
            or start.parent_workflow_execution.workflow_id
            or start.parent_workflow_execution.run_id
        ):
            _reject()
        accepted = await self.client.data_converter.decode(start.input.payloads)
        self._check(full=False)
        if len(accepted) != 1 or type(accepted[0]) is not dict:
            _reject()
        accepted, i = accepted[0], self.intent
        key = i["session_ref"]["key"]
        if (
            accepted.get("scope") != i["scope"]
            or accepted.get("namespace_id") != i["namespace"]["id"]
            or accepted.get("session_namespace") != key["namespace"]
            or accepted.get("session_id") != key["session_id"]
            or accepted.get("task_queue") != description.task_queue
        ):
            _reject()

    def selector(self, kind):
        i = self.intent
        return {
            **(
                {"intent_digest": i["intent_digest"]} if kind != "deployment_session_intent" else {}
            ),
            "kind": kind,
            "scope": detached(i["scope"]),
            "namespace": detached(i["namespace"]),
            "coordinator_execution_epoch": i["coordinator_execution_epoch"],
            "session_command_id": i["session_command_id"],
            "turn_id": i["turn_id"],
        }

    async def validate(self, *, _full_release=True):
        # The public default brackets the set with full inventory checks. Only
        # the matching warm Coding callback delegates those to its independent
        # outer boundary; every original identity/port pin remains per await.
        if type(_full_release) is not bool:
            _reject()
        self._check(full=_full_release)
        i, client = self.intent, self.client
        current = client.get_workflow_handle(i["coordinator_id"])
        handle = client.get_workflow_handle(
            i["coordinator_id"], run_id=i["coordinator_execution_epoch"]
        )
        manifest = i["binding"]["manifest"]
        protocol = manifest.get("deployment_admission_protocol")
        coding = (
            type(protocol) is dict
            and type(protocol.get("version")) is int
            and protocol["version"] == 4
            and "coding_execution_protocol" in manifest
        )
        if coding:
            import asyncio

            async def read(operation, *args):
                self._check(full=False)
                try:
                    return await operation(*args)
                finally:
                    self._check(full=False)

            async def coordinator_facts():
                # Temporal's consistent-query buffer is per Workflow. Keep
                # both fresh facts, but do not make them compete for one slot.
                values = []
                for kind in ("deployment_session_intent", "deployment_session_command"):
                    try:
                        value = await read(handle.query, "view", self.selector(kind))
                    except (Exception, asyncio.CancelledError) as error:
                        value = error
                    values.append(value)
                return values

            # Namespace/description can overlap the coordinator reads. Drain
            # every started reader on failure/cancellation before returning.
            readers = asyncio.gather(
                self._namespace(),
                read(current.describe),
                coordinator_facts(),
                return_exceptions=True,
            )
            try:
                results = await asyncio.shield(readers)
            except asyncio.CancelledError:
                while not readers.done():
                    try:
                        await asyncio.shield(readers)
                    except asyncio.CancelledError:
                        pass
                self._check(full=False)
                raise
            self._check(full=False)
            if isinstance(results[2], BaseException):
                raise results[2]
            results = [results[0], results[1], *results[2]]
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            _, description, intent, command = results
        else:
            await self._namespace()
            self._check(full=False)
            description = await current.describe()
            self._check(full=False)
        self._description(description)
        await self._start(handle, description)
        self._check(full=False)
        if not coding:
            intent = await handle.query("view", self.selector("deployment_session_intent"))
            self._check(full=False)
        if intent != i:
            _reject()
        if not coding:
            command = await handle.query("view", self.selector("deployment_session_command"))
            self._check(full=False)
        if type(command) is not dict or set(command) != {"receipt", "session_ref"}:
            _reject()
        receipt = command["receipt"]
        if (
            command["session_ref"] != i["session_ref"]
            or type(receipt) is not dict
            or set(receipt)
            != {"command_id", "kind", "run_id", "record_state", "apply_state", "outcome"}
            or receipt["command_id"] != i["session_command_id"]
            or receipt["kind"] != "session_submit"
            or receipt["run_id"] is not None
            or receipt["record_state"] != "durably_recorded"
            or receipt["apply_state"] != "applied"
            or type(receipt["outcome"]) is not dict
            or type(receipt["outcome"].get("turn")) is not dict
        ):
            _reject()
        turn = receipt["outcome"]["turn"]
        if turn.get("session") != i["session_ref"] or any(
            turn.get(k) != i[k] for k in ("turn_id", "turn_seq")
        ):
            _reject()
        if (
            turn.get("command_id") != i["session_command_id"]
            or turn.get("run", {}).get("run_id") != i["run_id"]
        ):
            _reject()
        # A reset while an epoch-pinned Query succeeds must still refuse.
        description = await client.get_workflow_handle(i["coordinator_id"]).describe()
        self._check(full=False)
        self._description(description)
        await self._namespace()
        self._check(full=_full_release)
        origin = {
            "version": 1,
            **{
                name: detached(i[name])
                for name in (
                    "namespace",
                    "coordinator_id",
                    "coordinator_execution_epoch",
                    "session_ref",
                    "session_command_id",
                    "turn_id",
                    "turn_seq",
                    "intent_digest",
                )
            },
            "coordinator_first_execution_epoch": i["coordinator_execution_epoch"],
            "coordinator_original_execution_epoch": i["coordinator_execution_epoch"],
        }
        return {
            "intent": detached(i),
            "session_origin": validate_origin(
                origin,
                intent=i,
                deployment_id=self.deployment_id,
            ),
        }

    async def lifecycle(self):
        await self.validate()
        self._check()
        i = self.intent
        result = await self.client.get_workflow_handle(
            i["coordinator_id"],
            run_id=i["coordinator_execution_epoch"],
        ).query("view", self.selector("deployment_session_lifecycle"))
        self._check()
        await self.validate()
        self._check()
        if (
            type(result) is not dict
            or set(result) != {"start", "start_issued", "refusal_barrier"}
            or type(result["start_issued"]) is not bool
            or type(result["start"]) is not dict
            or result["start"].get("intent") != i
        ):
            _reject()
        return detached(result)


REGISTRY_ACTIVITY = "ralf.temporal.session-deployment-verify.v1"


async def registry_epoch(runtime, client, *, manifest, namespace, scope, expected=None, check=None):
    """Read the original Registry's current/first/original SDK epochs and config."""
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

    from .temporal_deployment_admission import registry_id
    from .temporal_deployment_execution import _policy
    from .temporal_state import COMMAND_REGISTRY_NAME

    policy = _policy(runtime, expected=manifest)
    if policy is None or manifest.get("session_deployment_protocol") != 1:
        _reject()
    identity = registry_id(policy["deployment_id"])
    resources = client.workflow_service, client.data_converter
    ports = (
        _binding(runtime.validate_release),
        _binding(client.get_workflow_handle),
        _binding(client.workflow_service.describe_namespace),
        _binding(client.data_converter.decode),
    )

    def checked():
        if (
            resources != (client.workflow_service, client.data_converter)
            or client.namespace != namespace["name"]
            or ports
            != (
                _binding(runtime.validate_release),
                _binding(client.get_workflow_handle),
                _binding(client.workflow_service.describe_namespace),
                _binding(client.data_converter.decode),
            )
        ):
            _reject()
        runtime.validate_release(manifest)
        if check is not None:
            check()

    async def uuid():
        checked()
        ns = await client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=namespace["name"])
        )
        checked()
        if ns.namespace_info.id != namespace["id"]:
            _reject()

    checked()
    await uuid()
    description = await client.get_workflow_handle(identity).describe()
    checked()
    epoch = description.run_id
    if (
        description.id != identity
        or description.namespace != namespace["name"]
        or description.workflow_type != COMMAND_REGISTRY_NAME
        or type(epoch) is not str
        or not epoch
        or expected is not None
        and epoch != expected
        or description.raw_info.first_run_id != epoch
        or description.parent_id is not None
        or description.parent_run_id is not None
    ):
        _reject()
    handle = client.get_workflow_handle(identity, run_id=epoch)
    events = handle.fetch_history_events(page_size=1)
    try:
        first = await anext(events)
    except StopAsyncIteration:
        _reject()
    checked()
    if first.event_id != 1 or not first.HasField("workflow_execution_started_event_attributes"):
        _reject()
    start = first.workflow_execution_started_event_attributes
    if (
        start.original_execution_run_id != epoch
        or start.first_execution_run_id != epoch
        or start.continued_execution_run_id
        or start.workflow_type.name != COMMAND_REGISTRY_NAME
        or start.task_queue.name != description.task_queue
        or start.parent_workflow_execution.workflow_id
        or start.parent_workflow_execution.run_id
    ):
        _reject()
    accepted = await client.data_converter.decode(start.input.payloads)
    checked()
    configuration = {"version": 4, "policy": policy, "namespace": namespace}
    if accepted != [{"deployment_admission": configuration}]:
        _reject()
    result = await handle.query(
        "view",
        {
            "kind": "deployment_configuration",
            "scope": scope,
            "admission_policy": policy,
            "namespace": namespace,
        },
    )
    checked()
    if result != {**configuration, "registry_id": identity}:
        _reject()
    last = await client.get_workflow_handle(identity).describe()
    checked()
    if last.run_id != epoch or last.raw_info.first_run_id != epoch:
        _reject()
    await uuid()
    return handle, epoch, policy


async def verify_registry_request(runtime, client, request, *, info):
    """Registry-owned Activity verification; returned bytes are internal to commit."""
    from .temporal_deployment_admission import registry_id
    from .temporal_deployment_execution import _actual, _policy

    if type(request) is not dict or set(request) != {
        "mode",
        "scope",
        "manifest",
        "registry_execution_epoch",
        "prepared",
    }:
        _reject()
    value = detached(request)
    policy = _policy(runtime, expected=value["manifest"])
    if policy is None or value["mode"] not in {
        "session_root",
        "session_never_claimed",
        "session_receipt",
    }:
        _reject()
    if (
        info.activity_type != REGISTRY_ACTIVITY
        or info.workflow_id != registry_id(policy["deployment_id"])
        or info.workflow_run_id != value["registry_execution_epoch"]
    ):
        _reject()
    prepared = value["prepared"]
    if value["mode"] == "session_receipt":
        return await _verify_receipt(runtime, client, value, info=info)
    expected_fields = {"request", "intent", "session_origin"} | (
        {"barrier"} if value["mode"] == "session_never_claimed" else set()
    )
    if type(prepared) is not dict or set(prepared) != expected_fields:
        _reject()
    i = prepared["intent"]
    wire = {
        "version": 1,
        "mode": "register",
        **{
            k: i[k]
            for k in (
                "scope",
                "namespace",
                "coordinator_id",
                "coordinator_execution_epoch",
            )
        },
        "intent": i,
    }
    validation = SessionControlValidation(
        runtime,
        client,
        wire,
        info,
        deployment_id=policy["deployment_id"],
        _coordinator_activity=False,
    )

    def checked():
        validation._check()
        _actual(
            client,
            info,
            run_id=registry_id(policy["deployment_id"]),
            epoch=value["registry_execution_epoch"],
        )
        if value["scope"] != i["scope"] or value["manifest"] != i["submission"]["manifest"]:
            _reject()

    checked()
    await registry_epoch(
        runtime,
        client,
        manifest=value["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        expected=value["registry_execution_epoch"],
        check=checked,
    )
    verified = await validation.validate()
    checked()
    if verified != {k: prepared[k] for k in ("intent", "session_origin")}:
        _reject()
    if value["mode"] == "session_never_claimed":
        lifecycle = await validation.lifecycle()
        checked()
        barrier = prepared["barrier"]
        if (
            type(barrier) is not dict
            or set(barrier)
            != {
                "version",
                "intent_digest",
                "coordinator_execution_epoch",
                "start_issued",
                "code",
                "barrier_digest",
            }
            or type(barrier["version"]) is not int
            or barrier["version"] != 1
            or barrier["start_issued"] is not False
            or lifecycle["start_issued"] is not False
            or lifecycle["refusal_barrier"] != barrier
            or barrier["code"] not in PERMANENT_REFUSAL_CODES
            or barrier["intent_digest"] != i["intent_digest"]
            or barrier["coordinator_execution_epoch"] != i["coordinator_execution_epoch"]
            or barrier["barrier_digest"]
            != digest({k: v for k, v in barrier.items() if k != "barrier_digest"})
        ):
            _reject()
        verified["barrier"] = detached(barrier)
    await registry_epoch(
        runtime,
        client,
        manifest=value["manifest"],
        namespace=i["namespace"],
        scope=i["scope"],
        expected=value["registry_execution_epoch"],
        check=checked,
    )
    checked()
    return {"ok": True, "result": verified}


async def _verify_receipt(runtime, client, value, *, info):
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

    from .session_types import SessionKey, SessionRef
    from .temporal_deployment_admission import registry_id
    from .temporal_deployment_execution import _actual, _policy
    from .temporal_session_identity import data_resource_id, selected_source
    from .temporal_session_state import workflow_id

    prepared = value["prepared"]
    if type(prepared) is not dict or set(prepared) != {"session_submission", "receipt"}:
        _reject()
    submission = prepared["session_submission"]
    if type(submission) is not dict or set(submission) != {
        "version",
        "session_key",
        "payload",
        "logical_payload",
        "binding",
    }:
        _reject()
    binding = submission["binding"]
    key = SessionKey.from_dict(submission["session_key"])
    identity = workflow_id(key)
    policy = _policy(runtime, expected=value["manifest"])
    resources = client, client.workflow_service, client.data_converter
    ports = (
        _binding(runtime.validate_release),
        _binding(client.get_workflow_handle),
        _binding(client.workflow_service.describe_namespace),
        _binding(client.data_converter.decode),
    )
    claim = tuple(getattr(info, k, None) for k in _ACTIVITY_FIELDS)

    def checked():
        from temporalio import activity

        if (
            resources != (client, client.workflow_service, client.data_converter)
            or ports
            != (
                _binding(runtime.validate_release),
                _binding(client.get_workflow_handle),
                _binding(client.workflow_service.describe_namespace),
                _binding(client.data_converter.decode),
            )
            or tuple(getattr(info, k, None) for k in _ACTIVITY_FIELDS) != claim
            or info.activity_type != REGISTRY_ACTIVITY
            or value["scope"] != {"workspace": key.workspace, "principal": key.principal}
            or binding["manifest"] != value["manifest"]
            or info.task_queue != binding["task_queue"]
        ):
            _reject()
        try:
            live = activity.info()
        except RuntimeError:
            live = None
        if live is not None and tuple(getattr(live, k, None) for k in _ACTIVITY_FIELDS) != claim:
            _reject()
        _actual(
            client,
            info,
            run_id=registry_id(policy["deployment_id"]),
            epoch=value["registry_execution_epoch"],
        )
        runtime.validate_release(binding["manifest"])

    checked()
    ns = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=client.namespace)
    )
    checked()
    namespace = {"name": client.namespace, "id": ns.namespace_info.id}
    source = selected_source(binding["request"], binding["manifest"])
    if data_resource_id(namespace["id"], source) != key.resource_id:
        _reject()
    await registry_epoch(
        runtime,
        client,
        manifest=value["manifest"],
        namespace=namespace,
        scope=value["scope"],
        expected=value["registry_execution_epoch"],
        check=checked,
    )
    description = await client.get_workflow_handle(identity).describe()
    checked()
    epoch = description.run_id
    if (
        description.id != identity
        or description.namespace != namespace["name"]
        or description.workflow_type != SESSION_WORKFLOW
        or type(epoch) is not str
        or not epoch
        or description.raw_info.first_run_id != epoch
        or description.parent_id is not None
        or description.parent_run_id is not None
    ):
        _reject()
    handle = client.get_workflow_handle(identity, run_id=epoch)
    events = handle.fetch_history_events(page_size=1)
    try:
        first = await anext(events)
    except StopAsyncIteration:
        _reject()
    checked()
    if first.event_id != 1 or not first.HasField("workflow_execution_started_event_attributes"):
        _reject()
    start = first.workflow_execution_started_event_attributes
    if (
        start.original_execution_run_id != epoch
        or start.first_execution_run_id != epoch
        or start.workflow_type.name != SESSION_WORKFLOW
        or start.task_queue.name != description.task_queue
        or start.continued_execution_run_id
        or start.parent_workflow_execution.workflow_id
        or start.parent_workflow_execution.run_id
    ):
        _reject()
    accepted = await client.data_converter.decode(start.input.payloads)
    checked()
    if len(accepted) != 1 or type(accepted[0]) is not dict:
        _reject()
    original = accepted[0]
    if (
        original.get("scope") != value["scope"]
        or original.get("namespace_id") != namespace["id"]
        or original.get("session_namespace") != key.namespace
        or original.get("session_id") != key.session_id
        or original.get("task_queue") != description.task_queue
    ):
        _reject()
    result = await handle.query(
        "view",
        {
            "kind": "deployment_session_receipt",
            "scope": value["scope"],
            "namespace": namespace,
            "coordinator_execution_epoch": epoch,
            "command_id": submission["payload"]["command_id"],
        },
    )
    checked()
    if (
        type(result) is not dict
        or set(result) != {"receipt", "session_ref"}
        or result["receipt"] != prepared["receipt"]
    ):
        _reject()
    ref = SessionRef.from_dict(result["session_ref"])
    if ref.key != key:
        _reject()
    payload, receipt = submission["payload"], prepared["receipt"]
    if (
        receipt["apply_state"] == "applied"
        and payload["kind"] in {"open", "rebind"}
        and ref.definition_digest != digest(binding)
    ):
        _reject()
    if payload["kind"] == "submit" and result["session_ref"] != payload["session_ref"]:
        _reject()
    if (
        payload["kind"] == "rebind"
        and receipt["apply_state"] == "rejected"
        and result["session_ref"] != payload["session_ref"]
    ):
        _reject()
    last = await client.get_workflow_handle(identity).describe()
    checked()
    if last.run_id != epoch or last.raw_info.first_run_id != epoch:
        _reject()
    await registry_epoch(
        runtime,
        client,
        manifest=value["manifest"],
        namespace=namespace,
        scope=value["scope"],
        expected=value["registry_execution_epoch"],
        check=checked,
    )
    checked()
    return {"ok": True, "result": detached(prepared)}


async def _read_session_node(
    runtime, client, policy, scope, run_id, epoch, *, expected_identity=None
):
    """Read a correlated node proposal; no independent Session SDK authority."""
    from . import temporal_deployment_execution as execution

    value, description = await execution._read_admission(
        runtime, client, policy, scope, run_id, epoch, required=True
    )
    response, identity = await execution._start_record(client, policy, value)
    if identity is None or (
        expected_identity is not None and canonical(identity) != expected_identity
    ):
        _reject()
    await execution._start_record_binding(client, value, description, response)
    return detached(value), detached(identity)


class _SessionTreeReading:
    """Invocation-local proposals, usable only after the independent SDK exit.

    This reader has no admission, mutation or proof-returning port. In particular,
    its intermediate Run readings are not a substitute for execution._proof.
    """

    def __init__(self, validation, readonly, policy, proof):
        from .temporal_session_deployment_control import _CheckedClient

        if type(readonly) is not _CheckedClient or readonly.validation is not validation:
            _reject()
        validation._check()
        readonly._full_read()
        i = detached(validation.intent)
        manifest = i["submission"]["manifest"]
        protocol = manifest.get("deployment_admission_protocol", {})
        if (
            type(protocol) is not dict
            or type(protocol.get("version")) is not int
            or protocol["version"] != 4
            or manifest.get("binding_protocol") not in (22, 23)
            or "coding_execution_protocol" not in manifest
            or protocol.get("policy") != policy
            or proof["run_id"] != i["run_id"]
            or proof["scope"] != i["scope"]
            or proof["manifest"] != manifest
            or proof["request"] != i["submission"]["request"]
            or proof["admission"]["lineage"] != []
        ):
            _reject()
        origin = detached(proof["admission"].get("session_origin"))
        validate_origin(origin, intent=i, deployment_id=validation.deployment_id)
        self._outer, self._readonly = validation, readonly
        self._resources = validation.runtime, validation.client, validation.info
        self._intent = canonical(i)
        self._identity = canonical({"intent": i, "session_origin": origin})
        self._policy, self._proof = detached(policy), detached(proof)
        # The outer object's validate() is not evidence. All group reads use a
        # separate pinned verifier; the exit reads the original SDK transport.
        self._validation = SessionControlValidation(
            validation.runtime,
            validation.client,
            detached(validation.value),
            validation.info,
            deployment_id=validation.deployment_id,
        )
        self._client = _CheckedClient(self._validation, _aggregate=True)
        self._check()

    def _check(self):
        runtime, client, info = self._resources
        outer, readonly = self._outer, self._readonly
        outer._check(full=False)
        readonly._full_read()
        self._validation._check(full=False)
        if (
            readonly.validation is not outer
            or outer.runtime is not runtime
            or outer.client is not client
            or outer.info is not info
            or canonical(outer.intent) != self._intent
            or self._validation.runtime is not runtime
            or self._validation.client is not client
            or self._validation.info is not info
            or canonical(self._validation.intent) != self._intent
            or self._client.validation is not self._validation
        ):
            _reject()

    async def _node(self, run_id, epoch):
        self._check()
        runtime, _, _ = self._resources
        value, _ = await _read_session_node(
            runtime,
            self._client,
            self._policy,
            self._proof["scope"],
            run_id,
            epoch,
            expected_identity=self._identity,
        )
        self._check()
        return value

    async def _ancestry(self, original):
        from . import temporal_deployment_execution as execution

        current = original
        for index in range(len(original["admission"]["lineage"]) - 1, -1, -1):
            link = original["admission"]["lineage"][index]
            parent = await self._node(link["parent_run_id"], link["parent_execution_epoch"])
            if (
                parent["request_digest"] != link["parent_request_digest"]
                or parent["manifest_digest"] != link["parent_manifest_digest"]
                or parent["admission"]
                != {**original["admission"], "lineage": original["admission"]["lineage"][:index]}
            ):
                _reject()
            call = execution._child(parent, current["run_id"])
            if (
                call.get("id") != link["call_id"]
                or call.get("command_id") != current["command_id"]
                or call.get("request") != current["request"]
                or call.get("deployment_admission") != current["admission"]
                or call.get("dispatch_started") is not True
                or call.get("deployment_execution_epoch") != current["execution_epoch"]
            ):
                _reject()
            refreshed = await self._node(parent["run_id"], parent["execution_epoch"])
            pinned = execution._child(refreshed, current["run_id"])
            if (
                pinned.get("deployment_execution_epoch") != current["execution_epoch"]
                or pinned.get("request") != current["request"]
                or pinned.get("deployment_admission") != current["admission"]
            ):
                _reject()
            current = refreshed
        if (
            current["run_id"] != self._proof["run_id"]
            or current["execution_epoch"] != self._proof["execution_epoch"]
        ):
            _reject()

    async def _tree(self, proof, seen):
        from . import temporal_deployment_release as release

        self._check()
        if proof["run_id"] in seen or len(seen) >= 4096:
            _reject()
        seen.add(proof["run_id"])
        runtime, _, _ = self._resources
        closure = await release._closure(runtime, self._client, self._policy, proof)
        proof, children = closure["deployment"], []
        for call in proof["children"]:
            if call.get("settled") is not True or call.get("uncertain") is True:
                _reject()
            if call.get("dispatch_started") is not True and call.get("started") is not True:
                if (
                    call.get("deployment_execution_epoch") is not None
                    or call.get("state") not in release.state.TERMINAL
                ):
                    _reject()
                children.append(release._child_entry(call, None))
                continue
            epoch = call.get("deployment_execution_epoch")
            if type(epoch) is not str or not epoch:
                _reject()
            child = await self._node(call["run_id"], epoch)
            if (
                child["request"] != call["request"]
                or child["command_id"] != call["command_id"]
                or child["admission"] != call["deployment_admission"]
            ):
                _reject()
            await self._ancestry(child)
            certificate = await self._tree(child, seen)
            children.append(release._child_entry(call, certificate))
        certificate = closure["seal"]
        if certificate is None:
            _reject()
        release._certificate(certificate, proof)
        if certificate["children"] != children:
            _reject()
        current = await self._node(proof["run_id"], proof["execution_epoch"])
        readback = await release._closure(runtime, self._client, self._policy, current)
        if readback["seal"] != certificate:
            _reject()
        self._check()
        return detached(certificate)

    async def read(self):
        certificate = await self._tree(self._proof, set())
        self._check()
        verified = await self._validation.validate()
        self._check()
        if canonical(verified) != self._identity:
            _reject()
        self._resources[0].validate_release(self._proof["manifest"])
        self._check()
        return certificate

    async def read_descendants(self):
        """Collect original descendant proposals before one independent SDK exit."""
        descendants, pending, seen = [], list(self._proof["children"]), {self._proof["run_id"]}
        while pending:
            child = pending.pop()
            if child.get("dispatch_started") is not True and child.get("started") is not True:
                continue
            child_id, child_epoch = child["run_id"], child.get("deployment_execution_epoch")
            if (
                child_id in seen
                or len(seen) >= 4096
                or type(child_epoch) is not str
                or not child_epoch
            ):
                _reject()
            seen.add(child_id)
            physical = await self._node(child_id, child_epoch)
            await self._ancestry(physical)
            descendants.append(
                await self._client.get_workflow_handle(child_id, run_id=child_epoch).query(
                    "view", {"kind": "session_proof", "scope": self._proof["scope"]}
                )
            )
            self._check()
            pending.extend(physical["children"])
        self._check()
        verified = await self._validation.validate()
        self._check()
        if canonical(verified) != self._identity:
            _reject()
        self._resources[0].validate_release(self._proof["manifest"])
        self._check()
        return detached(descendants)


async def _read_session_tree(validation, readonly, policy, proof):
    """Return a closed certificate only after fresh independent Session facts."""
    return await _SessionTreeReading(validation, readonly, policy, proof).read()


async def _read_session_descendants(validation, readonly, policy, proof):
    """Return fresh descendant proposals only after independent Session facts."""
    return await _SessionTreeReading(validation, readonly, policy, proof).read_descendants()


def source_bindings():
    """Pin executable verifier ports, including in-memory source replacements."""
    from . import temporal_deployment_execution as execution
    from . import temporal_deployment_release as release
    from . import temporal_session_deployment_dto as dto
    from .temporal_session_deployment_control import (
        _CheckedClient,
        _CheckedHandle,
        _CheckedService,
    )

    return tuple(
        _binding(function)
        for function in (
            _reject,
            validate_intent,
            validate_origin,
            registry_epoch,
            verify_registry_request,
            _verify_receipt,
            validate_session_origin,
            execution._read_admission,
            execution._start_record,
            execution._start_record_binding,
            execution._public_start_binding,
            execution._child,
            release._closure,
            release._certificate,
            release._child_entry,
            _SessionTreeReading,
            _SessionTreeReading.__init__,
            _SessionTreeReading._check,
            _SessionTreeReading._node,
            _SessionTreeReading._ancestry,
            _SessionTreeReading._tree,
            _SessionTreeReading.read,
            _SessionTreeReading.read_descendants,
            _read_session_tree,
            _read_session_descendants,
            _read_session_node,
            dto.encode_control_body,
            dto.decode_control_body,
            dto._coded_control_body,
            dto._body_reject,
            _CheckedClient.__init__,
            _CheckedClient._full_read,
            _CheckedClient._after_read,
            _CheckedClient.get_workflow_handle,
            _CheckedClient.namespace.fget,
            _CheckedClient.workflow_service.fget,
            _CheckedClient.data_converter.fget,
            _CheckedService.__init__,
            _CheckedService.describe_namespace,
            _CheckedHandle.__init__,
            _CheckedHandle.query,
            _CheckedHandle.describe,
            _CheckedHandle.fetch_history_events,
            SessionControlValidation.__init__,
            SessionControlValidation._check,
            SessionControlValidation.validate,
            SessionControlValidation.lifecycle,
            SessionControlValidation._start,
            SessionControlValidation._description,
            SessionControlValidation._namespace,
            SessionControlValidation.selector,
        )
    )


async def validate_session_origin(runtime, client, intent, origin, *, _release_boundary=None):
    """Fresh original coordinator SDK read for an independently verified Run edge.

    This read does not claim that the calling Activity belongs to the Session.
    Its caller retains actual Run/Parent identity and admission responsibility.
    The private boundary is supplied only by a warm Coding read set bracketed
    by independent full checks for that same fixed Manifest.
    """
    from .temporal_session_deployment_control import _CheckedClient

    # A verifier must read the original SDK transport, not a transport that
    # recursively verifies the same Session after each of its own seven reads.
    # Keep an independent verifier; the wrapper's validate() is never evidence.
    outer, transport, info, intent_digest = None, client, None, None
    if type(client) is _CheckedClient and type(client.validation) is SessionControlValidation:
        candidate = client.validation
        candidate._check()
        if candidate.runtime is runtime and digest(candidate.intent) == digest(intent):
            outer, transport, info = candidate, candidate.client, candidate.info
            intent_digest = digest(candidate.intent)

    manifest = intent["submission"]["manifest"]
    policy = manifest.get("deployment_admission_protocol", {}).get("policy", {})
    protocol = manifest.get("deployment_admission_protocol", {})
    full_release = True
    if (
        type(_release_boundary) is dict
        and type(protocol) is dict
        and type(protocol.get("version")) is int
        and protocol["version"] == 4
        and manifest.get("binding_protocol") in (22, 23)
        and "coding_execution_protocol" in manifest
    ):
        boundary = canonical(_release_boundary)
        full_release = not (
            canonical(intent["binding"]["manifest"]) == boundary and canonical(manifest) == boundary
        )
    wire = {
        "version": 1,
        "mode": "observe",
        "intent": intent,
        **{
            k: intent[k]
            for k in (
                "scope",
                "namespace",
                "coordinator_id",
                "coordinator_execution_epoch",
            )
        },
    }
    checks = {} if full_release else {"_full_release": False}
    validation = SessionControlValidation(
        runtime,
        transport,
        wire,
        info,
        deployment_id=policy.get("deployment_id"),
        _coordinator_activity=False,
        **checks,
    )
    result = await validation.validate(**checks)
    if outer is not None:
        outer._check()
        if (
            client.validation is not outer
            or outer.client is not transport
            or outer.info is not info
            or outer.runtime is not runtime
            or digest(outer.intent) != intent_digest
        ):
            _reject()
    if result["session_origin"] != origin:
        _reject()
    return result
