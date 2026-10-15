"""Fresh selected Coding SDK identity reads around original native I/O.

Only immutable identities survive the bootstrap. Permission is read afresh and
is still acted on by the original Run's native grant Update.
"""

import asyncio

from .errors import DefinitionMismatch
from .task_controls import _binding
from .temporal_state import COMMAND_REGISTRY_NAME, WORKFLOW_NAME, detached
from .types import canonical, digest

_NODE_FIELDS = {
    "version",
    "scope",
    "namespace",
    "run_id",
    "execution_epoch",
    "original_execution_epoch",
    "identity_digest",
    "revision",
    "state",
    "stop_requested",
    "sealed",
    "edge",
    "proof_digest",
}
_EDGE_FIELDS = {
    "call_id",
    "child_run_id",
    "child_execution_epoch",
    "identity_digest",
    "dispatch_started",
    "owned",
}
_REGISTRY_FIELDS = {
    "version",
    "registry_id",
    "registry_execution_epoch",
    "configuration_version",
    "policy",
    "scope",
    "namespace",
    "root_identity_digest",
    "submission_digest",
    "held",
    "retired",
    "close_requested",
    "admitted",
    "proof_digest",
}
_STATES = {
    "queued",
    "running",
    "waiting_approval",
    "waiting_input",
    "waiting_reconciliation",
    "outcome_unknown",
    "cancelling",
    "cancelled",
    "failed",
    "succeeded",
}
_CLAIM_FIELDS = ("workflow_id", "workflow_run_id", "workflow_namespace", "activity_id", "attempt")


def _reject():
    raise DefinitionMismatch("Original selected3 Coding validation identity changed")


def _signed(value, fields):
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value.get("version")) is not int
        or value["version"] != 1
        or value["proof_digest"] != digest({k: v for k, v in value.items() if k != "proof_digest"})
    ):
        _reject()
    return value


class CodingValidation:
    """One original Activity/invocation, with no Runtime permission cache."""

    def __init__(self, runtime, client, request, info):
        from . import temporal_coding_composition_control as composition
        from . import temporal_deployment_control_projection as projection
        from . import temporal_deployment_execution as execution
        from .temporal_deployment_coding_bridge import _selected

        self._runtime, self._client, self._info = runtime, client, info
        self._resources = (runtime, client, client.workflow_service)
        self._request = detached(request)
        self._request_digest = digest(self._request)
        self._manifest = detached(self._request["runtime_manifest"])
        if not _selected(self._manifest):
            _reject()
        self._claim = tuple(getattr(info, field, None) for field in _CLAIM_FIELDS)
        self._policy = execution._policy(runtime)
        if self._manifest["deployment_admission_protocol"]["policy"] != self._policy:
            _reject()
        self._ports = [
            (runtime, "validate_release"),
            (client, "get_workflow_handle"),
            (client.workflow_service, "describe_namespace"),
        ]
        self._ports += [
            (self, name)
            for name in (
                "validate",
                "_validate_readset",
                "permission",
                "_check",
                "_bootstrap",
                "_fresh",
                "_description",
                "_node",
                "_registry",
                "_parent_type",
            )
        ]
        self._ports += [
            (execution, name)
            for name in ("_actual", "_policy", "_proof", "_ancestry", "_namespace")
        ]
        self._ports += [(composition, name) for name in ("_proof", "_ancestry")]
        self._ports += [
            (projection, name)
            for name in (
                "node_identity_digest",
                "edge_identity_digest",
                "root_identity_digest",
                "submission_identity_digest",
            )
        ]
        if self._manifest["deployment_admission_protocol"]["version"] == 4:
            from . import temporal_session_deployment_verification as verification

            self._ports += [(verification, "validate_session_origin"), (self, "_session_origin")]
        self._ports += [(globals(), "_signed"), (globals(), "_reject")]
        self._bindings = tuple(
            _binding(owner[name] if isinstance(owner, dict) else getattr(owner, name))
            for owner, name in self._ports
        )
        self._check_pin = _binding(self._check)
        self._snapshot = None
        self._snapshot_digest = None
        self._bootstrap_lock = asyncio.Lock()
        self._check(full=True)

    def _check(self, *, full):
        from . import temporal_deployment_execution as execution

        if type(full) is not bool:
            _reject()
        runtime, client, service = self._resources
        if (
            self._runtime is not runtime
            or self._client is not client
            or client.workflow_service is not service
        ):
            _reject()
        if self._bindings != tuple(
            _binding(owner[name] if isinstance(owner, dict) else getattr(owner, name))
            for owner, name in self._ports
        ):
            _reject()
        if self._claim != tuple(getattr(self._info, field, None) for field in _CLAIM_FIELDS):
            _reject()
        try:
            from temporalio import activity

            live = activity.info()
        except RuntimeError:
            live = None
        if live is not None and self._claim != tuple(
            getattr(live, field, None) for field in _CLAIM_FIELDS
        ):
            _reject()
        if self._snapshot is not None and digest(self._snapshot) != self._snapshot_digest:
            _reject()
        if digest(self._request) != self._request_digest:
            _reject()
        execution._actual(
            client,
            self._info,
            run_id=self._request["run_id"],
            epoch=self._request["execution_epoch"],
        )
        # Policy inspection already validates the full release on both sides.
        if full and execution._policy(runtime, expected=self._manifest) != self._policy:
            _reject()

    async def _bootstrap(self):
        from . import temporal_coding_composition_control as composition
        from . import temporal_deployment_control_projection as projection
        from . import temporal_deployment_execution as execution
        from .temporal_deployment_coding_bridge import _ReadOnlyClient, registry

        async with self._bootstrap_lock:
            self._check(full=True)
            if self._snapshot is not None:
                return
            runtime, client, request = self._runtime, self._client, self._request
            readonly = _ReadOnlyClient(client)
            leaf = await execution._proof(
                runtime,
                readonly,
                self._policy,
                request["scope"],
                request["run_id"],
                request["execution_epoch"],
                required=True,
            )
            self._check(full=True)
            if canonical(leaf["manifest"]) != canonical(self._manifest):
                _reject()
            if (
                "deployment_admission" in request
                and request["deployment_admission"] != leaf["admission"]
            ):
                _reject()
            if "coding_parent" in request and request["coding_parent"] != leaf["request"].get(
                "coding_parent"
            ):
                _reject()
            root = await execution._ancestry(runtime, readonly, self._policy, leaf, read_only=True)
            self._check(full=True)
            proofs = [leaf]
            for link in reversed(leaf["admission"]["lineage"]):
                parent = await execution._proof(
                    runtime,
                    readonly,
                    self._policy,
                    request["scope"],
                    link["parent_run_id"],
                    link["parent_execution_epoch"],
                    required=True,
                )
                self._check(full=True)
                proofs.append(parent)
            if proofs[-1] != root:
                # Mutable proof fields may change between reads; bind only the original identity.
                if any(
                    proofs[-1][name] != root[name]
                    for name in (
                        "scope",
                        "run_id",
                        "execution_epoch",
                        "request_digest",
                        "manifest_digest",
                        "admission",
                        "admission_receipt",
                    )
                ):
                    _reject()
                root = proofs[-1]
            coding = {}
            if self._manifest["binding_protocol"] == 23:
                original = await composition._proof(
                    readonly,
                    request["scope"],
                    request["run_id"],
                    request["execution_epoch"],
                    self._manifest,
                    leaf["namespace"],
                    request=leaf["request"],
                )
                self._check(full=True)
                chain = await composition._ancestry(
                    readonly, original, self._manifest, leaf["namespace"]
                )
                self._check(full=True)
                coding[original["run_id"]] = original
                coding.update((parent["run_id"], parent) for parent, _ in chain)
                if set(coding) != {p["run_id"] for p in proofs}:
                    _reject()
                for parent, call in chain:
                    child = next((p for p in proofs if p["run_id"] == call["run_id"]), None)
                    original_call = next(
                        (
                            c
                            for p in proofs
                            if p["run_id"] == parent["run_id"]
                            for c in p["children"]
                            if c.get("id") == call.get("id")
                        ),
                        None,
                    )
                    if (
                        child is None
                        or original_call is None
                        or projection.edge_identity_digest(original_call)
                        != projection.edge_identity_digest(call)
                    ):
                        _reject()
                    if original_call.get("deployment_execution_epoch") != child[
                        "execution_epoch"
                    ] or call.get("child_execution") != {
                        "namespace": child["namespace"],
                        "execution_epoch": child["execution_epoch"],
                        "original_execution_epoch": child["execution_epoch"],
                    }:
                        _reject()
            nodes = []
            child = None
            for proof in proofs:
                start = detached(
                    await readonly.get_workflow_handle(
                        proof["run_id"], run_id=proof["execution_epoch"]
                    ).query("view", {"kind": "deployment_start", "scope": request["scope"]})
                )
                self._check(full=True)
                identity = projection.node_identity_digest(
                    proof, start, coding.get(proof["run_id"])
                )
                edge = None
                if child is not None:
                    matches = [c for c in proof["children"] if c.get("run_id") == child["run_id"]]
                    if len(matches) != 1:
                        _reject()
                    call = matches[0]
                    if (
                        call.get("dispatch_started") is not True
                        or call.get("deployment_execution_epoch") != child["execution_epoch"]
                    ):
                        _reject()
                    edge = {
                        "call_id": call["id"],
                        "child_run_id": child["run_id"],
                        "child_execution_epoch": child["execution_epoch"],
                        "identity_digest": projection.edge_identity_digest(call),
                    }
                description = await client.get_workflow_handle(proof["run_id"]).describe()
                self._check(full=True)
                expected_parent = (
                    proof["admission"]["lineage"][-1] if proof["admission"]["lineage"] else None
                )
                if expected_parent is None and "session_origin" in proof["admission"]:
                    origin = proof["admission"]["session_origin"]
                    expected_parent = {
                        "parent_run_id": origin["coordinator_id"],
                        "parent_execution_epoch": origin["coordinator_execution_epoch"],
                    }
                desc = {
                    "id": proof["run_id"],
                    "run_id": proof["execution_epoch"],
                    "namespace": proof["namespace"]["name"],
                    "task_queue": start["task_queue"],
                    "parent_id": None
                    if expected_parent is None
                    else expected_parent["parent_run_id"],
                    "parent_run_id": None
                    if expected_parent is None
                    else expected_parent["parent_execution_epoch"],
                    "workflow_type": WORKFLOW_NAME
                    if proof["request"]["definition"]["kind"] in {"agent", "sequence"}
                    else self._parent_type(),
                }
                self._description(description, desc)
                nodes.append(
                    {
                        "id": proof["run_id"],
                        "epoch": proof["execution_epoch"],
                        "identity": identity,
                        "edge": edge,
                        "description": desc,
                        "activity_timeout": start["activity_timeout"],
                    }
                )
                child = proof
            proxy = registry(readonly, request["scope"], self._manifest)
            await proxy._authority()
            self._check(full=True)
            session = self._manifest["deployment_admission_protocol"]["version"] == 4
            record = detached(
                await proxy.handle.query(
                    "view",
                    {
                        "kind": "deployment_session_root" if session else "deployment_submission",
                        "scope": root["scope"],
                        "command_id": root["command_id"],
                        "payload_digest": root["request_digest"],
                        "admission_policy": self._policy,
                        "namespace": root["namespace"],
                    },
                )
            )
            self._check(full=True)
            execution._exact(
                record,
                {"reservation", "submission", "run_receipt", "execution_epoch"}
                | ({"intent", "session_origin"} if session else set()),
            )
            session_identity = None
            if session:
                from .temporal_session_deployment_dto import validate_intent, validate_origin

                intent, origin = record["intent"], record["session_origin"]
                validate_intent(
                    intent,
                    deployment_id=self._policy["deployment_id"],
                    scope=root["scope"],
                    namespace=root["namespace"],
                    coordinator_execution_epoch=root["admission"]["session_origin"][
                        "coordinator_execution_epoch"
                    ],
                )
                validate_origin(origin, intent=intent, deployment_id=self._policy["deployment_id"])
                if (
                    origin != root["admission"]["session_origin"]
                    or intent["submission"] != record["submission"]
                    or intent["run_id"] != root["run_id"]
                    or intent["run_command_id"] != root["command_id"]
                ):
                    _reject()
                session_identity = {"intent": detached(intent), "session_origin": detached(origin)}
                await self._session_origin(session_identity)
            envelope = record["submission"]
            execution._exact(
                envelope, {"version", "request", "manifest", "activity_timeout", "task_queue"}
            )
            reservation = record["reservation"]
            execution._exact(
                reservation,
                {"command_id", "target", "record_state", "apply_state", "root_admission"},
            )
            if (
                reservation
                != {
                    "command_id": root["command_id"],
                    "target": root["run_id"],
                    "record_state": "durably_recorded",
                    "apply_state": "not_applied",
                    "root_admission": root["admission"]["root"],
                }
                or record["execution_epoch"] not in (None, root["execution_epoch"])
                or record["execution_epoch"] is None
                and record["run_receipt"] is not None
                or canonical(envelope["request"]) != canonical(root["request"])
                or canonical(envelope["manifest"]) != canonical(self._manifest)
                or type(envelope["version"]) is not int
                or envelope["version"] != 1
            ):
                _reject()
            for node in nodes:
                if (
                    node["description"]["task_queue"] != envelope["task_queue"]
                    or node["activity_timeout"] != envelope["activity_timeout"]
                ):
                    _reject()
                # Every start's immutable timeout is also bound by its identity digest.
            from .temporal_deployment_submissions import _receipt

            if record["run_receipt"] is not None:
                _receipt(
                    record["run_receipt"], command_id=root["command_id"], run_id=root["run_id"]
                )
            registry_description = await client.get_workflow_handle(proxy.id).describe()
            self._check(full=True)
            registry_expected = {
                "id": proxy.id,
                "run_id": proxy.execution_epoch,
                "namespace": root["namespace"]["name"],
                "workflow_type": COMMAND_REGISTRY_NAME,
                "parent_id": None,
                "parent_run_id": None,
                "task_queue": registry_description.task_queue,
            }
            self._description(registry_description, registry_expected)
            bound = root["admission_receipt"]["root"]
            configuration_version = proxy.configuration_version
            if type(configuration_version) is not int or configuration_version not in (
                (4,) if session else (3, 4)
            ):
                _reject()
            snapshot = {
                "configuration_version": configuration_version,
                "session": session_identity,
                "registry_description": registry_expected,
                "nodes": nodes,
                "namespace": detached(root["namespace"]),
                "registry_id": proxy.id,
                "registry_epoch": proxy.execution_epoch,
                "root_digest": projection.root_identity_digest(bound),
                "submission_digest": projection.submission_identity_digest(envelope),
                "registry_request": {
                    "kind": "deployment_coding_validation",
                    "scope": root["scope"],
                    "admission_policy": self._policy,
                    "namespace": root["namespace"],
                    "command_id": root["command_id"],
                    "run_id": root["run_id"],
                    "execution_epoch": root["execution_epoch"],
                    "request_digest": root["request_digest"],
                    "manifest_digest": root["manifest_digest"],
                },
            }
            self._check(full=True)
            self._snapshot_digest = digest(snapshot)
            self._snapshot = detached(snapshot)

    @staticmethod
    def _parent_type():
        from .temporal_parent_state import PARENT_WORKFLOW_NAME

        return PARENT_WORKFLOW_NAME

    def _description(self, value, expected):
        from temporalio.client import WorkflowExecutionStatus

        if (
            any(getattr(value, field, None) != item for field, item in expected.items())
            or value.status is not WorkflowExecutionStatus.RUNNING
            or getattr(getattr(value, "raw_info", None), "first_run_id", None) != expected["run_id"]
        ):
            _reject()

    def _node(self, value, node):
        value = _signed(value, _NODE_FIELDS)
        if (
            any(
                value[name] != expected
                for name, expected in (
                    ("scope", self._request["scope"]),
                    ("namespace", self._snapshot["namespace"]),
                    ("run_id", node["id"]),
                    ("execution_epoch", node["epoch"]),
                    ("original_execution_epoch", node["epoch"]),
                    ("identity_digest", node["identity"]),
                )
            )
            or type(value["revision"]) is not int
            or value["revision"] < 0
            or type(value["state"]) is not str
            or value["state"] not in _STATES
            or any(type(value[name]) is not bool for name in ("stop_requested", "sealed"))
        ):
            _reject()
        edge = value["edge"]
        if node["edge"] is None:
            if edge is not None:
                _reject()
        elif (
            type(edge) is not dict
            or set(edge) != _EDGE_FIELDS
            or any(edge[k] != v for k, v in node["edge"].items())
            or edge["dispatch_started"] is not True
            or edge["owned"] is not True
        ):
            _reject()
        return not (
            value["stop_requested"]
            or value["sealed"]
            or value["state"] in {"cancelling", "cancelled", "failed", "succeeded"}
        )

    def _registry(self, value):
        value = _signed(value, _REGISTRY_FIELDS)
        s = self._snapshot
        if (
            any(
                value[name] != expected
                for name, expected in (
                    ("registry_id", s["registry_id"]),
                    ("registry_execution_epoch", s["registry_epoch"]),
                    ("configuration_version", s["configuration_version"]),
                    ("policy", self._policy),
                    ("scope", self._request["scope"]),
                    ("namespace", s["namespace"]),
                    ("root_identity_digest", s["root_digest"]),
                    ("submission_digest", s["submission_digest"]),
                )
            )
            or type(value["configuration_version"]) is not int
            or any(
                type(value[name]) is not bool
                for name in ("held", "retired", "close_requested", "admitted")
            )
            or value["held"] == value["retired"]
            or value["admitted"]
            != (value["held"] and not value["retired"] and not value["close_requested"])
        ):
            _reject()
        return value["admitted"]

    async def _session_origin(self, identity, *, _full_release=True):
        from .temporal_session_deployment_verification import validate_session_origin

        if type(_full_release) is not bool:
            _reject()
        result = await validate_session_origin(
            self._runtime,
            self._client,
            identity["intent"],
            identity["session_origin"],
            **(
                {"_release_boundary": self._request["runtime_manifest"]}
                if not _full_release
                else {}
            ),
        )
        self._check(full=_full_release)
        if result != identity:
            _reject()

    async def _fresh(self, *, _full_release=True):
        from . import temporal_deployment_execution as execution

        if type(_full_release) is not bool:
            _reject()
        check = self._check
        if _binding(check) != self._check_pin:
            _reject()
        check(full=_full_release)
        # Only an already-bootstrapped original-Scope read-set may defer full
        # release validation to its public exit. Bootstrap keeps every full check.
        steady = self._snapshot is not None
        if self._snapshot is None:
            await self._bootstrap()
            if _binding(check) != self._check_pin:
                _reject()
            check(full=_full_release)
        s, client = self._snapshot, self._client
        await execution._namespace(client, s["namespace"])
        if _binding(check) != self._check_pin:
            _reject()
        check(full=_full_release and not steady)
        reads = []
        for node in s["nodes"]:
            handle = client.get_workflow_handle(node["id"], run_id=node["epoch"])
            reads.extend(
                [
                    handle.query(
                        "view",
                        {
                            "kind": "deployment_coding_validation",
                            "scope": self._request["scope"],
                            "run_id": node["id"],
                            "execution_epoch": node["epoch"],
                            "child_call_id": None
                            if node["edge"] is None
                            else node["edge"]["call_id"],
                        },
                    ),
                    client.get_workflow_handle(node["id"]).describe(),
                ]
            )
        reads.extend(
            [
                client.get_workflow_handle(s["registry_id"], run_id=s["registry_epoch"]).query(
                    "view", detached(s["registry_request"])
                ),
                client.get_workflow_handle(s["registry_id"]).describe(),
            ]
        )
        results = await asyncio.gather(*reads, return_exceptions=True)
        if _binding(check) != self._check_pin:
            _reject()
        check(full=_full_release and not steady)
        for value in results:
            if isinstance(value, BaseException):
                raise value
        await execution._namespace(client, s["namespace"])
        if s["session"] is not None:
            # A cold invocation retains every bootstrap/full Session check.
            # Only the warm private callback has independent outer full checks
            # for this exact fixed Manifest before and after the complete set.
            await self._session_origin(s["session"], _full_release=_full_release or not steady)
        # Only synchronous DTO checks remain. The public callback immediately
        # performs the full post-I/O check, including the pinned _fresh method.
        permitted = True
        for index, node in enumerate(s["nodes"]):
            permitted = self._node(results[index * 2], node) and permitted
            self._description(results[index * 2 + 1], node["description"])
        permitted = self._registry(results[-2]) and permitted
        self._description(results[-1], s["registry_description"])
        return permitted

    async def _validate_readset(self):
        # Only the selected4 aggregate callback uses this private read-set.
        # Its independent full Runtime checks bracket this whole await; the
        # original Session verifier and bootstrap retain their own full checks.
        await self._fresh(_full_release=False)
        check = self._check
        if _binding(check) != self._check_pin:
            _reject()
        check(full=False)
        return None

    async def validate(self):
        await self._fresh()
        check = self._check
        if _binding(check) != self._check_pin:
            _reject()
        check(full=True)
        return None

    async def permission(self):
        value = await self._fresh()
        check = self._check
        if _binding(check) != self._check_pin:
            _reject()
        check(full=True)
        return value
