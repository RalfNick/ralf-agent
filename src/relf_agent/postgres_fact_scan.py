"""Native bounded PostgreSQL Facts enumeration under the existing writer lock."""

import json
import uuid

from .errors import BudgetExceeded
from .fact_scan import _async_scan_page, _scan_binding, _scan_position, _scan_snapshot
from .types import canonical

SCAN_SCHEMA = """CREATE TABLE IF NOT EXISTS ralf_memory_fact_scan_epochs (
    workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
    epoch TEXT NOT NULL,
    PRIMARY KEY (workspace,principal,namespace))"""


async def _snapshot(source, scope, namespace, prefix):
    await source._execute(
        "INSERT INTO ralf_memory_fact_scan_epochs (workspace,principal,namespace,epoch) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (workspace,principal,namespace) DO NOTHING",
        (*prefix, uuid.uuid4().hex),
    )
    epoch, generation = await source._execute(
        "SELECT s.epoch,COALESCE(g.generation,0) FROM ralf_memory_fact_scan_epochs s "
        "LEFT JOIN ralf_memory_fact_generations g USING (workspace,principal,namespace) "
        "WHERE s.workspace=%s AND s.principal=%s AND s.namespace=%s",
        prefix,
        fetch="one",
    )
    return _scan_snapshot(scope, namespace, epoch, generation)


async def fact_snapshot(source, scope, namespace):
    from .postgres import _prefix

    prefix = _prefix(scope, namespace)
    async with source._transaction(("facts", *prefix)):
        return canonical(await _snapshot(source, scope, namespace, prefix))


async def scan_facts(source, scope, namespace, query):
    from psycopg.rows import tuple_row

    from .postgres import _prefix

    binding, query = _scan_binding(source.backend_id, scope, namespace, query)
    prefix = _prefix(scope, namespace)
    async with source._transaction(("facts", *prefix)):
        snapshot, after = _scan_position(
            binding, await _snapshot(source, scope, namespace, prefix), query
        )
        # A named server cursor fetches one capped record at a time. A normal
        # cursor buffers a full libpq result even when fetchone is used later.
        async with source.connection.cursor(
            name="ralf_fact_scan_" + uuid.uuid4().hex, row_factory=tuple_row
        ) as cursor:
            cursor.itersize = 1
            await cursor.execute(
                source._statement(
                    "SELECT position,substr(convert_to(key,'UTF8'),1,%s),"
                    "substr(convert_to(value,'UTF8'),1,%s),version,expires_at "
                    "FROM ralf_memory_facts WHERE workspace=%s AND principal=%s "
                    "AND namespace=%s AND position>%s ORDER BY position LIMIT %s",
                ),
                (query.max_bytes + 1, query.max_bytes + 1, *prefix, after, query.limit + 1),
            )

            def load(row):
                if len(row[1]) > query.max_bytes or len(row[2]) > query.max_bytes:
                    raise BudgetExceeded("Fact record does not fit scan byte budget")
                return {
                    "key": row[1].decode("utf-8"),
                    "value": json.loads(row[2]),
                    "version": row[3],
                    "expires_at": row[4],
                }

            async def candidates():
                async for row in cursor:
                    yield row[0], lambda row=row: load(row)

            return await _async_scan_page(query, binding, snapshot, candidates())
