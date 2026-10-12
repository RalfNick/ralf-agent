"""Borrowed fixed Artifact targets; original Context phases own adoption."""

import inspect
import json

from .artifacts import ArtifactReference
from .component_fingerprint import executable_digest
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .memory import _validate_expires_at, memory_call
from .ports import is_async_callable, is_sync_callable
from .skills import _plain, _text
from .task_controls import _binding
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import Scope, canonical, digest


def _scope(scope):
    if type(scope) is not Scope:
        raise ValidationError("Artifact binding requires an original trusted Scope")
    _text(scope.workspace, "Artifact workspace", 512)
    _text(scope.principal, "Artifact principal", 512)
    return {"workspace": scope.workspace, "principal": scope.principal}


def _identity(backend):
    value = _plain(getattr(backend, "identity", None))
    identifier = getattr(backend, "backend_id", None)
    _text(identifier, "Artifact backend identity", 512)
    if (
        type(value) is not dict
        or value.get("backend_id") != identifier
        or len(canonical(value).encode("utf-8")) > 65536
    ):
        raise ValidationError("Artifact backend requires bounded fixed physical JSON identity")
    return value


def _reference(value):
    if type(value) is not ArtifactReference:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Artifact binding requires a completed original reference")
    for name in (
        "backend_id",
        "workspace",
        "principal",
        "namespace",
        "content_digest",
        "artifact_id",
    ):
        _text(getattr(value, name), "Artifact reference " + name, 512)
    if type(value.byte_length) is not int:
        raise ValidationError("Artifact reference byte length must be an ordinary integer")
    ArtifactReference.__post_init__(value)
    return ArtifactReference.from_dict(ArtifactReference.to_dict(value))


class ArtifactBindingResource:
    def __init__(
        self,
        backend,
        *,
        version,
        namespaces=("context-results",),
        default_namespace="context-results",
        sync_mode="thread",
    ):
        _text(version, "Artifact binding version", 256)
        if type(namespaces) not in (tuple, list) or not 1 <= len(namespaces) <= 256:
            raise ValidationError("Artifact binding requires one to256 approved namespaces")
        for name in namespaces:
            _text(name, "Artifact namespace", 512)
        _text(default_namespace, "Artifact default namespace", 512)
        if len(set(namespaces)) != len(namespaces) or default_namespace not in namespaces:
            raise ValidationError("Artifact namespaces must be unique and include the default")
        if type(sync_mode) is not str or sync_mode not in {"thread", "coordinator"}:
            raise ValidationError("Artifact sync mode must be thread or coordinator")
        asynchronous = is_async_callable(getattr(backend, "put", None))
        predicate = is_async_callable if asynchronous else is_sync_callable
        if any(not predicate(getattr(backend, name, None)) for name in ("put", "get")):
            raise ValidationError(
                "Artifact backend methods must use one completed sync or async mode"
            )
        self._backend, self._asynchronous = backend, asynchronous
        self._backend_identity = canonical(_identity(backend))
        self._methods = {name: _binding(getattr(backend, name)) for name in ("put", "get")}
        self._namespaces, self._default, self._sync_mode = (
            tuple(namespaces),
            default_namespace,
            sync_mode,
        )
        self._threads = ThreadExecutionTracker()
        self._description = {
            "kind": "artifact-binding-resource",
            "version": "1",
            "behavior_version": version,
            "backend": _plain(_identity(backend)),
            "namespaces": list(namespaces),
            "default_namespace": default_namespace,
            "sync_mode": sync_mode,
            "asynchronous": asynchronous,
            "implementation": {
                name: executable_digest(getattr(backend, name)) for name in ("put", "get")
            },
        }
        self._pin = canonical(self._description)
        self._original = (backend, self._namespaces, default_namespace, sync_mode, asynchronous)

    def check(self):
        if (
            (self._backend, self._namespaces, self._default, self._sync_mode, self._asynchronous)
            != self._original
            or canonical(self._description) != self._pin
            or canonical(_identity(self._backend)) != self._backend_identity
            or any(
                _binding(getattr(self._backend, name, None)) != original
                for name, original in self._methods.items()
            )
        ):
            raise DefinitionMismatch("Original Artifact resource or delegated backend changed")

    @property
    def identity(self):
        self.check()
        return _plain(self._description)

    def select(self, selector, scope):
        self.check()
        _scope(scope)
        if type(selector) is not dict or set(selector) - {"namespace"}:
            raise ValidationError("Artifact selector supports only namespace")
        name = selector.get("namespace", self._default)
        _text(name, "Selected Artifact namespace", 512)
        if name not in self._namespaces:
            raise AuthorizationDenied("Artifact namespace is not approved by the host")
        return ArtifactView(self, scope, name)

    async def wait_for_calls(self):
        await self._threads.drain()


class ArtifactView:
    def __init__(self, resource, scope, namespace):
        if type(resource) is not ArtifactBindingResource:
            raise ValidationError("Artifact view requires its original host resource")
        resource.check()
        _text(namespace, "Selected Artifact namespace", 512)
        if namespace not in resource._namespaces:
            raise AuthorizationDenied("Artifact namespace is not approved by the host")
        self._target, self._scope_json, self._namespace = (
            resource,
            canonical(_scope(scope)),
            namespace,
        )
        self._identity = canonical(
            {
                "kind": "artifact-binding-view",
                "version": "1",
                "backend_id": resource.identity["backend"]["backend_id"],
                "target": resource.identity,
                "scope": _scope(scope),
                "namespace": namespace,
            }
        )
        self._original = (resource, self._scope_json, namespace, self._identity)
        self._methods = {
            name: _binding(getattr(self, name)) for name in ("put", "get", "_check", "_call")
        }

    def _verify(self):
        if (
            self._target is not self._original[0]
            or (self._scope_json, self._namespace, self._identity) != self._original[1:]
            or any(
                _binding(getattr(self, name, None)) != original
                for name, original in self._methods.items()
            )
        ):
            raise DefinitionMismatch("Original Artifact view changed")
        self._target.check()

    @property
    def namespace(self):
        return self._namespace

    @property
    def backend_id(self):
        return self._target.identity["backend"]["backend_id"]

    @property
    def resource(self):
        return {"backend_id": self.backend_id, "namespace": self.namespace}

    @property
    def identity(self):
        ArtifactView._verify(self)
        value = _plain(json.loads(self._identity))
        if (
            value["namespace"] != self.namespace
            or value["target"] != self._target.identity
            or any(
                _binding(getattr(self, name, None)) != original
                for name, original in self._methods.items()
            )
        ):
            raise DefinitionMismatch("Original Artifact view changed")
        return value

    def _check(self, scope, namespace):
        _ = self.identity
        _text(namespace, "Artifact operation namespace", 512)
        if canonical(_scope(scope)) != self._scope_json or namespace != self.namespace:
            raise AuthorizationDenied("Artifact operation is outside the selected resource")

    async def _call(self, name, *args, **kwargs):
        target = self._target
        target.check()
        method = getattr(target._backend, name)
        if not target._asynchronous and target._sync_mode == "thread":
            tracker = current_thread_tracker.get() or target._threads
            result = await tracker.run(method, *args, group=current_thread_group.get(), **kwargs)
        elif target._asynchronous:
            result = await memory_call(method, *args, **kwargs)
        else:
            result = method(*args, **kwargs)
            if (
                inspect.isawaitable(result)
                or inspect.isgenerator(result)
                or inspect.isasyncgen(result)
            ):
                if inspect.iscoroutine(result) or inspect.isgenerator(result):
                    result.close()
                raise ValidationError("Synchronous Artifact methods require completed values")
        target.check()
        return result

    async def put(self, scope, namespace, value, *, expires_at=None):
        ArtifactView._verify(self)
        self._check(scope, namespace)
        value = _plain(value)
        text = canonical(value)
        size = len(text.encode("utf-8"))
        if size > 1048576:
            raise ValidationError("Artifact binding JSON exceeds one MiB")
        metadata = {
            "backend_id": self.backend_id,
            **_scope(scope),
            "namespace": namespace,
            "content_digest": digest(value),
            "byte_length": size,
            "expires_at": _validate_expires_at(expires_at),
        }
        expected = ArtifactReference(**metadata, artifact_id=digest(metadata))
        received = _reference(
            await self._call("put", scope, namespace, value, expires_at=expires_at)
        )
        self._check(scope, namespace)
        if received != expected:
            raise DefinitionMismatch("Artifact put receipt differs from its original intent")
        return received

    async def get(self, scope, reference, *, max_bytes=None):
        ArtifactView._verify(self)
        reference = _reference(reference)
        self._check(scope, reference.namespace)
        if reference.backend_id != self.backend_id or (
            reference.workspace,
            reference.principal,
        ) != (scope.workspace, scope.principal):
            raise AuthorizationDenied("Artifact reference is outside the selected resource")
        value = _plain(await self._call("get", scope, reference, max_bytes=max_bytes))
        self._check(scope, reference.namespace)
        if (
            digest(value) != reference.content_digest
            or len(canonical(value).encode("utf-8")) != reference.byte_length
        ):
            raise DefinitionMismatch("Artifact value differs from its original reference")
        return value
