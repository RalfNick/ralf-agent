"""Best-effort static diagnostics at the existing service fixture failure boundary."""

import asyncio
import json
import os
import re
from pathlib import Path


def _frame(frame, line):
    return {
        "file": Path(frame.f_code.co_filename).name,
        "function": frame.f_code.co_name,
        "line": line,
    }


def save_primary_failure(directory, error):
    try:
        # Read a declared error code only, never instance attributes/messages.
        code = next((vars(cls)["code"] for cls in type(error).__mro__ if "code" in vars(cls)), None)
        if type(code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = None
        frames, trace = [], error.__traceback__
        while trace is not None and len(frames) < 16:
            frames.append(_frame(trace.tb_frame, trace.tb_lineno))
            trace = trace.tb_next
        pending = []
        try:
            tasks = asyncio.all_tasks()
        except RuntimeError:
            tasks = ()
        for task in tasks:
            if task.done():
                continue
            pending.append(
                {
                    "cancelling": task.cancelling(),
                    "frames": [_frame(frame, frame.f_lineno) for frame in task.get_stack(limit=16)],
                }
            )
            if len(pending) == 32:
                break
        value = {
            "error": {"module": type(error).__module__, "type": type(error).__name__, "code": code},
            "frames": frames,
            "pending_tasks": pending,
        }
        path = Path(directory) / "primary-failure.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(value, output, sort_keys=True)
    except BaseException:
        # Failure to diagnose must not replace the fixture's original exception.
        pass
