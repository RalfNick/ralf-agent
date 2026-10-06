"""Local-owner CLI. Approvals always require an explicit command."""

import argparse
import asyncio
import importlib
import inspect
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .cli_views import inspection, render_inspection, render_result
from .demo import create_demo_engine, demo_spec
from .engine import LocalEngine
from .errors import AuthorizationDenied, DefinitionMismatch, RalfError, ValidationError
from .storage import SQLiteStore
from .types import RunSnapshot, Scope


def load_engine(db, factory_path=None):
    """Load only explicitly configured, trusted local Python runtime code."""
    if factory_path is None:
        return create_demo_engine(db)
    module, separator, name = factory_path.partition(":")
    if not separator or not module or not name or ":" in name:
        raise ValidationError("Engine factory must use the form module:callable")
    # An explicitly selected factory is trusted local code. Console entry points
    # otherwise search venv/bin rather than the user's project directory.
    project_path = str(Path.cwd())
    if project_path not in sys.path:
        sys.path.insert(0, project_path)
    try:
        factory = getattr(importlib.import_module(module), name)
    except Exception as exc:
        raise ValidationError("Cannot import configured engine factory") from exc
    if not callable(factory) or inspect.iscoroutinefunction(factory):
        raise ValidationError("Engine factory must be a synchronous callable accepting db_path")
    try:
        engine = factory(db)
    except RalfError:
        raise
    except Exception as exc:
        raise ValidationError("Configured engine factory failed to construct its runtime") from exc
    if not isinstance(engine, LocalEngine):
        raise ValidationError("Engine factory must return a LocalEngine")
    return engine


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ralf", description="Ralf-Agent local runtime preview")
    parser.add_argument("--db", default=".ralf/runs.sqlite", help="Local execution database")
    parser.add_argument("--version", action="version", version=f"Ralf-Agent {__version__}")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="Output format")
    parser.add_argument(
        "--factory",
        help="Trusted local module:callable accepting db_path and returning LocalEngine",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the offline Oncall fixture until approval")
    demo.add_argument("--ticket", default="INC-001")
    demo.add_argument("--command-id")
    init = commands.add_parser("init", help="Create a standalone, offline Agent starter")
    init.add_argument("directory")
    init.add_argument("--template", default="oncall", help="Starter template: oncall or rag")
    for command in ("status", "inspect", "events", "resume", "cancel"):
        subparser = commands.add_parser(command)
        subparser.add_argument("run_id")
        if command == "events":
            subparser.add_argument("--after", type=int, default=0)
            subparser.add_argument("--limit", type=int, default=1000)
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
        if args.command == "init":
            from .starter import create_starter

            result = asdict(create_starter(args.directory, template=args.template))
        elif args.command in {"status", "inspect", "events"}:
            with SQLiteStore(args.db, readonly=True) as store:
                # A read transaction keeps the summary and credit totals in one
                # SQLite snapshot while another process advances the Run.
                store.conn.execute("BEGIN")
                run = store.run(args.run_id)
                if run["scope"] != asdict(Scope()):
                    raise AuthorizationDenied("CLI local owner cannot access this Run")
                if args.command == "inspect" or (
                    args.command == "status" and args.format == "text"
                ):
                    result = inspection(run, store.budget(args.run_id), args.db, args.factory)
                elif args.command == "status":
                    result = asdict(RunSnapshot.from_record(run))
                else:
                    result = [
                        asdict(event) for event in store.events(args.run_id, args.after, args.limit)
                    ]
        else:
            if args.command == "demo" and args.factory:
                raise ValidationError(
                    "demo uses its offline profile; omit --factory for this command"
                )
            with load_engine(args.db, args.factory) as engine:
                if args.command == "demo":
                    handle = engine.submit(
                        demo_spec(),
                        {"ticket": args.ticket},
                        command_id=args.command_id or f"demo:{args.ticket}",
                    )
                    result = asdict(asyncio.run(engine.drive(handle.run_id)))
                elif args.command == "resume":
                    try:
                        result = asdict(asyncio.run(engine.drive(args.run_id)))
                    except DefinitionMismatch as exc:
                        if args.factory is None:
                            raise DefinitionMismatch(
                                "Run differs from the offline demo profile; configure "
                                "--factory module:callable with its original runtime configuration"
                            ) from exc
                        raise
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
                if args.format == "text" and args.command in {"demo", "resume"}:
                    run = engine.store.run(result["run_id"])
                    result = inspection(run, engine.store.budget(run["id"]), args.db, args.factory)
        if args.format == "text":
            print(render_inspection(result) if "release" in result else render_result(result))
        else:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except RalfError as exc:
        message = (
            f"{exc.code}: {exc}"
            if args.format == "text"
            else json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False)
        )
        print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
