"""Host-authorized immutable Session views; execution admission lives elsewhere."""

from dataclasses import dataclass

from .binding_types import text
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .memory import ThreadedMemoryAdapter, memory_call
from .recall import LegacyMemoryRecallAdapter
from .types import Scope, canonical


def session_storage_key(namespace, session_id):
    text(session_id, "Session ID")
    return (
        session_id if namespace is None else "ralf-session-v1:" + canonical([namespace, session_id])
    )


def session_identity(backend):
    if isinstance(backend, SessionView):
        raise ValidationError(
            "Register the original Session backend or SessionBindingResource, not a selected view"
        )
    identity = text(getattr(backend, "backend_id", None), "Session backend identity")
    if any(not callable(getattr(backend, name, None)) for name in ("read", "append")):
        raise ValidationError("Session backend must implement read and append")
    return {"backend_id": identity}


def namespace_options(namespaces, default_namespace):
    if not isinstance(namespaces, (tuple, list)) or not namespaces:
        raise ValidationError("Session resource requires a host namespace allowlist")
    if any(
        value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 128)
        for value in namespaces
    ):
        raise ValidationError("Session namespace requires 1 to 128 characters or None")
    if len(set(namespaces)) != len(namespaces) or default_namespace not in namespaces:
        raise ValidationError("Session namespaces must be unique and include the default")
    return tuple(namespaces)


@dataclass(frozen=True, init=False)
class SessionBindingResource:
    backend: object
    namespaces: tuple
    default_namespace: str | None

    def __init__(self, backend, *, namespaces=(None,), default_namespace=None):
        session_identity(backend)
        namespaces = namespace_options(namespaces, default_namespace)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "namespaces", namespaces)
        object.__setattr__(self, "default_namespace", default_namespace)

    @property
    def identity(self):
        return {
            "kind": "session-binding-resource",
            "version": "1",
            **session_identity(self.backend),
            "namespaces": list(self.namespaces),
            "default_namespace": self.default_namespace,
        }

    def select(self, selector, scope):
        if set(selector) - {"namespace"}:
            raise ValidationError("Session selector supports only namespace")
        namespace = selector.get("namespace", self.default_namespace)
        if namespace not in self.namespaces:
            raise AuthorizationDenied("Session namespace is not authorized by the host")
        return SessionView(self.backend, scope, namespace, self.backend.backend_id)


@dataclass(frozen=True)
class SessionView:
    backend: object
    scope: Scope
    namespace: str | None
    original_backend_id: str

    @property
    def backend_id(self):
        return self.backend.backend_id

    @property
    def resource(self):
        storage = (
            self.backend.backend
            if isinstance(self.backend, ThreadedMemoryAdapter)
            else self.backend
        )
        return {"backend_id": storage.backend_id, "namespace": self.namespace}

    def storage_key(self, session_id):
        return session_storage_key(self.namespace, session_id)

    def _check(self, scope):
        if scope != self.scope:
            raise AuthorizationDenied("Session view belongs to another trusted Scope")
        if self.backend_id != self.original_backend_id:
            raise DefinitionMismatch("The actual Session backend changed")

    async def read(self, scope, session_id):
        self._check(scope)
        value = await memory_call(self.backend.read, scope, self.storage_key(session_id))
        self._check(scope)
        return value

    async def append(self, scope, session_id, message, *, expected_revision, message_id):
        self._check(scope)
        value = await memory_call(
            self.backend.append,
            scope,
            self.storage_key(session_id),
            message,
            expected_revision=expected_revision,
            message_id=message_id,
        )
        self._check(scope)
        return value

    async def read_page(self, scope, session_id, query):
        self._check(scope)
        method = getattr(self.backend, "read_page", None)
        if not callable(method):
            method = LegacyMemoryRecallAdapter(self.backend).read_page
        value = await memory_call(method, scope, self.storage_key(session_id), query)
        self._check(scope)
        return value

    async def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import supports_remote_session, validate_inspection

        self._check(scope)
        if not supports_remote_session(self.backend):
            raise ValidationError("Session backend does not support exact write receipts")
        address = self.storage_key(session_id)
        value = await memory_call(self.backend.inspect_message, scope, address, message_id)
        self._check(scope)
        return validate_inspection(value, scope, address, message_id)
