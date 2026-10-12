"""Borrowed native Sandbox in the original managed ToolSource lane."""

import asyncio
import inspect
import math

from jsonschema import Draft202012Validator

from .component_fingerprint import executable_digest
from .errors import CloseIncomplete, DefinitionMismatch, ValidationError
from .ports import is_async_callable
from .sandbox import SandboxObservation, SandboxRequest, SandboxResult, validate_sandbox_result
from .skills import _plain, _text
from .task_controls import _binding
from .tool_execution import ToolExecutionOwner
from .tool_sources import ToolDescriptor
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import InvocationContext, Scope, canonical, digest
from .workspace import _bound


class SandboxToolSource:
    def __init__(self, provider, *, version, max_timeout=30, max_output_bytes=1048576, max_calls=4):
        _text(version, "Sandbox tool version", 256)
        if type(max_timeout) not in (int, float) or not 0 < max_timeout <= 300:
            raise ValidationError("Sandbox tool timeout requires seconds in (0,300]")
        _bound(max_output_bytes, 16777216, "Sandbox output")
        _bound(max_calls, 16, "Sandbox call")
        if any(
            not is_async_callable(getattr(provider, n, None))
            for n in ("run", "observe", "stop", "aclose")
        ):
            raise ValidationError("Sandbox source requires native async SandboxProvider methods")
        identity = self._provider_identity(provider)
        if type(identity.get("isolation")) is not dict or any(
            identity["isolation"].get(k) != v or type(identity["isolation"].get(k)) is not type(v)
            for k, v in {"network": "none", "host_mounts": False, "persistent_files": False}.items()
        ):
            raise ValidationError("Sandbox tools require the host restricted ephemeral profile")
        self._provider, self._provider_pin = provider, canonical(identity)
        self._methods = {
            n: _binding(getattr(provider, n)) for n in ("run", "observe", "stop", "aclose")
        }
        self._version, self._timeout, self._output, self._max_calls = (
            version,
            max_timeout,
            max_output_bytes,
            max_calls,
        )
        self._owner = ToolExecutionOwner(version=version, max_calls=max_calls)
        self._stop_owner = ToolExecutionOwner(version=version, max_calls=max_calls)
        self._threads, self._calls, self._closing = ThreadExecutionTracker(), {}, False
        self._descriptor = ToolDescriptor(
            "sandbox_run",
            "Run a bounded command in the host-approved ephemeral sandbox.",
            {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {"type": "string", "maxLength": 65536},
                    },
                    "timeout": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": max_timeout,
                        "default": max_timeout,
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        )
        self._source = {
            "kind": "sandbox-tool-source",
            "version": "1",
            "behavior_version": version,
            "provider": identity,
            "max_timeout": max_timeout,
            "max_output_bytes": max_output_bytes,
            "max_calls": max_calls,
            "implementation": {
                n: executable_digest(getattr(self, n)) for n in ("call_tool", "_execute", "aclose")
            },
        }
        self._identity = canonical(self._source)
        self._source_methods = {
            n: _binding(getattr(self, n))
            for n in (
                "call_tool",
                "_execute",
                "_stop_call",
                "_owned_stop",
                "aclose",
                "_check",
                "list_tools",
            )
        }
        self._allowances = (
            version,
            max_timeout,
            max_output_bytes,
            max_calls,
            provider,
            self._owner,
            self._stop_owner,
        )

    @staticmethod
    def _provider_identity(provider):
        value = _plain(getattr(provider, "identity", None))
        if type(value) is not dict or not value or len(canonical(value).encode("utf-8")) > 65536:
            raise ValidationError(
                "Sandbox provider requires a bounded ordinary fixed JSON identity"
            )
        return value

    def _check(self, *, closing=False):
        if (
            (
                self._version,
                self._timeout,
                self._output,
                self._max_calls,
                self._provider,
                self._owner,
                self._stop_owner,
            )
            != self._allowances
            or any(
                _binding(getattr(self, n, None)) != original
                for n, original in self._source_methods.items()
            )
            or canonical(self._source) != self._identity
            or canonical(self._provider_identity(self._provider)) != self._provider_pin
            or any(
                _binding(getattr(self._provider, n, None)) != original
                for n, original in self._methods.items()
            )
        ):
            raise DefinitionMismatch("Original Sandbox source or provider changed")
        if self._closing and not closing:
            raise ValidationError("Sandbox source is closing or closed")

    @property
    def identity(self):
        self._check()
        return _plain(self._source)

    async def list_tools(self):
        self._check()
        return (ToolDescriptor(**self._descriptor.to_dict()),)

    @staticmethod
    def _context(context):
        if type(context) is not InvocationContext or type(context.scope) is not Scope:
            raise ValidationError("Sandbox requires trusted original InvocationContext")
        for value in (context.scope.workspace, context.scope.principal):
            _text(value, "Sandbox Scope", 512)
        for n in ("run_id", "action_id", "attempt_id", "effect_key", "execution_epoch"):
            _text(getattr(context, n), "Sandbox original Action identity", 1024)

    async def _execute(self, call, request):
        tracker = current_thread_tracker.set(call["tracker"])
        group = current_thread_group.set(call["group"])
        try:
            self._check(closing=True)
            result = await self._provider.run(call["scope"], request, invocation_id=call["id"])
            if inspect.iscoroutine(result) or inspect.isgenerator(result):
                result.close()
            if inspect.isasyncgen(result):
                await result.aclose()
            self._check(closing=True)
            result = validate_sandbox_result(result, call["id"], max_output_bytes=self._output)
            call["stopped"] = True
            await call["tracker"].drain(call["group"])
            self._threads._finish(call["token"])
            self._calls.pop(call["id"], None)
            return SandboxResult.to_dict(result)
        finally:
            current_thread_group.reset(group)
            current_thread_tracker.reset(tracker)

    async def call_tool(self, descriptor, arguments, context):
        self._check()
        self._context(context)
        if type(descriptor) is not ToolDescriptor or canonical(descriptor.to_dict()) != canonical(
            self._descriptor.to_dict()
        ):
            raise DefinitionMismatch("Sandbox call differs from original descriptor")
        if type(arguments) is not dict or set(arguments) - {"argv", "timeout"}:
            raise ValidationError("Sandbox arguments require only argv and timeout")
        request = SandboxRequest.from_dict({"timeout": self._timeout, **arguments})
        if not Draft202012Validator(self._descriptor.input_schema).is_valid(request.to_dict()):
            raise ValidationError("Sandbox request exceeds its host allowance")
        identifier = digest(
            [
                self._source,
                {"workspace": context.scope.workspace, "principal": context.scope.principal},
                context.run_id,
                context.action_id,
                context.effect_key,
            ]
        )
        if identifier in self._calls or len(self._calls) >= self._max_calls:
            raise ValidationError("Sandbox source owns this Action or is at capacity")
        tracker = current_thread_tracker.get() or self._threads
        group = current_thread_group.get() or identifier
        call = {
            "id": identifier,
            "scope": context.scope,
            "tracker": tracker,
            "group": group,
            "token": self._threads._register("bridge:" + identifier),
            "stopped": False,
        }
        self._threads._begin(call["token"])
        self._calls[identifier] = call
        proof = {
            "scope": {"workspace": context.scope.workspace, "principal": context.scope.principal},
            "action_id": identifier,
            "release_digest": digest(self._source),
            "request_digest": digest(request.to_dict()),
            "execution_epoch": context.execution_epoch,
        }

        async def invoke():
            return await self._execute(call, request)

        return await self._owner.execute(invoke, proof=proof)

    async def wait_for_calls(self):
        await self._threads.drain()

    async def _stop_call(self, call):
        tracker = current_thread_tracker.set(call["tracker"])
        group = current_thread_group.set(call["group"])
        try:
            self._check(closing=True)
            observation = await self._provider.stop(call["scope"], call["id"])
            if type(observation) is not SandboxObservation:
                raise ValidationError("Sandbox stop requires completed native evidence")
            SandboxObservation.__post_init__(observation)
            if observation.invocation_id != call["id"] or observation.state not in {
                "stopped",
                "not_found",
            }:
                raise CloseIncomplete("Original Sandbox native stop is unresolved")
            self._check(closing=True)
            await call["tracker"].drain(call["group"])
            self._threads._finish(call["token"])
            self._calls.pop(call["id"], None)
            return None
        finally:
            current_thread_group.reset(group)
            current_thread_tracker.reset(tracker)

    async def _owned_stop(self, call):
        async def operation():
            return await self._stop_call(call)

        proof = {
            "scope": {"workspace": call["scope"].workspace, "principal": call["scope"].principal},
            "action_id": call["id"],
            "release_digest": digest(self._source),
            "request_digest": digest(["stop", call["id"]]),
            "execution_epoch": "sandbox-stop",
        }
        return await self._stop_owner.execute(operation, proof=proof)

    async def aclose(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or wait_timeout < 0
        ):
            raise ValidationError("Sandbox source close requires a finite nonnegative timeout")
        self._closing = True
        if self._calls and wait_timeout == 0:
            raise CloseIncomplete("Original Sandbox native calls remain owned")
        deadline = asyncio.get_running_loop().time() + wait_timeout
        try:
            for call in list(self._calls.values()):
                self._check(closing=True)
                task = call.get("stop_task")
                if task is None or task.done():
                    if task is not None and not task.cancelled():
                        task.exception()
                    if not await self._stop_owner.wait(
                        wait_timeout=max(0, deadline - asyncio.get_running_loop().time())
                    ):
                        raise CloseIncomplete("Original Sandbox stop remains owned")
                    task = call["stop_task"] = asyncio.create_task(self._owned_stop(call))
                    task.add_done_callback(
                        lambda done: None if done.cancelled() else done.exception()
                    )
                await asyncio.wait_for(
                    asyncio.shield(task), max(0, deadline - asyncio.get_running_loop().time())
                )
            await self._stop_owner.aclose(
                wait_timeout=max(0, deadline - asyncio.get_running_loop().time())
            )
            await self._owner.aclose(
                wait_timeout=max(0, deadline - asyncio.get_running_loop().time())
            )
        except TimeoutError:
            raise CloseIncomplete("Original Sandbox native calls remain owned") from None
