"""Opt-in native Facts maintenance; existing factories/defaults unchanged.

The build cache is weak by original BuildContext. Its values contain resources,
never the context; resource lifetime belongs to the original ownership ledger.
"""

import asyncio
import copy
import math
from dataclasses import asdict
from pathlib import Path
from types import MethodType
from weakref import WeakKeyDictionary

from .embeddings import HashEmbeddingProvider
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .fact_index_generation import GenerationIndexedMemoryStore
from .fact_index_maintenance_tools import NAME, READY_ONLY_SCHEMA, FactIndexMaintenanceToolSource
from .fact_index_ports import FactIndexCatalog
from .memory import SQLiteMemory
from .recall import _integer
from .runtime_builder import _fields
from .runtime_lifecycle import BuildContext
from .storage import SQLiteStore
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry
from .types import AgentSpec, Scope, canonical, digest
from .vector import SQLiteVectorIndex
from .workflow import GraphNode, GraphWorkflowSpec, Literal, ValueRef


def _text(value, label, maximum=128):
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > maximum
        or "\x00" in value
    ):
        raise ValidationError(label + " must be bounded nonblank text")
    return value


def _path(value):
    _text(value, "Native index path", 4096)
    if "://" in value or value == ":memory:":
        raise ValidationError("Maintenance requires a durable native file path")
    return value


def _native(declaration, adapter, allowed, default):
    if declaration is None:
        declaration = {"adapter": adapter, "config": default}
    if (
        type(declaration) is not dict
        or set(declaration) - {"adapter", "config"}
        or declaration.get("adapter") != adapter
    ):
        raise ValidationError("Maintenance supports exact native SQLite/Hash declarations only")
    options = declaration.get("config", {})
    if type(options) is not dict:
        raise ValidationError("Native component configuration must be an object")
    _fields(options, allowed)
    return {**default, **copy.deepcopy(options)}


def _options(config):
    if type(config) is not dict:
        raise ValidationError("Maintenance configuration must be an object")
    _fields(
        config,
        {
            "resource_id",
            "namespace",
            "scope",
            "backend",
            "embedding",
            "index",
            "catalog",
            "batch_size",
            "max_page_bytes",
            "max_records",
            "min_score",
            "max_pages",
            "version",
        },
    )
    resource_id = _text(config.get("resource_id"), "Maintenance resource ID")
    namespace = _text(config.get("namespace"), "Maintenance Facts namespace")
    scope_data = config.get("scope", asdict(Scope()))
    if type(scope_data) is not dict or set(scope_data) != {"workspace", "principal"}:
        raise ValidationError("Maintenance requires an explicit trusted Scope selection")
    scope = Scope(
        _text(scope_data["workspace"], "Maintenance workspace", 1024),
        _text(scope_data["principal"], "Maintenance principal", 1024),
    )
    backend = _native(config.get("backend"), "sqlite", {"path"}, {"path": ".ralf/facts.sqlite"})
    embedding = _native(config.get("embedding"), "hash", {"dimensions"}, {"dimensions": 128})
    _integer(embedding["dimensions"], "Fact embedding dimensions", 1, 32768)
    index = _native(
        config.get("index"),
        "sqlite",
        {"path", "dimensions"},
        {"path": ".ralf/fact-vectors.sqlite", "dimensions": embedding["dimensions"]},
    )
    _integer(index["dimensions"], "Fact vector dimensions", 1, 32768)
    if index["dimensions"] != embedding["dimensions"]:
        raise ValidationError("Fact vector and embedding dimensions differ")
    catalog = _native(
        config.get("catalog"),
        "memory-cas",
        {"backend", "namespace_prefix"},
        {
            "backend": {"adapter": "sqlite", "config": {"path": ".ralf/fact-catalog.sqlite"}},
            "namespace_prefix": "_ralf-fact-index:",
        },
    )
    metadata = _native(
        catalog["backend"], "sqlite", {"path"}, {"path": ".ralf/fact-catalog.sqlite"}
    )
    _text(catalog["namespace_prefix"], "Fact catalog namespace prefix", 64)
    paths = [_path(c["path"]) for c in (backend, index, metadata)]
    if len(set(paths)) != 3:
        raise ValidationError("Facts, vectors and metadata require separate native files")
    limits = {
        "batch_size": 32,
        "max_page_bytes": 64000,
        "max_records": 100000,
        "min_score": -1,
        "max_pages": 64,
    }
    limits.update({k: config[k] for k in limits if k in config})
    for name, low, high in [
        ("batch_size", 1, 128),
        ("max_page_bytes", 2, 64000),
        ("max_records", 1, 100000),
        ("max_pages", 1, 256),
    ]:
        _integer(limits[name], "Maintenance " + name, low, high)
    score = limits["min_score"]
    if type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 1:
        raise ValidationError("Maintenance threshold must be finite in [-1,1]")
    limits["min_score"] = float(score)
    return {
        "resource_id": resource_id,
        "namespace": namespace,
        "scope": asdict(scope),
        "backend": {"adapter": "sqlite", "config": backend},
        "embedding": {"adapter": "hash", "config": embedding},
        "index": {"adapter": "sqlite", "config": index},
        "catalog": {
            "adapter": "memory-cas",
            "config": {
                "backend": {"adapter": "sqlite", "config": metadata},
                "namespace_prefix": catalog["namespace_prefix"],
            },
        },
        "version": _text(config.get("version", "1"), "Maintenance version", 256),
        **limits,
    }


def _selection(config, base_dir, scope, db_path=None):
    options = _options(config)
    if type(scope) is not Scope or asdict(scope) != options["scope"]:
        raise AuthorizationDenied("Maintenance belongs to another trusted Scope")
    root = Path(base_dir).resolve()
    values = [
        options["backend"]["config"],
        options["index"]["config"],
        options["catalog"]["config"]["backend"]["config"],
    ]
    paths = []
    for value in values:
        path = Path(value["path"])
        value["path"] = str((path if path.is_absolute() else root / path).resolve())
        paths.append(value["path"])
    if len(set(paths)) != 3 or (db_path is not None and str(Path(db_path).resolve()) in paths):
        raise ValidationError("Execution, Facts, vector and catalog files must be distinct")
    return options


class FactIndexMaintenanceOwner:
    """Caller-owned SDK option; retain this original owner on incomplete drain."""

    def __init__(self, options):
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            raise ValidationError("Maintenance owner requires its hosting loop") from None
        self.config = copy.deepcopy(options)
        self.config_digest = digest(options)
        self._native_original = self._native_pending = ()
        self.index = self.source = None
        self._index_original = self._source_original = None
        self._source_close_original = None
        self.closed = False

    @property
    def native(self):
        """Read-only remaining original native resources; never a caller cleanup list."""
        return tuple(entry[0] for entry in self._native_pending)

    def _own_native(self, resource):
        store = resource.store
        entry = (resource, store, store.path, store.conn, resource.close)
        self._native_original += (entry,)
        self._native_pending += (entry,)
        return resource

    def _check_selection(self):
        if self.index is not self._index_original or self.source is not self._source_original:
            raise DefinitionMismatch("Maintenance owner original source or index changed")
        if (
            self._source_original is not None
            and self._source_original._index is not self._index_original
        ):
            raise DefinitionMismatch("Maintenance owner source selected another index")
        if self._source_original is not None:
            original = self._source_close_original
            current = getattr(self._source_original, "aclose", None)
            if (
                type(original) is not MethodType
                or type(current) is not MethodType
                or current.__self__ is not original.__self__
                or current.__func__ is not original.__func__
            ):
                raise DefinitionMismatch("Maintenance owner original source close binding changed")
        if len(self._native_pending) > len(self._native_original) or any(
            current is not original
            for current, original in zip(self._native_pending, self._native_original, strict=False)
        ):
            raise DefinitionMismatch("Maintenance owner original cleanup ledger changed")
        for resource, store, path, connection, _ in self._native_pending:
            if (
                resource.store is not store
                or type(store.path) is not str
                or store.path != path
                or store.conn is not connection
            ):
                raise DefinitionMismatch("Maintenance owner original native connection changed")

    def check(self):
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Maintenance owner must use its original hosting loop")
        self._check_selection()
        if self.closed or self.source is None or self.source._closing:
            raise ValidationError("Maintenance owner is closing or closed")
        if digest(self.config) != self.config_digest:
            raise DefinitionMismatch("Maintenance owner configuration changed")
        if (
            canonical(self.index.identity) != self.index_pin
            or canonical(self.source.identity) != self.source_pin
        ):
            raise DefinitionMismatch("Maintenance owner original identity changed")

    async def aclose(self, *, wait_timeout=30):
        # Selected fields cannot withdraw an active original source from its owner.
        try:
            if asyncio.get_running_loop() is not self._loop:
                raise ValidationError("Maintenance cleanup must use its original hosting loop")
            self._check_selection()
            if self.closed:
                return
            source = self._source_original
            if source is not None:
                await self._source_close_original(wait_timeout=wait_timeout)
            self._check_selection()
            while self._native_pending:
                self._check_selection()
                self._native_pending[-1][4]()
                self._native_pending = self._native_pending[:-1]
            self.closed = True
        except BaseException as error:
            error.maintenance_owner = self
            raise


def _allocate(owner, own):
    config = owner.config
    facts = own(SQLiteMemory(config["backend"]["config"]["path"]))
    vector = own(
        SQLiteVectorIndex(
            config["index"]["config"]["path"], dimensions=config["index"]["config"]["dimensions"]
        )
    )
    metadata = own(SQLiteMemory(config["catalog"]["config"]["backend"]["config"]["path"]))
    catalog = FactIndexCatalog(
        metadata, namespace_prefix=config["catalog"]["config"]["namespace_prefix"]
    )
    embedding = HashEmbeddingProvider(**config["embedding"]["config"])
    # Exact classes are intentional: this first declaration admits no hidden custom/HTTP effect.
    if any(
        type(obj) is not cls
        for obj, cls in [
            (facts, SQLiteMemory),
            (vector, SQLiteVectorIndex),
            (metadata, SQLiteMemory),
            (catalog, FactIndexCatalog),
            (embedding, HashEmbeddingProvider),
        ]
    ):
        raise ValidationError("Maintenance requires exact native component types")
    owner.index = GenerationIndexedMemoryStore(
        facts,
        embedding,
        vector,
        catalog,
        scope=Scope(**config["scope"]),
        namespace=config["namespace"],
        **{k: config[k] for k in ("batch_size", "max_page_bytes", "max_records", "min_score")},
    )
    owner._index_original = owner.index
    owner.source = FactIndexMaintenanceToolSource(
        owner.index,
        version=config["version"],
        scope=Scope(**config["scope"]),
        namespace=config["namespace"],
        max_pages=config["max_pages"],
    )
    owner._source_original = owner.source
    owner._source_close_original = owner.source.aclose
    owner.index_pin = canonical(owner.index.identity)
    owner.source_pin = canonical(owner.source.identity)


async def create_fact_index_maintenance_owner(config, *, base_dir, scope):
    owner = FactIndexMaintenanceOwner(_selection(config, base_dir, scope))

    try:
        _allocate(owner, owner._own_native)
        return owner
    except BaseException as error:
        error.maintenance_owner = owner
        try:
            await owner.aclose()
        except BaseException as cleanup_error:
            cleanup_error.maintenance_owner = owner
            raise cleanup_error from error
        raise


def fact_index_maintenance_components(config, *, borrowed=False, prefix=""):
    """Serialize the matching declarations; no opaque digest is supplied by users."""
    options = _options(config)
    if type(borrowed) is not bool:
        raise ValidationError("Borrowed selection must be explicit boolean")
    if prefix:
        _text(prefix, "Maintenance adapter prefix")
    elif type(prefix) is not str:
        raise ValidationError("Maintenance adapter prefix must be text")
    suffix = "-borrowed" if borrowed else ""
    return {
        "tools": {
            "adapter": prefix + "facts-index-maintenance" + suffix,
            "config": copy.deepcopy(options),
        },
        "memory_store": {
            "adapter": prefix + "maintained-index-reference" + suffix,
            "config": copy.deepcopy(options),
        },
    }


def fact_index_maintenance_writer(config, *, borrowed=False, prefix=""):
    """Explicit native CAS write grant; index recall remains a separate reader port."""
    if type(borrowed) is not bool:
        raise ValidationError("Borrowed selection must be explicit boolean")
    if prefix:
        _text(prefix, "Maintenance adapter prefix")
    elif type(prefix) is not str:
        raise ValidationError("Maintenance adapter prefix must be text")
    return {
        "adapter": prefix + "maintained-index-writer" + ("-borrowed" if borrowed else ""),
        "config": _options(config),
    }


def maintained_agent_workflow(reader, config, *, name="maintained-preferences", version="1"):
    options = _options(config)
    if type(reader) is not AgentSpec or reader.name != options["namespace"]:
        raise ValidationError("Reader Agent name must select the fixed maintenance Facts namespace")
    return GraphWorkflowSpec(
        name,
        [
            GraphNode("refresh", tool=NAME, input=Literal({}), output_schema=READY_ONLY_SCHEMA),
            GraphNode("reader", agent=reader, depends_on=("refresh",)),
        ],
        version,
        output=ValueRef("reader"),
        max_concurrency=1,
    )


def register_fact_index_maintenance(registry, *, borrowed=None, prefix=""):
    if borrowed is not None and type(borrowed) is not FactIndexMaintenanceOwner:
        raise ValidationError("Borrow only an explicit original maintenance owner")
    if prefix:
        _text(prefix, "Maintenance adapter prefix")
    elif type(prefix) is not str:
        raise ValidationError("Maintenance adapter prefix must be text")
    suffix = "-borrowed" if borrowed is not None else ""
    names = (
        ("tools", prefix + "facts-index-maintenance" + suffix),
        ("memory_store", prefix + "maintained-index-reference" + suffix),
        ("memory_store", prefix + "maintained-index-writer" + suffix),
    )
    registered = getattr(registry, "_fact_index_maintenance_registrations", set())
    if names in registered:
        if borrowed is not None:
            raise ValidationError(
                "Borrowed maintenance factories already registered on this registry"
            )
        return
    if any(name in registry._factories for name in names):
        raise ValidationError(
            "Maintenance adapter name collides with another explicit registration"
        )
    shared = WeakKeyDictionary()

    def validate(config):
        _options(config)

    def selection(config, context):
        if (
            type(context) is not BuildContext
            or not context._allow_async
            or type(context.store) is not SQLiteStore
            or context.store.readonly
        ):
            raise ValidationError("Maintenance requires local async RuntimeBuilder.abuild context")
        context._check_loop()
        return _selection(config, context.base_dir, context.scope, context.db_path)

    async def tools(config, context):
        options = selection(config, context)
        values = shared.setdefault(context, {})
        resource_id = options["resource_id"]
        owner = values.get(resource_id)
        if owner is not None:
            if owner.config_digest != digest(options):
                raise DefinitionMismatch(
                    "Maintenance resource ID already selects another configuration"
                )
            owner.check()
        elif borrowed is not None:
            borrowed.check()
            if borrowed.config_digest != digest(options):
                raise DefinitionMismatch(
                    "Borrowed maintenance owner differs from the paired declaration"
                )
            owner = borrowed
            values[resource_id] = owner
        else:
            owner = FactIndexMaintenanceOwner(options)
            _allocate(owner, context.own)
            context.own_async(owner.source)
            values[resource_id] = owner
        result = ToolRegistry()
        await register_tool_source(
            result,
            owner.source,
            policies={
                NAME: ToolPolicy(
                    version=options["version"],
                    effect="idempotent_write",
                    requires_approval=False,
                    cost=1,
                    effect_key_argument="effect_key",
                    reconciler=owner.source.reconcile,
                )
            },
        )
        return result

    async def reference(config, context):
        options = selection(config, context)
        owner = shared.get(context, {}).get(options["resource_id"])
        if owner is None:
            raise ValidationError(
                "Maintained Facts reference requires its tools-first construction"
            )
        if owner.config_digest != digest(options):
            raise DefinitionMismatch(
                "Maintained Facts reference differs from the original configuration"
            )
        owner.check()
        return owner.index

    async def writer(config, context):
        index = await reference(config, context)
        return index.backend

    registry.register_async(
        "memory_store", prefix + "maintained-index-writer" + suffix, writer, validator=validate
    )
    registry.register_async(
        "tools", prefix + "facts-index-maintenance" + suffix, tools, validator=validate
    )
    registry.register_async(
        "memory_store",
        prefix + "maintained-index-reference" + suffix,
        reference,
        validator=validate,
    )
    registry._fact_index_maintenance_registrations = {*registered, names}
