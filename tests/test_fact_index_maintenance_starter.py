import asyncio
import importlib
import json
import sqlite3
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_generated_application_modules():
    def clear():
        for name in list(sys.modules):
            if name == "agent_app" or name.startswith("agent_app."):
                sys.modules.pop(name)

    clear()
    try:
        yield
    finally:
        clear()


def generate(root):
    from relf_agent import fact_index_maintenance_starter as module

    files = module.fact_index_maintenance_files()
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return files


def application(root, monkeypatch):
    files = generate(root)
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    for name in list(sys.modules):
        if name == "agent_app" or name.startswith("agent_app."):
            del sys.modules[name]
    return importlib.import_module("agent_app.runtime"), files


@pytest.mark.parametrize("format", ["sdk", "json", "toml"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_default_session_chain_automatically_refreshes_grounded_preference_before_next_turn(
    tmp_path, monkeypatch, format, borrowed
):
    app, files = application(tmp_path, monkeypatch)
    assert "rebuild(" not in files["agent_app/runtime.py"]
    result = asyncio.run(
        app.run_turns(
            format=format, borrowed=borrowed, command_prefix="actual-" + format + str(borrowed)
        )
    )
    assert result["states"] == ["succeeded", "succeeded"]
    assert result["execution_authority"] == "local"
    assert result["semantic_quality"] is None and result["model_quality"] is None
    assert result["index_module"] == "agent_app.fact_index_generation"
    assert result["source_module"] == "agent_app.fact_index_maintenance_tools"
    assert all(budget["held"] == 0 and budget["spent"] == 3 for budget in result["budgets"])
    first, second = result["records"]

    def models(record):
        return [a for a in record["actions"] if a["kind"] == "model"]

    assert len(models(first)) == len(models(second)) == 1
    first_refs = [i for i in models(first)[0]["memory_references"] if "_fact_index" in i]
    second_refs = [i for i in models(second)[0]["memory_references"] if "_fact_index" in i]
    assert first_refs == []
    assert len(second_refs) == 1 and second_refs[0]["version"] == 1
    assert second_refs[0]["value"]["value"] == "green tea"
    assert second["result"]["observed_facts"] == [
        {"key": second_refs[0]["key"], "version": 1, "value": "green tea"}
    ]
    disclosed = [
        m["content"]
        for m in models(second)[0]["snapshot"]
        if m.get("content", "").startswith("Reference memory;")
    ]
    assert disclosed and second_refs[0]["key"] in disclosed[0]
    for record, stages in zip(result["records"], result["memory_stages"], strict=True):
        refresh = next(a for a in record["actions"] if a["kind"] == "tool")
        assert refresh["arguments"] == {} and refresh["result"]["status"] == "ready"
        assert refresh["result"]["effect_key"] == refresh["effect_key"]
        assert len(stages) == 1 and stages[0]["status"] == "completed"
        assert stages[0]["facts"][0]["receipt"]["version"] == 1
        assert record["session_turn"]["run"]["run_id"] == record["id"]
        assert record["session_turn"]["session"]["key"]["session_id"] == "preferences-session"
    assert result["closure"] == {
        "source_closed": True,
        "native_connections_closed": 3,
        "runtime_resources": 0,
        "active_handlers": 0,
        "active_tasks": 0,
    }
    # Original read-only factory has no allocation, seeding, refresh, or dispatch.
    before = {p: p.read_bytes() for p in (tmp_path / ".ralf").glob("*.sqlite")}
    engine = app.create_engine(".ralf/runs.sqlite")
    try:
        assert engine.status(second["id"]).state == "succeeded"
        assert engine.diagnostics(second["id"]).release_digest == second["release_digest"]
        assert engine._active is None
    finally:
        engine.close()
    assert {p: p.read_bytes() for p in (tmp_path / ".ralf").glob("*.sqlite")} == before
    (tmp_path / "session-evidence.json").write_text(json.dumps(result, indent=2))


def test_explicit_seed_is_idempotent_and_never_runs_during_construction(tmp_path, monkeypatch):
    app, _ = application(tmp_path, monkeypatch)
    engine = app.create_engine(".ralf/runs.sqlite")
    engine.close()
    assert not (tmp_path / ".ralf/facts.sqlite").exists()
    assert app.seed("coffee")["seeded"] == 1
    assert app.seed("coffee")["seeded"] == 0
    assert app.seed("tea")["seeded"] == 1


@pytest.mark.parametrize("borrowed", [False, True])
def test_original_session_resume_resolves_recorded_profile_after_default_alias_changes(
    tmp_path, monkeypatch, borrowed
):
    import sqlite3

    app, _ = application(tmp_path, monkeypatch)
    original = asyncio.run(
        app.run_turns(format="json", borrowed=borrowed, command_prefix="before-alias")
    )
    run = original["records"][0]
    catalog = json.loads((tmp_path / "runtime.json").read_text())
    changed = json.loads(json.dumps(catalog["profiles"][0]))
    changed["name"] = "other-default"
    changed["version"] = "9"
    catalog["profiles"].append(changed)
    catalog["default"] = {"name": "other-default", "version": "9"}
    (tmp_path / "runtime.json").write_text(json.dumps(catalog))
    before = {p: p.read_bytes() for p in (tmp_path / ".ralf").glob("*.sqlite")}
    done = asyncio.run(app.resume(run["id"], format="json", borrowed=borrowed))
    assert done["state"] == "succeeded" and done["result"] == run["result"]
    assert done["profile"] == run["manifest"]["runtime_profile"]
    assert done["session_ref"] == run["session_turn"]["session"]
    with sqlite3.connect(tmp_path / ".ralf/runs.sqlite") as reader:
        after = json.loads(
            reader.execute("SELECT data FROM runs WHERE id=?", (run["id"],)).fetchone()[0]
        )
    assert after == run
    assert {p: p.read_bytes() for p in (tmp_path / ".ralf").glob("*.sqlite")} == before
    # Missing original profile is refused before any source, stage or tool effects.
    catalog["profiles"] = [changed]
    (tmp_path / "runtime.json").write_text(json.dumps(catalog))
    from relf_agent.errors import DefinitionMismatch

    with pytest.raises(DefinitionMismatch):
        asyncio.run(app.resume(run["id"], format="json", borrowed=borrowed))
    assert {p: p.read_bytes() for p in (tmp_path / ".ralf").glob("*.sqlite")} == before
    (tmp_path / "resume-evidence.json").write_text(
        json.dumps({"original": run, "resumed": done, "after": after}, indent=2)
    )


@pytest.mark.parametrize("borrowed", [False, True])
def test_cancelled_application_retains_original_runtime_and_native_owner_until_same_loop_retry(
    tmp_path, monkeypatch, borrowed
):
    app, _ = application(tmp_path, monkeypatch)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original = app.OfflinePreferenceProvider.complete
        original_runtime = app.Runtime

        async def suspend(self, messages, tools):
            entered.set()
            await release.wait()
            return await original(self, messages, tools)

        def bounded_runtime(instance, *, owned):
            return original_runtime(instance, owned=owned, close_timeout=0.01)

        monkeypatch.setattr(app.OfflinePreferenceProvider, "complete", suspend)
        monkeypatch.setattr(app, "Runtime", bounded_runtime)
        caller = asyncio.create_task(
            app.run_turns(format="sdk", borrowed=borrowed, command_prefix="cancelled")
        )
        await asyncio.wait_for(entered.wait(), 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        cleanup = caught.value.application_cleanup
        runtime, instance = cleanup.runtime, cleanup.instance
        index = instance._engine.memory
        source = (
            cleanup.borrowed_owner.source if borrowed else instance._context._resources[-1].resource
        )
        native = [index.backend, index.index, index.original_catalog.backend]
        assert runtime.state == "quiescing" and len(runtime._supervisor.tasks) == 1
        assert cleanup.instance is runtime.engine
        assert source._closed is False
        for port in native:
            assert port.store.conn.execute("SELECT 1").fetchone()[0] == 1
        original_ids = {
            "runtime": id(runtime),
            "instance": id(instance),
            "source": id(source),
            "loop": id(asyncio.get_running_loop()),
            "active_tasks": list(runtime._supervisor.tasks),
        }
        release.set()
        await cleanup.aclose(close_timeout=2)
        assert runtime.state == "closed" and not runtime._supervisor.tasks
        assert instance._context._resources == []
        assert source._closed and source._owner._execution.active_count == 0
        for port in native:
            with pytest.raises(sqlite3.ProgrammingError):
                port.store.conn.execute("SELECT 1")
        assert len(asyncio.all_tasks()) == 1
        (tmp_path / "app-owner-closure.json").write_text(
            json.dumps(
                {
                    "borrowed": borrowed,
                    "original_ids": original_ids,
                    "same_runtime_after": id(cleanup.runtime) == original_ids["runtime"],
                    "source_closed": True,
                    "closed_native_connections": 3,
                    "active_tasks": 0,
                    "runtime_resources": 0,
                }
            )
        )

    asyncio.run(run())


def _invoke_generated_cli(arguments, monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["agent_app", *arguments])
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("agent_app", run_name="__main__")
    assert exited.value.code == 0
    return json.loads(capsys.readouterr().out)


def test_guide_exact_run_sequence_works_in_one_editable_app_with_explicit_mode_sessions(
    tmp_path, monkeypatch, capsys
):
    import shlex
    from pathlib import Path

    guide = Path(__file__).resolve().parents[1] / "docs/fact-index-maintenance.md"
    commands = [
        shlex.split(line)[3:]
        for line in guide.read_text().splitlines()
        if line.startswith("python -m agent_app run ")
    ]
    assert len(commands) == 2
    application(tmp_path, monkeypatch)
    first, second = [_invoke_generated_cli(command, monkeypatch, capsys) for command in commands]
    assert first["states"] == second["states"] == ["succeeded", "succeeded"]
    first_session = first["records"][0]["session_turn"]["session"]["key"]
    second_session = second["records"][0]["session_turn"]["session"]["key"]
    assert first_session["resource_id"] == second_session["resource_id"]
    assert first_session["session_id"] != second_session["session_id"]
    assert second["records"][0]["result"]["observed_facts"]
    (tmp_path / "guide-sequence-evidence.json").write_text(
        json.dumps({"commands": commands, "first": first, "second": second}, indent=2)
    )


def test_cli_caller_can_choose_explicit_session_id(tmp_path, monkeypatch, capsys):
    application(tmp_path, monkeypatch)
    result = _invoke_generated_cli(
        ["run", "--format", "sdk", "--session-id", "chosen-session", "--command-prefix", "chosen"],
        monkeypatch,
        capsys,
    )
    assert result["states"] == ["succeeded", "succeeded"]
    assert all(
        record["session_turn"]["session"]["key"]["session_id"] == "chosen-session"
        for record in result["records"]
    )


@pytest.mark.parametrize("borrowed", [False, True])
def test_format_changes_preserve_one_original_session_with_same_ownership(
    tmp_path, monkeypatch, borrowed
):
    app, _ = application(tmp_path, monkeypatch)
    results = [
        asyncio.run(
            app.run_turns(format=format, borrowed=borrowed, command_prefix="same-mode-" + format)
        )
        for format in ("sdk", "json", "toml")
    ]
    sessions = [
        record["session_turn"]["session"] for result in results for record in result["records"]
    ]
    assert len({json.dumps(session, sort_keys=True) for session in sessions}) == 1
    assert sessions[0]["key"]["session_id"] == "preferences-session"
    assert [
        record["session_turn"]["turn_seq"] for result in results for record in result["records"]
    ] == list(range(1, 7))
    assert all(result["states"] == ["succeeded", "succeeded"] for result in results)


def test_default_session_cannot_silently_switch_ownership_binding(tmp_path, monkeypatch):
    from relf_agent.errors import SessionBindingMismatch

    app, _ = application(tmp_path, monkeypatch)
    first = asyncio.run(app.run_turns(format="toml", command_prefix="fixed-owned"))
    with pytest.raises(SessionBindingMismatch):
        asyncio.run(app.run_turns(format="json", borrowed=True, command_prefix="wrong-borrowed"))
    assert first["states"] == ["succeeded", "succeeded"]
