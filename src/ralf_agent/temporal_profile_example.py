"""Installed offline-first configuration example; networking is explicit."""

import argparse
import asyncio
import json
from pathlib import Path

from . import AgentSpec, GraphNode, GraphWorkflowSpec, Runtime, Scope
from .temporal_builder import TemporalRuntimeBuilder
from .temporal_profile import TemporalProfileCatalog
from .types import digest

CONFIGURATION = """kind = "temporal-profiles"
schema_version = 1
[default]
name = "example"
version = "1"
[[profiles]]
name = "example"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.session_store]
adapter = "sqlite"
[profiles.components.session_store.config]
path = "sessions.sqlite"
[profiles.components.context_assembler]
adapter = "managed-summary"
[profiles.execution]
enable_sessions = true
session_writes = true
composite_sessions = true
context_reads = true
"""


async def execute(path, address, namespace):
    from .temporal import _sdk

    Client = _sdk()[0]
    client = await Client.connect(address, namespace=namespace)
    catalog = TemporalProfileCatalog.from_file(path)
    assembled = await TemporalRuntimeBuilder(base_dir=catalog.base_dir).abuild(
        catalog.default_profile, scope=Scope("temporal-profile-example", "developer")
    )
    host = None
    try:
        queue = "ralf-profile-example-" + digest(assembled.release)[:16]
        await assembled.start_worker(client, task_queue=queue)
        engine = assembled.create_engine(
            client, task_queue=queue, activity_timeout=5, drive_timeout=30
        )
        host = Runtime.from_temporal(engine)
        graph = GraphWorkflowSpec(
            "example", [GraphNode("answer", agent=AgentSpec("answer", "Answer"))]
        )
        entry = await host.open_session(graph, "chat", command_id="open")
        results = []
        for index in (1, 2):
            turn = await entry.submit("question", command_id=f"turn-{index}", budget=32)
            done = await engine.drive(turn.turn.run.run_id)
            if done.state != "succeeded":
                raise RuntimeError(f"Original Run requires attention: {done.state}, {done.error}")
            async with asyncio.timeout(30):
                while (await entry.status()).busy:  # noqa: ASYNC110 -- original History evidence
                    await asyncio.sleep(0.05)
            results.append({"run_id": done.run_id, "state": done.state, "result": done.result})
        print(
            json.dumps(
                {"profile": assembled.profile.identity, "turns": results}, ensure_ascii=False
            )
        )
    finally:
        if host is not None:
            await host.aclose()
        await assembled.aclose(wait_timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("ralf-temporal-example"))
    parser.add_argument(
        "--address", help="Explicit Temporal address; omitted writes configuration only"
    )
    parser.add_argument("--namespace", default="default")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    path = args.data_dir / "temporal.toml"
    if not path.exists():
        path.write_text(CONFIGURATION, encoding="utf-8")
    if args.address:
        asyncio.run(execute(path, args.address, args.namespace))
    else:
        print(f"Configuration saved: {path.resolve()}")


if __name__ == "__main__":
    main()
