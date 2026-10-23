import asyncio
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    LocalEngine,
    RuntimeBuilder,
    RuntimeProfile,
    SQLiteStore,
    ToolRegistry,
)
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import EchoProvider


def declaration(provider=None, **config):
    return {
        "adapter": "middleware",
        "config": {"provider": provider or {"adapter": "offline-echo"}, **config},
    }


def test_default_profile_wrappers_are_available_and_opt_in(tmp_path):
    profile = RuntimeProfile(
        "observed",
        "1",
        {"default": declaration(logging=True)},
        components={"tool_executor": {"adapter": "middleware-python", "config": {"logging": True}}},
    )
    with RuntimeBuilder().build(profile, tmp_path / "run.sqlite") as engine:
        handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="first")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        manifest = engine.diagnostics(handle.run_id).manifest
        assert manifest["providers"]["default"]["kind"] == "middleware-provider"
        assert manifest["tool_executor"]["kind"] == "middleware-tool-executor"


@pytest.mark.parametrize(
    "config",
    [
        {"provider": {"adapter": "middleware", "config": {}}},
        {"provider": {"adapter": "missing"}},
        {
            "provider": {
                "adapter": "chat-completions",
                "config": {"model": "fixture", "api_key": "embedded-private"},
            }
        },
        {"logging": 1},
        {"max_bytes": False},
        {"max_bytes": 4_000_001},
        {"unknown": True},
    ],
)
def test_invalid_middleware_config_leaves_no_database(tmp_path, config):
    db = tmp_path / "absent.sqlite"
    profile = RuntimeProfile(
        "observed",
        "1",
        {
            "default": {
                "adapter": "middleware",
                "config": {"provider": {"adapter": "offline-echo"}, **config},
            }
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, db)
    assert not db.exists()


def test_nested_async_factory_is_refused_before_store_creation(tmp_path):
    registry = ComponentRegistry()

    async def factory(config, context):
        raise AssertionError("must not construct")

    registry.register_async("provider", "async-fixture", factory)
    profile = RuntimeProfile(
        "observed", "1", {"default": declaration({"adapter": "async-fixture"})}
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry).build(profile, tmp_path / "absent.sqlite")
    assert not (tmp_path / "absent.sqlite").exists()


def test_observable_starter_runs_and_reuses_receipts_independently(tmp_path):
    from relf_agent.starter import create_starter

    result = create_starter(tmp_path / "app", template="observable")
    assert result.factory == "agent_app.runtime:create_engine"
    root = Path(__file__).parents[1] / "src"
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(root)}
    commands = []
    for _ in range(2):
        p = subprocess.run(
            [sys.executable, "-m", "agent_app"],
            cwd=result.directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert p.returncode == 0, p.stderr
        rows = [json.loads(line) for line in p.stdout.splitlines()]
        assert rows[-1]["type"] == "result" and rows[-1]["snapshot"]["state"] == "succeeded"
        events = [row["event"] for row in rows if row["type"] == "event"]
        assert events and [e["seq"] for e in events] == list(range(1, len(events) + 1))
        commands.append(rows[-1]["handle"])
    assert commands[0] == commands[1]


def test_event_watch_cli_json_sse_cursor_and_scope_refusal(tmp_path):
    module_name = "relf_agent.event_watch"
    assert importlib.util.find_spec(module_name), "Missing event watch CLI"
    main = importlib.import_module(module_name).main
    path = tmp_path / "run.sqlite"
    with LocalEngine(
        SQLiteStore(path), providers={"default": EchoProvider("test")}, tools=ToolRegistry()
    ) as e:
        handle = e.submit(AgentSpec("a", "Answer"), "q", command_id="first")
        asyncio.run(e.drive(handle.run_id))
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}

    def call(*args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                module_name,
                "--db",
                str(path),
                "--run-id",
                handle.run_id,
                *args,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    first = call("--max-events", "1")
    assert first.returncode == 0, first.stderr
    row = json.loads(first.stdout)
    rest = call("--after-cursor", row["cursor_token"])
    assert rest.returncode == 0 and json.loads(rest.stdout.splitlines()[0])["event"]["seq"] == 2
    sse = call("--sse", "--max-events", "1")
    assert sse.returncode == 0 and "\nevent: ralf.run\ndata: " in sse.stdout
    foreign = call("--workspace", "other")
    assert (
        foreign.returncode == 2
        and foreign.stdout == ""
        and "authorization_denied" in foreign.stderr
    )
    assert callable(main)


def test_event_watch_cli_does_not_create_a_missing_database(tmp_path):
    assert importlib.util.find_spec("relf_agent.event_watch"), "Missing event watch CLI"
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "relf_agent.event_watch",
            "--db",
            str(tmp_path / "absent.sqlite"),
            "--run-id",
            "absent",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert p.returncode == 2 and not (tmp_path / "absent.sqlite").exists()


def test_observable_starter_reports_a_paused_drive_without_hanging(tmp_path):
    from relf_agent.starter import create_starter

    result = create_starter(tmp_path / "paused-app", template="observable")
    source = Path(result.directory) / "agent_app/runtime.py"
    source.write_text(
        source.read_text().replace(
            "async def complete(self, messages, tools):",
            'async def complete(self, messages, tools):\n        raise RuntimeError("fixture unknown outcome")',
        )
    )
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    p = subprocess.run(
        [sys.executable, "-m", "agent_app"],
        cwd=result.directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert rows[-1]["snapshot"]["state"] == "waiting_reconciliation"
    assert rows[-2]["event"]["kind"] == "model_attempt_unknown"
    assert "fixture unknown outcome" not in p.stdout + p.stderr
