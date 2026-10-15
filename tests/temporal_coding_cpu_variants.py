"""Bounded code-copy telemetry for one opt-in test Worker; no execution authority."""

import json
import os
import sys
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from types import CodeType

_MAX_CODES = 256
_MAX_THREADS = 64
_MAX_DEPTH = 128
_MAX_ROWS = 2048
_MAX_BUCKET_ROWS = 2048
_MAX_BYTES = 1048576
_BIN_NS = 10_000_000_000


def _extra_targets():
    from ralf_agent import codex_runner, runner_journal_state
    from ralf_agent import temporal_coding_composition_protocol as composition
    from ralf_agent import temporal_coding_protocol as coding
    from ralf_agent import temporal_session_deployment_dto as dto
    from ralf_agent.postgres_runner_journal import PostgresRunnerJournal

    return (
        ("dto._intent", dto._intent),
        ("dto.validate_origin", dto.validate_origin),
        ("Runner._check_root", codex_runner.CodexCodingRunner._check_root),
        ("Runner._capacity_implementation", codex_runner._capacity_implementation),
        ("Runner._environment_implementation", codex_runner._environment_implementation),
        ("RunnerJournal._ready", PostgresRunnerJournal._ready),
        ("RunnerJournal._key", PostgresRunnerJournal._key),
        ("RunnerJournal._json", runner_journal_state._json),
        ("coding.validate_protocol", coding.validate_protocol),
        ("composition.validate_protocol", composition.validate_protocol),
    )


def _location(code):
    return code.co_filename, code.co_firstlineno, code.co_name, code.co_qualname


@contextmanager
def coding_cpu_variants(directory, original_targets):
    monitoring = sys.monitoring
    targets = dict(original_targets)
    targets.update({id(f.__code__): (f.__code__, label) for label, f in _extra_targets()})
    originals = tuple(targets.values())
    locations = {_location(code): (code, label) for code, label in originals}
    origins = {id(code): "original-code" for code, _ in originals}
    local_codes, callbacks, stacks, counts = [], {}, {}, {}
    buckets = {}
    active = installed = False
    faults = lost = 0
    first_fault_reason = None
    tool = None
    name = "ralf-test-coding-cpu-v2-" + str(id(targets))
    lock = threading.Lock()

    def fail(reason):
        nonlocal faults, active, first_fault_reason
        faults += 1
        if first_fault_reason is None:
            first_fault_reason = reason
        active = False

    def started(code, offset):
        nonlocal lost
        if not active:
            return None
        try:
            entry = targets.get(id(code))
            if entry is None:
                original = locations.get(_location(code)) if type(code) is CodeType else None
                if original is None or code != original[0]:
                    return monitoring.DISABLE
                if len(targets) >= _MAX_CODES:
                    lost += 1
                    fail("code_limit")
                    return None
                targets[id(code)] = entry = (code, original[1])
                origins[id(code)] = "equivalent-code-copy"
                local_codes.append(code)  # Clean even if registration fails part way.
                monitoring.set_local_events(
                    tool, code, monitoring.events.PY_START | monitoring.events.PY_RETURN
                )
            cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
            thread, label = threading.get_ident(), entry[1]
            key = thread, label, origins[id(code)]
            with lock:
                if thread not in stacks and len(stacks) >= _MAX_THREADS:
                    lost += 1
                    fail("thread_limit")
                    return None
                if key not in counts and len(counts) >= _MAX_ROWS:
                    lost += 1
                    fail("row_limit")
                    return None
                stack = stacks.setdefault(thread, [])
                if len(stack) >= _MAX_DEPTH:
                    lost += 1
                    fail("depth_limit")
                    return None
                counts.setdefault(
                    key,
                    {
                        "thread_id": thread,
                        "function": label,
                        "origin": origins[id(code)],
                        "calls": 0,
                        "exceptions": 0,
                        "inclusive_cpu_ns": 0,
                        "exclusive_cpu_ns": 0,
                        "inclusive_wall_ns": 0,
                        "exclusive_wall_ns": 0,
                    },
                )
                stack.append((code, key, cpu, wall, [0, 0]))
        except BaseException:
            fail("start_error")
        return None

    def finish(code, exceptional):
        try:
            cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
            with lock:
                thread = threading.get_ident()
                stack = stacks.get(thread)
                if not stack or stack[-1][0] is not code:
                    fail("stack_mismatch")
                    return
                _, key, begin_cpu, begin_wall, children = stack.pop()
                if not stack:
                    del stacks[thread]
                elapsed = cpu - begin_cpu, wall - begin_wall
                if any(
                    x < 0 or child < 0 or child > x
                    for x, child in zip(elapsed, children, strict=True)
                ):
                    fail("call_clock")
                    return
                row = counts[key]
                row["calls"] += 1
                row["exceptions"] += int(exceptional)
                for index, clock in enumerate(("cpu", "wall")):
                    row[f"inclusive_{clock}_ns"] += elapsed[index]
                    row[f"exclusive_{clock}_ns"] += elapsed[index] - children[index]
                    if stack:
                        stack[-1][4][index] += elapsed[index]
                bucket = (wall - window_wall) // _BIN_NS
                bucket_key = bucket, key[1], key[2]
                if bucket_key not in buckets and len(buckets) >= _MAX_BUCKET_ROWS:
                    fail("bucket_limit")
                    return
                summary = buckets.setdefault(
                    bucket_key,
                    {
                        "bucket": bucket,
                        "function": key[1],
                        "origin": key[2],
                        "calls": 0,
                        "exceptions": 0,
                        "inclusive_cpu_ns": 0,
                        "exclusive_cpu_ns": 0,
                        "max_call_wall_ns": 0,
                    },
                )
                summary["calls"] += 1
                summary["exceptions"] += int(exceptional)
                summary["inclusive_cpu_ns"] += elapsed[0]
                summary["exclusive_cpu_ns"] += elapsed[0] - children[0]
                summary["max_call_wall_ns"] = max(summary["max_call_wall_ns"], elapsed[1])
        except BaseException:
            fail("finish_error")

    def returned(code, offset, result):
        if active and id(code) in targets:
            finish(code, False)

    def unwound(code, offset, exception):
        if active and id(code) in targets:
            finish(code, True)

    def cleanup():
        if tool is None or monitoring.get_tool(tool) != name:
            return
        with suppress(BaseException):
            monitoring.set_events(tool, 0)
        for code in local_codes:
            with suppress(BaseException):
                monitoring.set_local_events(tool, code, 0)
        for event, previous in callbacks.items():
            with suppress(BaseException):
                monitoring.register_callback(tool, event, previous)
        with suppress(BaseException):
            monitoring.free_tool_id(tool)

    try:
        for candidate in (3, 4, 0, 1, 2, 5):
            if monitoring.get_tool(candidate) is None and monitoring.get_events(candidate) == 0:
                try:
                    monitoring.use_tool_id(candidate, name)
                except ValueError:
                    continue
                tool = candidate
                break
        if tool is not None:
            for event, callback in (
                (monitoring.events.PY_START, started),
                (monitoring.events.PY_RETURN, returned),
                (monitoring.events.PY_UNWIND, unwound),
            ):
                callbacks[event] = monitoring.register_callback(tool, event, callback)
                if callbacks[event] is not None:
                    raise RuntimeError("Foreign callback remains installed")
            for code, _ in originals:
                local_codes.append(code)
                monitoring.set_local_events(
                    tool, code, monitoring.events.PY_START | monitoring.events.PY_RETURN
                )
            window_cpu, window_wall = time.process_time_ns(), time.perf_counter_ns()
            begin_unix = time.time_ns()
            active = installed = True
            monitoring.set_events(tool, monitoring.events.PY_START | monitoring.events.PY_UNWIND)
    except BaseException:
        fail("setup_error")
        cleanup()
        installed = False
    try:
        yield installed
    finally:
        active = False
        with suppress(BaseException):
            cleanup()
        if installed:
            try:
                cpu, wall = (
                    time.process_time_ns() - window_cpu,
                    time.perf_counter_ns() - window_wall,
                )
                incomplete = lost + sum(len(stack) for stack in stacks.values())
                valid = (
                    faults == incomplete == 0
                    and cpu >= 0
                    and wall >= 0
                    and sum(r["exclusive_cpu_ns"] for r in counts.values()) <= cpu
                )
                if not valid and first_fault_reason is None:
                    first_fault_reason = (
                        "incomplete_calls"
                        if incomplete
                        else "window_clock"
                        if cpu < 0 or wall < 0
                        else "exclusive_cpu"
                    )
                record = {
                    "version": 2,
                    "pid": os.getpid(),
                    "coverage": "fixed synchronous targets and location/structure-equivalent code copies; telemetry only",
                    "timing_valid": valid,
                    "faults": faults,
                    "first_fault_reason": first_fault_reason,
                    "incomplete_calls": incomplete,
                    "process_cpu_ns": cpu,
                    "wall_ns": wall,
                    "window_started_unix_ns": begin_unix,
                    "bucket_ns": _BIN_NS,
                    "bucket_attribution": "assigned at synchronous return; boundary uncertainty includes max_call_wall_ns; not exact critical-path time",
                    "return_time_buckets": list(buckets.values()),
                    "observed_code_objects": len(targets),
                    "equivalent_code_copies": len(targets) - len(originals),
                    "functions": list(counts.values()),
                }
                data = (json.dumps(record, separators=(",", ":")) + "\n").encode()
                if len(data) > _MAX_BYTES:
                    raise ValueError("CPU diagnostic output exceeds its bound")
                fd = os.open(
                    Path(directory) / "cpu-timing.jsonl",
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
                    0o600,
                )
                try:
                    os.fchmod(fd, 0o600)
                    os.write(fd, data)
                finally:
                    os.close(fd)
            except BaseException:
                pass
