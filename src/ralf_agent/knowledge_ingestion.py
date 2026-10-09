"""Atomic data-only ingestion in local knowledge authorities."""

import json
from typing import Protocol

from .errors import BudgetExceeded, IdempotencyConflict, ValidationError
from .ingestion_types import INGESTION_CAPACITY, IngestionReceipt, PreparedIngestion, make_receipt
from .retrieval import Document, _scope, _text
from .types import Scope


class IngestionKnowledgeStore(Protocol):
    backend_id: str

    def ingest(
        self, scope: Scope, namespace: str, prepared: PreparedIngestion, *, command_id: str
    ) -> IngestionReceipt: ...
    def ingestion_receipt(
        self, scope: Scope, namespace: str, command_id: str
    ) -> IngestionReceipt | None: ...


class AsyncIngestionKnowledgeStore(Protocol):
    backend_id: str

    async def ingest(
        self, scope: Scope, namespace: str, prepared: PreparedIngestion, *, command_id: str
    ) -> IngestionReceipt: ...
    async def ingestion_receipt(
        self, scope: Scope, namespace: str, command_id: str
    ) -> IngestionReceipt | None: ...


def inputs(scope, namespace, command_id, prepared=None):
    prefix = _scope(scope, namespace)
    _text(command_id, "Ingestion command ID")
    if prepared is not None:
        if type(prepared) is not PreparedIngestion:
            raise ValidationError("Atomic ingestion requires PreparedIngestion")
        prepared.validate()
    return prefix


def replay(receipt, prepared):
    if receipt is not None and receipt.request_digest != prepared.request_digest:
        raise IdempotencyConflict("Ingestion command identifies different content")
    return receipt


def memory_receipt(store, scope, namespace, command_id):
    key = (*inputs(scope, namespace, command_id), command_id)
    with store._lock:
        value = store._ingestions.get(key)
        return None if value is None else IngestionReceipt.from_dict(value)


def memory_ingest(store, scope, namespace, prepared, *, command_id):
    prefix = inputs(scope, namespace, command_id, prepared)
    key = (*prefix, command_id)
    with store._lock:
        previous = memory_receipt(store, scope, namespace, command_id)
        if previous is not None:
            return replay(previous, prepared)
        if sum(k[:3] == prefix for k in store._ingestions) >= INGESTION_CAPACITY:
            raise BudgetExceeded("Knowledge ingestion receipt capacity reached")
        receipt = make_receipt(store.backend_id, scope, namespace, command_id, prepared)
        store._put(
            scope,
            namespace,
            Document(**prepared.document),
            expected_version=prepared.expected_version,
            expires_at=prepared.expires_at,
            prepared=prepared,
        )
        store._ingestions[key] = receipt.to_dict()
        return receipt


def sqlite_receipt(store, scope, namespace, command_id):
    prefix = inputs(scope, namespace, command_id)
    store.store._assert_file_identity()
    row = store.store.conn.execute(
        "SELECT receipt FROM knowledge_ingestions WHERE workspace=? AND principal=? AND namespace=? AND command_id=?",
        (*prefix, command_id),
    ).fetchone()
    return None if row is None else IngestionReceipt.from_dict(json.loads(row[0]))


def sqlite_ingest(store, scope, namespace, prepared, *, command_id):
    prefix = inputs(scope, namespace, command_id, prepared)
    if store.store.conn.in_transaction:
        raise ValidationError("Atomic ingestion must own its transaction boundary")
    with store.store.transaction():
        previous = sqlite_receipt(store, scope, namespace, command_id)
        if previous is not None:
            return replay(previous, prepared)
        count = store.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge_ingestions WHERE workspace=? AND principal=? AND namespace=?",
            prefix,
        ).fetchone()[0]
        if count >= INGESTION_CAPACITY:
            raise BudgetExceeded("Knowledge ingestion receipt capacity reached")
        receipt = make_receipt(store.backend_id, scope, namespace, command_id, prepared)
        store._put(
            scope,
            namespace,
            Document(**prepared.document),
            expected_version=prepared.expected_version,
            expires_at=prepared.expires_at,
            prepared=prepared,
        )
        store.store.conn.execute(
            "INSERT INTO knowledge_ingestions VALUES(?,?,?,?,?,?)",
            (*prefix, command_id, prepared.request_digest, receipt._data_json),
        )
    return receipt
