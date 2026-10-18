"""Only byte-identical copies of adopted receipts may be removed."""

import json

from .errors import DefinitionMismatch, ValidationError
from .ports import _complete_sync_none, is_async_callable, is_sync_callable
from .types import Scope, digest

TABLES = ("ralf_temporal_effects", "ralf_temporal_effect_evidence")


def request(scope, run_id, limit, after):
    if not isinstance(scope, Scope) or type(run_id) is not str or not run_id.strip():
        raise ValidationError("Effect compaction requires Scope and original Run identity")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValidationError("Effect compaction limit must be an integer between 1 and 1000")
    if after is not None and (type(after) is not str or not after.strip()):
        raise ValidationError("Effect compaction position must be a non-empty effect key")


def binding(journal):
    from .temporal_journal import PostgresEffectJournal

    schemas = getattr(journal, "_table_schemas", None)
    if (
        type(journal) is not PostgresEffectJournal
        or journal._closed
        or type(schemas) is not dict
        or any(type(schemas.get(table)) is not str or not schemas[table] for table in TABLES)
        or schemas[TABLES[0]] != schemas[TABLES[1]]
    ):
        raise ValidationError(
            "Effect compaction requires an initialized original PostgreSQL dataset"
        )
    return journal.connection, dict(schemas), journal.backend_id


async def compact(journal, scope, run_id, *, limit, after_effect_key, verify, namespace_check):
    request(scope, run_id, limit, after_effect_key)
    if not is_sync_callable(verify):
        raise ValidationError("Effect compaction requires a completed synchronous proof check")
    if namespace_check is not None and not is_async_callable(namespace_check):
        raise ValidationError("Effect compaction namespace check must be native async")
    original = binding(journal)

    def check():
        _complete_sync_none(verify(), "Effect compaction proof check")
        current = binding(journal)
        if current[0] is not original[0] or current[1:] != original[1:]:
            raise DefinitionMismatch("Original PostgreSQL compaction dataset changed")

    check()
    position = " AND effect_key>%s" if after_effect_key is not None else ""
    parameters = (scope.workspace, scope.principal, run_id)
    if after_effect_key is not None:
        parameters += (after_effect_key,)
    async with journal._transaction():
        check()
        rows = await journal._execute(
            "SELECT effect_key,target_digest FROM ralf_temporal_effects "
            "WHERE workspace=%s AND principal=%s AND run_id=%s AND state='adopted'"
            + position
            + " ORDER BY effect_key LIMIT %s",
            (*parameters, limit),
            fetch="all",
        )
        check()
    removed, payload_bytes = 0, 0
    for effect_key, target in rows:
        prefix = (scope.workspace, scope.principal, effect_key)
        async with journal._transaction(("temporal-effects", *prefix[:2], target)):
            check()
            record = await journal._record(prefix)
            check()
            if (
                record is None
                or record["run_id"] != run_id
                or record["target_digest"] != target
                or record["state"] != "adopted"
                or type(record["result"]) is not str
                or type(record["source"]) is not str
                or not record["source"].strip()
            ):
                continue
            try:
                result = json.loads(record["result"])
                if digest(result) != record["adopted_result_digest"]:
                    continue
                evidence_digest = digest([record["source"], result])
            except (ValueError, TypeError):
                continue
            deleted = await journal._execute(
                "DELETE FROM ralf_temporal_effect_evidence "
                "WHERE workspace=%s AND principal=%s AND effect_key=%s "
                "AND evidence_digest=%s AND result=%s AND source=%s RETURNING result",
                (*prefix, evidence_digest, record["result"], record["source"]),
                fetch="one",
            )
            check()
            if namespace_check is not None:
                _complete_sync_none(await namespace_check(), "Effect compaction namespace check")
                check()
        check()
        if deleted is not None:
            removed += 1
            payload_bytes += len(deleted[0].encode("utf-8"))
    check()
    return {
        "scanned_records": len(rows),
        "removed_records": removed,
        "removed_payload_bytes": payload_bytes,
        "next_after_effect_key": rows[-1][0] if len(rows) == limit else None,
    }
