"""Local-owner CLI. Approvals always require an explicit command."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from .demo import create_demo_engine, demo_spec
from .errors import AuthorizationDenied, RalfError
from .storage import SQLiteStore
from .types import RunSnapshot, Scope


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ralf", description="Ralf-Agent local runtime preview")
    parser.add_argument("--db", default=".ralf/runs.sqlite", help="Local execution database")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the offline Oncall fixture until approval")
    demo.add_argument("--ticket", default="INC-001")
    demo.add_argument("--command-id")
    for command in ("status", "events", "resume", "cancel"):
        subparser = commands.add_parser(command)
        subparser.add_argument("run_id")
        if command == "events":
            subparser.add_argument("--after", type=int, default=0)
        if command == "cancel":
            subparser.add_argument("--command-id", required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("run_id")
    approve.add_argument("action_id")
    approve.add_argument("--digest", required=True)
    approve.add_argument("--command-id", required=True)
    approve.add_argument("--reject", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in {"status", "events"}:
            with SQLiteStore(args.db) as store:
                run = store.run(args.run_id)
                if run["scope"] != asdict(Scope()):
                    raise AuthorizationDenied("CLI local owner cannot access this Run")
                result = (
                    asdict(RunSnapshot.from_record(run))
                    if args.command == "status"
                    else [asdict(event) for event in store.events(args.run_id, args.after)]
                )
        else:
            with create_demo_engine(args.db) as engine:
                if args.command == "demo":
                    handle = engine.submit(
                        demo_spec(),
                        {"ticket": args.ticket},
                        command_id=args.command_id or f"demo:{args.ticket}",
                    )
                    result = asdict(asyncio.run(engine.drive(handle.run_id)))
                elif args.command == "resume":
                    result = asdict(asyncio.run(engine.drive(args.run_id)))
                elif args.command == "approve":
                    result = asdict(
                        engine.approve(
                            args.run_id,
                            args.action_id,
                            args.digest,
                            command_id=args.command_id,
                            approved=not args.reject,
                        )
                    )
                else:
                    result = asdict(engine.cancel(args.run_id, command_id=args.command_id))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except RalfError as exc:
        print(
            json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
