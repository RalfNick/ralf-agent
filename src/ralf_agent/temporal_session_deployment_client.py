"""Client routing to original Session4 and Registry4 Histories."""

from dataclasses import asdict
from uuid import uuid4

from .errors import (
    CapacityExceeded,
    DefinitionMismatch,
    SessionBindingMismatch,
    SessionBusy,
    ValidationError,
)
from .session_types import SessionKey, SessionRef
from .temporal import _raise_code, _sdk
from .temporal_deployment_coding_bridge import logical_request
from .temporal_deployment_submissions import (
    _namespace,
    _policy,
    _query,
    _recheck,
    _registry,
    _update,
)
from .temporal_session_deployment_dto import validate_intent, validate_start_view
from .temporal_session_state import SESSION_WORKFLOW, detached, validate_binding, workflow_id
from .types import CommandReceipt, digest


def _reject():
    raise DefinitionMismatch("Original deployment Session command changed")


class DeploymentSessionClient:
    def __init__(self, legacy):
        self.legacy, self.engine, self.namespace_id = legacy, legacy.engine, legacy.namespace_id

    async def _context(self):
        engine = self.engine
        client, scope, policy = engine.client, asdict(engine.scope), _policy(engine)
        namespace = await _namespace(engine, client, scope, policy)
        if namespace["id"] != self.namespace_id:
            _reject()
        registry = await _registry(engine, client, scope, namespace, policy)
        return client, scope, namespace, policy, registry

    async def _check(self, context):
        client, scope, namespace, policy, _ = context
        await _recheck(self.engine, client, scope, namespace, policy)

    def _ref(self, ref, scope):
        if not isinstance(ref, SessionRef) or (ref.key.workspace, ref.key.principal) != (
            scope["workspace"],
            scope["principal"],
        ):
            _reject()
        if ref.coordination_ref != digest(
            ["temporal-session-coordination-v1", ref.key.resource_id, scope]
        ):
            _reject()

    async def _coordinator(self, context, key, *, epoch=None):
        await self._check(context)
        client, _, namespace, _, _ = context
        current = await client.get_workflow_handle(workflow_id(key)).describe()
        await self._check(context)
        if (
            current.id != workflow_id(key)
            or current.namespace != namespace["name"]
            or current.workflow_type != SESSION_WORKFLOW
            or type(current.run_id) is not str
            or not current.run_id
            or current.raw_info.first_run_id != current.run_id
            or current.parent_id is not None
            or current.parent_run_id is not None
            or epoch is not None
            and current.run_id != epoch
        ):
            _reject()
        return client.get_workflow_handle(workflow_id(key), run_id=current.run_id), current.run_id

    def _lookup(self, context, logical):
        _, scope, namespace, policy, _ = context
        command = logical["command_id"]
        if type(command) is not str or not command.strip() or len(command) > 1024:
            raise ValidationError("Session command requires a bounded stable ID")
        return {
            "kind": "deployment_session_command",
            "scope": scope,
            "namespace": namespace,
            "admission_policy": policy,
            "command_id": command,
            "payload_digest": digest(logical),
        }

    async def _find(self, context, logical):
        query = self._lookup(context, logical)
        saved = await _query(context[4], query)
        await self._check(context)
        if saved is not None:
            self._record(saved, logical)
        return saved

    def _record(self, saved, logical):
        if type(saved) is not dict or set(saved) != {
            "reservation",
            "session_submission",
            "session_receipt",
        }:
            _reject()
        submission, reservation = saved["session_submission"], saved["reservation"]
        if (
            type(submission) is not dict
            or set(submission)
            != {"version", "session_key", "payload", "logical_payload", "binding"}
            or type(submission["version"]) is not int
            or submission["version"] != 1
            or digest(submission["logical_payload"]) != digest(logical)
        ):
            _reject()
        key = SessionKey.from_dict(submission["session_key"])
        if (
            reservation
            != {
                "command_id": logical["command_id"],
                "target": workflow_id(key),
                "record_state": "durably_recorded",
                "apply_state": "not_applied",
            }
            or submission["payload"]["command_id"] != logical["command_id"]
            or submission["payload"]["kind"] != logical["kind"]
        ):
            _reject()
        return key, submission

    async def _reserve(self, context, logical, key, payload, binding):
        query = self._lookup(context, logical)
        request = {
            **query,
            "kind": "session_" + logical["kind"],
            "target": workflow_id(key),
            "session_submission": {
                "version": 1,
                "session_key": key.to_dict(),
                "payload": payload,
                "logical_payload": logical,
                "binding": binding,
            },
        }
        await _update(context[4], "reserve", request)
        await self._check(context)
        saved = await self._find(context, logical)
        if saved is None:
            _reject()
        return saved

    def _receipt(self, value, logical):
        if (
            type(value) is not dict
            or set(value)
            != {"command_id", "kind", "run_id", "record_state", "apply_state", "outcome"}
            or value["command_id"] != logical["command_id"]
            or value["kind"] != "session_" + logical["kind"]
            or value["run_id"] is not None
            or value["record_state"] != "durably_recorded"
            or value["apply_state"] not in ("applied", "rejected")
            or type(value["outcome"]) is not dict
        ):
            _reject()
        receipt = CommandReceipt(**detached(value))
        if receipt.apply_state == "rejected":
            if receipt.outcome.get("error") == "session_busy":
                from .agent_run import RunRef

                raise SessionBusy(receipt, RunRef.from_dict(receipt.outcome["active_run"]))
            raise SessionBindingMismatch(receipt)
        return receipt

    async def _complete(self, context, logical, saved, *, create=False):
        key, submission = self._record(saved, logical)
        if saved["session_receipt"] is not None:
            return self._receipt(saved["session_receipt"], logical)
        binding = submission["binding"]
        if create:
            sdk = _sdk()
            try:
                await context[0].start_workflow(
                    SESSION_WORKFLOW,
                    {
                        "scope": context[1],
                        "namespace_id": context[2]["id"],
                        "session_namespace": key.namespace,
                        "session_id": key.session_id,
                        "command_id": logical["command_id"],
                        **binding,
                    },
                    id=workflow_id(key),
                    task_queue=binding["task_queue"],
                    retry_policy=None,
                    id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                    id_conflict_policy=sdk[2].FAIL,
                )
            except sdk[5]:
                pass
            await self._check(context)
        handle, epoch = await self._coordinator(context, key)
        selector = {
            "kind": "deployment_session_receipt",
            "scope": context[1],
            "namespace": context[2],
            "coordinator_execution_epoch": epoch,
            "command_id": logical["command_id"],
        }
        applied = await _query(handle, selector)
        await self._coordinator(context, key, epoch=epoch)
        if applied is None:
            value = await _update(handle, "command", submission["payload"])
            await self._coordinator(context, key, epoch=epoch)
        else:
            if type(applied) is not dict or set(applied) != {"receipt", "session_ref"}:
                _reject()
            value = applied["receipt"]
        request = {k: v for k, v in self._lookup(context, logical).items() if k != "kind"}
        recorded = await _update(
            context[4], "record_deployment_session_command", {**request, "receipt": value}
        )
        await self._check(context)
        self._record(recorded, logical)
        if recorded["session_receipt"] != value:
            _reject()
        return self._receipt(value, logical)

    async def open(self, definition, session_id, *, command_id, namespace=None):
        from .agent_harness import AgentHarness
        from .temporal_session_identity import data_resource_id, selected_namespace, selected_source

        spec = definition.definition if isinstance(definition, AgentHarness) else definition
        context = await self._context()
        logical = {
            "kind": "open",
            "scope": context[1],
            "command_id": command_id,
            "session_namespace": namespace,
            "session_id": session_id,
            "request": logical_request(spec, None),
        }
        saved = await self._find(context, logical)
        if saved is None:
            binding = detached(self.legacy.binding(definition))
            validate_binding(binding, context[1])
            source = selected_source(binding["request"], binding["manifest"])
            key = SessionKey(
                **context[1],
                resource_id=data_resource_id(context[2]["id"], source),
                namespace=selected_namespace(source, namespace),
                session_id=session_id,
            )
            payload = {
                "kind": "open",
                "scope": context[1],
                "command_id": command_id,
                "binding": binding,
            }
            saved = await self._reserve(context, logical, key, payload, binding)
        return await self._complete(context, logical, saved, create=True)

    async def _binding(self, context, ref):
        self._ref(ref, context[1])
        handle, epoch = await self._coordinator(context, ref.key)
        binding = await _query(
            handle,
            {
                "kind": "deployment_session_binding",
                "scope": context[1],
                "namespace": context[2],
                "coordinator_execution_epoch": epoch,
                "session_ref": ref.to_dict(),
            },
        )
        await self._coordinator(context, ref.key, epoch=epoch)
        validate_binding(binding, context[1])
        if digest(binding) != ref.definition_digest:
            _reject()
        return binding

    async def rebind(self, ref, definition, *, command_id, expected_binding_revision):
        from .agent_harness import AgentHarness

        context = await self._context()
        self._ref(ref, context[1])
        spec = definition.definition if isinstance(definition, AgentHarness) else definition
        logical = {
            "kind": "rebind",
            "scope": context[1],
            "command_id": command_id,
            "session_ref": ref.to_dict(),
            "request": logical_request(spec, None),
            "expected_binding_revision": expected_binding_revision,
        }
        saved = await self._find(context, logical)
        if saved is None:
            await self._binding(context, ref)
            binding = detached(self.legacy.binding(definition))
            payload = {k: v for k, v in logical.items() if k != "request"}
            payload["binding"] = binding
            saved = await self._reserve(context, logical, ref.key, payload, binding)
        return await self._complete(context, logical, saved)

    async def submit(self, ref, input, *, command_id, budget):
        context = await self._context()
        self._ref(ref, context[1])
        logical = {
            "kind": "submit",
            "scope": context[1],
            "command_id": command_id,
            "session_ref": ref.to_dict(),
            "input": detached(input),
            "budget": budget,
        }
        saved = await self._find(context, logical)
        duplicate = saved is not None
        if saved is None:
            binding = await self._binding(context, ref)
            saved = await self._reserve(context, logical, ref.key, logical, binding)
        receipt = await self._complete(context, logical, saved)
        handle, epoch = await self._coordinator(context, ref.key)
        turn = receipt.outcome["turn"]
        selector = {
            "scope": context[1],
            "namespace": context[2],
            "coordinator_execution_epoch": epoch,
            "session_command_id": command_id,
            "turn_id": turn["turn_id"],
        }
        intent = await _query(handle, {"kind": "deployment_session_intent", **selector})
        await self._coordinator(context, ref.key, epoch=epoch)
        intent = validate_intent(
            intent,
            deployment_id=context[3]["deployment_id"],
            scope=context[1],
            namespace=context[2],
            coordinator_execution_epoch=epoch,
        )
        selector["intent_digest"] = intent["intent_digest"]
        if duplicate:
            # Fresh Update IDs wake the same logical intent after positive deferral.
            wake = await handle.execute_update(
                "retry_deployment_turn", selector, id="ralf-session-retry:" + uuid4().hex
            )
            await self._coordinator(context, ref.key, epoch=epoch)
            if (
                type(wake) is not dict
                or wake.get("intent_digest") != intent["intent_digest"]
                or type(wake.get("wake_recorded")) is not bool
            ):
                _reject()
        start = await handle.execute_update(
            "start_receipt", selector, id="ralf-session-start:" + uuid4().hex
        )
        await self._coordinator(context, ref.key, epoch=epoch)
        registry_description = await context[4].describe()
        await self._check(context)
        run_epoch = None
        if type(start) is dict and start.get("phase") == "started":
            original = await _query(
                context[4],
                {
                    "kind": "deployment_session_root",
                    "scope": context[1],
                    "admission_policy": context[3],
                    "namespace": context[2],
                    "command_id": intent["run_command_id"],
                    "payload_digest": digest(intent["submission"]["request"]),
                },
            )
            await self._check(context)
            if type(original) is not dict or original.get("intent") != intent:
                _reject()
            run_epoch = original["execution_epoch"]
            if any(
                start.get(name) != original[name]
                for name in ("reservation", "run_receipt", "execution_epoch")
            ):
                _reject()
        start = validate_start_view(
            start,
            intent=intent,
            deployment_id=context[3]["deployment_id"],
            registry_execution_epoch=registry_description.run_id,
            execution_epoch=run_epoch,
        )
        if start["phase"] == "capacity-deferred":
            error = CapacityExceeded("Original Session Turn awaits deployment capacity")
            error.receipt, error.start = receipt, start
            raise error
        if start["phase"] == "start-refused":
            proof = await _query(
                context[4],
                {
                    "kind": "deployment_session_never_claimed",
                    "scope": context[1],
                    "admission_policy": context[3],
                    "namespace": context[2],
                    "intent": intent,
                },
            )
            await self._check(context)
            if proof != start["start_refusal"]:
                _reject()
            _raise_code(proof["code"])
        if start["phase"] != "started":
            _reject()
        return receipt

    async def view(self, ref, kind, **options):
        context = await self._context()
        await self._binding(context, ref)
        handle, epoch = await self._coordinator(context, ref.key)
        result = await _query(handle, {"scope": context[1], "kind": kind, **options})
        await self._coordinator(context, ref.key, epoch=epoch)
        return result
