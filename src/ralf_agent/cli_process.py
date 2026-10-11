"""Bounded trusted POSIX process execution, without a shell or sandbox claim."""

import os
import selectors
import signal
import subprocess
import time

from .tool_json import decode_output
from .tool_sources import ToolSourceError


def stop_process(process):
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        if signum == signal.SIGTERM:
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
    process.wait()
    process.stdin.close()
    process.stdout.close()


def execute(command, cwd, env, payload, timeout, output_limit, stopped):
    process = None
    try:
        if stopped.is_set():
            raise ToolSourceError("CLI invocation stopped before launch")
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE, "input")
            selector.register(process.stdout, selectors.EVENT_READ, "output")
            remaining = memoryview(payload)
            while selector.get_map() or process.poll() is None:
                if stopped.is_set() or time.monotonic() >= deadline:
                    raise ToolSourceError("CLI invocation stopped or timed out")
                for key, _ in selector.select(0.02):
                    try:
                        if key.data == "input":
                            remaining = remaining[os.write(key.fd, remaining) :]
                            if not remaining:
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                        else:
                            chunk = os.read(key.fd, min(65536, output_limit + 1 - len(output)))
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            output.extend(chunk)
                            if len(output) > output_limit:
                                raise ToolSourceError("CLI output exceeds its byte limit")
                    except BlockingIOError:
                        continue
        if process.wait() != 0:
            raise ToolSourceError("CLI process exited unsuccessfully")
        return decode_output(output)
    except (OSError, ValueError, RecursionError):
        raise ToolSourceError("CLI returned invalid JSON or failed process I/O") from None
    finally:
        if process is not None:
            stop_process(process)
