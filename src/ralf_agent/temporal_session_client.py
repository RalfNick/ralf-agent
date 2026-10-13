"""Pinned async Session transport; all admission lives in Temporal History."""

from dataclasses import asdict

from .agent_harness import AgentHarness
from .agent_run import RunRef
from .errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    SessionBindingMismatch,
    SessionBusy,
    ValidationError,
)
from .session_types import SessionKey, SessionRef, SessionSnapshot
from .temporal import _raise_code, _sdk
from .temporal_bindings import normalize_request
from .temporal_session_state import (
    SESSION_WORKFLOW,
    detached,
    resource_id,
    validate_binding,
    workflow_id,
)
from .types import CommandReceipt, digest, submission_request


class TemporalSessionClient:
    def __init__(self, engine, namespace_id):
        self.engine, self.namespace_id = engine, namespace_id

    def validate(self, ref):
        if not isinstance(ref, SessionRef):
            raise ValidationError("Session attachment requires an immutable SessionRef")
        if (ref.key.workspace, ref.key.principal) != (
            self.engine.scope.workspace,
            self.engine.scope.principal,
        ):
            raise AuthorizationDenied("Session belongs to another trusted Scope")
        from .temporal_session_identity import data_resource_id

        possible = {resource_id(self.namespace_id)} | {
            data_resource_id(self.namespace_id, {"dataset_id": value})
            for value in self.engine.release.get("session_save_protocol", {})
            .get("dataset_ids", {})
            .values()
        }
        if ref.key.resource_id not in possible or ref.coordination_ref != digest(
            ["temporal-session-coordination-v1", ref.key.resource_id, asdict(self.engine.scope)]
        ):
            raise DefinitionMismatch("Session belongs to another actual namespace resource")

    def binding(self, definition):
        harness = definition if isinstance(definition, AgentHarness) else AgentHarness(definition)
        return {
            "request": normalize_request(
                submission_request(harness.definition, None), self.engine.release
            ),
            "manifest": self.engine.release,
            "task_queue": self.engine.task_queue,
            "activity_timeout": self.engine.activity_timeout,
        }

    async def _reserve(self, key, payload):
        command = payload.get("command_id")
        if type(command) is not str or not command.strip() or len(command) > 1024:
            raise ValidationError("Session command requires a bounded stable ID")
        identity = detached(payload)
        if "binding" in identity:
            identity["binding"] = {"request": identity["binding"]["request"]}
        await self.engine._guard(
            "session_" + payload["kind"], payload["command_id"], workflow_id(key), identity
        )

    async def command(self, key, payload):
        payload = detached(payload)
        await self._reserve(key, payload)
        return await self._apply(key, payload)

    async def _apply(self, key, payload):
        sdk = _sdk()
        try:
            value = await self.engine._handle(workflow_id(key)).execute_update("command", payload)
        except sdk[1] as exc:
            if isinstance(exc.cause, sdk[4]):
                _raise_code(exc.cause.type)
            raise
        receipt = CommandReceipt(**value)
        if (
            receipt.command_id != payload["command_id"]
            or receipt.kind != "session_" + payload["kind"]
            or receipt.record_state != "durably_recorded"
        ):
            raise ValidationError("Session authority returned another command receipt")
        if receipt.apply_state == "rejected":
            if receipt.outcome["error"] == "session_busy":
                raise SessionBusy(receipt, RunRef.from_dict(receipt.outcome["active_run"]))
            raise SessionBindingMismatch(receipt)
        if receipt.apply_state != "applied":
            raise ValidationError("Session command is not fully applied")
        return receipt

    async def open(self, definition, session_id, *, command_id, namespace=None):
        binding = detached(self.binding(definition))
        from .temporal_session_identity import data_resource_id, selected_namespace, selected_source

        source = selected_source(binding["request"], binding["manifest"])
        namespace = selected_namespace(source, namespace)
        key = SessionKey(
            **asdict(self.engine.scope),
            resource_id=data_resource_id(self.namespace_id, source),
            namespace=namespace,
            session_id=session_id,
        )
        payload = detached(
            {
                "kind": "open",
                "scope": asdict(self.engine.scope),
                "command_id": command_id,
                "binding": binding,
            }
        )
        if type(command_id) is not str or not command_id.strip() or len(command_id) > 1024:
            raise ValidationError("Session command requires a bounded stable ID")
        sdk = _sdk()
        try:
            await self.engine._handle(workflow_id(key)).describe()
        except sdk[6] as exc:
            if exc.status != sdk[7].NOT_FOUND:
                raise
            # Validate before reserving a new Workflow ID. Existing Sessions
            # replay their original receipts without re-resolving old releases.
            validate_binding(binding, asdict(self.engine.scope))
        # A conflicting global command must not create or fix a Session binding.
        await self._reserve(key, payload)
        # Creation records the original open command before a caller can lose
        # its Update reply; it never starts a business Run.
        try:
            await self.engine.client.start_workflow(
                SESSION_WORKFLOW,
                {
                    "scope": asdict(self.engine.scope),
                    "namespace_id": self.namespace_id,
                    "session_namespace": namespace,
                    "session_id": session_id,
                    "command_id": command_id,
                    **binding,
                },
                id=workflow_id(key),
                task_queue=self.engine.task_queue,
                id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                id_conflict_policy=sdk[2].FAIL,
            )
        except sdk[5]:
            pass
        return await self._apply(key, payload)

    async def submit(self, ref, input, *, command_id, budget):
        self.validate(ref)
        receipt = await self.command(
            ref.key,
            {
                "kind": "submit",
                "scope": asdict(self.engine.scope),
                "command_id": command_id,
                "session_ref": ref.to_dict(),
                "input": input,
                "budget": budget,
            },
        )
        run_id = receipt.outcome["turn"]["run"]["run_id"]
        await self.engine._handle(workflow_id(ref.key)).execute_update(
            "start_receipt", {"scope": asdict(self.engine.scope), "run_id": run_id}
        )
        return receipt

    async def rebind(self, ref, definition, *, command_id, expected_binding_revision):
        self.validate(ref)
        return await self.command(
            ref.key,
            {
                "kind": "rebind",
                "scope": asdict(self.engine.scope),
                "command_id": command_id,
                "session_ref": ref.to_dict(),
                "binding": self.binding(definition),
                "expected_binding_revision": expected_binding_revision,
            },
        )

    async def view(self, ref, kind, **options):
        self.validate(ref)
        value = await self.engine._handle(workflow_id(ref.key)).query(
            "view", {"scope": asdict(self.engine.scope), "kind": kind, **options}
        )
        if isinstance(value, dict) and set(value) == {"error"}:
            _raise_code(value["error"])
        return value

    async def status(self, ref):
        value = await self.view(ref, "status")
        return SessionSnapshot(
            SessionRef.from_dict(value["ref"]),
            value["binding_revision"],
            value["last_turn_seq"],
            None if value["active_run"] is None else RunRef.from_dict(value["active_run"]),
            value["busy"],
        )
