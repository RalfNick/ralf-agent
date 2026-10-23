"""Pure Facts evidence rules; no clients, clocks or execution authority."""

from .errors import DefinitionMismatch, ValidationError
from .recall import RecallQuery, _fact_records
from .types import canonical, digest


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    enabled = "facts_context" in manifest or any(
        "facts_context" in r.get("configuration", {}) for r in records
    )
    if enabled or "facts_protocol" in manifest or "facts_recall" in manifest:
        if (
            manifest.get("kernel") != "temporal-3"
            or manifest.get("facts_protocol") != 1
            or type(manifest.get("facts_recall")) is not dict
        ):
            raise DefinitionMismatch("Unsupported Temporal Facts recall protocol")


def validate_snapshot(snapshot, manifest):
    if "facts_context" not in manifest:
        return
    facts, knowledge, receipt = (
        snapshot.get("facts"),
        snapshot.get("knowledge_references"),
        snapshot.get("facts_recall"),
    )
    if (
        type(facts) is not list
        or type(knowledge) is not list
        or type(receipt) is not dict
        or snapshot.get("references") != knowledge + facts
        or ("knowledge_context" not in manifest and knowledge != [])
        or receipt.get("version") != 1
        or receipt.get("digest") != digest(facts)
    ):
        raise ValidationError("Invalid adopted Temporal Facts evidence")
    if _fact_records(facts) != facts or len({f["key"] for f in facts}) != len(facts):
        raise ValidationError("Invalid adopted Temporal Facts records")
    try:
        query = RecallQuery(**receipt["query"])
        page_query = RecallQuery(**receipt["page_query"])
        pages = receipt["pages"]
        count = receipt["max_pages"]
        if type(count) is not int or not 1 <= count <= 10:
            raise ValidationError("Invalid recall page count")
        allocated = min(count, query.max_items, query.max_chars // 2)
        if (
            query.cursor is not None
            or page_query.cursor is not None
            or type(pages) is not list
            or not 1 <= len(pages) <= allocated
            or page_query.max_items != query.max_items // allocated
            or page_query.max_chars != query.max_chars // allocated
            or page_query.scan_limit != query.scan_limit // allocated
            or page_query.text != query.text
            or len(facts) > query.max_items
            or len(canonical(facts)) > query.max_chars
            or sum(p["scanned"] for p in pages) > query.scan_limit
        ):
            raise ValidationError("Adopted Facts exceeded fixed recall allowance")
    except (KeyError, TypeError) as exc:
        raise ValidationError("Invalid adopted Facts recall receipt") from exc
