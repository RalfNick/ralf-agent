"""Pinned original SDK Workflow callbacks for actual Tool execution lifetime."""

import uuid

from .errors import DefinitionMismatch
from .temporal_state import detached
from .temporal_tool_execution_state import ADMISSION_UPDATE, END_UPDATE
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
            raise DefinitionMismatch("Tool changed original Workflow epoch or namespace")
        await validate_tree_activity(client, fixed, workflow_id=workflow_id)
        if client.namespace != namespace:
            raise DefinitionMismatch("Tool namespace changed during original validation")

    expected = {
        name: fixed[name] for name in ("scope", "action_id", "release_digest", "execution_epoch")
    } | {"request_digest": digest(fixed)}

    async def guard(value, *, invocation_id, owner_proof=None):
        if value != fixed:
            raise DefinitionMismatch("Tool changed original complete Activity request")
        await check()
        result = await handle.execute_update(
            ADMISSION_UPDATE,
            expected
            | {"run_id": workflow_id, "invocation_id": invocation_id}
            | ({"owner": detached(owner_proof)} if owner_proof is not None else {}),
            id="ralf-tool-dispatch:" + fixed["action_id"] + ":" + uuid.uuid4().hex,
        )
        await check()
        return result

    async def ended(value):
        if (
            type(value) is not dict
            or set(value) != set(expected) | {"invocation_id"}
            or any(value[name] != item for name, item in expected.items())
        ):
            raise DefinitionMismatch("Tool end lost original complete Activity identity")
        await check()
        from .temporal_deployment_protocol import public_selected, selected
        from .temporal_execution_end_transport import execute

        update_id = "ralf-tool-ended:" + digest(value)
        if selected(fixed["runtime_manifest"]) and not public_selected(fixed["runtime_manifest"]):
            result = await handle.execute_update(END_UPDATE, detached(value), id=update_id)
        else:
            result = await execute(
                client,
                workflow_id,
                END_UPDATE,
                value,
                execution_epoch=epoch,
                legacy_update_id=update_id,
            )
        await check()
        if result != {"action_id": fixed["action_id"], "recorded": True}:
            raise DefinitionMismatch("Tool end lacks original completed acknowledgement")

    return guard, ended
