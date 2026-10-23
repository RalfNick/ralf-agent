"""Workspace reads managed through the original ToolSource and thread owners."""

import copy
import hashlib
import inspect
import threading

from jsonschema import Draft202012Validator

from .errors import DefinitionMismatch, RalfError, ValidationError
from .ports import is_sync_callable
from .tool_sources import ToolDescriptor, _identity
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical
from .workspace import WorkspaceError, _bound, _path, _utf8


def _record(value, path):
    if (
        type(value) is not dict
        or set(value) != {"path", "kind", "size", "version"}
        or value["path"] != path
        or type(value["version"]) is not str
        or not value["version"]
        or value["kind"] not in {"file", "directory"}
        or (value["kind"] == "directory" and value["size"] is not None)
        or (value["kind"] == "file" and (type(value["size"]) is not int or value["size"] < 0))
    ):
        raise WorkspaceError("Workspace returned an invalid entry snapshot")
    _path(path, directory=True)


def _adopt(name, arguments, result, max_bytes, max_entries):
    if inspect.iscoroutine(result) or inspect.isgenerator(result):
        result.close()
    if type(result) is not dict:
        raise WorkspaceError("Workspace returned an invalid snapshot")
    try:
        if name == "workspace_stat":
            _record(result, arguments["path"])
        elif name == "workspace_list":
            path = arguments["directory"]
            if (
                set(result) != {"path", "entries"}
                or result["path"] != path
                or type(result["entries"]) is not list
                or len(result["entries"]) > max_entries
            ):
                raise WorkspaceError("Workspace returned an invalid directory snapshot")
            prefix = path + "/" if path else ""
            names = []
            for record in result["entries"]:
                if type(record) is not dict or type(record.get("path")) is not str:
                    raise WorkspaceError("Workspace returned an invalid directory entry")
                address = record["path"]
                if (
                    not address.startswith(prefix)
                    or not address[len(prefix) :]
                    or "/" in address[len(prefix) :]
                ):
                    raise WorkspaceError("Workspace directory entry is outside its selected path")
                _record(record, address)
                names.append(address)
            if names != sorted(set(names)):
                raise WorkspaceError("Workspace directory entries require unique sorted paths")
        else:
            if (
                set(result) != {"path", "text", "bytes", "sha256", "version"}
                or result["path"] != arguments["path"]
                or type(result["version"]) is not str
                or not result["version"]
            ):
                raise WorkspaceError("Workspace returned an invalid text snapshot")
            data = _utf8(result["text"], "Workspace text snapshot", max_bytes=max_bytes)
            if (
                b"\x00" in data
                or len(data) > max_bytes
                or type(result["bytes"]) is not int
                or result["bytes"] != len(data)
                or result["sha256"] != hashlib.sha256(data).hexdigest()
            ):
                raise WorkspaceError(
                    "Workspace text snapshot differs from its byte/digest allowance"
                )
        canonical(result).encode("utf-8")
    except (ValidationError, UnicodeError, ValueError, RecursionError, TypeError):
        raise WorkspaceError("Workspace returned invalid finite UTF-8 snapshot data") from None
    return copy.deepcopy(result)


class WorkspaceToolSource:
    def __init__(self, workspace, *, version, max_entries=100, max_bytes=1048576):
        if not _utf8(version, "Workspace tool version").strip():
            raise ValidationError("Workspace source requires an explicit behavior version")
        _bound(max_entries, 1000, "entry")
        _bound(max_bytes, 16777216, "byte")
        if any(
            not is_sync_callable(getattr(workspace, name, None))
            for name in ("stat", "list", "read_text", "close")
        ):
            raise ValidationError("Workspace source requires synchronous WorkspacePort methods")
        _identity(workspace)
        self._workspace, self._version = workspace, version
        self._max_entries, self._max_bytes = max_entries, max_bytes
        self._lock, self._closing = threading.Lock(), False
        self._tracker = ThreadExecutionTracker()
        self._descriptors = tuple(
            ToolDescriptor(
                name,
                description,
                {
                    "type": "object",
                    "properties": {field: {"type": "string"}},
                    "required": [field],
                    "additionalProperties": False,
                },
            )
            for name, field, description in (
                (
                    "workspace_stat",
                    "path",
                    "Read metadata for an allowed workspace-relative file or directory.",
                ),
                (
                    "workspace_list",
                    "directory",
                    "List a bounded complete allowed directory view; empty directory selects root.",
                ),
                (
                    "workspace_read_text",
                    "path",
                    "Read a bounded UTF-8 file snapshot with content digest.",
                ),
            )
        )
        self._identity = canonical(self.identity)

    @property
    def identity(self):
        return {
            "kind": "workspace-tool-source",
            "version": "1",
            "behavior_version": self._version,
            "workspace": _identity(self._workspace),
            "max_entries": self._max_entries,
            "max_bytes": self._max_bytes,
        }

    def _check(self):
        if canonical(self.identity) != self._identity:
            raise DefinitionMismatch("Original Workspace tool configuration changed")
        if self._closing:
            raise WorkspaceError("Workspace tool source is closing or closed")

    async def list_tools(self):
        with self._lock:
            self._check()
            return tuple(ToolDescriptor(**item.to_dict()) for item in self._descriptors)

    def validate_tool_policy(self, descriptor, policy):
        if (
            type(policy.effect) is not str
            or policy.effect != "read_only"
            or policy.effect_key_argument is not None
            or policy.reconciler is not None
        ):
            raise ValidationError(
                "Workspace tools require read_only without effect key or reconciler"
            )

    def _execute(self, token, name, arguments, scope):
        if token is not None and not self._tracker._begin(token):
            return None
        try:
            if name == "workspace_stat":
                result = self._workspace.stat(scope, arguments["path"])
            elif name == "workspace_list":
                result = self._workspace.list(
                    scope, arguments["directory"], max_entries=self._max_entries
                )
            else:
                result = self._workspace.read_text(
                    scope, arguments["path"], max_bytes=self._max_bytes
                )
            return _adopt(name, arguments, result, self._max_bytes, self._max_entries)
        except RalfError:
            raise
        except Exception:
            raise WorkspaceError("Workspace operation failed") from None
        finally:
            if token is not None:
                self._tracker._finish(token)

    async def call_tool(self, descriptor, arguments, context):
        if not isinstance(descriptor, ToolDescriptor) or descriptor.to_dict() not in [
            item.to_dict() for item in self._descriptors
        ]:
            raise DefinitionMismatch("Workspace invocation differs from its pinned descriptor")
        if type(arguments) is not dict or not Draft202012Validator(
            descriptor.input_schema
        ).is_valid(arguments):
            raise ValidationError("Workspace arguments differ from the pinned Schema")
        values = copy.deepcopy(arguments)
        _path(
            values.get("path", values.get("directory")),
            directory=descriptor.name != "workspace_read_text",
        )
        ambient = current_thread_tracker.get()
        tracker = ambient or self._tracker
        with self._lock:
            self._check()
            token = self._tracker._register(current_thread_group.get())
        try:
            result = await tracker.run(
                self._execute,
                token,
                descriptor.name,
                values,
                context.scope,
                group=current_thread_group.get(),
            )
            self._check()
            return result
        except BaseException:
            if token is not None:
                self._tracker._withdraw_pending(token)
            raise

    async def wait_for_calls(self):
        await self._tracker.drain()

    async def aclose(self):
        with self._lock:
            self._closing = True
        await self.wait_for_calls()
