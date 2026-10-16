"""Pinned SDK original-run callbacks outlive the observing Activity Task."""

import uuid

from .errors import DefinitionMismatch
from .temporal_context_read_state import END_UPDATE
from .temporal_managed_context import ADMISSION_UPDATE
from .temporal_state import detached
from .types import digest


def callbacks(client, request, info):
    fixed = detached(request)
    workflow_id, epoch, namespace = (
        info.workflow_id,
        info.workflow_run_id,
        info.workflow_namespace,
    )
    handle = None
    if client is not None and (
        workflow_id == fixed.get("run_id")
        and epoch == fixed.get("execution_epoch")
        and namespace == client.namespace
    ):
        handle = client.get_workflow_handle(workflow_id, run_id=epoch)

    async def check():
        from .temporal_session_activities import validate_tree_activity

        if handle is None or client.namespace != namespace:
            raise DefinitionMismatch("Context read changed actual Workflow epoch or namespace")
        await validate_tree_activity(client, fixed, workflow_id=workflow_id)
        if client.namespace != namespace:
            raise DefinitionMismatch("Context read namespace changed during validation")

    async def guard(value):
        if value != fixed:
            raise DefinitionMismatch("Context read changed its fixed Activity request")
        await check()
        result = await handle.execute_update(
            ADMISSION_UPDATE,
            {
                name: fixed[name]
                for name in (
                    "scope",
                    "run_id",
                    "action_id",
                    "release_digest",
                    "execution_epoch",
                    "phase",
                )
            }
            | {"request_digest": digest(fixed)},
            # A fresh observation must consult original History again after end;
            # a server-cached successful Update cannot authorize another reader.
            id="ralf-context-dispatch:" + fixed["action_id"] + ":" + uuid.uuid4().hex,
        )
        await check()
        return result

    async def ended(proof):
        expected = {
            name: fixed[name]
            for name in ("scope", "action_id", "release_digest", "execution_epoch")
        } | {"request_digest": digest(fixed)}
        if proof != expected:
            raise DefinitionMismatch("Context read end lost its fixed Activity identity")
        await check()
        from .temporal_deployment_protocol import public_selected, selected
        from .temporal_execution_end_transport import execute

        update_id = "ralf-context-read-ended:" + digest(proof)
        if selected(fixed["runtime_manifest"]) and not public_selected(fixed["runtime_manifest"]):
            result = await handle.execute_update(END_UPDATE, detached(proof), id=update_id)
        else:
            result = await execute(
                client,
                workflow_id,
                END_UPDATE,
                proof,
                execution_epoch=epoch,
                legacy_update_id=update_id,
            )
        await check()
        if (
            type(result) is not dict
            or set(result) != {"action_id", "recorded"}
            or result["action_id"] != fixed["action_id"]
            or result["recorded"] is not True
        ):
            raise DefinitionMismatch("Context read end lacks original completed acknowledgement")

    return guard, ended
