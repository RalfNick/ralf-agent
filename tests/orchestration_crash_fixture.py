"""Local real-process proposal/child durability windows; counters are test probes."""

import argparse
import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from ralf_agent import (
    AgentSpec,
    DAGNode,
    DAGProposal,
    DynamicWorkflowSpec,
    LocalEngine,
    ModelResponse,
    PlanProposal,
    PlanStep,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
    ValueRef,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--crash")
    parser.add_argument("--run-id")
    parser.add_argument("--dag", action="store_true")
    parser.add_argument("--nested", action="store_true")
    args = parser.parse_args()
    counter = Path(args.database).with_suffix(".counter.sqlite")

    def count(kind):
        with sqlite3.connect(counter) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS counts(kind TEXT)")
            conn.execute("INSERT INTO counts VALUES (?)", (kind,))

    class Provider:
        identity = {"kind": "crash-counted", "version": "1"}

        async def complete(self, messages, tools):
            count("model")
            return ModelResponse(output="done")

    class Planner:
        identity = {"kind": "crash-planner", "version": "1"}

        async def plan(self, request, caller):
            count("plan")
            if args.dag:
                return DAGProposal(
                    [
                        DAGNode("work", "one"),
                        DAGNode("finish", "two", depends_on=("work",), input=ValueRef("work")),
                    ],
                    output=ValueRef("finish"),
                )
            return PlanProposal([PlanStep("work", "one", "task")])

    class Store(SQLiteStore):
        @contextmanager
        def transaction(self):
            with super().transaction():
                yield
            if (
                args.crash
                and not self.conn.in_transaction
                and self.conn.execute("SELECT 1 FROM events WHERE kind=?", (args.crash,)).fetchone()
            ):
                os._exit(77)

    with LocalEngine(
        Store(args.database),
        providers={"default": Provider()},
        tools=ToolRegistry(),
        planners={"counted": Planner()},
    ) as e:
        run_id = args.run_id
        if run_id is None:
            members = {"one": AgentSpec("one", "One")}
            if args.dag:
                members["two"] = AgentSpec("two", "Two")
            if args.nested:
                members["one"] = TeamSpec(
                    "inner", {"leaf": AgentSpec("leaf", "Leaf")}, child_budget=2
                )
            run_id = e.submit(
                DynamicWorkflowSpec(
                    "crash",
                    members,
                    planner="counted",
                    child_budget=4,
                    plan_mode="dag" if args.dag else "flat",
                ),
                "task",
                command_id="s",
                budget=8,
            ).run_id
        print(json.dumps({"run_id": run_id}), flush=True)
        print(json.dumps(asdict(asyncio.run(e.drive(run_id)))), flush=True)


if __name__ == "__main__":
    main()
