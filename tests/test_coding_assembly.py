"""Explicit async Coding assembly never starts native work or duplicates ownership."""

import asyncio
import json

import pytest

from ralf_agent import BindingSelection, Scope
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from ralf_agent.runtime_config import RuntimeProfile


def options(tmp_path):
    root = tmp_path / "runner"
    root.mkdir(mode=0o700)
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf 'unexpected native call' >> '" + str(tmp_path / "native") + "'\nexit 1\n"
    )
    docker.chmod(0o700)
    return {
        "name": "coding",
        "description": "One contained task",
        "cost": 2,
        "runner_root": str(root),
        "journal_path": str(tmp_path / "runner.sqlite"),
        "fixed_dependencies": {"fixture": "assembly-v1"},
        "docker_executable": str(docker),
        "docker_host": "unix:///unused.sock",
        "request_timeout": 1,
    }


def profile(config, *, reference="coding"):
    return RuntimeProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "codex-coding", "config": config}},
        binding_components=[
            {
                "role": "runner",
                "component_id": "native",
                "version": "1",
                "component": {"adapter": "registered-tool", "config": {"name": reference}},
            }
        ],
    )


def test_async_assembly_borrows_the_registered_runner_and_closes_journal(tmp_path):
    config = options(tmp_path)

    async def scenario():
        runtime = await RuntimeBuilder().abuild(profile(config), tmp_path / "runs.sqlite")
        try:
            handler = runtime.tools.get("coding").handler
            selected, _ = runtime.binding_catalog.resolve(
                "runner", BindingSelection.ref("native", "1"), Scope()
            )
            assert selected is handler.runner
            assert runtime.tools.get("coding").spec.cost == 2
            assert runtime.tools.get("coding").spec.description == "One contained task"
            assert selected.identity["request_timeout"] == 1
            assert selected.identity["credentials"] == "unavailable"
            assert not (tmp_path / "native").exists()
            assert list((tmp_path / "runner").iterdir()) == []
        finally:
            await runtime.aclose()
        from ralf_agent.runner_journal import RunnerJournal

        reopened = RunnerJournal(config["journal_path"], identity=config["fixed_dependencies"])
        reopened.close()

    asyncio.run(scenario())


def test_two_declared_runners_have_distinct_resources_and_borrowed_refs(tmp_path):
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first_dir.mkdir(mode=0o700)
    second_dir.mkdir(mode=0o700)
    first, second = options(first_dir), options(second_dir)
    second["name"] = "other_coding"
    declarations = profile(first).binding_components
    declarations.append(
        {
            "role": "runner",
            "component_id": "other",
            "version": "1",
            "component": {"adapter": "registered-tool", "config": {"name": "other_coding"}},
        }
    )
    selected = RuntimeProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "codex-coding", "config": {"tools": [first, second]}}},
        binding_components=declarations,
    )

    async def scenario():
        runtime = await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")
        try:
            a = runtime.tools.get("coding").handler.runner
            b = runtime.tools.get("other_coding").handler.runner
            assert a is not b
            assert a.identity["root"]["path"] == first["runner_root"]
            assert b.identity["root"]["path"] == second["runner_root"]
            assert a.identity["journal"] != b.identity["journal"]
            for name, identity in (("native", a), ("other", b)):
                runner, _ = runtime.binding_catalog.resolve(
                    "runner", BindingSelection.ref(name, "1"), Scope()
                )
                assert runner is identity
            assert not (first_dir / "native").exists()
            assert not (second_dir / "native").exists()
        finally:
            await runtime.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"description": 1},
        {"cost": True},
        {"cost": -1},
        {"runner_root": "relative"},
        {"journal_path": "/private/tmp/../journal"},
        {"docker_executable": "docker"},
        {"docker_host": "tcp://example:1234"},
        {"docker_host": "unix:///unused.sock?token=private"},
        {"request_timeout": True},
        {"request_timeout": 61},
        {"request_timeout": 0},
        {"fixed_dependencies": {}},
        {"fixed_dependencies": {"large": "x" * 65536}},
        {"env": {}},
        {"mounts": []},
        {"credentials": "private"},
        {"config": {}},
    ],
)
def test_invalid_entry_refused_before_any_resource_io(tmp_path, monkeypatch, change):
    config = options(tmp_path)
    config.update(change)
    selected = profile(config)
    import ralf_agent.coding_factories as factories

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid declaration performed filesystem admission or resource acquisition")

    monkeypatch.setattr(factories, "_check_paths", forbidden)
    builder = RuntimeBuilder(store_factory=forbidden)
    with pytest.raises(ValidationError):
        asyncio.run(builder.abuild(selected, tmp_path / "absent.sqlite"))
    assert not (tmp_path / "runner.sqlite").exists()
    assert not (tmp_path / "absent.sqlite").exists()


@pytest.mark.parametrize(
    "conflict",
    ["name", "runner_root", "journal_path", "lease", "nested", "mixed", "empty", "too_many"],
)
def test_multi_entry_conflicts_refused_before_acquisition(tmp_path, conflict):
    config = options(tmp_path)
    second = dict(
        config,
        name="other",
        runner_root=str(tmp_path / "other"),
        journal_path=str(tmp_path / "other.sqlite"),
    )
    if conflict in {"name", "runner_root", "journal_path"}:
        second[conflict] = config[conflict]
    elif conflict == "lease":
        second["journal_path"] = config["journal_path"] + ".owner"
    elif conflict == "nested":
        second["runner_root"] = config["runner_root"] + "/child"
    declaration = {"tools": [config, second]}
    if conflict == "mixed":
        declaration["name"] = "mixed"
    elif conflict == "empty":
        declaration = {"tools": []}
    elif conflict == "too_many":
        declaration = {"tools": [config] * 17}

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid batch acquired execution authority")

    with pytest.raises(ValidationError):
        asyncio.run(
            RuntimeBuilder(store_factory=forbidden).abuild(
                profile(declaration), tmp_path / "absent.sqlite"
            )
        )
    assert not (tmp_path / "runner.sqlite").exists()


def test_missing_tool_ref_and_sync_build_refused_without_opening_journal(tmp_path):
    config = options(tmp_path)
    for selected in (profile(config, reference="absent"), profile(config)):
        with pytest.raises(ValidationError):
            RuntimeBuilder().build(selected, tmp_path / "absent.sqlite")
        assert not (tmp_path / "absent.sqlite").exists()
        assert not (tmp_path / "runner.sqlite").exists()
        assert not (tmp_path / "runner.sqlite.owner").exists()


def test_all_filesystem_runner_admissions_precede_any_journal_open(tmp_path):
    config = options(tmp_path)
    second = dict(
        config,
        name="other",
        runner_root=str(tmp_path / "missing"),
        journal_path=str(tmp_path / "other.sqlite"),
    )
    with pytest.raises(ValidationError):
        asyncio.run(
            RuntimeBuilder().abuild(profile({"tools": [config, second]}), tmp_path / "runs.sqlite")
        )
    assert not (tmp_path / "runner.sqlite").exists()
    assert not (tmp_path / "runner.sqlite.owner").exists()


def test_json_and_toml_load_equivalent_explicit_coding_assembly(tmp_path):
    from ralf_agent.runtime_config import load_catalog

    config = options(tmp_path)
    source = profile({"tools": [config]})
    json_path, toml_path = tmp_path / "runtime.json", tmp_path / "runtime.toml"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "default": {"name": "coding", "version": "1"},
                "profiles": [
                    {
                        "name": "coding",
                        "version": "1",
                        "providers": source.providers,
                        "components": source.components,
                        "binding_components": source.binding_components,
                    }
                ],
            }
        )
    )
    scalar_config = "\n".join(
        f"{k} = {json.dumps(v)}" for k, v in config.items() if k != "fixed_dependencies"
    )
    toml_path.write_text(
        """schema_version = 2
[default]
name = "coding"
version = "1"
[[profiles]]
name = "coding"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.tools]
adapter = "codex-coding"
[[profiles.components.tools.config.tools]]
"""
        + scalar_config
        + """
[profiles.components.tools.config.tools.fixed_dependencies]
fixture = "assembly-v1"
[[profiles.binding_components]]
role = "runner"
component_id = "native"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tool"
[profiles.binding_components.component.config]
name = "coding"
"""
    )
    json_profile, toml_profile = load_catalog(json_path).default, load_catalog(toml_path).default
    assert json_profile.identity == toml_profile.identity

    async def scenario():
        identities = []
        for declaration in (json_profile, toml_profile):
            runtime = await RuntimeBuilder().abuild(declaration, tmp_path / "runs.sqlite")
            try:
                identities.append(runtime.tools.get("coding").handler.runner.identity)
            finally:
                await runtime.aclose()
        assert identities[0] == identities[1]

    asyncio.run(scenario())


def test_physical_root_aliases_rejected_before_journal_acquisition(tmp_path):
    config = options(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    second = dict(
        config,
        name="other",
        runner_root=str(alias / "runner"),
        journal_path=str(tmp_path / "other.sqlite"),
    )
    with pytest.raises(ValidationError):
        asyncio.run(
            RuntimeBuilder().abuild(profile({"tools": [config, second]}), tmp_path / "runs.sqlite")
        )
    assert not (tmp_path / "runner.sqlite").exists()
    assert not (tmp_path / "other.sqlite").exists()


def test_partial_journal_identity_failure_closes_first_runner_then_journal(tmp_path, monkeypatch):
    from ralf_agent.codex_runner import CodexCodingRunner
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.runner_journal import RunnerJournal

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(mode=0o700)
    b.mkdir(mode=0o700)
    first, second = options(a), options(b)
    second["name"] = "other"
    existing = RunnerJournal(second["journal_path"], identity={"fixture": "original"})
    existing.close()
    events = []
    runner_close, journal_close = CodexCodingRunner.aclose, RunnerJournal.close

    async def close_runner(self, **kwargs):
        events.append("runner")
        await runner_close(self, **kwargs)

    def close_journal(self):
        if self._path == first["journal_path"]:
            events.append("journal")
        journal_close(self)

    monkeypatch.setattr(CodexCodingRunner, "aclose", close_runner)
    monkeypatch.setattr(RunnerJournal, "close", close_journal)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(
            RuntimeBuilder().abuild(profile({"tools": [first, second]}), tmp_path / "runs.sqlite")
        )
    assert events == ["runner", "journal"]
    for config, identity in (
        (first, first["fixed_dependencies"]),
        (second, {"fixture": "original"}),
    ):
        journal = RunnerJournal(config["journal_path"], identity=identity)
        journal.close()
    assert not (a / "native").exists()
    assert not (b / "native").exists()


def test_factory_cleanup_failure_retains_journal_lease_until_retry(tmp_path, monkeypatch):
    from ralf_agent.codex_runner import CodexCodingRunner
    from ralf_agent.errors import CoordinatorBusy
    from ralf_agent.runner_journal import RunnerJournal
    from ralf_agent.runtime_builder import RuntimeBuildError

    config = options(tmp_path)
    close = CodexCodingRunner.aclose
    attempts = []

    async def interrupted_close(self):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("controlled resource close failure")
        await close(self)

    monkeypatch.setattr(CodexCodingRunner, "aclose", interrupted_close)
    factories = ComponentRegistry()

    def fail_after_tools(config, context):
        raise ValidationError("controlled later factory failure")

    factories.register("provider", "fail-after-tools", fail_after_tools)
    declarations = profile(config).binding_components + [
        {
            "role": "provider",
            "component_id": "later",
            "version": "1",
            "component": {"adapter": "fail-after-tools"},
        }
    ]
    selected = RuntimeProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        profile(config).components,
        binding_components=declarations,
    )

    async def scenario():
        with pytest.raises(RuntimeBuildError) as failed:
            await RuntimeBuilder(factories).abuild(selected, tmp_path / "runs.sqlite")
        with pytest.raises(CoordinatorBusy):
            RunnerJournal(config["journal_path"], identity=config["fixed_dependencies"])
        await failed.value.cleanup.aclose()
        journal = RunnerJournal(config["journal_path"], identity=config["fixed_dependencies"])
        journal.close()

    asyncio.run(scenario())
    assert len(attempts) == 2


def test_cancellation_after_tools_releases_actual_runner_journal(tmp_path):
    from ralf_agent.runner_journal import RunnerJournal

    config = options(tmp_path)

    async def scenario():
        started = asyncio.Event()

        async def pending(config, context):
            started.set()
            await asyncio.Future()

        factories = ComponentRegistry()
        factories.register_async("provider", "pending-after-tools", pending)
        declarations = profile(config).binding_components + [
            {
                "role": "provider",
                "component_id": "later",
                "version": "1",
                "component": {"adapter": "pending-after-tools"},
            }
        ]
        selected = RuntimeProfile(
            "coding",
            "1",
            {"default": {"adapter": "offline-echo"}},
            profile(config).components,
            binding_components=declarations,
        )
        task = asyncio.create_task(
            RuntimeBuilder(factories).abuild(selected, tmp_path / "runs.sqlite")
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        journal = RunnerJournal(config["journal_path"], identity=config["fixed_dependencies"])
        journal.close()
        assert not (tmp_path / "native").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["identity", "method", "resource"])
def test_registered_tool_factory_refuses_changed_original_resource(tmp_path, mutation):
    from ralf_agent.codex_runner import CodexCodingRunner
    from ralf_agent.delegated_coding import register_coding_tool
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.runner_journal import RunnerJournal
    from ralf_agent.tools import ToolRegistry

    config = options(tmp_path)
    journal = RunnerJournal(config["journal_path"], identity=config["fixed_dependencies"])
    runner = CodexCodingRunner(
        config["runner_root"],
        journal=journal,
        docker_executable=config["docker_executable"],
        docker_host=config["docker_host"],
        request_timeout=1,
    )
    tools = ToolRegistry()
    handler = register_coding_tool(tools, runner)
    if mutation == "identity":
        runner._identity["request_timeout"] = 2
    elif mutation == "method":
        runner.execute = lambda *args: None
    else:
        handler._runner = CodexCodingRunner(
            config["runner_root"],
            journal=journal,
            docker_executable=config["docker_executable"],
            docker_host=config["docker_host"],
            request_timeout=1,
        )
    factories = ComponentRegistry()
    factories.register("tools", "borrowed-coding", lambda c, ctx: tools)
    selected = RuntimeProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "borrowed-coding"}},
        binding_components=profile(config).binding_components,
    )
    try:
        with pytest.raises(DefinitionMismatch):
            RuntimeBuilder(factories).build(selected, tmp_path / "runs.sqlite")
        assert not (tmp_path / "native").exists()
    finally:
        asyncio.run(runner.aclose())
        journal.close()


def test_default_registry_keeps_posix_native_coding_imports_optional(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """import sys
sys.modules["fcntl"] = None
from ralf_agent.runtime_builder import RuntimeBuilder
builder = RuntimeBuilder()
builder.registry.prepare("provider", {"adapter": "offline-echo", "config": {}})
assert "ralf_agent.codex_runner" not in sys.modules
assert "ralf_agent.runner_journal" not in sys.modules
""",
            str(tmp_path / "default.sqlite"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
