"""Resolve server queue metadata before selecting an original published facade."""

from .agent_run import RunRef
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .temporal_state import WORKFLOW_NAME
from .types import digest


async def original_queue(host, identity, *, kinds):
    host._check(started=True)
    await host._check_namespace(started=True)
    description = await host._client.get_workflow_handle(identity).describe()
    await host._check_namespace(started=True)
    if (
        description.id != identity
        or description.namespace != host._route[1]
        or description.workflow_type not in kinds
        or description.task_queue not in host._queues
    ):
        raise DefinitionMismatch("Original Workflow queue, type or namespace is unavailable")
    return host._queues[description.task_queue]


async def attach_run(host, ref):
    from .temporal_parent_state import PARENT_WORKFLOW_NAME

    if not isinstance(ref, RunRef):
        raise ValidationError("Host attachment requires an immutable RunRef")
    if (ref.workspace, ref.principal) != (host.scope.workspace, host.scope.principal):
        raise AuthorizationDenied("RunRef belongs to another trusted Scope")
    assembly = await original_queue(host, ref.run_id, kinds={WORKFLOW_NAME, PARENT_WORKFLOW_NAME})
    runtime = host.runtime(assembly.profile.identity)
    attached = await runtime.aattach(ref)
    info = await attached.diagnostics()
    await host._check_namespace(started=True)
    if info.manifest.get("runtime_profile") != assembly.profile.identity or digest(
        info.manifest
    ) != digest(assembly.release):
        raise DefinitionMismatch("Original Workflow differs from its declared Profile release")
    return attached


async def attach_session(host, ref):
    from .session_types import SessionRef
    from .temporal_session_client import TemporalSessionClient
    from .temporal_session_state import SESSION_WORKFLOW, workflow_id

    if not isinstance(ref, SessionRef):
        raise ValidationError("Host attachment requires an immutable SessionRef")
    if (ref.key.workspace, ref.key.principal) != (host.scope.workspace, host.scope.principal):
        raise AuthorizationDenied("SessionRef belongs to another trusted Scope")
    coordinator = await original_queue(host, workflow_id(ref.key), kinds={SESSION_WORKFLOW})
    coordinator_engine = host._engines[digest(coordinator.profile.identity)]
    client = TemporalSessionClient(coordinator_engine, host._namespace_id)
    metadata = await client.view(ref, "profile_binding")
    await host._check_namespace(started=True)
    if (
        type(metadata) is not dict
        or set(metadata)
        != {"schema_version", "session_ref", "profile_identity", "task_queue", "manifest_digest"}
        or type(metadata["schema_version"]) is not int
        or metadata["schema_version"] != 1
        or metadata["session_ref"] != ref.to_dict()
    ):
        raise DefinitionMismatch("Session binding differs from its original reference")
    profile = host._profile(metadata["profile_identity"])
    assembly = host._queues.get(metadata["task_queue"])
    if (
        assembly is None
        or assembly.profile.identity != profile.identity
        or digest(assembly.release) != metadata["manifest_digest"]
    ):
        raise DefinitionMismatch("Original Session binding queue or release is unavailable")
    attached = await host.runtime(profile.identity).aattach_session(ref)
    await host._check_namespace(started=True)
    return attached
