"""Opt-in local monitoring keeps original calls and foreign tools untouched."""

import asyncio
import importlib
import importlib.util
import json
import sys

import pytest


def fixture_module():
    name = "tests.temporal_deployment_coding_cpu_fixture"
    assert importlib.util.find_spec(name) is not None, "bounded CPU context is missing"
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def disabled_by_default(monkeypatch):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU", raising=False)


@pytest.fixture
def monitoring():
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        pytest.skip("Python 3.12 local monitoring required")
    before = [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)]
    yield monitoring
    assert [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)] == before


def rows(directory):
    return [json.loads(line) for line in (directory / "cpu-timing.jsonl").read_text().splitlines()]


def runtime():
    from ralf_agent import ToolRegistry
    from ralf_agent.runtime_builder import EchoProvider
    from ralf_agent.temporal_activities import TemporalRuntime

    return TemporalRuntime(providers={"default": EchoProvider("cpu")}, tools=ToolRegistry())


def test_default_disabled_installs_nothing(tmp_path, monitoring):
    helper = fixture_module()
    before = [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)]
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed is False
        assert [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)] == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("unavailable", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_disabled_context_preserves_thrown_exception_identity(
    tmp_path, monkeypatch, unavailable, error_type
):
    helper = fixture_module()
    if unavailable:
        monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
        monkeypatch.delattr(sys, "monitoring", raising=False)
    error = error_type("original body")
    with pytest.raises(error_type) as caught:
        with helper.coding_cpu_profile(tmp_path) as installed:
            assert installed is False
            raise error
    assert caught.value is error


@pytest.mark.parametrize("method", ["exists", "touch"])
def test_marker_io_failure_preserves_original_body(tmp_path, monkeypatch, method):
    helper = fixture_module()
    from pathlib import Path

    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")

    def failed(*args, **kwargs):
        raise PermissionError("diagnostic marker")

    monkeypatch.setattr(Path, method, failed)
    error = RuntimeError("original")
    with pytest.raises(RuntimeError) as caught:
        with helper.coding_cpu_profile(tmp_path) as installed:
            assert installed is False
            raise error
    assert caught.value is error


@pytest.mark.parametrize("opt_in", ["marker", "environment"])
def test_real_targets_nested_exclusive_and_results_unchanged(
    tmp_path, monkeypatch, monitoring, opt_in
):
    helper = fixture_module()
    original = runtime()
    if opt_in == "marker":
        (tmp_path / "capture-coding-cpu").touch()
    else:
        monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed is True
        assert original.validate_release() == original.manifest
        assert not (tmp_path / "cpu-timing.jsonl").exists()
    result = rows(tmp_path)
    assert len(result) == 1
    assert result[0]["process_cpu_ns"] > 0 and result[0]["wall_ns"] > 0
    calls = {row["function"]: row for row in result[0]["functions"]}
    parent = calls["TemporalRuntime.validate_release"]
    child = calls["TemporalRuntime._current_manifest"]
    assert parent["calls"] == child["calls"] == 1
    assert parent["exceptions"] == child["exceptions"] == 0
    for clock in ("cpu", "wall"):
        assert parent[f"inclusive_{clock}_ns"] == (
            parent[f"exclusive_{clock}_ns"] + child[f"inclusive_{clock}_ns"]
        )
        assert child[f"inclusive_{clock}_ns"] > 0
    assert (tmp_path / "cpu-timing.jsonl").stat().st_mode & 0o777 == 0o600


def test_callback_clock_failure_never_escapes_original_target(tmp_path, monkeypatch, monitoring):
    helper = fixture_module()
    original = runtime()
    (tmp_path / "capture-coding-cpu").touch()

    def failed():
        raise RuntimeError("diagnostic clock failed")

    monkeypatch.setattr(helper.time, "thread_time_ns", failed)
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed
        assert original.validate_release() == original.manifest
    assert rows(tmp_path)[0]["faults"] == 1


def test_selected_stacks_are_independent_between_threads(tmp_path, monitoring):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    helper = fixture_module()
    original = runtime()
    barrier = threading.Barrier(2)

    def work():
        barrier.wait(timeout=5)
        assert original.validate_release() == original.manifest

    (tmp_path / "capture-coding-cpu").touch()
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(work) for _ in range(2)]
            for result in results:
                result.result(timeout=5)
    data = rows(tmp_path)[0]
    assert data["faults"] == data["incomplete_calls"] == 0
    parents = [
        row for row in data["functions"] if row["function"] == "TemporalRuntime.validate_release"
    ]
    assert len(parents) == 2
    assert len({row["thread_id"] for row in parents}) == 2
    assert all(row["calls"] == 1 for row in parents)


def test_original_return_and_exception_objects_and_unwind_stack(tmp_path, monitoring):
    helper = fixture_module()
    from ralf_agent.temporal_session_deployment_verification import SessionControlValidation
    from tests.test_temporal_session_deployment_control import Client, Runtime, fixture

    deployment, value, info = fixture()
    port = Runtime(value["intent"]["binding"]["manifest"])
    original = RuntimeError("must not be serialized")

    def fail(manifest):
        raise original

    port.validate_release = fail
    checked = SessionControlValidation(
        port, Client(value), value, info, deployment_id=deployment, _full_release=False
    )
    (tmp_path / "capture-coding-cpu").touch()
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed
        with pytest.raises(RuntimeError) as caught:
            checked._check()
        assert caught.value is original
        assert checked._check(full=False) is None
    data = rows(tmp_path)[0]
    selected = next(
        row for row in data["functions"] if row["function"] == "SessionControlValidation._check"
    )
    assert selected["calls"] == 2 and selected["exceptions"] == 1
    assert data["incomplete_calls"] == 0
    assert "must not be serialized" not in (tmp_path / "cpu-timing.jsonl").read_text()


def test_equivalent_reimported_code_is_outside_host_only_coverage(tmp_path, monitoring):
    from types import FunctionType

    from ralf_agent.errors import RalfError
    from ralf_agent.temporal_session_deployment_dto import validate_intent
    from tests.test_temporal_session_deployment_dto import DEPLOYMENT, intent

    helper = fixture_module()
    value = intent()
    copied_code = validate_intent.__code__.replace()
    assert copied_code is not validate_intent.__code__
    copied = FunctionType(copied_code, validate_intent.__globals__)
    copied.__kwdefaults__ = validate_intent.__kwdefaults__
    options = {
        "deployment_id": DEPLOYMENT,
        **{key: value[key] for key in ("scope", "namespace", "coordinator_execution_epoch")},
    }
    (tmp_path / "capture-coding-cpu").touch()
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed
        assert copied(value, **options) == value
        with pytest.raises(RalfError):
            copied({}, **options)
        assert validate_intent(value, **options) == value
    data = rows(tmp_path)[0]
    assert data["faults"] == data["incomplete_calls"] == 0
    assert data["coverage"] == "fixed host code objects only; sandbox reimports are not observed"
    selected = next(row for row in data["functions"] if row["function"] == "dto.validate_intent")
    assert selected["calls"] == 1 and selected["exceptions"] == 0


def test_only_fixed_codes_local_and_unwind_global_preserves_foreign_events(
    tmp_path, monkeypatch, monitoring
):
    helper = fixture_module()
    foreign = next(i for i in range(6) if monitoring.get_tool(i) is None)
    monitoring.use_tool_id(foreign, "foreign-cpu-test")
    monitoring.register_callback(foreign, monitoring.events.RAISE, lambda *args: None)
    monitoring.set_events(foreign, monitoring.events.RAISE)
    global_events, local_codes = [], []

    class Spy:
        def __getattr__(self, name):
            return getattr(monitoring, name)

        def set_events(self, tool, mask):
            global_events.append(mask)
            return monitoring.set_events(tool, mask)

        def set_local_events(self, tool, code, mask):
            if mask:
                local_codes.append(code)
                assert mask == monitoring.events.PY_START | monitoring.events.PY_RETURN
            return monitoring.set_local_events(tool, code, mask)

    monkeypatch.setattr(sys, "monitoring", Spy())
    (tmp_path / "capture-coding-cpu").touch()
    try:
        with helper.coding_cpu_profile(tmp_path) as installed:
            assert installed
            assert monitoring.get_events(foreign) == monitoring.events.RAISE
        assert len(set(local_codes)) == 8
        assert global_events == [monitoring.events.PY_UNWIND, 0]
        assert monitoring.get_events(foreign) == monitoring.events.RAISE
    finally:
        monitoring.set_events(foreign, 0)
        monitoring.register_callback(foreign, monitoring.events.RAISE, None)
        monitoring.free_tool_id(foreign)


def test_no_free_slot_yields_false_without_taking_over(tmp_path, monitoring):
    helper = fixture_module()
    owned = []
    try:
        for slot in range(6):
            if monitoring.get_tool(slot) is None:
                monitoring.use_tool_id(slot, "foreign-cpu-" + str(slot))
                owned.append(slot)
        before = [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)]
        (tmp_path / "capture-coding-cpu").touch()
        with helper.coding_cpu_profile(tmp_path) as installed:
            assert installed is False
        assert [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)] == before
        assert not (tmp_path / "cpu-timing.jsonl").exists()
    finally:
        for slot in owned:
            monitoring.free_tool_id(slot)


def test_partial_local_install_failure_cleans_own_slot(tmp_path, monkeypatch, monitoring):
    helper = fixture_module()
    original = runtime()
    touched = []

    class Failing:
        def __getattr__(self, name):
            return getattr(monitoring, name)

        def set_local_events(self, tool, code, mask):
            if mask:
                touched.append((tool, code))
                if len(touched) == 2:
                    raise RuntimeError("diagnostic install failed")
            return monitoring.set_local_events(tool, code, mask)

    monkeypatch.setattr(sys, "monitoring", Failing())
    (tmp_path / "capture-coding-cpu").touch()
    with helper.coding_cpu_profile(tmp_path) as installed:
        assert installed is False
        assert original.validate_release() == original.manifest
    assert all(monitoring.get_local_events(tool, code) == 0 for tool, code in touched)


@pytest.mark.parametrize("original_error", [False, True])
def test_write_failure_does_not_replace_body_result_or_exception(
    tmp_path, monkeypatch, monitoring, original_error
):
    helper = fixture_module()
    (tmp_path / "capture-coding-cpu").touch()

    def unwritable(*args, **kwargs):
        raise OSError("diagnostic output unavailable")

    monkeypatch.setattr(helper.os, "open", unwritable)
    error = RuntimeError("original")
    sentinel = object()

    def body():
        with helper.coding_cpu_profile(tmp_path) as installed:
            assert installed
            if original_error:
                raise error
            return sentinel

    if original_error:
        with pytest.raises(RuntimeError) as caught:
            body()
        assert caught.value is error
    else:
        assert body() is sentinel
