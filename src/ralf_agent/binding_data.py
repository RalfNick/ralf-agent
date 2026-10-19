"""Host-authorized read-only data views; no model I/O or execution authority."""

import copy
import json
from dataclasses import asdict, dataclass, replace

from .binding_types import text
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .memory import memory_call
from .recall import (
    LegacyMemoryRecallAdapter,
    RecallPage,
    RecallQuery,
    _binding,
    _decode_cursor,
    _encode_cursor,
    _fact_records,
    _method_backend,
    _validate_cursor,
)
from .retrieval import KnowledgeContext
from .types import Scope, canonical, digest


def data_namespace_options(namespaces, default_namespace):
    if (
        not isinstance(namespaces, (tuple, list))
        or not namespaces
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 128
            for value in namespaces
        )
    ):
        raise ValidationError(
            "Data resources require an allowlist of namespaces with 1 to 128 characters"
        )
    if len(set(namespaces)) != len(namespaces) or default_namespace not in namespaces:
        raise ValidationError("Data namespaces must be unique and include the default")
    return tuple(namespaces)


def _recall_mode(backend):
    mode = getattr(backend, "recall_mode", "cursor")
    if type(mode) is not str or mode not in {"cursor", "window"}:
        raise ValidationError("Facts recall_mode must be cursor or window")
    return mode


def facts_identity(backend):
    if isinstance(backend, FactsView):
        raise ValidationError(
            "Register the original Facts backend or FactsBindingResource, not a view"
        )
    identity = text(getattr(backend, "backend_id", None), "Facts backend identity")
    if not callable(getattr(backend, "facts", None)):
        raise ValidationError("Facts backend must implement facts")
    mode = _recall_mode(backend)
    return {"backend_id": identity, **({"recall_mode": mode} if mode != "cursor" else {})}


def _namespace(selector, scope, namespaces, default):
    if not isinstance(scope, Scope):
        raise ValidationError("Data views require a trusted Scope")
    if not isinstance(selector, dict) or set(selector) - {"namespace"}:
        raise ValidationError("Data selector supports only namespace")
    namespace = selector.get("namespace", default)
    if namespace not in namespaces:
        raise AuthorizationDenied("Data namespace is not authorized by the host")
    return namespace


@dataclass(frozen=True, init=False)
class FactsBindingResource:
    backend: object
    namespaces: tuple
    default_namespace: str

    def __init__(self, backend, *, namespaces=("default",), default_namespace="default"):
        facts_identity(backend)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(
            self, "namespaces", data_namespace_options(namespaces, default_namespace)
        )
        object.__setattr__(self, "default_namespace", default_namespace)

    @property
    def identity(self):
        return {
            "kind": "facts-binding-resource",
            "version": "1",
            **facts_identity(self.backend),
            "namespaces": list(self.namespaces),
            "default_namespace": self.default_namespace,
        }

    def select(self, selector, scope):
        namespace = _namespace(selector, scope, self.namespaces, self.default_namespace)
        return FactsView(
            self.backend, scope, namespace, self.backend.backend_id, _recall_mode(self.backend)
        )


@dataclass(frozen=True)
class FactsView:
    backend: object
    scope: Scope
    namespace: str
    original_backend_id: str
    original_recall_mode: str = "cursor"

    @property
    def backend_id(self):
        return self.backend.backend_id

    @property
    def resource(self):
        return {
            "backend_id": self.backend_id,
            "namespace": self.namespace,
            **(
                {"recall_mode": self.original_recall_mode}
                if self.original_recall_mode != "cursor"
                else {}
            ),
        }

    def _check(self, scope, logical_namespace):
        text(logical_namespace, "Logical Facts namespace")
        if scope != self.scope:
            raise AuthorizationDenied("Facts view belongs to another trusted Scope")
        if self.backend_id != self.original_backend_id:
            raise DefinitionMismatch("The actual Facts backend changed")
        if _recall_mode(self.backend) != self.original_recall_mode:
            raise DefinitionMismatch("The selected Facts recall mode changed")

    def _source(self, value):
        return {
            "backend_id": self.original_backend_id,
            "scope": asdict(self.scope),
            "namespace": self.namespace,
            "value_digest": digest(value),
        }

    def _annotate(self, items):
        return [
            {**item, "_facts_binding": self._source(item["value"])} for item in _fact_records(items)
        ]

    async def _call(self, method, *args):
        owner, identity = _method_backend(method)
        result = await memory_call(method, *args)
        if owner is not None and owner.backend_id != identity:
            raise DefinitionMismatch("The actual delegated Facts client changed")
        return result

    async def facts(self, scope, namespace):
        self._check(scope, namespace)
        items = await self._call(self.backend.facts, scope, self.namespace)
        self._check(scope, namespace)
        return self._annotate(items)

    async def recall(self, scope, namespace, query):
        self._check(scope, namespace)
        if not isinstance(query, RecallQuery):
            raise ValidationError("Facts recall requires RecallQuery")
        if self.original_recall_mode == "window":
            return await self._recall_window(scope, namespace, query)
        binding = _binding(self.backend_id, scope, "scoped-facts-v1", self.namespace, query)
        state = _decode_cursor(query.cursor, binding)
        raw_cursor, snapshot = None, None
        if state is not None:
            saved, offset = state
            if (
                set(saved) != {"cursor", "snapshot_id"}
                or offset != 0
                or not isinstance(saved["snapshot_id"], str)
                or not saved["snapshot_id"]
            ):
                raise ValidationError("Invalid scoped Facts cursor")
            _validate_cursor(saved["cursor"])
            raw_cursor, snapshot = saved["cursor"], saved["snapshot_id"]
        # One source candidate at a time avoids the underlying cumulative byte
        # filter permanently skipping a fact that would fit an empty view page.
        delegated = replace(query, max_items=1, scan_limit=1, cursor=None)
        method = getattr(self.backend, "recall", None)
        if not callable(method):
            method = LegacyMemoryRecallAdapter(self.backend).recall
        items, scanned, skipped, bounded, next_cursor, seen = [], 0, 0, True, None, set()
        while scanned < query.scan_limit and len(items) < query.max_items:
            page = await self._call(
                method, scope, self.namespace, replace(delegated, cursor=raw_cursor)
            )
            self._check(scope, namespace)
            if not isinstance(page, RecallPage):
                raise ValidationError("Facts recall must return RecallPage")
            if len(page.items) > 1 or page.used_chars > delegated.max_chars or page.scanned > 1:
                raise ValidationError("Facts backend exceeded the delegated recall allowance")
            if snapshot is not None and page.snapshot_id != snapshot:
                raise ValidationError("Facts pagination source snapshot changed")
            snapshot = page.snapshot_id
            scanned += page.scanned
            skipped += page.skipped
            bounded &= page.backend_bounded
            for item in self._annotate(page.items):
                if len(canonical([item])) > query.max_chars:
                    skipped += 1
                elif len(canonical([*items, item])) > query.max_chars:
                    # Resume before this candidate, with no record payload/state.
                    next_cursor = _encode_cursor(
                        binding, {"cursor": raw_cursor, "snapshot_id": snapshot}, 0
                    )
                    return RecallPage(
                        items,
                        next_cursor,
                        len(canonical(items)),
                        scanned,
                        skipped,
                        snapshot,
                        bounded,
                    )
                else:
                    items.append(item)
            if page.next_cursor is None:
                next_cursor = None
                break
            if page.scanned == 0 or page.next_cursor == raw_cursor or page.next_cursor in seen:
                raise ValidationError("Facts source pagination did not make progress")
            raw_cursor = page.next_cursor
            seen.add(raw_cursor)
            next_cursor = _encode_cursor(
                binding, {"cursor": raw_cursor, "snapshot_id": snapshot}, 0
            )
        return RecallPage(
            items,
            next_cursor,
            len(canonical(items)),
            scanned,
            skipped,
            snapshot,
            bounded,
        )

    async def _recall_window(self, scope, namespace, query):
        if query.cursor is not None:
            raise ValidationError("Window Facts recall does not support cursors")
        delegated = replace(query)
        page = await self._call(self.backend.recall, scope, self.namespace, delegated)
        self._check(scope, namespace)
        if not isinstance(page, RecallPage):
            raise ValidationError("Facts recall must return RecallPage")
        page = RecallPage(**asdict(page))
        if (
            page.next_cursor is not None
            or len(page.items) > query.max_items
            or page.scanned > query.scan_limit
            or page.used_chars > query.max_chars
        ):
            raise ValidationError("Window Facts backend exceeded the delegated recall allowance")
        items = []
        for item in self._annotate(page.items):
            if len(canonical([*items, item])) <= query.max_chars:
                items.append(item)
        return RecallPage(
            items,
            None,
            len(canonical(items)),
            page.scanned,
            page.skipped + len(page.items) - len(items),
            page.snapshot_id,
            page.backend_bounded,
        )

    async def validate_facts(self, scope, namespace, items):
        self._check(scope, namespace)
        records = _fact_records(items)
        for item in records:
            source = item.pop("_facts_binding", None)
            if not isinstance(source, dict):
                raise ValidationError("Scoped Facts references require provenance")
            if any(
                source.get(key) != value
                for key, value in self._source(item["value"]).items()
                if key != "value_digest"
            ):
                raise AuthorizationDenied("Facts reference belongs to another scoped resource")
            if source != self._source(item["value"]):
                raise ValidationError("Scoped Facts reference changed")
        method = getattr(self.backend, "validate_facts", None)
        if not callable(method):
            method = LegacyMemoryRecallAdapter(self.backend).validate_facts
        result = await self._call(method, scope, self.namespace, records)
        self._check(scope, namespace)
        if result is not None:
            raise ValidationError("Facts validation must return None")


def knowledge_identity(context):
    if type(context) is not KnowledgeContext:
        raise ValidationError(
            "Knowledge resources require native KnowledgeContext over a retriever"
        )
    return copy.deepcopy(context.identity)


@dataclass(frozen=True, init=False)
class KnowledgeBindingResource:
    context: object
    namespaces: tuple
    default_namespace: str

    def __init__(self, context, *, namespaces=("default",), default_namespace="default"):
        knowledge_identity(context)
        object.__setattr__(self, "context", context)
        object.__setattr__(
            self, "namespaces", data_namespace_options(namespaces, default_namespace)
        )
        object.__setattr__(self, "default_namespace", default_namespace)

    @property
    def identity(self):
        return {
            "kind": "knowledge-binding-resource",
            "version": "1",
            "context": knowledge_identity(self.context),
            "namespaces": list(self.namespaces),
            "default_namespace": self.default_namespace,
        }

    def select(self, selector, scope):
        namespace = _namespace(selector, scope, self.namespaces, self.default_namespace)
        return KnowledgeView(
            self.context,
            scope,
            namespace,
            canonical(knowledge_identity(self.context)),
            self.context.retriever,
        )


@dataclass(frozen=True)
class KnowledgeView:
    context: object
    scope: Scope
    namespace: str
    original_identity_json: str
    original_retriever: object

    @property
    def limit(self):
        return self.context.limit

    @property
    def max_chars(self):
        return self.context.max_chars

    @property
    def identity(self):
        return {
            "kind": "scoped-knowledge-context",
            "version": "1",
            "context": knowledge_identity(self.context),
            "scope": asdict(self.scope),
            "namespace": self.namespace,
        }

    @property
    def resource(self):
        return {"context": json.loads(self.original_identity_json), "namespace": self.namespace}

    def _selected(self, scope):
        self._check(scope)
        return KnowledgeContext(
            self.context.retriever,
            namespace=self.namespace,
            limit=self.limit,
            max_chars=self.max_chars,
        )

    def _check(self, scope):
        if scope != self.scope:
            raise AuthorizationDenied("Knowledge view belongs to another trusted Scope")
        if (
            self.context.retriever is not self.original_retriever
            or canonical(knowledge_identity(self.context)) != self.original_identity_json
        ):
            raise DefinitionMismatch("The actual Knowledge context changed")

    async def references(self, scope, text):
        result = await self._selected(scope).references(scope, text)
        self._check(scope)
        return result

    async def validate(self, scope, references):
        await self._selected(scope).validate(scope, references)
        self._check(scope)
