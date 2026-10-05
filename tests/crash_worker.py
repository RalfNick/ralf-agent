"""Test-only process: die after downstream commit, before tool result persistence."""

import asyncio
import json
import os
import sys

from ralf_agent.demo import DemoService, create_demo_engine, demo_spec

original_apply = DemoService.apply


def die_after_commit(self, arguments, effect_key):
    original_apply(self, arguments, effect_key)
    os._exit(77)


DemoService.apply = die_after_commit
with create_demo_engine(sys.argv[1]) as engine:
    run = engine.submit(demo_spec(), {"ticket": "INC-CRASH"}, command_id="crash-start")
    waiting = asyncio.run(engine.drive(run.run_id))
    print(json.dumps({"run_id": run.run_id}), flush=True)
    pending = waiting.pending[0]
    engine.approve(run.run_id, pending["action_id"], pending["digest"], command_id="crash-approve")
    asyncio.run(engine.drive(run.run_id))
