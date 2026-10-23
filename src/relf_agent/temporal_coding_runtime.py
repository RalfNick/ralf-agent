"""Original Worker resources, SDK callbacks and native effect observation."""

import asyncio
import os
import stat
import subprocess
import uuid
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .types import digest


def deployment(runner):
    """Physical same-host gate; a shared database does not grant foreign stop."""
    from .codex_runner import CodexCodingRunner

    CodexCodingRunner._check_root(runner)
    socket = Path(runner.identity["docker_host"].removeprefix("unix://"))
    info = socket.stat()
    if not stat.S_ISSOCK(info.st_mode):
        raise DefinitionMismatch("Coding deployment requires its original Unix socket")
    return digest(
        {
            "root": runner.identity["root"],
            "docker_socket": {"path": str(socket), "device": info.st_dev, "inode": info.st_ino},
        }
    )


def process_start(pid):
    """Bounded OS birth read; permission or ambiguous output fails closed."""
    if type(pid) is not int or pid <= 0:
        raise ValidationError("Coding owner requires a positive original PID")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        raise DefinitionMismatch("Original Worker process cannot be verified") from None
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        timeout=3,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    start = result.stdout.strip()
    if result.returncode == 0 and start and len(start) <= 256 and "\n" not in start:
        return start
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    raise DefinitionMismatch("Original Worker birth cannot be verified")


async def owner_proof(runner, invocation):
    pid = os.getpid()
    start = await asyncio.to_thread(process_start, pid)
    if start is None:
        raise DefinitionMismatch("Original Worker process is unavailable")
    return {
        "version": 1,
        "pid": pid,
        "start": start,
        "deployment": deployment(runner),
        "invocation_id": invocation,
    }


async def original_owner_stopped(runner, owner):
    if type(owner) is not dict or owner.get("deployment") != deployment(runner):
        raise DefinitionMismatch("Coding stop requires the original Worker deployment")
    start = await asyncio.to_thread(process_start, owner["pid"])
    return start is None or start != owner["start"]


def callbacks(client, request, info, runtime):
    """Create fixed per-claim authorities using the original SDK handle."""
    from .temporal_coding_authority import TemporalCodingAuthority
    from .temporal_state import detached

    fixed = detached(request)
    workflow_id, epoch, namespace = info.workflow_id, info.workflow_run_id, info.workflow_namespace
    if (
        client is None
        or workflow_id != fixed["run_id"]
        or epoch != fixed["execution_epoch"]
        or namespace != client.namespace
    ):
        raise DefinitionMismatch("Coding lost its original Workflow epoch or namespace")
    handle = client.get_workflow_handle(workflow_id, run_id=epoch)

    async def authority(invocation, runner, *, recovery=False):
        from .task_controls import _binding
        from .temporal_deployment_coding_state import selected as deployment_coding_selected

        validation = None
        if deployment_coding_selected(fixed["runtime_manifest"]):
            from .temporal_deployment_coding_validation import CodingValidation

            validation = CodingValidation(runtime, client, fixed, info)
        validation_names = ("validate", "permission")
        if (
            validation is not None
            and fixed["runtime_manifest"]["deployment_admission_protocol"]["version"] == 4
        ):
            validation_names += ("_validate_readset",)
        bindings = (
            None
            if validation is None
            else tuple(_binding(getattr(validation, name)) for name in validation_names)
        )

        def check_validation():
            if (
                validation is not None
                and tuple(_binding(getattr(validation, name)) for name in validation_names)
                != bindings
            ):
                raise DefinitionMismatch("Original compact Coding validation callbacks changed")

        async def validate():
            from .temporal_session_activities import validate_tree_activity

            runtime.validate_release(fixed["runtime_manifest"])
            if client.namespace != namespace:
                raise DefinitionMismatch("Coding original namespace changed")
            check_validation()
            if validation is None:
                await validate_tree_activity(client, fixed, workflow_id=workflow_id)
            else:
                operation = (
                    validation._validate_readset
                    if "_validate_readset" in validation_names
                    else validation.validate
                )
                completed = await operation()
                if completed is not None:
                    raise DefinitionMismatch("Coding validation requires completed None")
            check_validation()
            if client.namespace != namespace:
                raise DefinitionMismatch("Coding namespace changed during validation")
            runtime.validate_release(fixed["runtime_manifest"])

        async def query(name, payload):
            return await handle.query(name, payload)

        async def update(name, payload):
            from .temporal_coding_recovery_transport import OPERATIONS, execute
            from .temporal_coding_state import CODING_GRANT

            if name in OPERATIONS:
                return await execute(client, workflow_id, name, payload, execution_epoch=epoch)

            if name == CODING_GRANT and validation is not None:
                from .temporal_deployment_coding_bridge import grant_allowed

                check_validation()
                allowed = await grant_allowed(runtime, client, fixed, info, validation)
                check_validation()
                if type(allowed) is not bool:
                    raise DefinitionMismatch("Coding grant validation requires completed boolean")
                if not allowed:
                    command_id = "ralf-deployment-coding-close:" + digest([workflow_id, epoch])
                    try:
                        await handle.execute_update(
                            "command",
                            {
                                "command_id": command_id,
                                "payload": {"kind": "cancel", "scope": fixed["scope"]},
                            },
                            id=command_id,
                        )
                    finally:
                        # A completed or uncertain original cancel still has
                        # an I/O boundary; never resend it to regain evidence.
                        await validate()
                    raise DefinitionMismatch("Original scoped Coding admission is closed")
            return await handle.execute_update(
                name, payload, id="ralf-coding:" + name + ":" + digest(payload)
            )

        return TemporalCodingAuthority(
            request=fixed,
            invocation_id=invocation,
            query=query,
            update=update,
            validate=validate,
            owner_proof=None if recovery else await owner_proof(runner, invocation),
        )

    return authority


async def execute(runtime, request, authority):
    from .delegated_coding import registered_coding_tool
    from .temporal_activities import _completed_none, _observation
    from .temporal_coding_protocol import check

    check(getattr(runtime, "_selected_host", None) or runtime, request["runtime_manifest"])
    envelope, tool = runtime._envelope(request)
    handler = registered_coding_tool(tool)
    if handler is None or authority is None:
        raise ValidationError("Coding requires its original History callbacks")
    observation = _observation(
        await handler.runner.execute_history(envelope, authority), "CodingRunner.execute_history"
    )
    handler.check()
    if observation is None:
        return {"ok": False, "code": "effect_outcome_unknown", "dispatched": True}
    await _completed_received(runtime, envelope, observation, _completed_none)
    return {"ok": True, "result": observation.result, "source": observation.source}


async def _completed_received(runtime, envelope, observation, completed):
    completed(await runtime.journal.received(envelope, observation), "EffectJournal.received")


async def stop(runtime, request, factory):
    from .delegated_coding import registered_coding_tool
    from .temporal_coding_protocol import check
    from .temporal_coding_state import CODING_STOP

    check(runtime, request["runtime_manifest"])
    envelope, tool = runtime._envelope(request)
    handler = registered_coding_tool(tool)
    authority = await factory(uuid.uuid4().hex, handler.runner, recovery=True)
    admitted = await authority._call(CODING_STOP, authority._proof, update=True)
    if (
        admitted.get("admitted") is not True
        or admitted.get("request") != request["coding_request"]
        or admitted.get("runner") != handler.identity
    ):
        raise DefinitionMismatch("Coding stop lost original History admission")
    from .codex_runner import RunnerOutcomeUnknown

    try:
        observation = await handler.runner.reconcile_history(envelope, authority)
    except RunnerOutcomeUnknown:
        observation = None
    handler.check()
    value = await authority._state()
    native = value["state"]
    owner = native.get("owner")
    if (
        native["fenced"]
        and not native["pending_stop"]
        and owner is not None
        and await original_owner_stopped(handler.runner, owner)
    ):
        await authority._call(
            "coding_owner_stopped",
            authority._proof
            | {"evidence": {"owner": owner, "process_present": False, "native_fenced": True}},
            update=True,
        )
    if observation is not None:
        from .temporal_activities import _completed_none

        await _completed_received(runtime, envelope, observation, _completed_none)
        return {"ok": True, "result": observation.result, "source": observation.source}
    return {"ok": True, "code": "effect_outcome_unknown", "dispatched": True, "queried": True}


async def close(runtime, *, client, scope):
    """Fence recorded original resources before draining calls or closing PG."""
    from dataclasses import asdict
    from types import SimpleNamespace

    from .delegated_coding import registered_coding_tool
    from .errors import CloseIncomplete

    if not runtime.coding_execution:
        return
    runtime._tool_execution_closing = True
    runtime.validate_release()
    runners = {}
    for name in runtime.tools._tools:
        handler = registered_coding_tool(runtime.tools.get(name))
        if handler is not None:
            runners[digest(handler.identity)] = handler.runner
    journals = {id(runner._journal): runner._journal for runner in runners.values()}
    for journal in journals.values():
        records = await journal.pending_resources(scope)
        for resource in records:
            if client is None or digest(resource["runner"]) not in runners:
                raise CloseIncomplete(
                    {"coding_execution": "original resources require their client and release"}
                )
            dispatch = resource["request"]["dispatch"]
            handle = client.get_workflow_handle(
                dispatch["run_id"], run_id=dispatch["execution_epoch"]
            )
            requests = await handle.query(
                "view", {"scope": asdict(scope), "kind": "coding_requests"}
            )
            if type(requests) is not list:
                raise CloseIncomplete({"coding_execution": "original History requests unavailable"})
            request = next(
                (
                    item
                    for item in requests
                    if item.get("action_id") == dispatch["action_id"]
                    and item.get("coding_request") == resource["request"]
                ),
                None,
            )
            if request is None:
                raise CloseIncomplete({"coding_execution": "original History resource differs"})
            runtime.validate_release(request["runtime_manifest"])
            info = SimpleNamespace(
                workflow_id=dispatch["run_id"],
                workflow_run_id=dispatch["execution_epoch"],
                workflow_namespace=client.namespace,
            )
            await stop(runtime, request, callbacks(client, request, info, runtime))
        if await journal.pending_resources(scope):
            raise CloseIncomplete({"coding_execution": "original native fencing remains pending"})
