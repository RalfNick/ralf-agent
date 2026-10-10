"""Fixed borrowed data ports and a replaceable CAS catalog for derived indexes."""

import copy
import inspect
from typing import Protocol

from .errors import (
    BudgetExceeded,
    DefinitionMismatch,
    MemoryBackendError,
    RalfError,
    ValidationError,
)
from .fact_scan import _scan_size
from .recall import _fact_inputs, _fact_records, _integer, _name
from .retrieval_pipeline import _component, _lazy
from .storage import SQLiteStore
from .task_controls import _binding
from .types import digest


class FactIndexMetadataStore(Protocol):
    """Borrowed CAS metadata SPI; values are bounded JSON index control receipts.

    load returns (revision, detached value), or (0, None) when absent.
    save atomically checks expected_version and returns expected_version + 1.
    identity must fix the physical resource and the durable format version.
    """

    @property
    def identity(self) -> dict: ...

    def load(self, scope, index_id: str, key: str) -> tuple[int, dict | None]: ...

    def save(
        self, scope, index_id: str, key: str, value: dict, *, expected_version: int
    ) -> int: ...


class AsyncFactIndexMetadataStore(Protocol):
    """Native async equivalent, with the same CAS and durability contract."""

    @property
    def identity(self) -> dict: ...

    async def load(self, scope, index_id: str, key: str) -> tuple[int, dict | None]: ...

    async def save(
        self, scope, index_id: str, key: str, value: dict, *, expected_version: int
    ) -> int: ...


class _DataPort:
    def __init__(self, backend):
        self.backend = backend

    @property
    def identity(self):
        value = {"backend_id": self.backend.backend_id}
        declared = getattr(self.backend, "identity", None)
        if declared is not None:
            if not isinstance(declared, dict):
                _lazy(declared)
                raise ValidationError("Index data backend identity must be a JSON object")
            value["resource"] = copy.deepcopy(declared)
        for field in ("dimensions", "fact_scan_version", "fact_inspection_version"):
            if hasattr(self.backend, field):
                value[field] = getattr(self.backend, field)
        return value

    def __getattr__(self, name):
        return getattr(self.backend, name)


class _FixedPorts:
    def __init__(self, ports):
        self._ports = {}
        self._native = []
        for name, (backend, methods, data) in ports.items():
            target = _DataPort(backend) if data else backend
            self._ports[name] = (backend, _component(target, methods))
            store = getattr(backend, "store", None) if data else None
            if isinstance(store, SQLiteStore):
                self._native.append((backend, store, store.path, store.conn))

    @property
    def identity(self):
        self.check()
        return {name: captured[1] for name, (_, captured) in self._ports.items()}

    def check(self):
        for backend, store, path, connection in self._native:
            if backend.store is not store or store.path != path or store.conn is not connection:
                raise DefinitionMismatch("Index native database resource changed")
            store._assert_file_identity()
        for backend, (target, identity, bindings) in self._ports.values():
            if isinstance(target, _DataPort) and target.backend is not backend:
                raise DefinitionMismatch("Index data port changed")
            if any(
                _binding(getattr(target, name, None)) != original for name, original, _ in bindings
            ) or digest(_component(target, [name for name, _, _ in bindings])[1]) != digest(
                identity
            ):
                raise DefinitionMismatch("Index component registration changed")

    async def call(self, role, name, *args, **kwargs):
        self.check()
        _, (target, _, bindings) = self._ports[role]
        mode = next(mode for method, _, mode in bindings if method == name)
        try:
            result = getattr(target, name)(*args, **kwargs)
            if mode == "async":
                if not inspect.isawaitable(result):
                    _lazy(result)
                    raise ValidationError("Async index port must return awaitable")
                result = await result
            else:
                if inspect.isawaitable(result):
                    _lazy(result)
                    raise ValidationError("Sync index port returned unexpected awaitable")
            self.check()
            return result
        except RalfError:
            raise
        except Exception:
            raise MemoryBackendError("Index component operation failed") from None


class FactIndexCatalog:
    """Index control records over a borrowed CAS memory transport, not Agent Facts."""

    def __init__(self, backend, *, namespace_prefix="_ralf-fact-index:"):
        _name(namespace_prefix, "Index metadata namespace prefix")
        if len(namespace_prefix) > 64:
            raise ValidationError("Index catalog prefix exceeds 64 characters")
        self.backend, self.namespace_prefix = backend, namespace_prefix
        self._prefix = namespace_prefix
        self._fixed = _FixedPorts({"metadata": (backend, ["inspect_fact", "put_fact"], True)})

    @property
    def identity(self):
        if (
            self.namespace_prefix != self._prefix
            or self.backend is not self._fixed._ports["metadata"][0]
        ):
            raise DefinitionMismatch("Index catalog resource changed")
        return {
            "kind": "fact-index-catalog",
            "version": "1",
            "prefix": self._prefix,
            "transport": self._fixed.identity,
        }

    async def load(self, scope, index_id, key):
        _fact_inputs(scope, index_id, [])
        _name(key, "Index metadata key")
        _ = self.identity
        record = await self._fixed.call(
            "metadata", "inspect_fact", scope, self._prefix + index_id, key
        )
        _ = self.identity
        if record is None:
            return 0, None
        records = _fact_records([record])
        if (
            records[0]["key"] != key
            or records[0]["expires_at"] is not None
            or _scan_size(records[0]["value"]) > 1024 * 1024
        ):
            raise ValidationError("Invalid index metadata receipt")
        return records[0]["version"], copy.deepcopy(records[0]["value"])

    async def save(self, scope, index_id, key, value, *, expected_version):
        _fact_inputs(scope, index_id, [])
        _integer(expected_version, "Index metadata expected revision")
        _name(key, "Index metadata key")
        _ = self.identity
        if _scan_size(value) > 1024 * 1024:
            raise BudgetExceeded("Index metadata exceeds receipt capacity")
        before = digest(value)
        result = await self._fixed.call(
            "metadata",
            "put_fact",
            scope,
            self._prefix + index_id,
            key,
            copy.deepcopy(value),
            expected_version=expected_version,
        )
        _ = self.identity
        if type(result) is not int or result != expected_version + 1 or digest(value) != before:
            _lazy(result)
            raise ValidationError("Index metadata CAS returned an invalid receipt")
        return result
