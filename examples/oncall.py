"""Interactive SDK example. Approval is an explicit human action."""

import asyncio
import json
from dataclasses import asdict

from ralf_agent.demo import create_demo_engine, demo_spec


async def main():
    with create_demo_engine(".ralf/oncall.sqlite") as engine:
        run = engine.submit(demo_spec(), {"ticket": "INC-001"}, command_id="interactive:INC-001")
        state = await engine.drive(run.run_id)
        print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
        if state.state == "waiting_approval":
            pending = state.pending[0]
            if (
                await asyncio.to_thread(input, "Type APPROVE to apply the test change: ")
                == "APPROVE"
            ):
                engine.approve(
                    run.run_id,
                    pending["action_id"],
                    pending["digest"],
                    command_id=f"approve:{pending['action_id']}",
                )
                state = await engine.drive(run.run_id)
                print(json.dumps(asdict(state), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
