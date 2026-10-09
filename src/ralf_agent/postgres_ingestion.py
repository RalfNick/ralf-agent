"""One PostgreSQL transaction for CAS knowledge and immutable ingestion receipt."""

import json

from .errors import BudgetExceeded
from .ingestion_types import INGESTION_CAPACITY, IngestionReceipt, make_receipt
from .knowledge_ingestion import inputs, replay
from .postgres import _advisory_key
from .retrieval import Document

INGESTION_SCHEMA = """CREATE TABLE IF NOT EXISTS ralf_knowledge_ingestions (
    workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
    command_id TEXT NOT NULL, request_digest TEXT NOT NULL, receipt TEXT NOT NULL,
    PRIMARY KEY(workspace,principal,namespace,command_id))"""


async def _receipt(store, prefix, command_id):
    row = await store._execute(
        "SELECT receipt FROM ralf_knowledge_ingestions WHERE workspace=%s AND principal=%s AND namespace=%s AND command_id=%s",
        (*prefix, command_id),
        fetch="one",
    )
    return None if row is None else IngestionReceipt.from_dict(json.loads(row[0]))


async def postgres_receipt(store, scope, namespace, command_id):
    prefix = inputs(scope, namespace, command_id)
    async with store._transaction():
        return await _receipt(store, prefix, command_id)


async def postgres_ingest(store, scope, namespace, prepared, *, command_id):
    prefix = inputs(scope, namespace, command_id, prepared)
    async with store._transaction(("document", *prefix, prepared.document["document_id"])):
        # Serialize all command admissions/capacity within this namespace while
        # retaining the ordinary document lock shared by legacy put/delete.
        await store._execute(
            "SELECT pg_advisory_xact_lock(%s)", (_advisory_key(("ingestion", *prefix)),)
        )
        previous = await _receipt(store, prefix, command_id)
        if previous is not None:
            return replay(previous, prepared)
        row = await store._execute(
            "SELECT COUNT(*) FROM ralf_knowledge_ingestions WHERE workspace=%s AND principal=%s AND namespace=%s",
            prefix,
            fetch="one",
        )
        if row[0] >= INGESTION_CAPACITY:
            raise BudgetExceeded("Knowledge ingestion receipt capacity reached")
        receipt = make_receipt(store.backend_id, scope, namespace, command_id, prepared)
        await store._write_document(
            prefix,
            Document(**prepared.document),
            prepared.expected_version,
            prepared.expires_at,
            prepared,
        )
        await store._execute(
            "INSERT INTO ralf_knowledge_ingestions VALUES(%s,%s,%s,%s,%s,%s)",
            (*prefix, command_id, prepared.request_digest, receipt._data_json),
        )
    return receipt
