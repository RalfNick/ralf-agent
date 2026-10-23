"""Pure refusal precedes any SDK constructors, callbacks or namespace lookup."""

import importlib
from datetime import timedelta

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError


def options():
    return importlib.import_module("relf_agent.temporal_startup_options")


@pytest.mark.parametrize("value", [True, None, 0, -1, 86401, float("nan"), float("inf"), "1"])
def test_host_timeout_refuses_invalid_primitive(value):
    with pytest.raises(ValidationError):
        options().validate_engine_options({"activity_timeout": value})


@pytest.mark.parametrize(
    "key", ["client", "scope", "namespace", "release", "task_queue", "unknown"]
)
def test_engine_names_refuse_without_sdk(key):
    with pytest.raises(ValidationError):
        options().validate_engine_options({key: 1})


def test_seconds_values_detach_and_numeric_subclasses_never_run_in_host():
    calls = []

    class LazyNumber(float):
        def __lt__(self, other):
            calls.append("compare")
            return super().__lt__(other)

        def __float__(self):
            calls.append("float")
            return super().__float__()

    supplied = {"activity_timeout": 0.25, "drive_timeout": 86400}
    result = options().validate_engine_options(supplied)
    supplied["activity_timeout"] = 0
    assert result == {"activity_timeout": 0.25, "drive_timeout": 86400}
    with pytest.raises(ValidationError):
        options().validate_engine_options({"drive_timeout": LazyNumber(1)})
    assert calls == []


@pytest.mark.parametrize(
    "key", ["client", "task_queue", "runtime", "activity_owner", "workflows", "activities"]
)
def test_host_owned_worker_fields_refuse(key):
    with pytest.raises(ValidationError):
        options().validate_worker_options({key: object()}, releases=[])


@pytest.mark.parametrize(
    "declaration",
    [
        {"max_cached_workflows": -1},
        {"max_cached_workflows": True},
        {"max_concurrent_activities": 0},
        {"max_concurrent_activities": 1.5},
        {"max_concurrent_activity_task_polls": False},
        {"debug_mode": 1},
        {"max_activities_per_second": float("nan")},
        {"max_task_queue_activities_per_second": -1},
        {"nonsticky_to_sticky_poll_ratio": float("inf")},
        {"graceful_shutdown_timeout": timedelta(seconds=-1)},
        {"max_heartbeat_throttle_interval": 1},
    ],
)
def test_common_worker_values_refuse_without_constructor(declaration, monkeypatch):
    module = options()
    monkeypatch.setattr(module, "_worker_parameters", lambda: set(declaration))
    with pytest.raises(ValidationError):
        module.validate_worker_options(declaration, releases=[])


def test_installed_sdk_unknown_field_refuses_without_constructing_worker(monkeypatch):
    worker = pytest.importorskip("temporalio.worker")
    constructed = []

    class OlderWorker:
        def __init__(self, client, *, task_queue, activities=(), workflows=(), debug_mode=False):
            constructed.append("constructed")

    monkeypatch.setattr(worker, "Worker", OlderWorker)
    with pytest.raises(ValidationError):
        options().validate_worker_options({"new_sdk_only_field": True}, releases=[])
    assert options().validate_worker_options({"debug_mode": False}, releases=[]) == {
        "debug_mode": False
    }
    assert constructed == []


def test_cross_field_constraints_and_all_profile_build_ids(monkeypatch):
    module = options()
    allowed = {
        "tuner",
        "max_concurrent_activities",
        "max_concurrent_workflow_tasks",
        "max_cached_workflows",
        "build_id",
    }
    monkeypatch.setattr(module, "_worker_parameters", lambda: allowed)
    with pytest.raises(ValidationError):
        module.validate_worker_options(
            {"tuner": object(), "max_concurrent_activities": 1}, releases=[]
        )
    with pytest.raises(ValidationError):
        module.validate_worker_options({"max_concurrent_workflow_tasks": 1}, releases=[])
    assert module.validate_worker_options(
        {"max_cached_workflows": 0, "max_concurrent_workflow_tasks": 1}, releases=[]
    ) == {"max_cached_workflows": 0, "max_concurrent_workflow_tasks": 1}
    from relf_agent.types import digest

    first, second = {"release": "1"}, {"release": "2"}
    with pytest.raises(DefinitionMismatch):
        module.validate_worker_options({"build_id": digest(first)}, releases=[first, second])
    assert module.validate_worker_options({"build_id": digest(first)}, releases=[first]) == {
        "build_id": digest(first)
    }


def test_nullable_and_valid_primitive_worker_values_are_detached(monkeypatch):
    module = options()
    values = {
        "max_concurrent_activities": None,
        "max_activities_per_second": None,
        "max_cached_workflows": 0,
        "graceful_shutdown_timeout": timedelta(0),
        "debug_mode": False,
    }
    monkeypatch.setattr(module, "_worker_parameters", lambda: set(values))
    detached = module.validate_worker_options(values, releases=[])
    assert detached == values and detached is not values


def test_build_identity_does_not_invoke_caller_comparison(monkeypatch):
    module = options()
    monkeypatch.setattr(module, "_worker_parameters", lambda: {"build_id"})
    calls = []

    class LazyIdentity:
        def __ne__(self, other):
            calls.append("compared")
            return False

    with pytest.raises(DefinitionMismatch):
        module.validate_worker_options({"build_id": LazyIdentity()}, releases=[{"release": "1"}])
    assert calls == []


def test_strict_timeout_never_reads_caller_class():
    calls = []

    class Lazy:
        @property
        def __class__(self):
            calls.append("class")
            raise RuntimeError("caller code executed")

    with pytest.raises(ValidationError):
        options().validate_engine_options({"activity_timeout": Lazy()})
    assert calls == []


@pytest.mark.parametrize(
    "field", ["nonsticky_to_sticky_poll_ratio", "max_task_queue_activities_per_second"]
)
def test_sdk_compatible_zero_ratio_and_task_queue_rate(field, monkeypatch):
    module = options()
    monkeypatch.setattr(module, "_worker_parameters", lambda: {field})
    assert module.validate_worker_options({field: 0}, releases=[]) == {field: 0}


@pytest.mark.parametrize("value", [42, True, object()])
def test_identity_refuses_non_string_without_conversion(value, monkeypatch):
    module = options()
    monkeypatch.setattr(module, "_worker_parameters", lambda: {"identity"})
    with pytest.raises(ValidationError):
        module.validate_worker_options({"identity": value}, releases=[])


def test_identity_never_invokes_caller_properties_or_conversion(monkeypatch):
    module = options()
    monkeypatch.setattr(module, "_worker_parameters", lambda: {"identity"})
    calls = []

    class Lazy:
        @property
        def __class__(self):
            calls.append("class")
            return str

        def __str__(self):
            calls.append("str")
            return "worker"

    with pytest.raises(ValidationError):
        module.validate_worker_options({"identity": Lazy()}, releases=[])
    assert calls == []
    for value in (None, "", "worker"):
        assert module.validate_worker_options({"identity": value}, releases=[]) == {
            "identity": value
        }
