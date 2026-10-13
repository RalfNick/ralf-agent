"""Factory resources borrow one original PostgreSQL owner and never start native work."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from ralf_agent import BindingSelection, Scope, TemporalProfile, TemporalProfileCatalog
from ralf_agent.coding_factories import binding
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import ComponentRegistry
from ralf_agent.runtime_lifecycle import BuildContext
from ralf_agent.temporal_coding_factories import build, entries, preflight_coding_references
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.types import canonical
from tests.test_coding_assembly import options


def entry(tmp_path):
    value = options(tmp_path)
    value.pop("journal_path")
    return value


class Connection:
    autocommit = True

    def __init__(self, events):
        self.events = events

    def cursor(self, **kwargs):
        pytest.fail("Factory performed unexpected database I/O")

    def transaction(self):
        pytest.fail("Factory performed unexpected database I/O")

    async def close(self):
        self.events.append("connection")


def publish_initialization(monkeypatch, events):
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    async def initialize(self):
        events.append("initialize-view")
        metadata = {
            "kind": "postgres-runner-journal",
            "version": "1",
            "dataset_uuid": "ae40dcee-b4dc-446f-9282-bad6d58e2e25",
            "dependencies": json.loads(self._dependencies),
            "effect_journal": self._effect.identity,
            "capacity": self._capacity,
        }
        self._metadata_json = canonical(metadata)
        self._identity_json = canonical({k: v for k, v in metadata.items() if k != "capacity"})

    monkeypatch.setattr(PostgresRunnerJournal, "initialize", initialize)

    async def no_pending_resources(self, scope):
        assert scope == Scope()
        return ()

    monkeypatch.setattr(PostgresRunnerJournal, "pending_resources", no_pending_resources)


def test_factory_uses_one_shared_original_view_and_borrowed_runner_bindings(tmp_path, monkeypatch):
    from ralf_agent.binding_catalog import BindingCatalog
    from ralf_agent.codex_runner import CodexCodingRunner
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    events = []
    publish_initialization(monkeypatch, events)
    close_runner, close_view = CodexCodingRunner.aclose, PostgresRunnerJournal.aclose

    async def runner_close(self):
        events.append("runner:" + self.identity["root"]["path"])
        await close_runner(self)

    async def view_close(self):
        events.append("view")
        await close_view(self)

    monkeypatch.setattr(CodexCodingRunner, "aclose", runner_close)
    monkeypatch.setattr(PostgresRunnerJournal, "aclose", view_close)
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir(mode=0o700)
    second_dir.mkdir(mode=0o700)
    first, second = entry(first_dir), entry(second_dir)
    second["name"] = "other"

    async def run():
        context = BuildContext(None, tmp_path / "unused", Scope(), tmp_path, allow_async=True)
        owner = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.effect_journal, context.coding_execution = owner, True
        context.tools = await build({"tools": [first, second]}, context)
        a, b = (context.tools.get(name).handler.runner for name in ("coding", "other"))
        assert a is not b and a._journal is b._journal
        assert a._journal._effect is owner
        assert a._journal._effect._lock is owner._lock
        assert len(context._resources) == 4
        catalog = BindingCatalog(scope=Scope())
        catalog.register("runner", "first", "1", binding({"name": "coding"}, context))
        borrowed, _ = catalog.resolve("runner", BindingSelection.ref("first", "1"), Scope())
        assert borrowed is a and len(context._resources) == 4
        assert not (first_dir / "native").exists() and not (second_dir / "native").exists()
        await context.cleanup_async()
        assert context._resources == []

    asyncio.run(run())
    assert events == [
        "initialize-view",
        "runner:" + second["runner_root"],
        "runner:" + first["runner_root"],
        "view",
        "connection",
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"journal_path": "/private/tmp/forbidden"},
        {"credentials": "secret"},
        {"runner_root": "relative"},
        {"cost": True},
        {"request_timeout": 0},
        {"fixed_dependencies": {}},
        {"docker_host": "tcp://remote"},
    ],
)
def test_invalid_declaration_is_refused_by_default_registry_before_io(tmp_path, change):
    value = {**entry(tmp_path), **change}
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "codex-coding-postgres", "config": value})
    assert not (tmp_path / "native").exists()


def test_batch_requires_same_dataset_dependencies_and_separate_roots(tmp_path):
    first = entry(tmp_path)
    second = {**first, "name": "other", "runner_root": first["runner_root"] + "/nested"}
    with pytest.raises(ValidationError):
        entries({"tools": [first, second]})
    second["runner_root"] = str(tmp_path / "second")
    second["fixed_dependencies"] = {"fixture": "other"}
    with pytest.raises(ValidationError):
        entries({"tools": [first, second]})


def test_factory_refuses_local_context_or_foreign_effect_owner_before_paths(tmp_path):
    value = entry(tmp_path)
    for context in [
        SimpleNamespace(),
        SimpleNamespace(coding_execution=True, effect_journal=object()),
    ]:
        with pytest.raises(ValidationError):
            asyncio.run(build(value, context))
    assert not (tmp_path / "native").exists()


def test_json_toml_profile_declarations_pin_identical_optional_coding_selection(tmp_path):
    value = entry(tmp_path)
    selected = TemporalProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "tools": {"adapter": "codex-coding-postgres", "config": value},
            "effect_journal": {
                "adapter": "postgres",
                "config": {"dsn_env": "CODING_DSN", "backend_id": "effects", "initialize": True},
            },
        },
        execution={"coding_execution": True},
        binding_components=[
            {
                "role": "runner",
                "component_id": "native",
                "version": "1",
                "component": {"adapter": "registered-tool", "config": {"name": "coding"}},
            }
        ],
    )
    catalog = TemporalProfileCatalog(base_dir=tmp_path)
    catalog.register(selected, default=True)
    json_path, toml_path = tmp_path / "coding.json", tmp_path / "coding.toml"
    json_path.write_text(json.dumps(catalog.to_dict()))
    toml_path.write_text(
        """kind = "temporal-profiles"
schema_version = 1
[default]
name = "coding"
version = "1"
[[profiles]]
name = "coding"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.execution]
coding_execution = true
[profiles.components.effect_journal]
adapter = "postgres"
[profiles.components.effect_journal.config]
dsn_env = "CODING_DSN"
backend_id = "effects"
initialize = true
[profiles.components.tools]
adapter = "codex-coding-postgres"
[profiles.components.tools.config]
"""
        + "\n".join(f"{k} = {json.dumps(v)}" for k, v in value.items() if k != "fixed_dependencies")
        + """
[profiles.components.tools.config.fixed_dependencies]
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
    for path in (json_path, toml_path):
        restored = TemporalProfileCatalog.from_file(path).default_profile
        assert restored.identity == selected.identity
        preflight_coding_references(restored)
    bad = copy.deepcopy(selected.to_dict())
    bad["binding_components"][0]["component"]["config"]["name"] = "missing"
    with pytest.raises(ValidationError):
        preflight_coding_references(TemporalProfile(**bad))


def test_builtin_profile_publishes_original_journal_and_two_selected_agent_resources(
    tmp_path, monkeypatch
):
    from dataclasses import asdict

    from ralf_agent import AgentSpec, TemporalRuntimeBuilder, WorkflowSpec
    from ralf_agent.binding_definitions import BoundDefinition
    from ralf_agent.binding_types import AgentBindingDescriptor
    from ralf_agent.temporal_bindings import normalize_request, validate_bindings
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.types import submission_request

    events = []
    publish_initialization(monkeypatch, events)

    async def connect(dsn, *, backend_id):
        assert dsn == "fixture-secret" and backend_id == "effects"
        return PostgresEffectJournal(
            Connection(events), backend_id=backend_id, owns_connection=True
        )

    async def initialize(self):
        events.append("initialize-owner")

    monkeypatch.setattr(PostgresEffectJournal, "connect", connect)
    monkeypatch.setattr(PostgresEffectJournal, "initialize", initialize)
    monkeypatch.setenv("CODING_DSN", "fixture-secret")
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir(mode=0o700)
    b_dir.mkdir(mode=0o700)
    a, b = entry(a_dir), entry(b_dir)
    b["name"] = "other"
    declarations = [
        {
            "role": "runner",
            "component_id": name,
            "version": "1",
            "component": {"adapter": "registered-tool", "config": {"name": tool}},
        }
        for name, tool in [("a", "coding"), ("b", "other")]
    ]
    selected = TemporalProfile(
        "coding",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "tools": {"adapter": "codex-coding-postgres", "config": {"tools": [a, b]}},
            "effect_journal": {
                "adapter": "postgres",
                "config": {"dsn_env": "CODING_DSN", "backend_id": "effects", "initialize": True},
            },
        },
        execution={"coding_execution": True},
        binding_components=declarations,
    )

    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        try:
            runtime, release = assembly._runtime, assembly.release
            assert release["binding_protocol"] == 11 and release["kernel"] == "temporal-3"
            assert release["coding_execution_protocol"]["version"] == 1
            assert set(release["coding_execution_protocol"]["tools"]) == {"coding", "other"}
            assert runtime.tool_execution is not None
            assert runtime.tools.get("coding").handler.runner._journal._effect is runtime.journal
            choices = {
                f"sequence/steps/{i}": AgentBindingDescriptor(
                    runner=BindingSelection.ref(name, "1")
                )
                for i, name in enumerate(["a", "b"])
            }
            definition = BoundDefinition(
                WorkflowSpec(
                    "two",
                    (
                        AgentSpec("a", "First", tools=("coding",)),
                        AgentSpec("b", "Second", tools=("other",)),
                    ),
                ),
                choices,
            )
            request = normalize_request(submission_request(definition, "q"), release)
            validate_bindings(request, release, asdict(Scope()))
            state = TemporalRunState("run", asdict(Scope()), "first", request, release)
            assert state.next_operation() is not None
            for i, name in enumerate(["a", "b"]):
                runner, _ = runtime.binding_catalog.resolve(
                    "runner", BindingSelection.ref(name, "1"), Scope()
                )
                assert runner is runtime.tools.get(["coding", "other"][i]).handler.runner
            assert not (a_dir / "native").exists() and not (b_dir / "native").exists()
        finally:
            await assembly.aclose()

    asyncio.run(run())
    assert events == ["initialize-owner", "initialize-view", "connection"]
