"""Fixed-command JSON ToolSource, using original actual-thread ownership."""

import copy
import os
import threading
from pathlib import Path

from jsonschema import Draft202012Validator

from . import cli_process
from .errors import DefinitionMismatch, ValidationError
from .tool_sources import ToolDescriptor, ToolSourceError
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical, digest


class CLIToolSource:
    def __init__(
        self,
        descriptor,
        command,
        *,
        version,
        cwd=None,
        env=None,
        timeout=30,
        max_input_bytes=1048576,
        max_output_bytes=1048576,
    ):
        if os.name != "posix":
            raise ValidationError("CLI process tools require POSIX")
        if not isinstance(descriptor, ToolDescriptor):
            raise ValidationError("CLI source requires one explicit ToolDescriptor")
        if (
            type(command) not in (tuple, list)
            or not command
            or any(type(part) is not str or "\x00" in part for part in command)
            or not command[0]
            or not Path(command[0]).is_absolute()
        ):
            raise ValidationError("CLI command requires fixed argv and an absolute executable")
        if type(version) is not str or not version.strip():
            raise ValidationError("CLI source requires an explicit behavior version")
        if cwd is not None and (
            not isinstance(cwd, (str, Path)) or not str(cwd) or "\x00" in str(cwd)
        ):
            raise ValidationError("CLI cwd requires a nonempty filesystem path")
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValidationError("CLI timeout must be finite seconds in (0,300]")
        for value in (max_input_bytes, max_output_bytes):
            if type(value) is not int or not 1 <= value <= 16777216:
                raise ValidationError("CLI byte limits must be integers in [1,16777216]")
        if env is not None and type(env) is not dict:
            raise ValidationError("CLI environment requires an explicit dictionary")
        values = {} if env is None else dict(env)
        if any(
            type(k) is not str
            or not k
            or "=" in k
            or "\x00" in k
            or type(v) is not str
            or "\x00" in v
            for k, v in values.items()
        ):
            raise ValidationError("CLI environment requires explicit string fields")
        self._descriptor = ToolDescriptor(**descriptor.to_dict())
        self._command, self._version = tuple(command), version
        self._cwd, self._env = str(Path(Path.cwd() if cwd is None else cwd).resolve()), values
        self._timeout, self._input_limit, self._output_limit = (
            timeout,
            max_input_bytes,
            max_output_bytes,
        )
        self._lock, self._stops, self._closing = threading.Lock(), set(), False
        self._tracker = ThreadExecutionTracker()
        self._identity = canonical(self.identity)

    @property
    def identity(self):
        return {
            "kind": "cli-json-tool-source",
            "version": "1",
            "behavior_version": self._version,
            "command": list(self._command),
            "cwd": self._cwd,
            "environment_keys": sorted(self._env),
            "environment_fingerprint": digest(self._env),
            "timeout": self._timeout,
            "max_input_bytes": self._input_limit,
            "max_output_bytes": self._output_limit,
            "tool": self._descriptor.to_dict(),
        }

    def _check(self):
        if canonical(self.identity) != self._identity:
            raise DefinitionMismatch("Original CLI configuration changed")
        if self._closing:
            raise ToolSourceError("CLI tool source is closing or closed")

    async def list_tools(self):
        with self._lock:
            self._check()
            return (ToolDescriptor(**self._descriptor.to_dict()),)

    def _execute(self, token, payload, stopped):
        if token is not None and not self._tracker._begin(token):
            return None
        try:
            result = cli_process.execute(
                self._command,
                self._cwd,
                self._env,
                payload,
                self._timeout,
                self._output_limit,
                stopped,
            )
            if self._descriptor.output_schema is not None and not Draft202012Validator(
                self._descriptor.output_schema
            ).is_valid(result):
                raise ToolSourceError("CLI output differs from the pinned Schema")
            return result
        finally:
            if token is not None:
                self._tracker._finish(token)

    async def call_tool(self, descriptor, arguments, context):
        if (
            not isinstance(descriptor, ToolDescriptor)
            or descriptor.to_dict() != self._descriptor.to_dict()
        ):
            raise DefinitionMismatch("CLI invocation differs from its pinned descriptor")
        if not isinstance(arguments, dict) or not Draft202012Validator(
            self._descriptor.input_schema
        ).is_valid(arguments):
            raise ValidationError("CLI arguments differ from the pinned Schema")
        try:
            payload = (canonical(copy.deepcopy(arguments)) + "\n").encode("utf-8")
        except UnicodeError:
            raise ValidationError("CLI input must be valid UTF-8 JSON") from None
        if len(payload) > self._input_limit:
            raise ValidationError("CLI input exceeds its byte limit")
        stopped = threading.Event()
        ambient = current_thread_tracker.get()
        tracker = ambient or self._tracker
        with self._lock:
            self._check()
            self._stops.add(stopped)
            token = (
                self._tracker._register(current_thread_group.get()) if ambient is not None else None
            )
        try:
            result = await tracker.run(
                self._execute, token, payload, stopped, group=current_thread_group.get()
            )
            self._check()
            return copy.deepcopy(result)
        except BaseException:
            stopped.set()
            if token is not None:
                self._tracker._withdraw_pending(token)
            raise
        finally:
            with self._lock:
                self._stops.discard(stopped)

    async def wait_for_calls(self):
        await self._tracker.drain()

    async def aclose(self):
        with self._lock:
            self._closing = True
            for stopped in self._stops:
                stopped.set()
        await self.wait_for_calls()
