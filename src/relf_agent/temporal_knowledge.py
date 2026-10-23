"""Borrowed Knowledge registration; execution and adoption remain in History."""

from .binding_data import KnowledgeBindingResource
from .errors import DefinitionMismatch
from .fact_index_ports import _FixedPorts
from .query_retrieval import _native_resources
from .retrieval import KnowledgeContext
from .types import digest


def _resources(context):
    result = [("context", context, ("references", "validate"))]
    if isinstance(context, KnowledgeContext):
        result.extend(
            (path, obj, tuple(name for name, _ in methods))
            for path, obj, methods in _native_resources(context.retriever)
        )
        from .model_query import ModelQueryTransform

        for path, obj, _ in tuple(result):
            if isinstance(obj, ModelQueryTransform):
                from .model_http import HTTPModelProvider

                methods = (
                    ("complete", "_client")
                    if isinstance(obj.provider, HTTPModelProvider)
                    else ("complete",)
                )
                result.append((path + ".provider", obj.provider, methods))
    return tuple(result)


def _physical(component):
    from .postgres import PostgresKnowledgeStore
    from .storage import SQLiteStore

    store = getattr(component, "store", None)
    if isinstance(store, SQLiteStore):
        return {"kind": "sqlite", "path": store.path, "backend_id": store.backend_id}

    if isinstance(component, PostgresKnowledgeStore):
        info = component.connection.info
        return {
            "kind": "postgres",
            "address": {k: getattr(info, k) for k in ("host", "port", "dbname")},
        }
    return {}


class KnowledgeRegistration:
    """Pin known native composition edges; custom ports declare their own internals."""

    def __init__(self, source):
        self.source = source
        self.context = source.context if isinstance(source, KnowledgeBindingResource) else source
        self.resources = _resources(self.context)
        self.ports = _FixedPorts(
            {
                path: (obj, methods, hasattr(obj, "backend_id"))
                for path, obj, methods in self.resources
            }
        )
        self.connections = [
            (obj, getattr(obj, "connection", None), digest(_physical(obj)))
            for _, obj, _ in self.resources
        ]
        self.clients = []
        from .model_http import HTTPModelProvider

        for _, obj, _ in self.resources:
            if isinstance(obj, HTTPModelProvider):
                self.clients.append([obj, "client", obj.client, False])
            elif hasattr(obj, "_client") and not callable(obj._client):
                self.clients.append([obj, "_client", obj._client, self._lazy_client(obj)])
        self._identity = self._configuration()

    @staticmethod
    def _lazy_client(obj):
        from .embedding_http import OpenAIEmbeddingProvider
        from .rerank_http import HTTPReranker

        return (
            isinstance(obj, (OpenAIEmbeddingProvider, HTTPReranker))
            and obj._owned
            and obj._client is None
        )

    def _configuration(self):
        return {
            "version": 1,
            "ports": self.ports.identity,
            "physical": {
                path: value for path, obj, _ in self.resources if (value := _physical(obj))
            },
        }

    @property
    def identity(self):
        self.check()
        return self._configuration()

    def check(self):
        if (
            isinstance(self.source, KnowledgeBindingResource)
            and self.source.context is not self.context
        ):
            raise DefinitionMismatch("Knowledge binding context replaced")
        current = _resources(self.context)
        if len(current) != len(self.resources) or any(
            path != old_path or obj is not old_obj or methods != old_methods
            for (path, obj, methods), (old_path, old_obj, old_methods) in zip(
                current, self.resources, strict=True
            )
        ):
            raise DefinitionMismatch("Knowledge composition edge replaced")
        self.ports.check()
        for obj, connection, physical in self.connections:
            if (
                getattr(obj, "connection", None) is not connection
                or digest(_physical(obj)) != physical
            ):
                raise DefinitionMismatch("Knowledge physical connection changed")
        for slot in self.clients:
            obj, attribute, original, lazy = slot
            current_client = getattr(obj, attribute)
            if lazy and original is None and current_client is not None:
                import httpx

                if not isinstance(current_client, httpx.AsyncClient):
                    raise DefinitionMismatch("Knowledge owned client initialization is invalid")
                slot[2], slot[3] = current_client, False
            elif current_client is not original:
                raise DefinitionMismatch("Knowledge HTTP client replaced")
        if digest(self._configuration()) != digest(self._identity):
            raise DefinitionMismatch("Knowledge registered configuration changed")
