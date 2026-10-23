import asyncio
import importlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry
from relf_agent.errors import DefinitionMismatch, IdempotencyConflict, ValidationError

from .test_cli import subprocess_env
from .test_runtime_config import declaration


def api():
    return importlib.import_module("relf_agent.runtime_router")


def catalog(default="1"):
    module = importlib.import_module("relf_agent.runtime_config")
    value = module.RuntimeCatalog()
    for version, label in [("1", "first"), ("2", "second")]:
        value.register(module.RuntimeProfile(**declaration(version, label)))
    value.set_default("app", default)
    return value


def test_new_default_changes_new_runs_but_old_runs_resolve_original_components(tmp_path):
    selected = catalog()
    with api().ProfiledEngine(selected, tmp_path / "versions.sqlite") as runtime:
        first = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s1")
        selected.set_default("app", "2")
        second = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s2")
        assert asyncio.run(runtime.drive(first.run_id)).result["label"] == "first"
        assert asyncio.run(runtime.drive(second.run_id)).result["label"] == "second"
        replay = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s1")
        assert asdict(replay) == asdict(first)


def test_submit_replay_ignores_unusable_new_default_and_checks_original_request(tmp_path):
    selected = catalog()
    module = importlib.import_module("relf_agent.runtime_config")
    with api().ProfiledEngine(selected, tmp_path / "replay.sqlite") as runtime:
        first = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        selected.register(
            module.RuntimeProfile("app", "broken", {"default": {"adapter": "not-installed"}}),
            default=True,
        )
        assert asdict(runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")) == asdict(
            first
        )
        with pytest.raises(IdempotencyConflict):
            runtime.submit(AgentSpec("a", "Answer"), "different", command_id="s")


def test_missing_original_profile_is_observable_but_never_uses_new_default(tmp_path):
    path = tmp_path / "missing.sqlite"
    with api().ProfiledEngine(catalog(), path) as runtime:
        first = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
    config_module = importlib.import_module("relf_agent.runtime_config")
    replacement = config_module.RuntimeCatalog()
    replacement.register(config_module.RuntimeProfile(**declaration("2", "second")), default=True)
    with api().ProfiledEngine(replacement, path) as runtime:
        assert runtime.status(first.run_id).state == "queued"
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(first.run_id))
    assert api().SQLiteRunReader(path).status(first.run_id).state == "queued"


def test_active_execution_blocks_switching_and_cancellation_keeps_original_runtime(tmp_path):
    async def scenario():
        builder_module = importlib.import_module("relf_agent.runtime_builder")
        started, release = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "slow-fixture", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return ModelResponse(output="done")

        selected = catalog()
        config_module = importlib.import_module("relf_agent.runtime_config")
        selected.register(
            config_module.RuntimeProfile("slow", "1", {"default": {"adapter": "slow"}}),
            default=True,
        )
        registry = builder_module.ComponentRegistry()
        registry.register("provider", "slow", lambda config, context: Provider())
        runtime = api().ProfiledEngine(
            selected, tmp_path / "active.sqlite", builder=builder_module.RuntimeBuilder(registry)
        )
        try:
            handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            running = asyncio.create_task(runtime.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            selected.set_default("app", "2")
            with pytest.raises(ValidationError):
                runtime.submit(AgentSpec("b", "Answer"), "q", command_id="other")
            runtime.cancel(handle.run_id, command_id="cancel")
            release.set()
            assert (await running).state == "cancelled"
            other = runtime.submit(AgentSpec("b", "Answer"), "q", command_id="other")
            assert (await runtime.drive(other.run_id)).result["label"] == "second"
        finally:
            release.set()
            await runtime.wait_for_threads()
            runtime.close()

    asyncio.run(scenario())


def test_legacy_run_requires_explicit_original_factory(tmp_path):
    class Provider:
        identity = {"kind": "legacy-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output="legacy")

    def legacy_factory(path):
        return LocalEngine(
            SQLiteStore(path), providers={"default": Provider()}, tools=ToolRegistry()
        )

    path = tmp_path / "legacy.sqlite"
    with legacy_factory(path) as runtime:
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
    with api().ProfiledEngine(catalog(), path) as runtime:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
    with api().ProfiledEngine(catalog(), path, legacy_factory=legacy_factory) as runtime:
        assert asyncio.run(runtime.drive(handle.run_id)).result == "legacy"


def test_config_cli_accepts_tasks_and_resolves_old_version_across_processes(tmp_path):
    config = tmp_path / "runtime.json"
    spec = tmp_path / "agent.json"
    database = tmp_path / "cli.sqlite"
    payload = {
        "schema_version": 1,
        "default": {"name": "app", "version": "1"},
        "profiles": [declaration(), declaration("2", "second")],
    }
    config.write_text(json.dumps(payload))
    spec.write_text(json.dumps({"kind": "agent", "name": "a", "instructions": "Answer"}))

    def cli(*arguments):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "relf_agent",
                "--db",
                str(database),
                "--config",
                str(config),
                *arguments,
            ],
            env=subprocess_env(),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)

    first = cli("run", "--spec", str(spec), "--input", "q", "--command-id", "s", "--submit-only")
    payload["default"]["version"] = "2"
    config.write_text(json.dumps(payload))
    done = cli("resume", first["run_id"])
    assert done["result"]["label"] == "first"
    other = cli("run", "--spec", str(spec), "--input", "q", "--command-id", "other")
    assert other["result"]["label"] == "second"
    replay = cli("run", "--spec", str(spec), "--input", "q", "--command-id", "s", "--submit-only")
    assert replay == first


def test_approval_restart_uses_original_provider_and_tool_version_once(tmp_path):
    database = tmp_path / "business.sqlite"
    config = tmp_path / "business.sqlite.runtime.json"
    spec = tmp_path / "business-agent.json"
    payload = {
        "schema_version": 1,
        "default": {"name": "app", "version": "1"},
        "profiles": [
            {
                "name": "app",
                "version": version,
                "providers": {"default": {"adapter": "business", "config": {"label": label}}},
                "components": {"tools": {"adapter": "business", "config": {"version": version}}},
            }
            for version, label in [("1", "first"), ("2", "second")]
        ],
    }
    config.write_text(json.dumps(payload))
    spec.write_text(
        json.dumps(
            {
                "kind": "agent",
                "name": "business",
                "instructions": "Execute after approval",
                "tools": ["write"],
            }
        )
    )

    def cli(*arguments):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "relf_agent",
                "--db",
                str(database),
                "--factory",
                "tests.runtime_profile_fixture:create_engine",
                *arguments,
            ],
            env=subprocess_env(),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    waiting = cli("run", "--spec", str(spec), "--input", "q", "--command-id", "start")
    assert waiting["state"] == "waiting_approval"
    pending = waiting["pending"][0]
    payload["default"]["version"] = "2"
    config.write_text(json.dumps(payload))
    decision = [
        "approve",
        waiting["run_id"],
        pending["action_id"],
        "--digest",
        pending["digest"],
        "--command-id",
        "approve",
    ]
    original = cli(*decision)
    assert cli(*decision) == original
    done = cli("resume", waiting["run_id"])
    assert done["state"] == "succeeded" and done["result"]["label"] == "first"
    assert cli("resume", waiting["run_id"])["result"] == done["result"]
    with sqlite3.connect(str(database) + ".effects.sqlite") as connection:
        effects = connection.execute("SELECT result FROM effects").fetchall()
    assert len(effects) == 1 and json.loads(effects[0][0])["label"] == "first"
