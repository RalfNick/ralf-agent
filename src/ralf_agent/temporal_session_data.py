"""Fixed scoped Session read ports; original Context History adopts the evidence."""

from dataclasses import asdict, replace

from .binding_sessions import SessionBindingResource, SessionView
from .errors import DefinitionMismatch, ValidationError
from .fact_index_ports import _FixedPorts
from .memory import InMemoryMemory, SQLiteMemory, ThreadedMemoryAdapter
from .recall import RecallPage, RecallQuery
from .session_receipts import supports_remote_session
from .temporal_session_data_state import private_address as private_address
from .temporal_session_data_state import references
from .types import Scope, canonical


def _physical(backend):
    if isinstance(backend, ThreadedMemoryAdapter):
        return {"kind": "threaded", "source": _physical(backend.backend)}
    if isinstance(backend, SQLiteMemory):
        return {"kind": "sqlite", "backend_id": backend.backend_id, "path": backend.store.path}
    if isinstance(backend, InMemoryMemory):
        return {"kind": "memory", "instance": backend._session_instance_id}
    from .data_resources import remote_physical

    physical = remote_physical(backend)
    if physical:
        if physical["kind"] == "postgres":
            routing = getattr(backend, "_table_schemas", None)
            if not routing:
                raise ValidationError("Initialize PostgreSQL Session tables before registration")
            physical["tables"] = dict(routing)
        return physical
    value = getattr(backend, "identity", None)
    if type(value) is not dict or not value:
        raise ValidationError("Custom Session data requires an explicit physical resource identity")
    return {"kind": "custom", "resource": value}


class SessionReadRegistration:
    def __init__(self, source, query):
        if isinstance(source, SessionView):
            raise ValidationError("Register the original Session source, not a selected view")
        self.source = source
        self.resource = (
            source if isinstance(source, SessionBindingResource) else SessionBindingResource(source)
        )
        self.backend = self.resource.backend
        self._original_source = (
            self.backend.backend
            if isinstance(self.backend, ThreadedMemoryAdapter)
            else self.backend
        )
        if not isinstance(query, RecallQuery) or query.cursor is not None:
            raise ValidationError("Session data requires a fixed RecallQuery without a cursor")
        self.query = replace(query)
        if not callable(getattr(self._original_source, "read_page", None)):
            raise ValidationError("Session data requires a native bounded read_page port")
        if not supports_remote_session(self.backend):
            raise ValidationError("Session data requires exact message receipt v1")
        ports = {"session": (self.backend, ["read_page", "append", "inspect_message"], True)}
        if self._original_source is not self.backend:
            ports["session-source"] = (
                self._original_source,
                ["read_page", "append", "inspect_message"],
                True,
            )
        self.fixed = _FixedPorts(ports)
        from .temporal_state import detached

        roots = [self.backend]
        if isinstance(self.backend, ThreadedMemoryAdapter):
            roots.append(self.backend.backend)
        self._clients = [
            (owner, name, getattr(owner, name))
            for owner in roots
            for name in ("_client", "connection")
            if hasattr(owner, name)
        ]
        self._clients.extend(
            (client, "connection_pool", client.connection_pool)
            for _, _, client in list(self._clients)
            if hasattr(client, "connection_pool")
        )
        self.physical = detached(_physical(self.backend))
        self._identity = {
            "version": 1,
            "identity": self.resource.identity,
            "physical": self.physical,
            "port": self.fixed.identity,
            "query": asdict(self.query),
            "namespace": self.resource.default_namespace,
            "receipt_version": 1,
        }
        canonical(self._identity)

    def check(self):
        self.fixed.check()
        if any(getattr(owner, name, None) is not client for owner, name, client in self._clients):
            raise DefinitionMismatch("Temporal Session client or pool changed")
        if (
            self.resource.backend is not self.backend
            or (
                isinstance(self.backend, ThreadedMemoryAdapter)
                and self.backend.backend is not self._original_source
            )
            or not supports_remote_session(self.backend)
            or self.resource.identity != self._identity["identity"]
            or _physical(self.backend) != self.physical
        ):
            raise DefinitionMismatch("Temporal Session data resource changed")

    @property
    def identity(self):
        from .temporal_state import detached

        self.check()
        return detached(self._identity)


def registration(source, query):
    return SessionReadRegistration(source, query).identity


def selected_registration(runtime, request):
    source = runtime.session_store
    backend = (
        source.backend if isinstance(source, (SessionBindingResource, SessionView)) else source
    )
    for original in runtime._session_read_pins:
        if original.backend is backend:
            return original
    raise DefinitionMismatch("Original Session read source is unavailable")


async def load(runtime, request):
    if runtime.session_store is None:
        return {}
    from .temporal_session_data_state import expected_read, validate_snapshot
    from .temporal_state import detached

    manifest = runtime.manifest
    expected = expected_read(manifest, request)
    original = selected_registration(runtime, request)
    original.check()
    query = RecallQuery(**expected["query"])
    page = await original.fixed.call(
        "session", "read_page", Scope(**request["scope"]), expected["address"], query
    )
    runtime.validate_release(request["runtime_manifest"])
    original.check()
    if not isinstance(page, RecallPage):
        from .temporal_activities import _close_lazy

        _close_lazy(page)
        raise ValidationError("Session bounded read requires a completed RecallPage")
    import json

    try:
        revision = json.loads(page.snapshot_id)["revision"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Session snapshot requires an exact revision") from exc
    evidence = {**expected, "page": asdict(page), "revision": revision}
    result = {"session_data": evidence, "session_data_references": references(evidence)}
    validate_snapshot(result, manifest, request)
    return detached(result)
