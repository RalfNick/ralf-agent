"""CPU opt-in uses the existing test Worker lifecycle, with no service execution."""

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

from tests import temporal_deployment_coding_worker_fixture as worker


@pytest.fixture(autouse=True)
def clear_diagnostic_environment(monkeypatch):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU", raising=False)
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", raising=False)


@pytest.fixture
def cpu_context(monkeypatch):
    events = []
    module = ModuleType("tests.temporal_deployment_coding_cpu_fixture")

    @contextmanager
    def coding_cpu_profile(directory):
        events.append(("cpu-enter", directory))
        try:
            yield True
        finally:
            events.append(("cpu-exit", directory))

    module.coding_cpu_profile = coding_cpu_profile
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return events


class Client:
    def __init__(self):
        self.workflow_service = object()
        self.original_plugin = object()
        self.original_config = {"plugins": [self.original_plugin]}

    def config(self, **options):
        assert not options
        return self.original_config


@pytest.mark.parametrize("opt_in", ["environment", "marker"])
def test_cpu_only_registers_lifecycle_without_sdk_spans(tmp_path, monkeypatch, cpu_context, opt_in):
    marker = tmp_path / "capture-coding-cpu"
    if opt_in == "environment":
        monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    else:
        marker.touch()
    original = Client()
    client = worker.FaultClient(original, tmp_path)
    assert client.timing.enabled is False
    assert client.workflow_service is original.workflow_service
    with client.timing.span("query", None, "view", None) as span:
        assert span is None
    assert not (tmp_path / "sdk-timing.jsonl").exists()
    configured = client.config()
    assert len(configured["plugins"]) == 2
    assert configured["plugins"][0] is original.original_plugin
    assert marker.exists()
    assert not (tmp_path / "capture-coding-timing").exists()
    assert not cpu_context
    sentinel, actual_worker = object(), object()

    async def run():
        baseline = asyncio.all_tasks()

        async def next_worker(value):
            assert value is actual_worker
            assert cpu_context == [("cpu-enter", tmp_path)]
            assert asyncio.all_tasks() == baseline  # Disabled loop probe owns no Task.
            return sentinel

        assert await configured["plugins"][-1].run_worker(actual_worker, next_worker) is sentinel
        assert asyncio.all_tasks() == baseline

    asyncio.run(run())
    assert cpu_context == [("cpu-enter", tmp_path), ("cpu-exit", tmp_path)]
    assert not (tmp_path / "worker-loop-lag.jsonl").exists()


def test_default_client_and_peer_install_no_cpu_or_sdk_hook(tmp_path, cpu_context):
    original = Client()
    client = worker.FaultClient(original, tmp_path)
    assert client.config() is original.original_config
    assert client.workflow_service is original.workflow_service
    assert client._timing_plugin is None
    worker.peer(tmp_path)
    assert not cpu_context
    assert not (tmp_path / "capture-coding-cpu").exists()
    assert not (tmp_path / "capture-coding-timing").exists()


def test_peer_persists_cpu_marker_before_worker_environment_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    worker.peer(tmp_path)
    assert (tmp_path / "capture-coding-cpu").exists()
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU")
    client = worker.FaultClient(Client(), tmp_path)
    assert client._timing_plugin is not None
    assert client.timing.enabled is False


@pytest.mark.parametrize("operation", ["exists", "touch"])
def test_cpu_marker_io_failure_keeps_original_peer_client_and_worker_results(
    tmp_path, monkeypatch, cpu_context, operation
):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    original_operation = getattr(Path, operation)

    def marker_failure(path, *args, **options):
        if path.name == "capture-coding-cpu":
            raise PermissionError("CPU marker unavailable")
        return original_operation(path, *args, **options)

    monkeypatch.setattr(Path, operation, marker_failure)
    assert worker.peer(tmp_path).is_file()
    client = worker.FaultClient(Client(), tmp_path)
    assert client.timing.enabled is False
    sentinel = object()

    async def run():
        async def next_worker(value):
            return sentinel

        assert await client.config()["plugins"][-1].run_worker(object(), next_worker) is sentinel

    asyncio.run(run())
    assert cpu_context == [("cpu-enter", tmp_path), ("cpu-exit", tmp_path)]


@pytest.mark.parametrize("error", [RuntimeError("original failure"), asyncio.CancelledError()])
def test_worker_failure_or_cancellation_is_preserved_and_cpu_context_exits(
    tmp_path, monkeypatch, cpu_context, error
):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    plugin = worker.FaultClient(Client(), tmp_path).config()["plugins"][-1]

    async def run():
        async def next_worker(value):
            raise error

        with pytest.raises(type(error)) as caught:
            await plugin.run_worker(object(), next_worker)
        assert caught.value is error

    asyncio.run(run())
    assert cpu_context == [("cpu-enter", tmp_path), ("cpu-exit", tmp_path)]


def test_cpu_and_sdk_loop_cleanup_share_original_worker_lifecycle(
    tmp_path, monkeypatch, cpu_context
):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_TIMING", "1")
    client = worker.FaultClient(Client(), tmp_path)
    plugin = client.config()["plugins"][-1]
    sentinel = object()

    async def run():
        baseline = asyncio.all_tasks()

        async def next_worker(value):
            assert cpu_context == [("cpu-enter", tmp_path)]
            await asyncio.sleep(0.08)
            return sentinel

        assert await plugin.run_worker(object(), next_worker) is sentinel
        assert asyncio.all_tasks() == baseline

    asyncio.run(run())
    assert cpu_context == [("cpu-enter", tmp_path), ("cpu-exit", tmp_path)]
    assert (tmp_path / "worker-loop-lag.jsonl").exists()
