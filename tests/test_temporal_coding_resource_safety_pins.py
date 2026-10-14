"""Selected Worker pins physical capacity and complete original Docker control."""

import asyncio
import builtins
import importlib

import pytest

from ralf_agent import codex_environment, codex_runner_capacity
from ralf_agent import temporal_coding_protocol as protocol
from ralf_agent.codex_environment import DockerCodingEnvironment
from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.errors import DefinitionMismatch

# Literal inventories name the physical decisions each mutation must invalidate.
CAPACITY_FUNCTIONS = ("_require", "_hex", "_pin", "_private_file", "_pairs")
CAPACITY_METHODS = (
    "__init__",
    "_check_root",
    "_check_lock",
    "_validate_state",
    "_read",
    "_write",
    "_drop_lock",
    "try_acquire",
    "_owned",
    "mark_native_intent",
    "release",
    "close",
)
CAPACITY_PROPERTIES = ("claim",)
CAPACITY_CONSTANTS = ("_LOCK", "_RECORD", "_LIMIT")
ENVIRONMENT_METHODS = (
    "__init__",
    "prepare",
    "inspect",
    "stop",
    "stop_existing",
    "observe_namespace_absence",
    "_observe_namespace_absence",
    "_namespace_query",
    "aclose",
    "_owned",
    "_serialized_operation",
    "_check_root",
    "_acquire",
    "_read_metadata",
    "_write_metadata",
    "_provision",
    "_check_files",
    "_labels",
    "_create_argv",
    "_prepare",
    "_prepare_legacy_locator",
    "_create_operation_digest",
    "_validate_create_operation",
    "_create_candidates",
    "_submit_create",
    "_recover_create",
    "_inspect_raw",
    "_validate_container",
    "_inspect",
    "_stop",
    "_stop_existing",
    "_validate_retirement",
    "_container_present",
    "_record_fenced",
    "_close",
    "_cli",
)
ENVIRONMENT_PROPERTIES = ("identity", "transport_env", "active_operations", "transport_argv")
ENVIRONMENT_FUNCTIONS = ("_canonical", "_digest", "_require", "_pin")
ENVIRONMENT_CONSTANTS = (
    "_SECCOMP_DIGEST",
    "_COMMAND",
    "_ENTRYPOINT",
    "_IMAGE_ENV",
    "_REGISTRY",
    "_REGISTRY_OPTIONS",
    "_CAP",
    "_ZERO_TIME",
)


@pytest.fixture
def registered(tmp_path, monkeypatch, request):
    from ralf_agent.delegated_coding import register_coding_tool
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal
    from ralf_agent.temporal_activities import TemporalRuntime
    from ralf_agent.temporal_journal import PostgresEffectJournal
    from ralf_agent.tools import ToolRegistry
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
    from tests.test_temporal_engine import Provider

    events = []
    publish_initialization(monkeypatch, events)
    options = entry(tmp_path)
    effect = PostgresEffectJournal(Connection(events), owns_connection=True)
    journal = PostgresRunnerJournal(effect, identity={"publication": "physical-safety"})
    asyncio.run(journal.initialize())
    runner = CodexCodingRunner(
        options["runner_root"],
        journal=journal,
        docker_executable=options["docker_executable"],
        docker_host=options["docker_host"],
    )
    tools = ToolRegistry()
    register_coding_tool(tools, runner)
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=tools,
        journal=effect,
        coding_execution=True,
        coding_composition=getattr(request, "param", False),
    )
    runtime.validate_release()
    original = runtime.manifest
    assert original["binding_protocol"] == (23 if getattr(request, "param", False) else 22)
    assert original["coding_execution_protocol"]["version"] == 6
    assert list((tmp_path / "runner").iterdir()) == []
    try:
        yield runtime, original, tmp_path / "runner"
    finally:
        asyncio.run(runner.aclose())
        asyncio.run(journal.aclose())
        asyncio.run(effect.aclose())


def foreign_body(*args, **kwargs):
    raise AssertionError("Physical implementation executed during pin validation")


def assert_worker_rejects(registered):
    runtime, original, root = registered
    # History validates complete SHA declarations without comparing physical code.
    protocol.validate_protocol(original)
    with pytest.raises(DefinitionMismatch):
        protocol.check(runtime, original)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("name", CAPACITY_FUNCTIONS)
def test_worker_refuses_changed_capacity_function(registered, monkeypatch, name):
    monkeypatch.setattr(codex_runner_capacity, name, foreign_body)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", CAPACITY_METHODS)
def test_worker_refuses_changed_capacity_method(registered, monkeypatch, name):
    monkeypatch.setattr(codex_runner_capacity.RootCapacity, name, foreign_body)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", CAPACITY_PROPERTIES)
def test_worker_refuses_changed_capacity_property(registered, monkeypatch, name):
    monkeypatch.setattr(codex_runner_capacity.RootCapacity, name, property(foreign_body))
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", CAPACITY_CONSTANTS)
def test_worker_refuses_changed_capacity_constant(registered, monkeypatch, name):
    monkeypatch.setattr(codex_runner_capacity, name, "foreign")
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", ENVIRONMENT_METHODS)
def test_worker_refuses_changed_environment_lifecycle_method(registered, monkeypatch, name):
    monkeypatch.setattr(DockerCodingEnvironment, name, foreign_body)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", ENVIRONMENT_PROPERTIES)
def test_worker_refuses_changed_environment_property(registered, monkeypatch, name):
    monkeypatch.setattr(DockerCodingEnvironment, name, property(foreign_body))
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", ENVIRONMENT_FUNCTIONS)
def test_worker_refuses_changed_environment_module_helper(registered, monkeypatch, name):
    monkeypatch.setattr(codex_environment, name, foreign_body)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("name", ENVIRONMENT_CONSTANTS)
def test_worker_refuses_changed_environment_constant(registered, monkeypatch, name):
    monkeypatch.setattr(codex_environment, name, "foreign")
    assert_worker_rejects(registered)


@pytest.mark.parametrize(
    "name",
    [
        "_acquire_capacity",
        "_release_capacity",
        "_release_unprepared_capacity",
        "_wait_owner",
        "_check_capacity",
        "__init__",
    ],
)
def test_worker_refuses_changed_runner_capacity_gate(registered, monkeypatch, name):
    monkeypatch.setattr(CodexCodingRunner, name, foreign_body, raising=False)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("registered", [False, True], indirect=True)
def test_history_does_not_import_or_discover_physical_modules(registered, monkeypatch):
    _, original, _ = registered
    real_import = builtins.__import__

    def pure_only(name, globals=None, locals=None, fromlist=(), level=0):
        forbidden = {
            "codex_runner_capacity",
            "codex_environment",
            "codex_runner",
            "temporal_coding_runtime",
            "postgres_coding_resources",
            "temporal_activities",
            "temporal_coding_authority",
        }
        if name.rsplit(".", 1)[-1] in forbidden or forbidden.intersection(fromlist or ()):
            raise AssertionError("History imported physical Worker implementation")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", pure_only)
    protocol.validate_protocol(original)


@pytest.mark.parametrize("group", ["capacity", "environment", "io_inventory", "runner_support"])
@pytest.mark.parametrize("mutation", ["missing", "extra", "bad_sha"])
def test_history_requires_complete_bounded_physical_sha_inventory(registered, group, mutation):
    import copy

    _, original, _ = registered
    value = copy.deepcopy(original)
    fields = value["coding_execution_protocol"]["implementation"]
    assert group in fields
    if mutation == "missing":
        fields[group].pop(next(iter(fields[group])))
    elif mutation == "extra":
        fields[group]["unpublished"] = "a" * 64
    else:
        fields[group][next(iter(fields[group]))] = "short"
    with pytest.raises((DefinitionMismatch, ValueError)):
        protocol.validate_protocol(value)


def test_worker_cannot_hide_physical_mutation_with_stale_implementation_inventory(
    registered,
    monkeypatch,
):
    import copy

    runtime, original, _ = registered
    fixed = copy.deepcopy(original["coding_execution_protocol"]["implementation"])

    def stale():
        return copy.deepcopy(fixed)

    monkeypatch.setattr(codex_runner_capacity.RootCapacity, "release", foreign_body)
    monkeypatch.setattr(protocol, "implementation", stale)
    with pytest.raises(DefinitionMismatch):
        protocol.check(runtime, original)


@pytest.mark.parametrize("registered", [False, True], indirect=True)
def test_both_selected_publications_reject_original_control_body_drift(registered, monkeypatch):
    monkeypatch.setattr(DockerCodingEnvironment, "_recover_create", foreign_body)
    assert_worker_rejects(registered)


@pytest.mark.parametrize(
    "name",
    [
        "RUNNER_METHODS",
        "CAPACITY_FUNCTIONS",
        "CAPACITY_METHODS",
        "CAPACITY_PROPERTIES",
        "CAPACITY_CONSTANTS",
        "ENVIRONMENT_METHODS",
        "ENVIRONMENT_PROPERTIES",
        "ENVIRONMENT_FUNCTIONS",
        "ENVIRONMENT_CONSTANTS",
    ],
)
def test_worker_refuses_narrowed_fixed_discovery_inventory(registered, monkeypatch, name):
    fields = getattr(protocol, name)
    monkeypatch.setattr(protocol, name, fields[1:])
    runtime, original, _ = registered
    with pytest.raises(DefinitionMismatch):
        protocol.check(runtime, original)


def test_worker_refuses_substituted_physical_getter_fingerprint_function(registered, monkeypatch):
    def constant_sha(owner, name):
        return "a" * 64

    monkeypatch.setattr(protocol, "_physical_digest", constant_sha)
    assert_worker_rejects(registered)


@pytest.mark.parametrize("target", ["inventory", "constructor", "cached_environment"])
def test_physical_support_publication_changes_without_invoking_replaced_entry(monkeypatch, target):
    from ralf_agent import codex_runner

    original = protocol.implementation()
    if target == "inventory":
        monkeypatch.setattr(codex_runner, "_capacity_implementation", foreign_body)
    elif target == "constructor":
        monkeypatch.setattr(CodexCodingRunner, "__init__", foreign_body)
    else:
        cached = codex_runner._environment_implementation()

        def stale_environment():
            import copy

            return copy.deepcopy(cached)

        monkeypatch.setattr(codex_runner, "_environment_implementation", stale_environment)
    changed = protocol.implementation()
    assert changed != original


@pytest.mark.parametrize("name", ["__init__", "_check_capacity"])
def test_history_requires_original_constructor_and_slot_validation_pin(registered, name):
    import copy

    _, original, _ = registered
    value = copy.deepcopy(original)
    metadata = value["coding_execution_protocol"]["tools"]["coding"]["implementation"]
    assert name in metadata
    metadata.pop(name)
    with pytest.raises(DefinitionMismatch):
        protocol.validate_protocol(value)


def policy():
    name = "ralf_agent.coding_resource_fingerprint"
    assert importlib.util.find_spec(name) is not None, "Typed resource policy is not implemented"
    return importlib.import_module(name).policy_value


class DifferentTmpfs(str):
    def __format__(self, spec):
        return "rw,size=9999999999"


def test_environment_constant_subclass_cannot_preserve_sha_but_change_docker_semantics(monkeypatch):
    from ralf_agent.types import digest

    original = codex_environment._REGISTRY_OPTIONS
    changed = DifferentTmpfs(original)
    assert digest(changed) == digest(original)
    assert f"{changed}" != f"{original}"
    monkeypatch.setattr(codex_environment, "_REGISTRY_OPTIONS", changed)
    with pytest.raises(DefinitionMismatch):
        protocol.implementation()


@pytest.mark.parametrize(
    "base,value",
    [
        (str, "same"),
        (int, 1),
        (float, 1.0),
        (list, ["same"]),
        (tuple, ("same",)),
        (dict, {"key": "same"}),
        (frozenset, frozenset({"same"})),
    ],
)
def test_policy_rejects_builtin_subtypes_even_when_json_value_matches(base, value):
    subtype = type("ForeignPolicy", (base,), {})
    changed = subtype(value)
    with pytest.raises(DefinitionMismatch):
        policy()(changed)


@pytest.mark.parametrize(
    "value",
    [
        {DifferentTmpfs("key"): "value"},
        {1: "value"},
        {"value": DifferentTmpfs("same")},
        [DifferentTmpfs("same")],
        {"value": object()},
        b"bytes",
        {"set"},
        float("nan"),
        float("inf"),
    ],
)
def test_policy_rejects_nested_unsupported_or_ambiguous_data(value):
    with pytest.raises(DefinitionMismatch):
        policy()(value)


def test_policy_preserves_builtin_container_and_scalar_types():
    assert policy()(
        {
            "items": [None, True, 1, 1.0, "one"],
            "ordered": ("b", "a"),
            "unordered": frozenset({"b", "a"}),
        }
    ) == {
        "dict": {
            "items": {"list": [None, True, 1, 1.0, "one"]},
            "ordered": {"tuple": ["b", "a"]},
            "unordered": {"frozenset": ["a", "b"]},
        },
    }
    from ralf_agent.types import digest

    assert digest(policy()(["one"])) != digest(policy()(("one",)))
    assert digest(policy()(True)) != digest(policy()(1))
    assert digest(policy()(1)) != digest(policy()(1.0))


def test_policy_rejects_cycles_and_bounded_depth_without_recursion_leak():
    cycle = []
    cycle.append(cycle)
    deep = "leaf"
    for _ in range(66):
        deep = [deep]
    for value in (cycle, deep):
        with pytest.raises(DefinitionMismatch):
            policy()(value)


def test_cached_policy_helper_cannot_hide_entry_mutation(monkeypatch):
    name = "ralf_agent.coding_resource_fingerprint"
    actual = policy()
    module = importlib.import_module(name)
    protocol.implementation()
    values = ("same", ["same"], ("same",), {"same": 1})
    saved = [actual(value) for value in values]

    def cached(value):
        import copy

        for candidate, result in zip(values, saved, strict=True):
            if type(value) is type(candidate) and value == candidate:
                return copy.deepcopy(result)
        return actual(value)

    monkeypatch.setattr(module, "policy_value", cached)
    # Rebound imported roles fail before stale policy bytes can be published.
    with pytest.raises(DefinitionMismatch, match="alias"):
        protocol.implementation()
