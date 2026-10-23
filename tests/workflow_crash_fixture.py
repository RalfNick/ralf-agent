"""Real-process graph recovery fixture; only isolated local business storage."""

import argparse
import asyncio
import json
import os
from dataclasses import asdict

from relf_agent import GraphNode, GraphWorkflowSpec, ValueRef
from tests.receipt_runtime import create_engine, spec


def graph_spec():
    return GraphWorkflowSpec(
        "recoverable-graph",
        [
            GraphNode("apply", agent=spec("queryable_write")),
            GraphNode(
                "finish", transform="identity", depends_on=("apply",), input=ValueRef("apply")
            ),
        ],
        output=ValueRef("finish"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--crash", choices=("started", "completed", "session"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    trigger = {"started": "workflow_node_started", "completed": "workflow_node_completed"}.get(
        args.crash
    )
    with create_engine(args.database, "queryable_write", trigger_event=trigger) as engine:
        if args.crash == "session":
            append = engine.sessions.append

            def crash_after_append(*values, **options):
                append(*values, **options)
                os._exit(77)

            engine.sessions.append = crash_after_append
        run_id = args.run_id
        if run_id is None:
            run_id = engine.submit(
                graph_spec(), {"ticket": "fixture"}, command_id="start", budget=12
            ).run_id
        if args.crash:
            print(json.dumps({"run_id": run_id}), flush=True)
        print(json.dumps(asdict(asyncio.run(engine.drive(run_id)))))


if __name__ == "__main__":
    main()
