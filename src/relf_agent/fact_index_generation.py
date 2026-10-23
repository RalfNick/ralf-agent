"""Fixed-snapshot generations over the original bounded Facts-index algorithm.

Build and active records are isolated by source snapshot. A late historical
publisher cannot replace the current generation, while ordinary recall retains
original source validation. All data ports are borrowed; this wrapper creates
no execution authority, retry loop, embedding transport or resource ownership.
Automatic maintenance factories admit native SQLite/Hash compositions only.
"""

import contextvars
import copy
import json
from dataclasses import asdict

from .binding_artifacts import _method_binding, _same_binding
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .fact_index import IndexedMemoryStore
from .fact_index_ports import _FixedPorts
from .recall import _name
from .tools import _callable_identity
from .types import Scope, canonical, digest


class GenerationSourceChanged(ValidationError):
    """The selected maintenance invocation no longer has its original snapshot."""


def _pins(target, methods):
    return tuple(
        (
            name,
            _method_binding(getattr(target, name)),
            digest(_callable_identity(getattr(target, name))),
        )
        for name in methods
    )


def _check_pins(target, pins):
    for name, binding, fingerprint in pins:
        current = getattr(target, name, None)
        if (
            not callable(current)
            or not _same_binding(_method_binding(current), binding)
            or digest(_callable_identity(current)) != fingerprint
        ):
            raise DefinitionMismatch("Generation index operation binding changed")


def _identity_getter(target):
    value = getattr(type(target), "identity", None)
    return value.fget if isinstance(value, property) else value


class _GenerationPorts(_FixedPorts):
    """Check pinned-source adoption without changing original registered ports."""

    def __init__(self, original, owner):
        self._original = self._original_ref = original
        self._owner = self._owner_ref = owner
        self._ports = self._ports_ref = original._ports
        self._original_methods = _pins(original, ("check", "call"))
        self._selector = _pins(owner, ("_snapshot", "_selection"))
        self._methods = _pins(self, ("check", "call", "_source_current"))
        self._identity_getter = type(self).identity.fget

    def check(self):
        if (
            self._original is not self._original_ref
            or self._owner is not self._owner_ref
            or self._ports is not self._ports_ref
            or self._ports is not self._original._ports
            or type(self).identity.fget is not self._identity_getter
        ):
            raise DefinitionMismatch("Generation source-read boundary resource changed")
        _check_pins(self, self._methods)
        _check_pins(self._original, self._original_methods)
        _check_pins(self._owner, self._selector)
        self._original.check()

    async def _source_current(self, args):
        scope, namespace = args[:2]
        self._owner._selection(scope, namespace)
        await self._owner._snapshot(scope, namespace)

    async def call(self, role, name, *args, **kwargs):
        self.check()
        guarded = (
            role == "source"
            and name in {"scan_facts", "validate_facts", "inspect_fact"}
            and self._owner._expected.get() is not None
        )
        if not guarded:
            return await self._original.call(role, name, *args, **kwargs)
        try:
            result = await self._original.call(role, name, *args, **kwargs)
        except ValidationError:
            # Source cursor/schema validation can refuse after a real writer.
            # Only this source-read boundary rechecks; CAS, budget and all other
            # operations keep their original refusal and pending effect intent.
            await self._source_current(args)
            raise
        await self._source_current(args)
        return result


class _GenerationCatalog:
    """Route existing build/active operations; original effect journal is separate."""

    def __init__(self, original, owner):
        self.original, self.owner = original, owner
        self._original, self._owner = original, owner
        self._original_pin = canonical(original.identity)
        self._original_identity_getter = _identity_getter(original)
        self._original_methods = _pins(original, ("load", "save"))
        self._delegate = _FixedPorts({"original": (original, ["load", "save"], False)})
        self._delegate_ref = self._delegate
        self._selector = _pins(owner, ("_generation_snapshot",))
        self._methods = _pins(self, ("load", "save", "_key"))
        self._identity_getter = type(self).identity.fget

    @property
    def identity(self):
        if (
            self.original is not self._original
            or self.owner is not self._owner
            or self._delegate is not self._delegate_ref
            or _identity_getter(self.original) is not self._original_identity_getter
            or type(self).identity.fget is not self._identity_getter
        ):
            raise DefinitionMismatch("Generation catalog resource changed")
        _check_pins(self, self._methods)
        _check_pins(self.original, self._original_methods)
        _check_pins(self.owner, self._selector)
        if canonical(self.original.identity) != self._original_pin:
            raise DefinitionMismatch("Generation catalog original transport changed")
        return {
            "kind": "fact-index-generation-catalog",
            "version": "1",
            "key_scheme": "build-active:sha256-source-snapshot-v1",
            "original": json.loads(self._original_pin),
            "selection": json.loads(self.owner._selection_pin),
            "implementation": {name: pin for name, _, pin in self._methods},
        }

    async def _key(self, scope, key):
        _ = self.identity
        if type(key) is not str or key not in {"build", "active"}:
            raise ValidationError("Generation catalog routes only build and active records")
        snapshot = await self.owner._generation_snapshot(scope)
        _ = self.identity
        return key + ":" + digest(snapshot), snapshot

    async def load(self, scope, index_id, key):
        selected, snapshot = await self._key(scope, key)
        result = await self._delegate.call("original", "load", scope, index_id, selected)
        _ = self.identity
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or type(result[0]) is not int
            or result[0] < 0
            or (
                result[1] is not None
                and (type(result[1]) is not dict or result[1].get("source_snapshot") != snapshot)
            )
        ):
            raise ValidationError("Generation catalog receipt does not match its selected snapshot")
        return result[0], copy.deepcopy(result[1])

    async def save(self, scope, index_id, key, value, *, expected_version):
        selected, snapshot = await self._key(scope, key)
        if type(value) is not dict or value.get("source_snapshot") != snapshot:
            raise ValidationError("Generation catalog state does not match its selected snapshot")
        result = await self._delegate.call(
            "original",
            "save",
            scope,
            index_id,
            selected,
            copy.deepcopy(value),
            expected_version=expected_version,
        )
        _ = self.identity
        if type(result) is not int or result != expected_version + 1:
            raise ValidationError("Generation catalog commit has an invalid CAS receipt")
        return result


class GenerationIndexedMemoryStore(IndexedMemoryStore):
    """One fixed selection, per-invocation snapshot, inherited original algorithms.

    ``original_catalog`` is the original borrowed catalog passed to the constructor
    and is available for a separate exact maintenance-effect journal. ``catalog``
    is the internal generation-key routing delegate. Neither is owned/closed here.
    """

    def __init__(
        self,
        backend,
        embedding,
        index,
        catalog,
        *,
        scope,
        namespace,
        batch_size=32,
        max_page_bytes=64000,
        min_score=-1,
        max_records=100000,
    ):
        if type(scope) is not Scope:
            raise ValidationError("Generation index requires a trusted native Scope")
        _name(namespace, "Generation Facts namespace")
        if type(namespace) is not str or len(namespace) > 128:
            raise ValidationError("Generation Facts namespace exceeds its fixed selection bound")
        self._scope = Scope(scope.workspace, scope.principal)
        self._namespace = namespace
        self._selection_pin = canonical({"scope": asdict(self._scope), "namespace": namespace})
        self._expected = contextvars.ContextVar("ralf-fact-index-expected-snapshot", default=None)
        self._expected_ref = self._expected
        self.original_catalog = self._original_catalog = catalog
        self._routing = _GenerationCatalog(catalog, self)
        super().__init__(
            backend,
            embedding,
            index,
            self._routing,
            batch_size=batch_size,
            max_page_bytes=max_page_bytes,
            min_score=min_score,
            max_records=max_records,
        )
        self._source_ports = self._source_ports_ref = _GenerationPorts(self._fixed, self)
        self._source_boundary_methods = _pins(
            self._source_ports, ("check", "call", "_source_current")
        )
        self._fixed = self._source_ports
        self._generation_methods = _pins(
            self,
            tuple(
                dict.fromkeys(
                    (
                        *self._hooks,
                        "source_snapshot",
                        "rebuild_for_snapshot",
                        "_generation_snapshot",
                        "_selection",
                    )
                )
            ),
        )
        self._identity_getter = type(self).identity.fget
        self._data_methods = (
            (
                backend,
                _pins(backend, ("scan_facts", "fact_snapshot", "inspect_fact", "validate_facts")),
            ),
            (embedding, _pins(embedding, ("embed",))),
            (index, _pins(index, ("upsert", "search"))),
            (catalog, _pins(catalog, ("load", "save"))),
        )

    @property
    def identity(self):
        if (
            self._expected is not self._expected_ref
            or self._fixed is not self._source_ports
            or self._source_ports is not self._source_ports_ref
            or self.original_catalog is not self._original_catalog
            or self.catalog is not self._routing
            or type(self).identity.fget is not self._identity_getter
        ):
            raise DefinitionMismatch("Generation index selected resource changed")
        if (
            type(self._scope) is not Scope
            or type(self._namespace) is not str
            or canonical({"scope": asdict(self._scope), "namespace": self._namespace})
            != self._selection_pin
        ):
            raise DefinitionMismatch("Generation index fixed selection changed")
        _check_pins(self, self._generation_methods)
        _check_pins(self._source_ports, self._source_boundary_methods)
        for target, pins in self._data_methods:
            _check_pins(target, pins)
        value = super().identity
        value["generation_protocol"] = {
            "kind": "fixed-source-snapshot-generation-index",
            "version": "1",
            "selection": json.loads(self._selection_pin),
            "implementation": {name: pin for name, _, pin in self._generation_methods},
            "source_read_boundary": {
                "version": "1",
                "implementation": {name: pin for name, _, pin in self._source_boundary_methods},
            },
        }
        return value

    def _selection(self, scope, namespace):
        if (
            type(scope) is not Scope
            or type(namespace) is not str
            or canonical({"scope": asdict(scope), "namespace": namespace}) != self._selection_pin
        ):
            raise AuthorizationDenied(
                "Generation index selection belongs to another Scope or namespace"
            )

    def _address(self, scope, namespace):
        self._selection(scope, namespace)
        return super()._address(scope, namespace)

    async def source_snapshot(self, scope, namespace):
        """Return actual current source identity, without changing index metadata."""
        self._selection(scope, namespace)
        return await super()._snapshot(scope, namespace)

    async def _snapshot(self, scope, namespace):
        self._selection(scope, namespace)
        result = await super()._snapshot(scope, namespace)
        expected = self._expected.get()
        if expected is not None and result != expected:
            raise GenerationSourceChanged("Generation index original source snapshot changed")
        return result

    async def _generation_snapshot(self, scope):
        self._selection(scope, self._namespace)
        expected = self._expected.get()
        if expected is not None:
            return expected
        return await self.source_snapshot(scope, self._namespace)

    async def rebuild_for_snapshot(self, scope, namespace, expected_snapshot, *, max_pages=64):
        self._selection(scope, namespace)
        _ = self.identity
        if type(expected_snapshot) is not str:
            raise ValidationError("Generation expected source snapshot must be a string")
        _name(expected_snapshot, "Generation expected source snapshot")
        if self._expected.get() is not None:
            raise ValidationError("Generation rebuild cannot reenter a pinned invocation")
        token = self._expected.set(expected_snapshot)
        try:
            result = await super().rebuild(scope, namespace, max_pages=max_pages)
            _ = self.identity
            if result["source_snapshot"] != expected_snapshot:
                raise GenerationSourceChanged(
                    "Generation rebuild returned a substituted source snapshot"
                )
            return result
        finally:
            self._expected_ref.reset(token)
