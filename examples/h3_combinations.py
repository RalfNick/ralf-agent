"""Offline Plan/Team starting combinations; Echo demonstrates wiring only."""

import argparse
import asyncio

from relf_agent import Runtime, RuntimeBuilder, recommended_harness, recommended_profile


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("plan-and-execute", "team"))
    parser.add_argument("--database", default="h3-runs.sqlite")
    parser.add_argument("--task", default="Describe the task's evidence and open questions")
    parser.add_argument("--command-id", default="example-one")
    args = parser.parse_args()
    instance = await RuntimeBuilder().abuild(recommended_profile(args.kind), args.database)
    async with Runtime(instance, owned=True) as runtime:
        run = await runtime.submit(
            recommended_harness(args.kind), args.task, command_id=args.command_id
        )
        print(await run.wait())


if __name__ == "__main__":
    asyncio.run(main())
