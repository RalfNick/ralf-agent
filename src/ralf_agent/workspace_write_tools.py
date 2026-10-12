"""Native writable Workspace tools reuse original true-thread ownership."""

import copy
import inspect

from .errors import RalfError, ValidationError
from .ports import is_sync_callable
from .tool_sources import ToolDescriptor
from .tools import current_thread_group, current_thread_tracker
from .workspace import WorkspaceError
from .workspace_tools import WorkspaceToolSource
from .workspace_writes import validate_write_receipt, write_request


class WritableWorkspaceToolSource(WorkspaceToolSource):
    def __init__(self, workspace, *, version, max_entries=100, max_bytes=1048576):
        if any(
            not is_sync_callable(getattr(workspace, name, None))
            for name in ("write_text", "query_write")
        ):
            raise ValidationError(
                "Writable Workspace source requires synchronous write and query ports"
            )
        super().__init__(workspace, version=version, max_entries=max_entries, max_bytes=max_bytes)
        self._descriptors += (
            ToolDescriptor(
                "workspace_write_text",
                "Create or replace allowed UTF-8 text with an exact original version and stable effect key. Null expected_version means create only.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "text": {"type": "string"},
                        "expected_version": {
                            "type": ["string", "null"],
                            "pattern": "^[0-9a-f]{64}$",
                        },
                        "effect_key": {"type": "string", "minLength": 1},
                    },
                    "required": ["path", "text", "expected_version", "effect_key"],
                    "additionalProperties": False,
                },
            ),
        )

    @property
    def identity(self):
        return {**super().identity, "version": "2"}

    def validate_tool_policy(self, descriptor, policy):
        if descriptor.name != "workspace_write_text":
            return super().validate_tool_policy(descriptor, policy)
        if (
            type(policy.effect) is not str
            or policy.effect != "idempotent_write"
            or type(policy.effect_key_argument) is not str
            or policy.effect_key_argument != "effect_key"
            or (
                policy.reconciler is not None
                and (
                    getattr(policy.reconciler, "__self__", None) is not self
                    or getattr(policy.reconciler, "__func__", None)
                    is not WritableWorkspaceToolSource.reconcile
                )
            )
        ):
            raise ValidationError(
                "Native Workspace writes require idempotent effect keys and their original reconciler"
            )

    def _execute(self, token, name, arguments, scope):
        if name not in {"workspace_write_text", "@query_write"}:
            return super()._execute(token, name, arguments, scope)
        if token is not None and not self._tracker._begin(token):
            return None
        try:
            request, _ = write_request(
                scope,
                arguments["path"],
                arguments["text"],
                arguments["expected_version"],
                arguments["effect_key"],
                max_bytes=self._max_bytes,
            )
            if name == "@query_write":
                value = self._workspace.query_write(scope, arguments["effect_key"])
                if value is None:
                    return None
            else:
                value = self._workspace.write_text(
                    scope,
                    arguments["path"],
                    arguments["text"],
                    expected_version=arguments["expected_version"],
                    effect_key=arguments["effect_key"],
                )
            if inspect.iscoroutine(value) or inspect.isgenerator(value):
                value.close()
            return validate_write_receipt(value, scope, arguments["effect_key"], request)
        except RalfError:
            raise
        except Exception:
            raise WorkspaceError("Workspace write or evidence query failed") from None
        finally:
            if token is not None:
                self._tracker._finish(token)

    async def reconcile(self, arguments, context):
        if type(arguments) is not dict or set(arguments) != {"path", "text", "expected_version"}:
            raise ValidationError(
                "Workspace reconcile requires original unmodified caller arguments"
            )
        values = {**copy.deepcopy(arguments), "effect_key": context.effect_key}
        write_request(
            context.scope,
            values["path"],
            values["text"],
            values["expected_version"],
            context.effect_key,
            max_bytes=self._max_bytes,
        )
        tracker = current_thread_tracker.get() or self._tracker
        with self._lock:
            self._check()
            token = self._tracker._register(current_thread_group.get())
        try:
            result = await tracker.run(
                self._execute,
                token,
                "@query_write",
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
