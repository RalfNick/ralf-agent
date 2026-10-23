"""Explicit, bounded synchronous CPU diagnostics for eight original functions."""

import json
import os
import sys
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path


@contextmanager
def coding_cpu_profile(directory):
    """Observe fixed host code only; Sandbox reimports are outside coverage.

    Exclusive time excludes only nested selected targets, not all Python callees.
    The process CPU window covers all threads and is not elapsed wall time.
    """
    try:
        marker = Path(directory) / "capture-coding-cpu"
        monitoring = getattr(sys, "monitoring", None)
        enabled = marker.exists() or os.getenv("RALF_TEST_DEPLOYMENT_CODING_CPU") == "1"
        enabled = enabled and monitoring is not None
        if enabled:
            marker.touch(mode=0o600)
            variants = (
                os.getenv("RALF_TEST_DEPLOYMENT_CODING_CPU_VARIANTS") == "1"
                or (Path(directory) / "capture-coding-cpu-variants").exists()
            )
            from relf_agent.temporal_activities import TemporalRuntime
            from relf_agent.temporal_deployment_coding_validation import (
                CodingValidation,
                _ObservationValidation,
            )
            from relf_agent.temporal_deployment_control_projection import node, registry
            from relf_agent.temporal_session_deployment_dto import validate_intent
            from relf_agent.temporal_session_deployment_verification import SessionControlValidation

            targets = {
                id(function.__code__): (function.__code__, label)
                for label, function in (
                    ("TemporalRuntime.validate_release", TemporalRuntime.validate_release),
                    ("TemporalRuntime._current_manifest", TemporalRuntime._current_manifest),
                    ("SessionControlValidation._check", SessionControlValidation._check),
                    ("CodingValidation._check", CodingValidation._check),
                    ("_ObservationValidation._check", _ObservationValidation._check),
                    ("dto.validate_intent", validate_intent),
                    ("projection.node", node),
                    ("projection.registry", registry),
                )
            }
    except BaseException:
        enabled = False
    if not enabled:
        yield False
        return

    if variants:
        try:
            from tests.temporal_coding_cpu_variants import coding_cpu_variants

            context = coding_cpu_variants(directory, targets)
            installed = context.__enter__()
        except BaseException:
            yield False
            return
        try:
            yield installed
        finally:
            with suppress(BaseException):
                context.__exit__(*sys.exc_info())
        return

    active, installed, faults, lost = False, False, 0, 0
    stacks, counts, callbacks, local_codes = {}, {}, {}, []
    tool, tool_name = None, "ralf-test-coding-cpu-" + str(id(stacks))
    lock = threading.Lock()

    def started(code, offset):
        nonlocal faults, active, lost
        if id(code) not in targets or not active:
            return None
        try:
            cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
            thread = threading.get_ident()
            with lock:
                if thread not in stacks:
                    if len(stacks) >= 64:
                        lost += 1
                        return None
                    stacks[thread] = []
                stack = stacks[thread]
                if len(stack) >= 128:
                    lost += 1
                    active = False
                    return None
                label = targets[id(code)][1]
                key = thread, label
                if key not in counts:
                    counts[key] = {
                        "thread_id": thread,
                        "function": label,
                        "calls": 0,
                        "exceptions": 0,
                        "inclusive_cpu_ns": 0,
                        "exclusive_cpu_ns": 0,
                        "inclusive_wall_ns": 0,
                        "exclusive_wall_ns": 0,
                    }
                stack.append([code, cpu, wall, 0, 0])
        except BaseException:
            faults += 1
            active = False
        return None

    def finish(code, exceptional):
        nonlocal faults, active
        try:
            cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
            thread = threading.get_ident()
            with lock:
                stack = stacks.get(thread)
                if not stack or stack[-1][0] is not code:
                    faults += 1
                    active = False
                    return
                _, begin_cpu, begin_wall, child_cpu, child_wall = stack.pop()
                elapsed_cpu, elapsed_wall = cpu - begin_cpu, wall - begin_wall
                row = counts[thread, targets[id(code)][1]]
                row["calls"] += 1
                row["exceptions"] += int(exceptional)
                row["inclusive_cpu_ns"] += elapsed_cpu
                row["inclusive_wall_ns"] += elapsed_wall
                row["exclusive_cpu_ns"] += max(0, elapsed_cpu - child_cpu)
                row["exclusive_wall_ns"] += max(0, elapsed_wall - child_wall)
                if stack:
                    stack[-1][3] += elapsed_cpu
                    stack[-1][4] += elapsed_wall
        except BaseException:
            faults += 1
            active = False

    def returned(code, offset, result):
        if id(code) in targets and active:
            finish(code, False)
        return None

    def unwound(code, offset, exception):
        # UNWIND cannot be local in Python 3.12. All foreign code takes only
        # this membership branch: no clocks, arguments, exception inspection/IO.
        if id(code) not in targets:
            return None
        if active:
            finish(code, True)
        return None

    def cleanup():
        if tool is None:
            return
        try:
            if monitoring.get_tool(tool) != tool_name:
                return
        except BaseException:
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
            if (
                monitoring.get_tool(candidate) is None
                and monitoring.get_events(candidate) == 0
                and all(
                    monitoring.get_local_events(candidate, code) == 0
                    for code, _ in targets.values()
                )
            ):
                try:
                    monitoring.use_tool_id(candidate, tool_name)
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
                previous = monitoring.register_callback(tool, event, callback)
                callbacks[event] = previous
                if previous is not None:
                    raise RuntimeError("Foreign callback remains installed")
            for code, _ in targets.values():
                local_codes.append(code)
                monitoring.set_local_events(
                    tool, code, monitoring.events.PY_START | monitoring.events.PY_RETURN
                )
            monitoring.set_events(tool, monitoring.events.PY_UNWIND)
            begin_cpu, begin_wall = time.process_time_ns(), time.perf_counter_ns()
            active = installed = True
    except BaseException:
        active = False
        cleanup()

    try:
        yield installed
    finally:
        process_cpu_ns, wall_ns = 0, 0
        if installed:
            try:
                process_cpu_ns = time.process_time_ns() - begin_cpu
                wall_ns = time.perf_counter_ns() - begin_wall
            except BaseException:
                faults += 1
        active = False
        cleanup()
        if installed:
            try:
                with lock:
                    record = {
                        "version": 1,
                        "pid": os.getpid(),
                        "faults": faults,
                        "coverage": "fixed host code objects only; sandbox reimports are not observed",
                        "process_cpu_ns": process_cpu_ns,
                        "wall_ns": wall_ns,
                        "incomplete_calls": lost + sum(len(stack) for stack in stacks.values()),
                        "functions": list(counts.values()),
                    }
                data = (json.dumps(record, separators=(",", ":")) + "\n").encode()
                descriptor = os.open(
                    Path(directory) / "cpu-timing.jsonl",
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
                    0o600,
                )
                try:
                    os.fchmod(descriptor, 0o600)
                    os.write(descriptor, data)
                finally:
                    os.close(descriptor)
            except BaseException:
                pass  # Diagnostics never replace a business return/exception.
