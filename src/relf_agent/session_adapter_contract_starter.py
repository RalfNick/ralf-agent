"""Generate a complete editable independent Session adapter application."""

import inspect
import json

from . import session_adapter_contract_reference
from .recommended import recommended_profile

_RUNTIME = '''"""Explicit source seed and original Local application assembly."""
from pathlib import Path

from relf_agent import (
    AgentSpec, ComponentRegistry, ProfiledEngine, Runtime, RuntimeBuilder, Scope,
    load_catalog,
)
from .adapter import ReferenceSessionSource, ReferenceSQLiteSessionStore, register_session_reference_components


def source_path():
    return Path(".ralf/sessions.sqlite").resolve()


def seed():
    source = ReferenceSessionSource(source_path())
    try:
        store = ReferenceSQLiteSessionStore(source)
        seeded = 0
        for address in ("example-core", "example"):
            if not store.read(Scope(), address)[0]:
                store.append(Scope(), address, {"role": "user", "content": "original seeded history"},
                             expected_revision=0, message_id="seed:" + address)
                seeded += 1
        return {"seeded": seeded}
    finally:
        source.close()


def components(*, source=None, asynchronous=False, owned=True):
    registry = ComponentRegistry()
    register_session_reference_components(registry, source, asynchronous=asynchronous, owned=owned)
    return registry


def create_engine(db_path):
    # Registry construction and historical observations do not open Session data.
    registry = components()
    return ProfiledEngine(load_catalog("runtime.toml"), db_path,
        builder=RuntimeBuilder(registry, base_dir=Path.cwd()))


async def run(*, mode="receipts", format="toml", asynchronous=False, owned=True,
              command_id="session-first"):
    source = None
    try:
        if not owned:
            source = ReferenceSessionSource(source_path())
        registry = components(source=source, asynchronous=asynchronous, owned=owned)
        catalog = load_catalog("runtime." + format)
        if mode == "core":
            catalog.set_default("external-session-core", "1")
        profile = catalog.default
        builder = RuntimeBuilder(registry, base_dir=Path.cwd())
        instance = await builder.abuild(profile, ".ralf/runs.sqlite") if asynchronous else builder.build(profile, ".ralf/runs.sqlite")
        session_ref = None
        async with Runtime(instance, owned=True) as runtime:
            source = instance.sessions._original_source
            before = source.audit()
            definition = AgentSpec("reader", "Use the actual original Session history")
            if mode == "receipts":
                session = await runtime.create_agent(definition).open_session("example", command_id="open:example")
                handle = await session.submit("read original history", command_id=command_id, budget=32)
                snapshot = (await handle.wait(wait_timeout=10, terminal_only=True)).snapshot
                run_id = handle.ref.run_id
                session_ref = session.ref.to_dict()
            else:
                # Base Store is independently usable by the original Local Agent.
                handle = instance.submit(definition, "read original history", command_id=command_id,
                                         budget=32, session_id="example-core")
                snapshot = await instance.drive(handle.run_id)
                run_id = handle.run_id
        after = source.audit()
        return {
            "run_id": run_id, "session_ref": session_ref,
            "state": snapshot.state, "result": snapshot.result, "error": snapshot.error,
            "audit": {key: after[key] - before[key] for key in after},
            "adapter_module": "agent_app.adapter", "execution_authority": "local",
            "model_quality": None,
        }
    finally:
        # Borrowed sources remain host-owned until original Runtime shutdown.
        if source is not None:
            source.close()
'''

_MAIN = """import argparse
import asyncio
import json

from .adapter import offline_session_fixture
from .runtime import run, seed


async def check(evidence_dir, profile):
    from relf_agent import AdapterContractSuite
    from relf_agent.errors import CloseIncomplete

    suite = AdapterContractSuite(role="session-store", contract_version="1", profile=profile)
    try:
        return await suite.run(offline_session_fixture(), evidence_dir=evidence_dir)
    finally:
        try:
            await suite.aclose()
        except CloseIncomplete:
            # Retry the same actual owner on its original loop; retain the failure.
            await suite.aclose()
            raise


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    checks = commands.add_parser("check")
    checks.add_argument("--profile", choices=("core", "receipts"), default="core")
    checks.add_argument("--evidence-dir")
    execute = commands.add_parser("run")
    execute.add_argument("--mode", choices=("core", "receipts"), default="receipts")
    execute.add_argument("--format", choices=("json", "toml"), default="toml")
    execute.add_argument("--async", dest="asynchronous", action="store_true")
    execute.add_argument("--borrowed", action="store_true")
    execute.add_argument("--command-id", default="session-first")
    arguments = parser.parse_args()
    if arguments.command == "seed":
        result = seed()
    elif arguments.command == "check":
        from relf_agent.errors import CloseIncomplete, ValidationError
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

_README = """# Independent Session adapter application

Install relf-agent and run these commands from this directory. `agent_app/adapter.py`
contains the full independently editable SQLite data source and structural Session
Store. It directly implements scoped messages, CAS, stable message dedupe and exact
version 1 receipts; it never delegates Session storage to a native SDK backend.

```shell
python -m agent_app check
python -m agent_app check --profile receipts
python -m agent_app seed
python -m agent_app run --mode core --command-id core-first
python -m agent_app run --mode receipts --command-id managed-first
python -m agent_app run --format json --async --borrowed --command-id async-first
```

`core` checks read/append only. `receipts` selects the additional exact inspection
contract and original managed Session/Turn recovery. Core run uses the original
Local Agent directly; receipt run uses Runtime/create_agent/open_session. These
commands share the same independent data and original Local Run database. The
core example uses address `example-core`; managed Turns use `example`. Explicit
`seed` initializes both empty streams so either mode can read its actual history.
The offline Provider reports history from its committed model request for wiring
evidence; model quality remains unverified.

JSON and TOML declare the same explicit registered factories. Configuration does
not import application code. Owned source construction happens inside original
BuildContext assembly; `--async` uses register_async/abuild/own_async. `--borrowed`
leaves source cleanup with this application's host, after Runtime drains. Factory
construction, status, inspect and exact command receipt lookup do not open Session
data. Sources pin a persistent dataset UUID and live physical file identity.

Seeding is an explicit command, never part of run or recovery. Keep original code,
catalogs and databases for historical Runs. Observe the original Run using:

```shell
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

A committed receipt is adopted without another model request or duplicate save.
Actual independent-process save-window tests are distinct from suite passes.
Suite evidence covers this explicit Local offline combination, not arbitrary
remote services, Temporal Worker/History, model quality or full R25/H3/M1 completion.
Use `--evidence-dir` with a new private directory to retain bounded evidence. A
failed cleanup retains the original suite owner and retries on the original loop;
it cannot become a passed report merely because its resource later closes.
"""


def session_contract_files():
    """Return installed-SDK-only editable application files, without source I/O."""
    source = inspect.getsource(session_adapter_contract_reference)
    for name in ("errors", "types", "providers", "session_adapter_contract"):
        source = source.replace("from ." + name + " import", "from relf_agent." + name + " import")
    profiles = [
        recommended_profile(
            "local-basic",
            name="external-session" if receipts else "external-session-core",
            provider={
                "adapter": "external-session-reader",
                "config": {"path": ".ralf/sessions.sqlite"},
            },
            components={
                "context_assembler": {"adapter": "default"},
                "session_store": {
                    "adapter": "external-session",
                    "config": {"path": ".ralf/sessions.sqlite", "receipts": receipts},
                },
            },
        )
        for receipts in (True, False)
    ]
    catalog = {
        "schema_version": 1,
        "default": {"name": profiles[0].name, "version": profiles[0].version},
        "profiles": [
            {
                "name": profile.name,
                "version": profile.version,
                "providers": profile.providers,
                "components": profile.components,
            }
            for profile in profiles
        ],
    }
    toml = ["schema_version = 1", "[default]", 'name = "external-session"', 'version = "1"']
    for profile in profiles:
        toml.extend(["[[profiles]]", "name = " + json.dumps(profile.name), 'version = "1"'])
        for section, declarations in (
            ("providers", profile.providers),
            ("components", profile.components),
        ):
            for role, declaration in declarations.items():
                toml.extend(
                    [
                        "[profiles." + section + "." + role + "]",
                        "adapter = " + json.dumps(declaration["adapter"]),
                    ]
                )
                if declaration.get("config"):
                    toml.append("[profiles." + section + "." + role + ".config]")
                    for key, value in declaration["config"].items():
                        toml.append(
                            key
                            + " = "
                            + (str(value).lower() if type(value) is bool else json.dumps(value))
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
