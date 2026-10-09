"""Installed offline planning/team projects; runtime remains the public SDK."""

import json

_RUNTIME = """from ralf_agent import ProfiledEngine, load_catalog


def create_engine(db_path):
    return ProfiledEngine(load_catalog("runtime.toml"), db_path)
"""

_MAIN = """import argparse
import asyncio
import json
from dataclasses import asdict

from ralf_agent import load_spec
from ralf_agent.types import digest
from .runtime import create_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--input")
    parser.add_argument("--command-id")
    parser.add_argument("--resume")
    parser.add_argument("--submit-only", action="store_true")
    args = parser.parse_args()
    if (args.input is None) == (args.resume is None):
        parser.error("Provide --input or --resume")
    with create_engine(args.db) as engine:
        if args.resume:
            result = asyncio.run(engine.drive(args.resume))
        else:
            spec = load_spec("workflow.json")
            handle = engine.submit(spec, args.input,
                command_id=args.command_id or "starter:" + digest(args.input), budget=16)
            result = handle if args.submit_only else asyncio.run(engine.drive(handle.run_id))
        print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
"""

_CATALOG = """schema_version = 1
[default]
name = "orchestration"
version = "1"
[[profiles]]
name = "orchestration"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
"""


def _files(kind):
    members = {
        name: {"name": name, "instructions": "Answer the assigned task"}
        for name in ("research", "review", "supervisor")[: 3 if kind == "team" else 2]
    }
    spec = {
        "kind": kind,
        "name": "offline-" + kind,
        "members": members,
        "child_budget": 4,
        "max_concurrency": 2 if kind == "team" else 1,
    }
    if kind == "team":
        spec.update(strategy="supervisor", strategy_config={"supervisor": "supervisor"})
    else:
        spec.update(planner="rule", verifier="complete", max_revisions=3, max_steps=16)
    return {
        "agent_app/__init__.py": "",
        "agent_app/__main__.py": _MAIN,
        "agent_app/runtime.py": _RUNTIME,
        "runtime.toml": _CATALOG,
        "workflow.json": json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        ".gitignore": ".ralf/\n__pycache__/\n",
        "README.md": f"""# Offline {kind} starter

Install ralf-agent in your Python environment, then run from this directory:

```shell
python -m agent_app --input hello --command-id first
python -m agent_app --input hello --command-id first
python -m agent_app --input later --command-id queued --submit-only
python -m agent_app --resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

workflow.json declares members and finite bounds; runtime.toml declares the
versioned provider profile. This fixture uses offline Echo and rule planning;
no AI/network charge is hidden. It establishes SDK/recovery behavior, not AI
task quality. Replace provider/member instructions for your application, and
retain the original profile/definitions/code for old Run recovery.

Children have separate Run/Session IDs; parent credits escrow the child cap.
Inspect the child Run for actual approval/effect evidence, then apply controls
to that child and resume the parent. Do not submit a new Run for unknown writes.
Parent cancellation stops new dispatch and propagates to linked children.
Finite team coordination is local; remote A2A/MQ and distributed authority
are separate capabilities. See the framework orchestration guide for custom
Planner/TeamStrategy and managed ModelPlanner configuration.
""",
    }


TEAM_FILES = _files("team")
PLAN_FILES = _files("dynamic")
