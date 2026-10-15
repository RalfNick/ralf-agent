"""Closed read-only Session origins for the original Model and Context Activity."""

from . import temporal_deployment_execution as execution
from . import temporal_session_deployment_verification as verification
from .errors import DefinitionMismatch
from .task_controls import _binding
from .temporal_bindings import _plain_binding_inputs
from .temporal_state import CONTEXT_ACTIVITY, MODEL_ACTIVITY, detached
from .types import canonical, digest


def _reject():
    raise DefinitionMismatch("Original Session Activity reading changed")


class _MissingPin(Exception):
    """An unpinned edge requires the original independent admission path."""


class _ActivityReading:
    def __init__(self, runtime, client, policy, request, info):
        self.runtime, self.client, self.info = runtime, client, info
        self.request, self.policy = detached(request), detached(policy)
        self._request_digest, self._policy_digest = digest(self.request), digest(self.policy)
        self._policy_resource = getattr(runtime, "_deployment_admission_policy_pin", None)
        self._resources = runtime, client, client.workflow_service, client.data_converter, info
        self._claim = tuple(getattr(info, name, None) for name in verification._ACTIVITY_FIELDS)
        self._source_function, self._sources = _binding(source_bindings), source_bindings()
        self._ports = (
            (runtime, "validate_release"),
            (client, "get_workflow_handle"),
            (client.workflow_service, "describe_namespace"),
            (client.data_converter, "decode"),
            (self, "_check"),
            (self, "_node"),
            (self, "_ancestry"),
            (self, "read"),
        )
        self._bindings = tuple(_binding(getattr(owner, name)) for owner, name in self._ports)
        self._identity = None
        self._proposal = None
        self.readonly = _ReadOnlyClient(self)
        self._readonly = self.readonly
        self._service = self.readonly._service
        self._ports += (
            (self.readonly, "get_workflow_handle"),
            (self.readonly, "_check"),
            (self.readonly, "_checker"),
            (self.readonly, "start_workflow"),
            (self._service, "describe_namespace"),
        )
        self._bindings = tuple(_binding(getattr(owner, name)) for owner, name in self._ports)
        self._handle_pins = []
        self._check()

    def _check(self):
        runtime, client, service, converter, info = self._resources
        if (
            self.runtime is not runtime
            or self.client is not client
            or self.info is not info
            or client.workflow_service is not service
            or client.data_converter is not converter
            or self.readonly is not self._readonly
            or type(self.readonly) is not _ReadOnlyClient
            or self.readonly._client is not client
            or self.readonly._reading is not self
            or self.readonly._service is not self._service
            or type(self._service) is not _ReadOnlyService
            or self._service._client is not self.readonly
            or self._source_function != _binding(source_bindings)
            or self._sources != source_bindings()
            or self._request_digest != digest(self.request)
            or self._policy_digest != digest(self.policy)
            or (self._proposal is not None and canonical(self._proposal) != self._identity)
            or self._bindings != tuple(_binding(getattr(o, n)) for o, n in self._ports)
            or self._claim
            != tuple(getattr(info, name, None) for name in verification._ACTIVITY_FIELDS)
            or getattr(runtime, "_deployment_admission_policy_pin", None)
            is not self._policy_resource
            or getattr(runtime, "_deployment_admission_policy", None) is not self._policy_resource
            or getattr(runtime, "_deployment_admission_identity", None) != self.policy
            or self._policy_resource is None
            or self._policy_resource.identity != self.policy
        ):
            _reject()
        for handle, raw, ports in self._handle_pins:
            if (
                type(handle) is not _ReadOnlyHandle
                or handle._client is not self.readonly
                or handle._handle is not raw
                or ports
                != tuple(
                    _binding(getattr(owner, name))
                    for owner, name in (
                        (handle, "_check"),
                        (handle, "query"),
                        (handle, "describe"),
                        (handle, "fetch_history_events"),
                        (handle, "execute_update"),
                        (raw, "query"),
                        (raw, "describe"),
                        (raw, "fetch_history_events"),
                    )
                )
            ):
                _reject()
        execution._actual(client, info, run_id=self._claim[0], epoch=self._claim[1])
        from temporalio import activity

        try:
            current = activity.info()
        except RuntimeError:
            current = None
        if current is not None and self._claim != tuple(
            getattr(current, name, None) for name in verification._ACTIVITY_FIELDS
        ):
            _reject()

    async def _node(self, run_id, epoch):
        checked = self._check
        checked()
        value, identity = await verification._read_session_node(
            self.runtime,
            self.readonly,
            self.policy,
            self.request["scope"],
            run_id,
            epoch,
            expected_identity=self._identity,
        )
        checked()
        if self._identity is None:
            self._identity = canonical(identity)
            self._proposal = detached(identity)
        elif self._identity != canonical(identity):
            _reject()
        return value

    async def _ancestry(self, original):
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
            ):
                _reject()
            if call.get("deployment_execution_epoch") is None:
                raise _MissingPin()
            if call["deployment_execution_epoch"] != current["execution_epoch"]:
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
        return current

    async def read(self):
        checked = self._check
        try:
            checked()
            proof = await self._node(self.info.workflow_id, self.info.workflow_run_id)
            body = execution._activity_body(self.request)
            original = body.get("original_request", body)
            for payload in (self.request, body, original):
                if (
                    "deployment_admission" in payload
                    and payload["deployment_admission"] != proof["admission"]
                ):
                    _reject()
            root = await self._ancestry(proof)
            held = await execution._held(self.readonly, self.policy, root, bind=False)
            checked()
            if proof["admission_receipt"]["root"] != held:
                _reject()
            # Registry bytes remain proposals until this new verifier reads the
            # raw original transport. No outer object's validate() is authority.
            intent = self._proposal["intent"]
            value = {
                "version": 1,
                "mode": "observe",
                "intent": intent,
                **{
                    name: intent[name]
                    for name in (
                        "scope",
                        "namespace",
                        "coordinator_id",
                        "coordinator_execution_epoch",
                    )
                },
            }
            validation = verification.SessionControlValidation(
                self.runtime,
                self.client,
                value,
                self.info,
                deployment_id=self.policy["deployment_id"],
                _coordinator_activity=False,
            )
            checked()
            verified = await validation.validate()
            checked()
            if canonical(verified) != self._identity:
                _reject()
            if execution._policy(self.runtime, expected=proof["manifest"]) != self.policy:
                _reject()
            checked()
            return detached(proof)
        except _MissingPin:
            checked()
            return None
        finally:
            self._identity = None
            self._proposal = None


class _ReadOnlyClient:
    def __init__(self, reading):
        self._reading, self._client = reading, reading.client
        self._checker, self._checker_pin = reading._check, _binding(reading._check)
        self._service = _ReadOnlyService(self)

    def _check(self):
        if self._reading.client is not self._client or _binding(self._checker) != self._checker_pin:
            _reject()
        self._checker()

    @property
    def namespace(self):
        self._check()
        return self._client.namespace

    @property
    def workflow_service(self):
        self._check()
        return self._service

    @property
    def data_converter(self):
        self._check()
        return self._client.data_converter

    def get_workflow_handle(self, *args, **kwargs):
        self._check()
        handle = self._client.get_workflow_handle(*args, **kwargs)
        self._check()
        wrapped = _ReadOnlyHandle(self, handle)
        ports = tuple(
            _binding(getattr(owner, name))
            for owner, name in (
                (wrapped, "_check"),
                (wrapped, "query"),
                (wrapped, "describe"),
                (wrapped, "fetch_history_events"),
                (wrapped, "execute_update"),
                (handle, "query"),
                (handle, "describe"),
                (handle, "fetch_history_events"),
            )
        )
        self._reading._handle_pins.append((wrapped, handle, ports))
        self._checker()
        return wrapped

    async def start_workflow(self, *args, **kwargs):
        _reject()


class _ReadOnlyService:
    def __init__(self, client):
        self._client = client

    async def describe_namespace(self, *args, **kwargs):
        checked = self._client._checker
        checked()
        try:
            return await self._client._client.workflow_service.describe_namespace(*args, **kwargs)
        finally:
            checked()


class _ReadOnlyHandle:
    def __init__(self, client, handle):
        self._client, self._handle = client, handle
        self._methods = tuple(
            _binding(getattr(handle, name))
            for name in ("query", "describe", "fetch_history_events")
        )

    def _check(self):
        self._client._checker()
        if self._methods != tuple(
            _binding(getattr(self._handle, name))
            for name in ("query", "describe", "fetch_history_events")
        ):
            _reject()

    async def query(self, *args, **kwargs):
        checked = self._client._checker
        checked()
        try:
            return await self._handle.query(*args, **kwargs)
        finally:
            checked()

    async def describe(self, *args, **kwargs):
        checked = self._client._checker
        checked()
        try:
            return await self._handle.describe(*args, **kwargs)
        finally:
            checked()

    def fetch_history_events(self, *args, **kwargs):
        async def events():
            checked = self._client._checker
            checked()
            source = self._handle.fetch_history_events(*args, **kwargs)
            while True:
                checked()
                try:
                    item = await anext(source)
                except StopAsyncIteration:
                    return
                finally:
                    checked()
                yield item

        return events()

    async def execute_update(self, *args, **kwargs):
        _reject()


def source_bindings():
    """Capture original implementations before the first proposal SDK await."""
    return (
        tuple(
            _binding(function)
            for function in (
                _reject,
                _MissingPin,
                read_activity,
                source_bindings,
                _plain_binding_inputs,
                _ActivityReading,
                _ActivityReading.__init__,
                _ActivityReading._check,
                _ActivityReading._node,
                _ActivityReading._ancestry,
                _ActivityReading.read,
                _ReadOnlyClient,
                _ReadOnlyClient.__init__,
                _ReadOnlyClient._check,
                _ReadOnlyClient.namespace.fget,
                _ReadOnlyClient.workflow_service.fget,
                _ReadOnlyClient.data_converter.fget,
                _ReadOnlyClient.get_workflow_handle,
                _ReadOnlyClient.start_workflow,
                _ReadOnlyService,
                _ReadOnlyService.__init__,
                _ReadOnlyService.describe_namespace,
                _ReadOnlyHandle,
                _ReadOnlyHandle.__init__,
                _ReadOnlyHandle._check,
                _ReadOnlyHandle.query,
                _ReadOnlyHandle.describe,
                _ReadOnlyHandle.fetch_history_events,
                _ReadOnlyHandle.execute_update,
                execution._actual,
                execution._policy,
                execution.DeploymentAdmissionPolicy.identity.fget,
                execution._namespace,
                execution._read_admission,
                execution._start_record,
                execution._start_record_binding,
                execution._held,
                execution._child,
                execution._activity_body,
                execution._metadata,
                execution._receipt,
                execution._sealed,
                execution._exact,
                execution._text,
                verification._read_session_node,
                verification.SessionControlValidation,
                verification.SessionControlValidation.__init__,
                verification.SessionControlValidation._check,
                verification.SessionControlValidation.validate,
                verification.SessionControlValidation._namespace,
                verification.SessionControlValidation._description,
                verification.SessionControlValidation._start,
                verification.SessionControlValidation.selector,
                verification.source_bindings,
            )
        )
        + verification.source_bindings()
        + (
            verification._ACTIVITY_FIELDS,
            MODEL_ACTIVITY,
            CONTEXT_ACTIVITY,
        )
    )


async def read_activity(runtime, client, policy, request, info):
    """Return a complete original proof, or defer ineligible/unpinned calls."""
    body = execution._activity_body(request)
    original = body.get("original_request", body)
    manifest = original.get("runtime_manifest")
    if (
        info is None
        or getattr(info, "activity_type", None) not in {MODEL_ACTIVITY, CONTEXT_ACTIVITY}
        or type(manifest) is not dict
        or not _plain_binding_inputs(manifest, {})
    ):
        return None
    protocol = manifest.get("deployment_admission_protocol")
    if (
        type(protocol) is not dict
        or type(protocol.get("version")) is not int
        or protocol["version"] != 4
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (22, 23)
        or "coding_execution_protocol" not in manifest
    ):
        return None
    if execution._policy(runtime, expected=manifest) != policy:
        _reject()
    return await _ActivityReading(runtime, client, policy, request, info).read()
