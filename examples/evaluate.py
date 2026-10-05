"""Offline runtime regression baseline; no model API calls or production writes."""

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from ralf_agent.demo import create_demo_engine, demo_spec


async def evaluate(path, ticket):
    started = time.perf_counter()
    with create_demo_engine(path) as engine:
        handle = engine.submit(demo_spec(), {"ticket": ticket}, command_id=f"eval:{ticket}")
        waiting = await engine.drive(handle.run_id)
        assert waiting.state == "waiting_approval"
        pending = waiting.pending[0]
    # Close/reopen to exercise durable waiting instead of merely continuing in memory.
    with create_demo_engine(path) as engine:
        engine.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id=f"approved:{ticket}"
        )
        done = await engine.drive(handle.run_id)
        budget = engine.store.budget(handle.run_id)
    with sqlite3.connect(str(path) + ".business.sqlite") as conn:
        writes = conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    sequence = [a["tool"] for a in done.actions if a["kind"] == "tool"]
    passed = (
        done.state == "succeeded"
        and done.result["verified"]
        and writes == 1
        and sequence == ["read_ticket", "apply_change", "verify_change"]
    )
    return {
        "ticket": ticket,
        "passed": passed,
        "state": done.state,
        "business_writes": writes,
        "tool_sequence": sequence,
        "approval_decisions": 1,
        "budget": budget,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def main():
    with tempfile.TemporaryDirectory(prefix="ralf-eval-") as directory:
        cases = [
            await evaluate(Path(directory) / f"case-{index}.sqlite", ticket)
            for index, ticket in enumerate(["INC-001", "INC-中文", "INC-003"])
        ]
    report = {
        "scope": "offline-runtime-regression",
        "provider": "offline-scripted-oncall:1",
        "total": len(cases),
        "passed": sum(case["passed"] for case in cases),
        "cases": cases,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
