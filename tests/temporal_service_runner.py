"""Run an actual local Temporal Service for opt-in CI contracts, with persisted DB."""

import argparse
import asyncio
from pathlib import Path


async def serve(directory):
    from temporalio.testing import WorkflowEnvironment

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bin").mkdir(exist_ok=True)
    environment = await WorkflowEnvironment.start_local(
        download_dest_dir=str(directory / "bin"),
        dev_server_database_filename=str(directory / "temporal.sqlite"),
        dev_server_log_level="error",
    )
    try:
        address = environment.client.service_client.config.target_host
        (directory / "address").write_text(address, encoding="utf-8")
        print("Actual Temporal Service ready", flush=True)
        # CI controls this separate process through a filesystem stop marker.
        while not (directory / "stop").exists():  # noqa: ASYNC110
            await asyncio.sleep(0.25)
    finally:
        await environment.shutdown()
        (directory / "stopped").touch()
        print("Actual Temporal Service stopped", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.state_dir.resolve()))


if __name__ == "__main__":
    main()
