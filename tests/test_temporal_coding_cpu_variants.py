"""Opt-in observations of equivalent code copies are telemetry, never authority."""

import asyncio
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import FunctionType, SimpleNamespace

import pytest

from relf_agent import temporal_session_deployment_dto as dto
from relf_agent.errors import ValidationError
from tests.temporal_deployment_coding_cpu_fixture import coding_cpu_profile

pytestmark = pytest.mark.skipif(not hasattr(sys, "monitoring"), reason="Python 3.12 monitoring")


@pytest.fixture(autouse=True)
def opt_in(monkeypatch):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU", "1")
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_CPU_VARIANTS", "1")


def invalid_intent(function):
    with pytest.raises(ValidationError):
        function({}, "private-input-not-for-telemetry")


def record(directory):
    values = [
        json.loads(line) for line in (directory / "cpu-timing.jsonl").read_text().splitlines()
    ]
    assert len(values) == 1
    value = values[0]
    assert value["version"] == 2
    assert value["faults"] == value["incomplete_calls"] == 0
    assert value["timing_valid"] is True
    for row in value["functions"]:
        for clock in ("cpu", "wall"):
            assert 0 <= row[f"exclusive_{clock}_ns"] <= row[f"inclusive_{clock}_ns"]
    assert "private-input-not-for-telemetry" not in json.dumps(value)
    return value


def rows(value, name):
    return [row for row in value["functions"] if row["function"] == name]


def test_original_and_equivalent_code_copy_have_separate_observations(tmp_path):
    original = dto._intent
    clone = FunctionType(original.__code__.replace(), original.__globals__)
    assert clone.__code__ == original.__code__ and clone.__code__ is not original.__code__
    with coding_cpu_profile(tmp_path) as installed:
        assert installed
        invalid_intent(original)
        invalid_intent(clone)
    value = record(tmp_path)
    observed = rows(value, "dto._intent")
    assert sorted((r["origin"], r["calls"], r["exceptions"]) for r in observed) == [
        ("equivalent-code-copy", 1, 1),
        ("original-code", 1, 1),
    ]


@pytest.mark.parametrize("change", ["constants", "filename", "qualname"])
def test_lookalike_with_changed_code_or_source_address_is_not_observed(tmp_path, change):
    code = dto._intent.__code__
    options = {
        "constants": {"co_consts": (*code.co_consts, "changed")},
        "filename": {"co_filename": "/untrusted/same-name.py"},
        "qualname": {"co_qualname": "AnotherClass._intent"},
    }[change]
    clone = FunctionType(code.replace(**options), dto._intent.__globals__)
    with coding_cpu_profile(tmp_path):
        invalid_intent(clone)
        invalid_intent(dto._intent)
    observed = rows(record(tmp_path), "dto._intent")
    assert len(observed) == 1 and observed[0]["origin"] == "original-code"
    assert observed[0]["calls"] == 1


def test_nested_exception_counts_and_multiple_threads_remain_balanced(tmp_path):
    clone = FunctionType(dto._intent.__code__.replace(), dto._intent.__globals__)
    with coding_cpu_profile(tmp_path):
        with pytest.raises(ValidationError):
            dto.validate_origin({}, intent={}, deployment_id="private-input-not-for-telemetry")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: invalid_intent(clone), range(16)))
    value = record(tmp_path)
    assert sum(r["calls"] for r in rows(value, "dto._intent")) == 17
    assert sum(r["exceptions"] for r in rows(value, "dto.validate_origin")) == 1


def test_completed_threads_do_not_consume_the_concurrent_stack_allowance(tmp_path, monkeypatch):
    from tests import temporal_coding_cpu_variants as variants

    identity = [1000]
    monkeypatch.setattr(
        variants,
        "threading",
        SimpleNamespace(Lock=threading.Lock, get_ident=lambda: identity[0]),
    )
    with coding_cpu_profile(tmp_path):
        for thread in range(1000, 1065):
            identity[0] = thread
            invalid_intent(dto._intent)
    value = record(tmp_path)
    observed = rows(value, "dto._intent")
    assert len(observed) == 65 and sum(row["calls"] for row in observed) == 65
    assert value["first_fault_reason"] is None


def test_two_contexts_restore_monitoring_and_observe_the_same_clone(tmp_path):
    monitoring = sys.monitoring
    before = [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)]
    clone = FunctionType(dto._intent.__code__.replace(), dto._intent.__globals__)
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        with coding_cpu_profile(directory):
            invalid_intent(clone)
        assert sum(r["calls"] for r in rows(record(directory), "dto._intent")) == 1
        assert [(monitoring.get_tool(i), monitoring.get_events(i)) for i in range(6)] == before


@pytest.mark.parametrize(
    "error", [RuntimeError("original-business-error"), asyncio.CancelledError()]
)
def test_output_limit_never_swallows_original_business_exception(tmp_path, monkeypatch, error):
    from tests import temporal_coding_cpu_variants as variants

    monkeypatch.setattr(variants, "_MAX_BYTES", 1)
    with pytest.raises(type(error)) as caught:
        with coding_cpu_profile(tmp_path):
            raise error
    assert caught.value is error
    assert not (tmp_path / "cpu-timing.jsonl").exists()


def test_nested_copies_and_first_exception_are_balanced(tmp_path):
    intent = FunctionType(dto._intent.__code__.replace(), dto._intent.__globals__)
    namespace = {**dto.validate_origin.__globals__, "_intent": intent}
    origin = FunctionType(dto.validate_origin.__code__.replace(), namespace)
    with coding_cpu_profile(tmp_path):
        with pytest.raises(ValidationError):
            origin({}, intent={}, deployment_id="private-input-not-for-telemetry")
    value = record(tmp_path)
    for name in ("dto._intent", "dto.validate_origin"):
        observed = rows(value, name)
        assert len(observed) == 1 and observed[0]["origin"] == "equivalent-code-copy"
        assert observed[0]["calls"] == observed[0]["exceptions"] == 1


def test_code_capacity_failure_is_explicit_and_cleans_registered_events(tmp_path, monkeypatch):
    from tests import temporal_coding_cpu_variants as variants

    monkeypatch.setattr(variants, "_MAX_CODES", 0)
    code = dto._intent.__code__.replace()
    clone = FunctionType(code, dto._intent.__globals__)
    before = [(sys.monitoring.get_tool(i), sys.monitoring.get_events(i)) for i in range(6)]
    with coding_cpu_profile(tmp_path):
        invalid_intent(clone)
    value = json.loads((tmp_path / "cpu-timing.jsonl").read_text())
    assert not value["timing_valid"] and value["faults"] > 0
    assert value["first_fault_reason"] == "code_limit"
    assert value["incomplete_calls"] > 0
    assert [(sys.monitoring.get_tool(i), sys.monitoring.get_events(i)) for i in range(6)] == before
    assert all(sys.monitoring.get_local_events(i, code) == 0 for i in range(6))


def test_variants_alone_do_not_install_a_collector(tmp_path, monkeypatch):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU")
    with coding_cpu_profile(tmp_path) as installed:
        assert installed is False
        invalid_intent(dto._intent)
    assert not (tmp_path / "cpu-timing.jsonl").exists()


def test_foreign_tool_disabled_start_locations_are_not_restarted(tmp_path):
    monitoring = sys.monitoring
    slot = next(i for i in range(6) if monitoring.get_tool(i) is None)
    seen = []

    def foreign():
        return 7

    def callback(code, offset):
        if code is foreign.__code__:
            seen.append(1)
        return monitoring.DISABLE

    monitoring.use_tool_id(slot, "foreign-test-tool")
    previous = monitoring.register_callback(slot, monitoring.events.PY_START, callback)
    try:
        monitoring.set_events(slot, monitoring.events.PY_START)
        assert foreign() == 7 and seen == [1]
        with coding_cpu_profile(tmp_path):
            assert foreign() == 7
            invalid_intent(dto._intent)
        assert foreign() == 7 and seen == [1]
        assert monitoring.get_tool(slot) == "foreign-test-tool"
        record(tmp_path)
    finally:
        monitoring.set_events(slot, 0)
        monitoring.register_callback(slot, monitoring.events.PY_START, previous)
        monitoring.free_tool_id(slot)


def test_partial_variant_registration_failure_keeps_business_error_and_cleans(
    tmp_path, monkeypatch
):
    monitoring = sys.monitoring
    code = dto._intent.__code__.replace()
    clone = FunctionType(code, dto._intent.__globals__)
    original = monitoring.set_local_events

    def reject_variant(slot, target, events):
        if target is code and events:
            raise RuntimeError("registration failed")
        return original(slot, target, events)

    monkeypatch.setattr(monitoring, "set_local_events", reject_variant)
    with coding_cpu_profile(tmp_path):
        invalid_intent(clone)
    value = json.loads((tmp_path / "cpu-timing.jsonl").read_text())
    assert not value["timing_valid"] and value["faults"] > 0
    assert all(monitoring.get_local_events(i, code) == 0 for i in range(6))


def test_marker_failure_disables_diagnostic_without_changing_business_result(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU_VARIANTS")
    original = Path.exists

    def unavailable(path):
        if path.name == "capture-coding-cpu-variants":
            raise PermissionError("marker unavailable")
        return original(path)

    monkeypatch.setattr(Path, "exists", unavailable)
    with coding_cpu_profile(tmp_path) as installed:
        assert installed is False
        invalid_intent(dto._intent)


def test_original_worker_peer_persists_variant_selection_before_env_is_filtered(
    tmp_path, monkeypatch
):
    from tests.temporal_deployment_coding_worker_fixture import peer

    peer(tmp_path)
    assert (tmp_path / "capture-coding-cpu-variants").exists()
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU")
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_CPU_VARIANTS")
    with coding_cpu_profile(tmp_path) as installed:
        assert installed
        invalid_intent(dto._intent)
    assert rows(record(tmp_path), "dto._intent")[0]["calls"] == 1


def test_return_time_buckets_reconcile_with_totals_for_body_and_close_analysis(
    tmp_path, monkeypatch
):
    from tests import temporal_coding_cpu_variants as variants

    monkeypatch.setattr(variants, "_BIN_NS", 1, raising=False)
    with coding_cpu_profile(tmp_path):
        invalid_intent(dto._intent)
        time.sleep(0.01)
        invalid_intent(dto._intent)
    value = record(tmp_path)
    assert value["window_started_unix_ns"] > 0
    assert value["bucket_ns"] == 1
    buckets = [r for r in value["return_time_buckets"] if r["function"] == "dto._intent"]
    assert len(buckets) == 2 and len({r["bucket"] for r in buckets}) == 2
    assert buckets[1]["bucket"] - buckets[0]["bucket"] >= 10_000_000
    totals = rows(value, "dto._intent")
    for field in ("calls", "exceptions", "inclusive_cpu_ns", "exclusive_cpu_ns"):
        assert sum(r[field] for r in buckets) == sum(r[field] for r in totals)
    assert all(r["max_call_wall_ns"] >= 0 for r in buckets)
