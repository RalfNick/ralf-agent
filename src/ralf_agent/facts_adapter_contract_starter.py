"""Generate a complete editable independent Facts adapter application."""

import inspect
import json

from . import facts_adapter_contract_reference

_RUNTIME = '''"""Explicit idempotent seed and original Local application assembly."""
from pathlib import Path

from ralf_agent import (
    AgentSpec, ComponentRegistry, MemoryPipeline, ProfiledEngine, Runtime,
    RuntimeBuilder, Scope, load_catalog,
)
from .adapter import ReferenceFactsSource, ReferenceSQLiteManagedFactsStore, register_facts_reference_components


def source_path():
    return Path(".ralf/facts.sqlite").resolve()


def seed():
    source = ReferenceFactsSource(source_path())
    try:
        store = ReferenceSQLiteManagedFactsStore(source)
        seeded = 0
        entries = [
            (Scope(), "seed", "original seeded fact", None),
            (Scope(), "expired", "expired fact excluded", 1),
            (Scope(workspace="foreign-workspace"), "seed", "foreign workspace excluded", None),
            (Scope(principal="foreign-principal"), "seed", "foreign principal excluded", None),
        ]
        for scope, key, value, expiry in entries:
            if store.inspect_fact(scope, "reader", key) is None:
                store.put_fact(scope, "reader", key, value, expected_version=0, expires_at=expiry)
                seeded += 1
        return {"seeded": seeded}
    finally:
        source.close()


def components(*, source=None, asynchronous=False, owned=True):
    registry = ComponentRegistry()
    register_facts_reference_components(registry, source, asynchronous=asynchronous, owned=owned)
    return registry


def create_engine(db_path):
    # Registration and historical observations never open the Facts dataset.
    return ProfiledEngine(load_catalog("runtime.toml"), db_path,
        builder=RuntimeBuilder(components(), base_dir=Path.cwd()))


async def run(*, mode="managed", format="toml", asynchronous=False, owned=True,
              command_id="facts-first"):
    source = None
    try:
        if not owned:
            source = ReferenceFactsSource(source_path())
        registry = components(source=source, asynchronous=asynchronous, owned=owned)
        catalog = load_catalog("runtime." + format)
        catalog.set_default("external-facts-" + mode, "1")
        builder = RuntimeBuilder(registry, base_dir=Path.cwd())
        instance = await builder.abuild(catalog.default, ".ralf/runs.sqlite") if asynchronous else builder.build(catalog.default, ".ralf/runs.sqlite")
        async with Runtime(instance, owned=True):
            source = instance.memory._original_source
            before = source.audit()
            definition = AgentSpec("reader", "Read actual current scoped facts")
            if mode == "pipeline":
                pipeline = MemoryPipeline(instance, namespace="observations")
                result = await pipeline.run(definition, "read actual facts", command_id=command_id, budget=32)
                snapshot, memory = result["task"], result["memory"]
                run_id = snapshot["run_id"]
            else:
                handle = instance.submit(definition, "read actual facts", command_id=command_id, budget=32)
                done = await instance.drive(handle.run_id)
                snapshot = {"state": done.state, "result": done.result, "error": done.error}
                run_id = handle.run_id
                memory = instance.memory_stages(run_id) if mode == "managed" else None
        after = source.audit()
        return {
            "run_id": run_id, "state": snapshot["state"], "result": snapshot["result"],
            "error": snapshot["error"], "memory": memory,
            "audit": {key: after[key] - before[key] for key in after},
            "adapter_module": "agent_app.adapter", "execution_authority": "local",
            "model_quality": None,
        }
    finally:
        # Borrowed sources remain host-owned until the original Runtime drains.
        if source is not None:
            source.close()
'''

_MAIN = """import argparse
import asyncio
import json

from .adapter import offline_facts_fixture
from .runtime import run, seed


async def check(evidence_dir, profile):
    from ralf_agent import AdapterContractSuite
    from ralf_agent.errors import CloseIncomplete

    suite = AdapterContractSuite(role="facts-store", contract_version="1", profile=profile)
    try:
        return await suite.run(offline_facts_fixture(), evidence_dir=evidence_dir)
    finally:
        try:
            await suite.aclose()
        except CloseIncomplete:
            await suite.aclose()
            raise


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    checks = commands.add_parser("check")
    checks.add_argument("--profile", choices=("core", "managed"), default="core")
    checks.add_argument("--evidence-dir")
    execute = commands.add_parser("run")
    execute.add_argument("--mode", choices=("core", "pipeline", "managed"), default="managed")
    execute.add_argument("--format", choices=("json", "toml"), default="toml")
    execute.add_argument("--async", dest="asynchronous", action="store_true")
    execute.add_argument("--borrowed", action="store_true")
    execute.add_argument("--command-id", default="facts-first")
    arguments = parser.parse_args()
    if arguments.command == "seed":
        result = seed()
    elif arguments.command == "check":
        from ralf_agent.errors import CloseIncomplete, ValidationError
        try:
            result = asyncio.run(check(arguments.evidence_dir, arguments.profile)).to_dict()
        except CloseIncomplete as exc:
            result = {"status": "failed", "reason": "cleanup_incomplete",
                      "contract_report": exc.report.get("contract_report")}
        except ValidationError:
            result = {"status": "invalid", "reason": "invalid_contract_configuration"}
    else:
        result = asyncio.run(run(mode=arguments.mode, format=arguments.format,
            asynchronous=arguments.asynchronous, owned=not arguments.borrowed,
            command_id=arguments.command_id))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if arguments.command == "check":
        return 0 if result["status"] in {"passed", "not_run"} else 1
    return 0 if arguments.command == "seed" or result["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""

_README = """# Independent Facts adapter application

Install relf-agent and run these commands from this directory. The full SQLite
source and core/managed Facts adapter are editable in `agent_app/adapter.py`.
They store facts independently of native SDK Memory. The original Local engine
owns Runs, Actions, command receipts, memory stages and budget settlement.

```shell
python -m agent_app check
python -m agent_app check --profile managed
python -m agent_app seed
python -m agent_app run --mode core --command-id facts-core-first
python -m agent_app run --mode pipeline --command-id facts-pipeline-first
python -m agent_app run --mode managed --command-id facts-managed-first
python -m agent_app run --format json --async --borrowed --command-id facts-async-first
```

Core implements current reads and raw CAS; an accepted raw CAS retry conflicts.
Managed adds bounded recall, validation and exact current-state inspection.
Inspection includes expired records and is not a historical write receipt.
`pipeline` uses original MemoryPipeline; `managed` uses original ManagedMemoryPolicy.
Business success and an unknown auxiliary memory outcome are separate results.

All modes share `.ralf/facts.sqlite` and `.ralf/runs.sqlite`. Seed is explicit and
idempotent. It adds one current fact plus expired and foreign Scope facts, which
the actual Agent context excludes. Runs and recovery never seed. Reader facts
use namespace `reader`; sourced observations use `observations`. Choose distinct
command IDs for distinct Runs when switching mode or configuration.

JSON and TOML declare the same registered factories. Registry construction is
zero I/O. Owned data opens lazily inside original BuildContext; `--async` uses
register_async/abuild/own_async. `--borrowed` closes the host source after Runtime
drains. The source pins a persisted dataset UUID and live physical file identity.
Historical observation factory construction leaves the Facts dataset unopened.

Keep original application code, profiles and databases for historical Runs:

```shell
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Exact inspection can adopt an accepted write after lost acknowledgement; a
committed original receipt settles its original reservation without another
model request or accepted write. Independent process interruption tests cover
these windows separately from suite checks. This offline Provider reports its
committed Facts context for wiring evidence; model/service/task quality remains
unverified. Suite results do not certify arbitrary remote services, Temporal
History, full R25/H3/M1 completion or independent adoption. Use a fresh private
evidence directory for bounded evidence. Failed cleanup retries the same actual
suite owner on the original loop and retains its failure.
"""


def _toml_value(value):
    if type(value) is bool:
        return str(value).lower()
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(json.dumps(key) + " = " + _toml_value(item) for key, item in value.items())
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def facts_contract_files():
    """Return an installed-SDK-only editable application without data I/O."""
    source = inspect.getsource(facts_adapter_contract_reference)
    for name in (
        "errors",
        "recall",
        "types",
        "providers",
        "facts_adapter_contract",
        "managed_memory",
        "memory_extraction",
    ):
        source = source.replace("from ." + name + " import", "from ralf_agent." + name + " import")
    profiles = []
    for mode in ("managed", "core", "pipeline"):
        components = {
            "context_assembler": {"adapter": "default"},
            "verifier": {"adapter": "schema"},
            "memory_store": {
                "adapter": "external-facts",
                "config": {"path": ".ralf/facts.sqlite", "managed": mode != "core"},
            },
        }
        if mode == "managed":
            components["stage_policy"] = {
                "adapter": "external-facts-stage",
                "config": {
                    "path": ".ralf/facts.sqlite",
                    "namespace": "observations",
                    "fields": {"answer": ["result", "answer"]},
                },
            }
        profiles.append(
            {
                "name": "external-facts-" + mode,
                "version": "1",
                "providers": {
                    "default": {
                        "adapter": "external-facts-reader",
                        "config": {"path": ".ralf/facts.sqlite"},
                    }
                },
                "components": components,
            }
        )
    catalog = {
        "schema_version": 1,
        "default": {"name": "external-facts-managed", "version": "1"},
        "profiles": profiles,
    }
    toml = ["schema_version = 1", "[default]", 'name = "external-facts-managed"', 'version = "1"']
    for profile in profiles:
        toml.extend(["[[profiles]]", "name = " + json.dumps(profile["name"]), 'version = "1"'])
        for section in ("providers", "components"):
            for role, declaration in profile[section].items():
                toml.extend(
                    [
                        "[profiles." + section + "." + role + "]",
                        "adapter = " + json.dumps(declaration["adapter"]),
                    ]
                )
                if declaration.get("config"):
                    toml.append("[profiles." + section + "." + role + ".config]")
                    toml.extend(
                        key + " = " + _toml_value(value)
                        for key, value in declaration["config"].items()
                    )
    return {
        "agent_app/__init__.py": "",
        "agent_app/adapter.py": source,
        "agent_app/runtime.py": _RUNTIME,
        "agent_app/__main__.py": _MAIN,
        "runtime.json": json.dumps(catalog, indent=2) + "\n",
        "runtime.toml": "\n".join(toml) + "\n",
        ".gitignore": ".ralf/\n__pycache__/\n",
        "README.md": _README,
    }
