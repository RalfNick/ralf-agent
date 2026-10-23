"""SDK routing of original deployment/Coding evidence; no business authority."""

import asyncio
import json
from dataclasses import asdict

from .errors import CloseIncomplete, DefinitionMismatch, RalfError
from .temporal_deployment_admission import registry_id
from .temporal_state import COMMAND_REGISTRY_NAME, detached
from .types import canonical, digest, submission_request

STOP_ACTIVITY = "ralf.temporal.deployment-coding-stop.v3"
_STOP_MARKER = object()
_CANDIDATE_FIELDS = {
    "version",
    "identity",
    "action_id",
    "tool_request_digest",
    "owner",
    "owner_stop_proof",
    "runner",
    "namespace",
    "execution_epoch",
}


def _reject():
    raise DefinitionMismatch("Original deployment Coding bridge identity changed")


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        _reject()


def _selected(manifest):
    protocol = manifest.get("deployment_admission_protocol", {})
    return (
        type(protocol) is dict
        and type(protocol.get("version")) is int
        and (
            protocol["version"] == 3
            or protocol["version"] == 4
            and "coding_execution_protocol" in manifest
        )
        and manifest.get("binding_protocol") in (22, 23)
        and "coding_execution_protocol" in manifest
    )


def logical_request(spec, input, *, budget=32, session_id=None):
    """Decode only caller structure; first-acceptance authorization comes later."""
    from .binding_definitions import AgentDefinition, BoundDefinition, decode_definition

    request = submission_request(spec, input, budget=budget, session_id=session_id)
    if request["definition"]["kind"] in {"bound_agent", "bound_definition"}:
        wrapper = decode_definition(request["definition"])
        if isinstance(wrapper, AgentDefinition):
            definition, bindings = wrapper.spec, {"agent": wrapper.bindings.to_dict()}
        elif isinstance(wrapper, BoundDefinition):
            definition, bindings = (
                wrapper.definition,
                {path: value.to_dict() for path, value in wrapper.agent_bindings.items()},
            )
        else:
            _reject()
        request = submission_request(definition, input, budget=budget, session_id=session_id)
        request["agent_bindings"] = bindings
    return json.loads(canonical(request))


class _Registry:
    def __init__(self, client, scope, manifest):
        if not _selected(manifest):
            _reject()
        self.client, self.scope, self.manifest = client, detached(scope), detached(manifest)
        from .governance import DeploymentAdmissionPolicy

        protocol = self.manifest["deployment_admission_protocol"]
        self.policy = DeploymentAdmissionPolicy.from_identity(protocol["policy"]).identity
        self.id = registry_id(self.policy["deployment_id"])
        if protocol["registry_id"] != self.id:
            _reject()
        self.handle = client.get_workflow_handle(self.id)
        self.namespace = None
        self.execution_epoch = None
        self.configuration_version = None

    async def _authority(self):
        from temporalio.client import WorkflowExecutionStatus

        from .temporal_deployment_execution import _namespace
        from .temporal_session_activities import namespace_id

        namespace = self.namespace
        if namespace is None:
            name = self.client.namespace
            namespace = {"name": name, "id": await namespace_id(self.client)}
            self.namespace = detached(namespace)
        await _namespace(self.client, namespace)
        description = await self.handle.describe()
        if (
            description.id != self.id
            or description.namespace != namespace["name"]
            or description.workflow_type != COMMAND_REGISTRY_NAME
            or description.status is not WorkflowExecutionStatus.RUNNING
            or type(description.run_id) is not str
            or not description.run_id
            or description.run_id
            != getattr(getattr(description, "raw_info", None), "first_run_id", None)
            or self.execution_epoch is not None
            and description.run_id != self.execution_epoch
        ):
            _reject()
        self.execution_epoch = description.run_id
        self.handle = self.client.get_workflow_handle(self.id, run_id=description.run_id)
        configuration = await self.handle.query(
            "view",
            {
                "kind": "deployment_configuration",
                "scope": self.scope,
                "admission_policy": self.policy,
                "namespace": namespace,
            },
        )
        allowed = (3, 4) if self.manifest["deployment_admission_protocol"]["version"] == 3 else (4,)
        if (
            type(configuration) is not dict
            or type(configuration.get("version")) is not int
            or configuration["version"] not in allowed
            or configuration
            != {
                "version": configuration["version"],
                "registry_id": self.id,
                "policy": self.policy,
                "namespace": namespace,
            }
        ):
            _reject()
        self.configuration_version = configuration["version"]
        await _namespace(self.client, namespace)
        self.namespace = detached(namespace)
        return namespace

    async def _initialize_owned_close(self, task_queue):
        from .temporal import _sdk
        from .temporal_deployment_execution import _namespace

        if type(task_queue) is not str or not task_queue.strip():
            _reject()
        sdk = _sdk()
        try:
            await self._authority()
        except sdk[6] as exc:
            if exc.status != sdk[7].NOT_FOUND or self.execution_epoch is not None:
                raise
            await _namespace(self.client, self.namespace)
            try:
                await self.client.start_workflow(
                    COMMAND_REGISTRY_NAME,
                    {
                        "deployment_admission": {
                            "version": self.manifest["deployment_admission_protocol"]["version"],
                            "policy": self.policy,
                            "namespace": self.namespace,
                        }
                    },
                    id=self.id,
                    task_queue=task_queue,
                    id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                    id_conflict_policy=sdk[2].FAIL,
                    retry_policy=None,
                )
            except sdk[5]:
                pass
            await self._authority()

    def _payload(self, value, namespace):
        value = detached(value)
        if value.get("scope") != self.scope:
            _reject()
        if "namespace" in value and value["namespace"] != namespace:
            _reject()
        if "admission_policy" in value and value["admission_policy"] != self.policy:
            _reject()
        return {
            **value,
            "scope": self.scope,
            "admission_policy": self.policy,
            "namespace": namespace,
        }

    async def _result(self, value, namespace):
        from .temporal import _raise_code
        from .temporal_deployment_execution import _namespace

        value = detached(value)
        await _namespace(self.client, namespace)
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        return value

    async def query(self, name, value):
        if name != "view" or value.get("kind") not in {
            "coding_composition_candidates",
            "coding_composition_admission",
        }:
            _reject()
        value = detached(value)
        namespace = await self._authority()
        return await self._result(
            await self.handle.query(name, self._payload(value, namespace)), namespace
        )

    async def execute_update(self, name, value, **options):
        if name not in {
            "admit_coding_composition_submission",
            "close_coding_composition_submissions",
        }:
            _reject()
        value = detached(value)
        namespace = await self._authority()
        routed = (
            "close_deployment_coding_submissions"
            if name == "close_coding_composition_submissions"
            else name
        )
        return await self._result(
            await self.handle.execute_update(routed, self._payload(value, namespace), **options),
            namespace,
        )


def registry(client, scope, manifest):
    """Return a lazy read-handshaken proxy; never start a second Registry."""
    return _Registry(client, scope, manifest)


class _ReadOnlyHandle:
    def __init__(self, handle):
        self.handle = handle

    async def query(self, *args, **kwargs):
        return await self.handle.query(*args, **kwargs)

    async def describe(self):
        return await self.handle.describe()

    def fetch_history_events(self, *args, **kwargs):
        return self.handle.fetch_history_events(*args, **kwargs)

    async def execute_update(self, *args, **kwargs):
        _reject()

    async def signal(self, *args, **kwargs):
        _reject()


class _ReadOnlyClient:
    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def get_workflow_handle(self, *args, **kwargs):
        return _ReadOnlyHandle(self.client.get_workflow_handle(*args, **kwargs))

    async def start_workflow(self, *args, **kwargs):
        _reject()


async def _original(runtime, client, value, info):
    from . import temporal_deployment_execution as execution

    value = detached(value)
    runtime.validate_release(value["runtime_manifest"])
    if not _selected(value["runtime_manifest"]):
        _reject()
    policy = execution._policy(runtime)
    execution._actual(client, info, run_id=value["run_id"], epoch=value["execution_epoch"])
    proof = await execution._proof(
        runtime, client, policy, value["scope"], value["run_id"], value["execution_epoch"]
    )
    if (
        proof["manifest"] != value["runtime_manifest"]
        or proof["request"] != value["request"]
        or "command_id" in value
        and value["command_id"] != proof["command_id"]
        or "deployment_admission" in value
        and value["deployment_admission"] != proof["admission"]
    ):
        _reject()
    root = await execution._ancestry(runtime, client, policy, proof)
    await execution._namespace(client, root["namespace"])
    return proof, root


async def admission(runtime, client, value, info):
    """Sideband admission from the same root, including native and descendants."""
    from . import temporal_coding_composition_control as composition
    from . import temporal_deployment_execution as execution

    value = detached(value)
    proof, root = await _original(runtime, client, value, info)
    namespace = root["namespace"]
    expected = {
        "command_id": root["command_id"],
        "run_id": root["run_id"],
        "request_digest": digest(root["request"]),
        "manifest_digest": digest(root["manifest"]),
    }
    handle = registry(client, root["scope"], root["manifest"])
    receipt = await handle.execute_update(
        "admit_coding_composition_submission",
        {
            "scope": root["scope"],
            **expected,
            "execution_epoch": root["execution_epoch"],
            "namespace": namespace,
        },
        id="ralf-deployment-coding-admission:"
        + digest([root["scope"], expected, root["execution_epoch"], namespace]),
    )
    composition._validate_admission(receipt, expected, root["execution_epoch"], namespace)
    observed = await handle.query(
        "view", {"scope": root["scope"], "kind": "coding_composition_admission", **expected}
    )
    composition._validate_admission(observed, expected, root["execution_epoch"], namespace)
    admitted = observed["admitted"]
    if "coding_parent" in proof["request"]:
        original = await composition._proof(
            client,
            proof["scope"],
            proof["run_id"],
            proof["execution_epoch"],
            proof["manifest"],
            namespace,
            request=proof["request"],
        )
        chain, permitted = await composition._ancestry_admission(
            client, original, proof["manifest"], namespace
        )
        coding_root = chain[-1][0] if chain else original
        if any(
            coding_root[name] != root[name]
            for name in ("scope", "run_id", "execution_epoch", "request", "manifest", "namespace")
        ):
            _reject()
        admitted = admitted and permitted
    runtime.validate_release(value["runtime_manifest"])
    execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
    await execution._namespace(client, namespace)
    return {
        "namespace": detached(namespace),
        "execution_epoch": proof["execution_epoch"],
        "admitted": admitted,
    }


async def root_admission(runtime, client, value, info):
    from .temporal_coding_composition_control import _root_kind

    if value["runtime_manifest"].get("binding_protocol") != 23 or not _root_kind(
        value["runtime_manifest"], value["request"]["definition"]["kind"]
    ):
        _reject()
    return await admission(runtime, client, value, info)


async def grant_allowed(runtime, client, tool_request, info, validation=None):
    """Read original close admission before a new native phase grant only."""
    from . import temporal_coding_composition_control as composition
    from . import temporal_deployment_execution as execution

    if validation is not None:
        from .temporal_deployment_coding_validation import CodingValidation

        if (
            type(validation) is not CodingValidation
            or validation._runtime is not runtime
            or validation._client is not client
            or validation._info is not info
            or canonical(validation._request) != canonical(tool_request)
        ):
            _reject()
        return await validation.permission()

    request = detached(tool_request)
    client = _ReadOnlyClient(client)
    manifest = request["runtime_manifest"]
    runtime.validate_release(manifest)
    if not _selected(manifest):
        _reject()
    execution._actual(client, info, run_id=request["run_id"], epoch=request["execution_epoch"])
    proof = await execution._proof(
        runtime,
        client,
        execution._policy(runtime),
        request["scope"],
        request["run_id"],
        request["execution_epoch"],
        required=True,
    )
    if proof["manifest"] != manifest:
        _reject()
    root = await execution._ancestry(runtime, client, execution._policy(runtime), proof)
    expected = {
        "command_id": root["command_id"],
        "run_id": root["run_id"],
        "request_digest": digest(root["request"]),
        "manifest_digest": digest(root["manifest"]),
    }
    receipt = await registry(client, root["scope"], root["manifest"]).query(
        "view",
        {
            "kind": "coding_composition_admission",
            "scope": root["scope"],
            **expected,
        },
    )
    composition._validate_admission(receipt, expected, root["execution_epoch"], root["namespace"])
    admitted = receipt["admitted"]
    if manifest.get("binding_protocol") == 23:
        original = await composition._proof(
            client,
            proof["scope"],
            proof["run_id"],
            proof["execution_epoch"],
            manifest,
            root["namespace"],
            request=proof["request"],
        )
        chain, allowed = await composition._ancestry_admission(
            client, original, manifest, root["namespace"]
        )
        coding_root = chain[-1][0] if chain else original
        if any(
            coding_root[name] != root[name]
            for name in ("scope", "run_id", "execution_epoch", "request", "manifest", "namespace")
        ):
            _reject()
        admitted = admitted and allowed
    await execution._namespace(client, root["namespace"])
    execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
    runtime.validate_release(manifest)
    return admitted


async def sealed(runtime, client, original_coding_proof, namespace):
    """Observe a genuine original seal without any native or History mutation."""
    from . import temporal_coding_composition_control as composition
    from . import temporal_deployment_execution as execution
    from . import temporal_deployment_release as release

    original, namespace = detached(original_coding_proof), detached(namespace)
    client = _ReadOnlyClient(client)
    manifest = original["manifest"]
    runtime.validate_release(manifest)
    if not _selected(manifest):
        _reject()
    composition._validate_proof(
        original,
        scope=original["scope"],
        run_id=original["run_id"],
        epoch=original["execution_epoch"],
        manifest=manifest,
        namespace=namespace,
    )
    await execution._namespace(client, namespace)
    proof = await execution._proof(
        runtime,
        client,
        execution._policy(runtime),
        original["scope"],
        original["run_id"],
        original["execution_epoch"],
        required=True,
    )
    await execution._ancestry(runtime, client, execution._policy(runtime), proof)
    if any(
        original[name] != proof[name]
        for name in (
            "scope",
            "run_id",
            "execution_epoch",
            "original_execution_epoch",
            "namespace",
            "request",
            "request_digest",
            "manifest",
        )
    ):
        _reject()
    raw = detached(
        await client.get_workflow_handle(proof["run_id"], run_id=proof["execution_epoch"]).query(
            "view", {"scope": proof["scope"], "kind": "deployment_closure"}
        )
    )
    _exact(raw, {"version", "deployment", "ready", "reasons", "calls", "seal"})
    if raw["deployment"] != proof:
        _reject()
    await execution._namespace(client, namespace)
    if raw["seal"] is None:
        return False
    closure = await release._closure(runtime, client, execution._policy(runtime), proof)
    release._certificate(closure["seal"], proof)
    if closure["seal"] != raw["seal"]:
        _reject()
    runtime.validate_release(manifest)
    await execution._namespace(client, namespace)
    return True


async def control(runtime, client, value, info):
    from . import temporal_coding_composition_control as composition
    from . import temporal_deployment_execution as execution

    value = detached(value)
    runtime.validate_release(value["runtime_manifest"])
    if not _selected(value["runtime_manifest"]):
        _reject()
    proof = await execution.validate_activity(runtime, client, value, info)
    if proof is None or value.get("parent_id") != proof["run_id"]:
        _reject()
    call = execution._child(proof, value["child"].get("run_id"))
    if any(
        call.get(field) != value["child"].get(field)
        for field in ("id", "command_id", "run_id", "request", "deployment_admission")
    ):
        _reject()
    result = await composition.control(runtime, client, value, info)
    runtime.validate_release(value["runtime_manifest"])
    await execution._namespace(client, proof["namespace"])
    return detached(result)


async def close(runtime, *, client, scope, task_queue=None):
    """Retain original clients/resources until original native/tree close succeeds."""
    from . import temporal_coding_composition_control as composition
    from . import temporal_coding_runtime as native
    from . import temporal_deployment_execution as execution

    manifest, scoped = runtime.orchestration_release, asdict(scope)
    runtime.validate_release(manifest)
    if not _selected(manifest) or client is None:
        _reject()
    manifest = json.loads(canonical(manifest))
    runtime._tool_execution_closing = True
    handle = registry(client, scoped, manifest)
    if task_queue is not None:
        await handle._initialize_owned_close(task_queue)
    response = await handle.execute_update(
        "close_coding_composition_submissions",
        {"scope": scoped, "manifest_digest": digest(manifest)},
    )
    _exact(response, {"manifest_digest", "close_requested", "candidates"})
    if (
        response["manifest_digest"] != digest(manifest)
        or response["close_requested"] is not True
        or type(response["candidates"]) is not list
    ):
        _reject()
    from .temporal_session_activities import namespace_id

    namespace = {"name": client.namespace, "id": await namespace_id(client)}
    await execution._namespace(client, namespace)
    parents, obligations = [], []
    for candidate in response["candidates"]:
        try:
            _exact(
                candidate,
                {
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "close_requested",
                    "execution_epoch",
                    "namespace",
                },
            )
            if (
                candidate["manifest_digest"] != digest(manifest)
                or candidate["close_requested"] is not True
                or candidate["namespace"] not in (None, namespace)
            ):
                _reject()
            epoch = candidate["execution_epoch"]
            if epoch is None:
                epoch = (await client.get_workflow_handle(candidate["run_id"]).describe()).run_id
            proof = await execution._proof(
                runtime, client, execution._policy(runtime), scoped, candidate["run_id"], epoch
            )
            if (
                proof["command_id"] != candidate["command_id"]
                or digest(proof["request"]) != candidate["request_digest"]
                or proof["manifest"] != manifest
                or proof["admission"]["root"]["run_id"] != proof["run_id"]
            ):
                _reject()
            closure = detached(
                await client.get_workflow_handle(proof["run_id"], run_id=epoch).query(
                    "view", {"kind": "deployment_closure", "scope": scoped}
                )
            )
            _exact(closure, {"version", "deployment", "ready", "reasons", "calls", "seal"})
            if any(
                closure["deployment"].get(name) != proof.get(name)
                for name in (
                    "scope",
                    "run_id",
                    "command_id",
                    "namespace",
                    "execution_epoch",
                    "request",
                    "manifest",
                    "admission",
                )
            ):
                _reject()
            if closure["seal"] is not None:
                from .temporal_deployment_release import _certificate

                _certificate(closure["seal"], proof)
            if proof["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}:
                parents.append(candidate)
            elif closure["seal"] is None:
                await composition._command(client, proof, "cancel", owner_id=proof["run_id"])
        except Exception as exc:
            obligations.append(
                {
                    "root": candidate.get("run_id"),
                    "code": getattr(exc, "code", "original_root_unavailable"),
                }
            )
    try:
        if manifest.get("binding_protocol") == 23:
            await composition.close(runtime, client=client, scope=scope, candidates=parents)
        else:
            await native.close(runtime, client=client, scope=scope)
    except Exception as exc:
        obligations.append(
            {
                "phase": "original_coding_close",
                "code": getattr(exc, "code", "physical_close_incomplete"),
            }
        )
    runtime.validate_release(manifest)
    await execution._namespace(client, namespace)
    if obligations:
        raise CloseIncomplete({"deployment_coding": obligations})


async def wait_retirement(runtime, *, client, scope, wait_timeout=30):
    """Keep the owned poller for ready original roots; never release on their behalf."""
    from . import temporal_deployment_execution as execution
    from . import temporal_deployment_release as release
    from .temporal_bindings import request_release_digest

    manifest, scoped = json.loads(canonical(runtime.orchestration_release)), asdict(scope)
    runtime.validate_release(manifest)
    handle = registry(client, scoped, manifest)
    policy = execution._policy(runtime)

    async def original(candidate):
        _exact(
            candidate,
            {
                "command_id",
                "run_id",
                "request_digest",
                "manifest_digest",
                "close_requested",
                "execution_epoch",
                "namespace",
            },
        )
        if candidate["close_requested"] is not True or candidate["manifest_digest"] != digest(
            manifest
        ):
            _reject()
        epoch = candidate["execution_epoch"]
        if epoch is None:
            # A lost first-acceptance response does not authorize a replacement.
            epoch = (await client.get_workflow_handle(candidate["run_id"]).describe()).run_id
        proof = await execution._proof(
            runtime, client, policy, scoped, candidate["run_id"], epoch, required=True
        )
        if (
            proof["command_id"] != candidate["command_id"]
            or digest(proof["request"]) != candidate["request_digest"]
            or canonical(proof["manifest"]) != canonical(manifest)
            or candidate["namespace"] not in (None, proof["namespace"])
            or proof["admission_receipt"]["root"]["run_id"] != proof["run_id"]
        ):
            _reject()
        return proof

    async def closure(proof):
        value = detached(
            await client.get_workflow_handle(
                proof["run_id"], run_id=proof["execution_epoch"]
            ).query("view", {"kind": "deployment_closure", "scope": scoped})
        )
        _exact(value, {"version", "deployment", "ready", "reasons", "calls", "seal"})
        if (
            type(value["version"]) is not int
            or value["version"] != 1
            or type(value["ready"]) is not bool
            or type(value["reasons"]) is not list
            or type(value["calls"]) is not dict
        ):
            _reject()
        execution._sealed(value["deployment"])
        if any(
            value["deployment"].get(name) != proof.get(name)
            for name in execution._PROOF_FIELDS - {"children", "proof_digest"}
        ):
            _reject()
        await execution._namespace(client, proof["namespace"])
        runtime.validate_release(manifest)
        return value

    async def unknown(proof, value, seen=None):
        # A not-ready projection also covers queued SDK completions. Only
        # positive original-History unknown debt permits physical-only close.
        seen = set() if seen is None else seen
        if proof["run_id"] in seen or len(seen) >= 4096:
            _reject()
        seen.add(proof["run_id"])
        diagnostics = detached(
            await client.get_workflow_handle(
                proof["run_id"], run_id=proof["execution_epoch"]
            ).query("view", {"kind": "diagnostics", "scope": scoped})
        )
        if type(diagnostics) is not dict:
            _reject()
        snapshot, budget = diagnostics.get("snapshot"), diagnostics.get("budget")
        if (
            canonical(diagnostics.get("manifest")) != canonical(proof["manifest"])
            or diagnostics.get("release_digest")
            != request_release_digest(proof["request"], proof["manifest"])
            or type(snapshot) is not dict
            or snapshot.get("run_id") != proof["run_id"]
            or type(snapshot.get("state_revision")) is not int
            or snapshot["state_revision"] < 0
            or type(snapshot.get("actions")) is not list
            or any(type(action) is not dict for action in snapshot["actions"])
            or type(budget) is not dict
            or type(budget.get("unknown")) is not int
            or budget["unknown"] < 0
        ):
            _reject()
        await execution._namespace(client, proof["namespace"])
        runtime.validate_release(manifest)
        own_unknown = (
            "coding_native_unknown" in value["reasons"]
            or snapshot.get("state") in {"outcome_unknown", "waiting_reconciliation"}
            or budget["unknown"] > 0
            or any(
                action.get("status") == "outcome_unknown"
                or any(attempt.get("status") == "unknown" for attempt in action.get("attempts", []))
                for action in snapshot["actions"]
            )
        )
        transient = bool(
            set(value["reasons"])
            - {
                "business_not_terminal",
                "unsettled_reservation",
                "unfinished_action",
                "remote_uncertain",
                "coding_native_unknown",
                "child_unfinished",
            }
        ) or any(
            action.get("status") in {"executing", "received"}
            or any(attempt.get("status") == "executing" for attempt in action.get("attempts", []))
            for action in snapshot["actions"]
        )
        if (
            "business_not_terminal" in value["reasons"]
            and snapshot.get("state") not in {"outcome_unknown", "waiting_reconciliation"}
            or "unfinished_action" in value["reasons"]
            and not own_unknown
            or "unsettled_reservation" in value["reasons"]
            and budget.get("reserved", 0) != 0
        ):
            transient = True
        child_unknown = False
        for call in proof["children"]:
            if call.get("dispatch_started") is not True:
                if call.get("settled") is not True:
                    transient = True
                continue
            epoch = call.get("deployment_execution_epoch")
            if epoch is None:
                # Original pin/acceptance is still pending; never fill it here.
                transient = True
                continue
            child = await execution._proof(
                runtime, client, policy, scoped, call["run_id"], epoch, required=True
            )
            if (
                child["request"] != call["request"]
                or child["command_id"] != call["command_id"]
                or child["admission"] != call["deployment_admission"]
            ):
                _reject()
            await execution._ancestry(runtime, client, policy, child, read_only=True)
            child_closure = await closure(child)
            if child_closure["ready"] is False:
                if await unknown(child, child_closure, seen):
                    child_unknown = True
                else:
                    transient = True
            elif call.get("settled") is not True or call.get("uncertain") is True:
                # A ready child is not an adopted parent observation yet.
                transient = True
        if "child_unfinished" in value["reasons"] and not child_unknown:
            transient = True
        return (own_unknown or child_unknown) and not transient

    async def drain():
        candidates = await handle.query(
            "view",
            {
                "kind": "coding_composition_candidates",
                "scope": scoped,
                "manifest_digest": digest(manifest),
            },
        )
        if type(candidates) is not list:
            _reject()
        for candidate in candidates:
            proof = await original(candidate)
            while True:
                value = await closure(proof)
                if value["ready"] is False:
                    if value["seal"] is not None:
                        _reject()
                    if await unknown(proof, value):
                        await original(candidate)
                        namespace = await handle._authority()
                        await execution._namespace(client, namespace)
                        break
                    await asyncio.sleep(0.05)
                    proof = await original(candidate)
                    continue
                validated = await release._closure(runtime, client, policy, proof)
                certificate = validated["seal"]
                if certificate is not None:
                    release._certificate(certificate, proof)
                    namespace = await handle._authority()
                    if namespace != proof["namespace"]:
                        _reject()
                    record = await handle._result(
                        await handle.handle.query(
                            "view",
                            {
                                "kind": "deployment_retirement",
                                **release._binding(
                                    proof["admission_receipt"]["root"], policy, certificate
                                ),
                            },
                        ),
                        namespace,
                    )
                    if record is not None:
                        if record != {
                            "root": proof["admission_receipt"]["root"],
                            "certificate": certificate,
                            "released": True,
                        }:
                            _reject()
                        await original(candidate)
                        await handle._authority()
                        await execution._namespace(client, namespace)
                        break
                await asyncio.sleep(0.05)
                proof = await original(candidate)

    try:
        # Includes all read RPCs and all roots, not a fresh budget per poll.
        async with asyncio.timeout(wait_timeout):
            await drain()
    except TimeoutError:
        raise CloseIncomplete("Original ready deployment retirement remains owned") from None


async def verify_call_stop(runtime, client, value, info):
    from . import temporal_deployment_execution as execution
    from .delegated_coding import registered_coding_tool
    from .temporal_coding_runtime import original_owner_stopped
    from .temporal_coding_state import PROOF_FIELDS, validate_owner
    from .temporal_deployment_release_state import CALL_FIELDS
    from .temporal_state import TOOL_ACTIVITY

    value = detached(value)
    _exact(value, {"scope", "identity"})
    identity = value["identity"]
    _exact(identity, CALL_FIELDS)
    manifest = runtime.validate_release()
    if not _selected(manifest) or identity["scope"] != value["scope"]:
        _reject()
    if identity["activity_name"] != TOOL_ACTIVITY:
        _reject()
    execution._actual(client, info, run_id=identity["run_id"], epoch=identity["execution_epoch"])
    proof = await execution._proof(
        runtime,
        client,
        execution._policy(runtime),
        value["scope"],
        identity["run_id"],
        identity["execution_epoch"],
        required=True,
    )
    await execution._ancestry(runtime, client, execution._policy(runtime), proof)
    if identity["manifest_digest"] != digest(proof["manifest"]):
        _reject()
    namespace = proof["namespace"]
    handle = client.get_workflow_handle(identity["run_id"], run_id=identity["execution_epoch"])
    query = {
        "kind": "deployment_coding_call_candidate",
        "scope": value["scope"],
        "identity": identity,
    }
    candidate = detached(await handle.query("view", query))
    _exact(candidate, _CANDIDATE_FIELDS)
    if (
        type(candidate["version"]) is not int
        or candidate["version"] != 1
        or candidate["identity"] != identity
        or candidate["namespace"] != namespace
        or candidate["execution_epoch"] != identity["execution_epoch"]
    ):
        _reject()
    owner, stopped = candidate["owner"], candidate["owner_stop_proof"]
    validate_owner(owner, owner.get("invocation_id"))
    _exact(stopped, PROOF_FIELDS | {"evidence"})
    if (
        stopped["scope"] != value["scope"]
        or stopped["run_id"] != identity["run_id"]
        or stopped["execution_epoch"] != identity["execution_epoch"]
        or stopped["action_id"] != candidate["action_id"]
        or stopped["request_digest"] != candidate["tool_request_digest"]
        or stopped["evidence"] != {"owner": owner, "process_present": False, "native_fenced": True}
    ):
        _reject()
    requests = await handle.query("view", {"kind": "coding_requests", "scope": value["scope"]})
    if type(requests) is not list:
        _reject()
    matching = [
        r
        for r in requests
        if type(r) is dict
        and r.get("action_id") == candidate["action_id"]
        and digest(r) == candidate["tool_request_digest"]
    ]
    if len(matching) != 1:
        _reject()
    request = matching[0]
    if (
        digest({"scope": value["scope"], "_deployment_activity_request": request})
        != identity["request_digest"]
        or request["runtime_manifest"] != proof["manifest"]
        or request["scope"] != value["scope"]
        or request["run_id"] != identity["run_id"]
        or request["execution_epoch"] != identity["execution_epoch"]
    ):
        _reject()
    marker = request["tool_manifest"].get("config", {}).get("delegated_runner", {})
    handler = registered_coding_tool(runtime.tools.get(request["tool"]))
    if (
        handler is None
        or handler.identity != candidate["runner"]
        or marker.get("runner") != candidate["runner"]
    ):
        _reject()
    handler.check()
    await execution._namespace(client, namespace)
    if not await original_owner_stopped(handler.runner, owner):
        _reject()
    handler.check()
    if detached(await handle.query("view", query)) != candidate:
        _reject()
    await execution._namespace(client, namespace)
    execution._actual(client, info, run_id=identity["run_id"], epoch=identity["execution_epoch"])
    runtime.validate_release(proof["manifest"])
    return {**candidate, "process_present": False, "native_fenced": True}


def registered_stop_activity(runtime, client):
    from temporalio import activity

    @activity.defn(name=STOP_ACTIVITY)
    async def verify(value: dict) -> dict:
        try:
            return {
                "ok": True,
                "result": await verify_call_stop(runtime, client, value, activity.info()),
            }
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "deployment_coding_stop_failed",
            }

    verify.__ralf_deployment_coding_stop__ = (_STOP_MARKER, runtime, client, verify)
    return verify


def is_registered_stop_activity(runtime, client, function):
    return getattr(function, "__ralf_deployment_coding_stop__", None) == (
        _STOP_MARKER,
        runtime,
        client,
        function,
    )
