"""Read existing scoped Run events; no execution, creation or implicit follow."""

import argparse
import asyncio
import json
import sys

from .errors import RalfError
from .event_records import EventCursor
from .event_stream import RunEventSubscription
from .runtime_router import SQLiteRunReader
from .types import Scope


async def _watch(args):
    after = 0 if args.after_cursor is None else EventCursor.from_token(args.after_cursor)
    source = SQLiteRunReader(args.db, scope=Scope(args.workspace, args.principal))
    stream = RunEventSubscription(
        source,
        args.run_id,
        after=after,
        follow=args.follow,
        page_size=args.page_size,
        poll_interval=args.poll_interval,
        read_timeout=args.read_timeout,
        max_events=args.max_events,
    )
    try:
        async for event in stream:
            text = (
                event.to_sse()
                if args.sse
                else json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
            )
            sys.stdout.write(text)
            sys.stdout.flush()
    finally:
        await stream.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--principal", default="local-owner")
    parser.add_argument("--after-cursor")
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--sse", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-events", type=int, default=1000)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument("--read-timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        asyncio.run(_watch(args))
        return 0
    except KeyboardInterrupt:
        return 130
    except (RalfError, TimeoutError, OSError) as exc:
        known = {"authorization_denied", "definition_mismatch", "validation_error", "not_found"}
        code = getattr(exc, "code", None)
        code = code if isinstance(code, str) and code in known else "event_read_failed"
        print(json.dumps({"error": {"code": code}}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
