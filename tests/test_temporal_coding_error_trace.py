"""RAISE-only private diagnostics must never alter original execution semantics."""

import json
import sys
import threading
import time

import pytest

from relf_agent import errors
from tests import temporal_deployment_coding_worker_fixture as fixture

MONITORING = getattr(sys, "monitoring", None)


def source_raise(line=1, *, filename=None):
    namespace = {}
    exec(
        compile(
            "\n" * line + "def traced_source(error):\n raise error\n",
            filename or errors.__file__,
            "exec",
        ),
        namespace,
    )
    return namespace["traced_source"]


def caught(function, error):
    try:
        function(error)
    except BaseException as actual:
        assert actual is error
    else:
        raise AssertionError("Original exception must propagate unchanged")


def tools():
    return [(i, MONITORING.get_tool(i), MONITORING.get_events(i)) for i in range(6)]


@pytest.fixture(autouse=True)
def clean_opt_in(monkeypatch):
    monkeypatch.delenv("RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE", raising=False)


@pytest.fixture
def monitoring():
    if MONITORING is None:
        pytest.skip("Python 3.12 monitoring diagnostic unavailable; no trace fallback")
    before = tools()
    yield MONITORING
    assert tools() == before


def test_default_off_preserves_exception_without_installing_any_hook(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Must not install a Python call tracer")

    monkeypatch.setattr(sys, "settrace", forbidden)
    monkeypatch.setattr(threading, "settrace", forbidden)
    error = RuntimeError("original body failure")
    with pytest.raises(RuntimeError) as actual:
        with fixture.definition_mismatch_trace(tmp_path) as installed:
            assert installed is False
            raise error
    assert actual.value is error and list(tmp_path.iterdir()) == []


def test_python_without_monitoring_explicitly_skips_instead_of_trace_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE", "1")
    monkeypatch.delattr(sys, "monitoring", raising=False)

    def forbidden(*args):
        raise AssertionError("No fallback call tracer")

    monkeypatch.setattr(sys, "settrace", forbidden)
    monkeypatch.setattr(threading, "settrace", forbidden)
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is False
        caught(source_raise(), errors.DefinitionMismatch("original error"))


def test_only_raise_event_and_no_sys_thread_trace_mutation(tmp_path, monkeypatch, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    calls = []

    class Spy:
        def __getattr__(self, name):
            return getattr(monitoring, name)

        def set_events(self, tool, event):
            calls.append(("events", tool, event))
            return monitoring.set_events(tool, event)

        def register_callback(self, tool, event, callback):
            calls.append(("callback", tool, event, callback is None))
            return monitoring.register_callback(tool, event, callback)

    monkeypatch.setattr(sys, "monitoring", Spy())

    def forbidden(*args):
        raise AssertionError("Must not install any per-call tracer")

    monkeypatch.setattr(sys, "settrace", forbidden)
    monkeypatch.setattr(threading, "settrace", forbidden)
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is True
        caught(source_raise(), errors.DefinitionMismatch("original error"))
    assert [row[2] for row in calls if row[0] == "events"] == [monitoring.events.RAISE, 0]
    assert [(row[2], row[3]) for row in calls if row[0] == "callback"] == [
        (monitoring.events.RAISE, False),
        (monitoring.events.RAISE, True),
    ]


def test_enabled_monitor_preserves_exact_exception_and_safe_line_location(
    tmp_path, monkeypatch, monitoring
):
    monkeypatch.setenv("RALF_TEST_DEPLOYMENT_CODING_ERROR_TRACE", "1")
    secret = "postgresql://private:user-password@host/db sk-fixture-secret"
    error = errors.DefinitionMismatch(secret)
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is True
        caught(source_raise(), error)
    path = tmp_path / "definition-mismatch-locations.jsonl"
    text = path.read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    assert secret not in text and "password" not in text and "postgresql" not in text
    assert len(rows) == 1 and set(rows[0]) == {
        "pid",
        "basename",
        "function",
        "line",
        "exception_module",
        "exception_class",
        "monotonic",
    }
    assert (rows[0]["exception_module"], rows[0]["exception_class"]) == (
        "relf_agent.errors",
        "DefinitionMismatch",
    )
    assert (
        rows[0]["basename"] == "errors.py"
        and rows[0]["function"] == "traced_source"
        and rows[0]["line"] == 3
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_unrelated_expected_exceptions_do_not_consume_location_limit(tmp_path, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    with fixture.definition_mismatch_trace(tmp_path):
        for line in range(70):
            for error in (StopIteration(), GeneratorExit(), LookupError("private")):
                caught(source_raise(line), error)
        caught(source_raise(), errors.DefinitionMismatch("private"))
        caught(
            source_raise(filename=str(tmp_path / "outside.py")),
            errors.ValidationError("private"),
        )
    rows = [
        json.loads(line)
        for line in (tmp_path / "definition-mismatch-locations.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["exception_class"] == "DefinitionMismatch"


@pytest.mark.parametrize(
    "report",
    [
        {"coding_resource": "retirement_unconfirmed"},
        {"coding_transport": "cleanup_unconfirmed"},
        {"coding_resource": "cleanup_still_owned"},
    ],
)
def test_original_close_report_whitelist_and_monotonic_time(tmp_path, monitoring, report):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    error = errors.CloseIncomplete(report)
    before = time.monotonic()
    with fixture.definition_mismatch_trace(tmp_path):
        caught(source_raise(), error)
    after = time.monotonic()
    row = json.loads((tmp_path / "definition-mismatch-locations.jsonl").read_text())
    assert row["report"] == report
    assert before <= row["monotonic"] <= after
    assert error.report is report


@pytest.mark.parametrize(
    "report",
    [
        {"coding_resource": "private-secret"},
        {"coding_resource": "retirement_unconfirmed", "request": "private-secret"},
        {"deployment_coding": [{"request": "private-secret"}]},
        ["private-secret"],
        "private-secret",
    ],
)
def test_unapproved_close_report_is_not_serialized(tmp_path, monitoring, report):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    error = errors.CloseIncomplete(report)
    with fixture.definition_mismatch_trace(tmp_path):
        caught(source_raise(), error)
    text = (tmp_path / "definition-mismatch-locations.jsonl").read_text()
    assert "private-secret" not in text
    assert "report" not in json.loads(text)


def test_different_safe_reports_at_same_raise_location_remain_distinct(tmp_path, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    function = source_raise()
    reports = [
        {"coding_resource": "retirement_unconfirmed"},
        {"coding_transport": "cleanup_unconfirmed"},
    ]
    with fixture.definition_mismatch_trace(tmp_path):
        for report in reports:
            caught(function, errors.CloseIncomplete(report))
    rows = [
        json.loads(line)
        for line in (tmp_path / "definition-mismatch-locations.jsonl").read_text().splitlines()
    ]
    assert [row["report"] for row in rows] == reports
    assert rows[0]["line"] == rows[1]["line"]
    assert rows[0]["monotonic"] <= rows[1]["monotonic"]


def test_monitoring_preserves_original_bytecode_and_executable_digest(tmp_path, monitoring):
    from relf_agent import component_fingerprint as fingerprint
    from relf_agent.types import digest

    function = source_raise()

    def snapshot():
        code = function.__code__
        return (
            fingerprint.executable_digest(function),
            digest(
                {"algorithm": "python-code-v1", "function": fingerprint._function(function, set())}
            ),
            code.co_code,
            code.co_consts,
            code.co_names,
            code.co_varnames,
            code.co_flags,
            code.co_exceptiontable,
            code.co_linetable,
            tuple(code.co_lines()),
        )

    before = snapshot()
    (tmp_path / "trace-coding-definition-mismatch").touch()
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is True
        caught(function, errors.DefinitionMismatch("private"))
        assert snapshot() == before
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["ralf", "validation", "runner", "unknown", "rpc"])
def test_allowed_error_classes_log_static_type_only_and_preserve_instance(
    tmp_path, monitoring, kind
):
    from relf_agent.codex_rpc import CodexRPCError
    from relf_agent.codex_runner import RunnerOutcomeUnknown, RunnerUnavailable

    secret = "postgresql://private:user-password@host/db sk-fixture-secret"
    exception = {
        "ralf": lambda: errors.RalfError(secret),
        "validation": lambda: errors.ValidationError(secret),
        "runner": lambda: RunnerUnavailable(secret),
        "unknown": lambda: RunnerOutcomeUnknown(secret),
        "rpc": lambda: CodexRPCError(secret),
    }[kind]()
    (tmp_path / "trace-coding-definition-mismatch").touch()
    with fixture.definition_mismatch_trace(tmp_path):
        caught(source_raise(), exception)
    text = (tmp_path / "definition-mismatch-locations.jsonl").read_text()
    assert secret not in text and "password" not in text
    row = json.loads(text)
    assert row["exception_module"] == type(exception).__module__
    assert row["exception_class"] == type(exception).__name__


def test_existing_tool_with_events_is_untouched_while_another_slot_is_used(tmp_path, monitoring):
    free = [tool for tool in range(6) if monitoring.get_tool(tool) is None]
    if len(free) < 2:
        pytest.skip("Requires two free diagnostic slots")
    tool = 3 if 3 in free else free[0]
    monitoring.use_tool_id(tool, "existing-tool")
    monitoring.set_events(tool, monitoring.events.PY_START)
    try:
        (tmp_path / "trace-coding-definition-mismatch").touch()
        with fixture.definition_mismatch_trace(tmp_path) as installed:
            assert installed is True
            assert monitoring.get_tool(tool) == "existing-tool"
            assert monitoring.get_events(tool) == monitoring.events.PY_START
        assert monitoring.get_tool(tool) == "existing-tool"
        assert monitoring.get_events(tool) == monitoring.events.PY_START
    finally:
        monitoring.set_events(tool, 0)
        monitoring.free_tool_id(tool)


def test_64_unique_locations_and_no_per_location_disable(tmp_path, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    with fixture.definition_mismatch_trace(tmp_path):
        for line in range(70):
            caught(source_raise(line), errors.DefinitionMismatch("private"))
            caught(source_raise(line), errors.DefinitionMismatch("private"))
    rows = [
        json.loads(line)
        for line in (tmp_path / "definition-mismatch-locations.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 64
    assert len({(r["basename"], r["function"], r["line"]) for r in rows}) == 64


def test_existing_tool_ids_are_not_taken_and_all_occupied_means_skip(tmp_path, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    owned = []
    try:
        for tool in range(6):
            if monitoring.get_tool(tool) is None:
                monitoring.use_tool_id(tool, "other-tool-" + str(tool))
                owned.append(tool)
        before = tools()
        with fixture.definition_mismatch_trace(tmp_path) as installed:
            assert installed is False
            caught(source_raise(), errors.DefinitionMismatch("original"))
        assert tools() == before
    finally:
        for tool in owned:
            monitoring.free_tool_id(tool)


def test_worker_thread_raises_are_observed_and_no_hook_survives(tmp_path, monitoring):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    before = tools()
    results = []

    def child():
        caught(source_raise(), errors.DefinitionMismatch("private"))
        results.append(sys.gettrace())

    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is True
        thread = threading.Thread(target=child)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert results == [None] and tools() == before
    assert (tmp_path / "definition-mismatch-locations.jsonl").exists()


@pytest.mark.parametrize("port", ["open", "fchmod", "write"])
def test_diagnostic_io_failure_preserves_original_exception(
    tmp_path, monkeypatch, monitoring, port
):
    (tmp_path / "trace-coding-definition-mismatch").touch()

    def unavailable(*args, **options):
        raise OSError("private sk-secret")

    monkeypatch.setattr(fixture.os, port, unavailable)
    with fixture.definition_mismatch_trace(tmp_path):
        caught(source_raise(), errors.DefinitionMismatch("original error"))


def test_monitoring_and_timing_remain_independent(tmp_path, monitoring):
    (tmp_path / "capture-coding-timing").touch()
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is False
    (tmp_path / "capture-coding-timing").unlink()
    (tmp_path / "trace-coding-definition-mismatch").touch()
    with fixture.definition_mismatch_trace(tmp_path) as installed:
        assert installed is True and not fixture.SDKTiming(tmp_path).enabled


@pytest.mark.parametrize("failure", ["set_events", "register_callback", "free_tool_id"])
def test_cleanup_failure_cannot_replace_body_error_and_other_cleanup_still_runs(
    tmp_path, monkeypatch, monitoring, failure
):
    (tmp_path / "trace-coding-definition-mismatch").touch()
    calls = []

    class Spy:
        def __getattr__(self, name):
            return getattr(monitoring, name)

        def set_events(self, tool, event):
            monitoring.set_events(tool, event)
            if event == 0:
                calls.append("set_events")
                if failure == "set_events":
                    raise OSError("private")

        def register_callback(self, tool, event, callback):
            old = monitoring.register_callback(tool, event, callback)
            if callback is None:
                calls.append("register_callback")
                if failure == "register_callback":
                    raise OSError("private")
            return old

        def free_tool_id(self, tool):
            monitoring.free_tool_id(tool)
            calls.append("free_tool_id")
            if failure == "free_tool_id":
                raise OSError("private")

    monkeypatch.setattr(sys, "monitoring", Spy())
    error = RuntimeError("original business exception")
    with pytest.raises(RuntimeError) as actual:
        with fixture.definition_mismatch_trace(tmp_path) as installed:
            assert installed is True
            raise error
    assert actual.value is error and calls == ["set_events", "register_callback", "free_tool_id"]
