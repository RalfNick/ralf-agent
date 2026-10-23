"""Optional JSON-RPC event pages over the existing committed-event reader."""

from contextlib import aclosing

from .errors import AuthorizationDenied, ValidationError
from .event_records import EventCursor, EventEnvelope
from .event_stream import RunEventSubscription
from .messaging import _integer, _text
from .types import RunEvent, canonical

EXTENSION = "urn:ralf:a2a:run-events:v1"


def event_request(task_id, cursor=None, limit=100):
    _text(task_id, "Event Task identity")
    _integer(limit, "Event page limit", 1, 1000)
    params = {"id": task_id, "limit": limit}
    if cursor is not None:
        original = EventCursor.from_token(cursor)
        if original.run_id != task_id:
            raise AuthorizationDenied("Event cursor belongs to another Task")
        params["afterCursor"] = cursor
    return params


async def event_page(controls, params, *, max_bytes, request_id):
    if set(params) - {"id", "afterCursor", "limit"}:
        raise ValidationError("Invalid event page parameters")
    if "afterCursor" in params and params["afterCursor"] is None:
        raise ValidationError("Event cursor must be an encoded token")
    request = event_request(params.get("id"), params.get("afterCursor"), params.get("limit", 100))
    cursor = (
        EventCursor.from_token(request["afterCursor"])
        if "afterCursor" in request
        else EventCursor(controls.scope, request["id"])
    )
    if cursor.scope != controls.scope:
        raise AuthorizationDenied("Event cursor belongs to another Scope")
    controls.require_event_controls()
    await controls.status(request["id"])
    result = {
        "kind": "ralf.event-page",
        "taskId": request["id"],
        "events": [],
        "cursor_token": cursor.token,
    }

    def fits(value):
        return (
            len(canonical({"jsonrpc": "2.0", "id": request_id, "result": value}).encode())
            <= max_bytes
        )

    if not fits(result):
        raise ValueError("Event page header exceeds response limit")
    async with aclosing(
        RunEventSubscription(
            controls,
            request["id"],
            after=cursor,
            page_size=request["limit"],
            max_events=request["limit"],
            follow=False,
        )
    ) as stream:
        async for record in stream:
            candidate = {
                **result,
                "events": [*result["events"], record.to_dict()],
                "cursor_token": record.cursor.token,
            }
            if not fits(candidate):
                if not result["events"]:
                    raise ValueError("One durable event exceeds response limit")
                break
            result = candidate
    controls.verify()
    return result


def validate_event_page(value, params):
    request = event_request(params.get("id"), params.get("afterCursor"), params.get("limit", 100))
    if (
        type(value) is not dict
        or set(value) != {"kind", "taskId", "events", "cursor_token"}
        or value["kind"] != "ralf.event-page"
        or value["taskId"] != request["id"]
        or type(value["events"]) is not list
        or len(value["events"]) > request["limit"]
    ):
        raise ValidationError("Invalid event page")
    end = EventCursor.from_token(value["cursor_token"])
    previous = (
        EventCursor.from_token(request["afterCursor"])
        if "afterCursor" in request
        else EventCursor(end.scope, request["id"])
    )
    for item in value["events"]:
        if type(item) is not dict or set(item) != {"event", "cursor", "cursor_token"}:
            raise ValidationError("Invalid event envelope")
        record = EventEnvelope(previous.scope, RunEvent(**item["event"]))
        if (
            record.cursor.run_id != previous.run_id
            or record.cursor.after != previous.after + 1
            or canonical(item) != canonical(record.to_dict())
        ):
            raise ValidationError("Event page contains a gap or foreign event")
        previous = record.cursor
    if end != previous:
        raise ValidationError("Event page cursor does not match its records")
    return value
