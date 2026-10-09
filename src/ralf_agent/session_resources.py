"""Canonical Session claims, committed by the existing execution authority."""

import inspect

from .binding_sessions import session_storage_key
from .errors import ValidationError
from .ports import is_sync_callable
from .types import canonical


def session_claims(manifest, session_ids, plan=None):
    claims = []

    def add(backend, session, namespace=None):
        if backend is not None:
            claim = {"backend_id": backend, "session_id": session_storage_key(namespace, session)}
            if claim not in claims:
                claims.append(claim)

    bindings = manifest.get("agent_bindings")
    if bindings is None or "orchestration" in manifest:
        for session in session_ids:
            add(manifest.get("session_backend"), session)
    else:
        parallel = plan is not None and plan["schema_version"] == 3
        if "node_paths" in bindings:
            # The graph coordinator and direct nodes retain their host Session.
            add(manifest.get("session_backend"), session_ids[0])
        for path, entry in bindings["steps"].items():
            session = session_ids[0]
            if parallel:
                node_id = path.removeprefix("graph/nodes/")
                session += ":node:" + node_id
            resource = entry["resolved"]["session"].get("resource", {})
            add(
                resource.get("backend_id", entry["manifest"].get("session_backend")),
                session,
                resource.get("namespace"),
            )
        if parallel:
            for node in plan["nodes"]:
                if node["agent"] is None:
                    add(manifest.get("session_backend"), session_ids[0] + ":node:" + node["id"])
    return claims


def run_session_claims(run):
    return (
        run.get("session_resources")
        if "session_resources" in run
        else session_claims(
            run["manifest"], run.get("session_ids", [run["session_id"]]), run.get("plan")
        )
    )


def same_session_address(left, right):
    if left["session_id"] != right["session_id"]:
        return False
    a, b = left["backend_id"], right["backend_id"]
    # Legacy ThreadedMemoryAdapter encoded its delegation in backend_id, with
    # no separate storage address. Conservatively retain that known alias.
    return a == b or a == "threaded:" + b or b == "threaded:" + a


def admit_sessions(engine, manifest, session_ids, plan=None):
    """Called only inside first command acceptance; no independent lock/state."""
    claims = session_claims(manifest, session_ids, plan)
    owner = getattr(engine.store, "session_resource_owner", None)
    new_resources = any(
        entry["descriptor"]["session"]["mode"] == "ref"
        for entry in manifest.get("agent_bindings", {}).get("steps", {}).values()
    )
    if new_resources and not is_sync_callable(owner):
        raise ValidationError("Session refs require execution-authority Session resource admission")
    if callable(owner):
        if not is_sync_callable(owner):
            raise ValidationError("Session resource admission must be synchronous")
        for claim in claims:
            result = owner(engine.scope, claim)
            if result is not None and (not isinstance(result, str) or not result.strip()):
                if inspect.iscoroutine(result) or inspect.isgenerator(result):
                    result.close()
                raise ValidationError("Session resource owner must return a Run ID or None")
            if result is not None:
                raise ValidationError("Session resource already belongs to an active Run")
    elif any(engine.store.session_owner(engine.scope, name) for name in session_ids):
        raise ValidationError("Session already belongs to an active Run")
    if not new_resources:
        return {}
    # Old readers only know raw Session IDs: retain actual storage-key aliases.
    aliases = list(dict.fromkeys([*session_ids, *(claim["session_id"] for claim in claims)]))
    canonical(claims)
    return {"session_resources": claims, "session_ids": aliases}
