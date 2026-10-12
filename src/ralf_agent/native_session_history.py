"""Complete bounded native Session data reads, beneath the original authority."""

import json

from .binding_sessions import SessionView
from .context_budget import _positive
from .errors import DefinitionMismatch, ValidationError
from .fact_index_ports import _FixedPorts
from .memory import ThreadedMemoryAdapter
from .model_history import _reject_lazy
from .recall import LegacyMemoryRecallAdapter, RecallPage, RecallQuery
from .session_model_history import (
    _MAX_BYTES,
    _MAX_TURNS,
    _json_data,
    native_history_address,
    validate_native_history_envelope,
)
from .types import Scope, canonical, digest


def _native_page_source(backend):
    original = backend
    roots = [original]
    while isinstance(original, (SessionView, ThreadedMemoryAdapter)):
        original = original.backend
        if any(original is root for root in roots):
            raise ValidationError("Native history page source wrappers contain a cycle")
        roots.append(original)
    if isinstance(original, LegacyMemoryRecallAdapter) or not callable(
        getattr(original, "read_page", None)
    ):
        raise ValidationError("Native history requires an original bounded read_page port")
    return roots


async def read_native_history(
    backend, scope, address, *, stream, max_chars=8388608, max_turns=128
) -> dict:
    """Read a fixed complete snapshot with no skipping, trimming, or legacy reads."""
    _positive(max_chars, "Native stream character limit", _MAX_BYTES)
    _positive(max_turns, "Native stream Turn limit", _MAX_TURNS)
    if not isinstance(scope, Scope) or address != native_history_address(stream):
        raise ValidationError("Native history requires its trusted Scope and isolated address")
    roots = _native_page_source(backend)
    fixed = _FixedPorts(
        {
            "session" if index == 0 else f"source-{index}": (root, ["read_page"], True)
            for index, root in enumerate(roots)
        }
    )
    resources = [(root, "backend", root.backend) for root in roots[:-1]]
    resources.extend(
        (root, name, getattr(root, name))
        for root in roots
        for name in ("_client", "connection")
        if hasattr(root, name)
    )
    resources.extend(
        (client, "connection_pool", client.connection_pool)
        for _, _, client in list(resources)
        if hasattr(client, "connection_pool")
    )

    def check_resources():
        fixed.check()
        if any(getattr(owner, name, None) is not original for owner, name, original in resources):
            raise DefinitionMismatch("Native Session source, client or pool changed during read")

    cursor, snapshot_id, revision = None, None, None
    cursors, sources, pages = set(), set(), []
    count, chars, size = 0, 2, 2
    while True:
        check_resources()
        query = RecallQuery(
            max_items=1, max_chars=1_000_000, scan_limit=1, text=None, cursor=cursor
        )
        page = await fixed.call("session", "read_page", scope, address, query)
        check_resources()
        if not isinstance(page, RecallPage):
            _reject_lazy(page)
            raise ValidationError("Native history read requires a completed RecallPage")
        # Validate JSON before any deep copy could enter a deferred/custom value.
        items = _json_data(page.items, "Native history page", max_chars=1_000_000)
        page = RecallPage(
            items,
            page.next_cursor,
            page.used_chars,
            page.scanned,
            page.skipped,
            page.snapshot_id,
            page.backend_bounded,
        )
        if (
            not page.backend_bounded
            or page.skipped != 0
            or page.scanned != len(page.items)
            or page.scanned > query.scan_limit
            or len(page.items) > query.max_items
            or page.used_chars > query.max_chars
        ):
            raise ValidationError("Native history page must be bounded, complete and unskipped")
        if snapshot_id is None:
            snapshot_id = page.snapshot_id
            try:
                snapshot = _json_data(json.loads(snapshot_id), "Native Session snapshot")
            except (ValueError, RecursionError):
                raise ValidationError(
                    "Native Session snapshot requires an exact revision"
                ) from None
            if (
                type(snapshot) is not dict
                or type(snapshot.get("revision")) is not int
                or not 0 <= snapshot["revision"] <= max_turns
            ):
                raise ValidationError("Native Session snapshot revision exceeds its Turn limit")
            revision = snapshot["revision"]
        elif page.snapshot_id != snapshot_id:
            raise ValidationError("Native history read changed its fixed snapshot")
        selected = []
        for item in page.items:
            turn = validate_native_history_envelope(item, stream=stream)
            source = digest(turn["source"])
            if source in sources:
                raise ValidationError("Native history repeated a published Turn source")
            sources.add(source)
            encoded = canonical(turn)
            chars += len(encoded) + bool(count)
            size += len(encoded.encode("utf-8")) + bool(count)
            count += 1
            if count > max_turns or chars > max_chars or size > _MAX_BYTES:
                raise ValidationError("Native history stream exceeds its complete evidence limit")
            selected.append(turn)
        pages.append(selected)
        cursor = page.next_cursor
        if cursor is None:
            if count != revision:
                raise ValidationError("Native history read does not cover its snapshot revision")
            break
        if not page.items or count >= revision or cursor in cursors:
            raise ValidationError("Native history cursor did not advance a complete snapshot")
        cursors.add(cursor)
    # Session read_page walks newest pages first, with append order inside each page.
    return {
        "snapshot_id": snapshot_id,
        "revision": revision,
        "turns": [turn for page in reversed(pages) for turn in page],
    }
