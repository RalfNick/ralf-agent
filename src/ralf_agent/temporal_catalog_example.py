"""Installed multiversion Host example; service connection is always explicit."""

import argparse
import asyncio
import json
from pathlib import Path

from . import AgentSpec, Scope, TemporalProfile, TemporalProfileCatalog, TemporalRuntimeBuilder
from .types import digest


def configuration():
    catalog = TemporalProfileCatalog()
    for version in ("1", "2"):
        catalog.register(
            TemporalProfile("example", version, {"default": {"adapter": "offline-echo"}}),
            default=version == "1",
        )
    return catalog.to_dict()


async def execute(path, address, namespace):
    from .temporal import _sdk

    Client = _sdk()[0]
    client = await Client.connect(address, namespace=namespace)
    catalog = TemporalProfileCatalog.from_file(path)
    host = await TemporalRuntimeBuilder().abuild_catalog(
        catalog, scope=Scope("temporal-catalog-example", digest(str(path.resolve()))[:32])
    )
    try:
        await host.start_workers(
            client, queue_prefix="ralf-catalog-example", engine_options={"activity_timeout": 5}
        )
        definition = AgentSpec("answer", "Answer")
        original_profile = next(p for p in host.profiles if p.version == "1")
        replacement = next(p for p in host.profiles if p.version == "2")
        original = await host.runtime(original_profile.identity).submit(
            definition, "question", command_id="original", budget=16
        )
        host.select_default(replacement.identity)
        attached = await host.aattach(original.ref)
        completed = await attached.wait(wait_timeout=30, terminal_only=True)
        new = await host.runtime().submit(definition, "question", command_id="new", budget=16)
        new_result = await new.wait(wait_timeout=30, terminal_only=True)
        if any(r.snapshot.state != "succeeded" for r in (completed, new_result)):
            raise RuntimeError("Original Run requires attention")
        duplicate = await host.runtime().submit(
            definition, "question", command_id="original", budget=16
        )
        print(
            json.dumps(
                {
                    "original_profile": original_profile.identity,
                    "new_profile": host.default_profile.identity,
                    "original_run": original.ref.to_dict(),
                    "new_run": new.ref.to_dict(),
                    "duplicate_returns_original": duplicate.ref == original.ref
                    and duplicate.receipt == original.receipt,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await host.aclose(wait_timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("ralf-temporal-catalog"))
    parser.add_argument("--address", help="Explicit service address; omitted writes JSON only")
    parser.add_argument("--namespace", default="default")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    path = args.data_dir / "temporal.json"
    if not path.exists():
        path.write_text(json.dumps(configuration(), indent=2), encoding="utf-8")
    if args.address:
        asyncio.run(execute(path, args.address, args.namespace))
    else:
        print(f"Configuration saved: {path.resolve()}")


if __name__ == "__main__":
    main()
