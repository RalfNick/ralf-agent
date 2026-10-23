"""Simple async Agent entry; shared runtimes retain execution/resource ownership."""

from .agent_harness import AgentHarness
from .agent_runtime import Runtime
from .engine import LocalEngine
from .errors import RuntimeClosed, ValidationError
from .storage import SQLiteStore
from .tools import ToolRegistry
from .types import AgentSpec


class Agent:
    def __init__(
        self,
        *,
        runtime=None,
        definition=None,
        model=None,
        tools=(),
        name="assistant",
        instructions="Answer the request",
        db_path=".ralf/runs.sqlite",
    ):
        self._closed = False
        self._owned = runtime is None
        if runtime is None:
            if model is None:
                raise ValidationError("Standalone Agent requires an explicit model Provider")
            if isinstance(tools, ToolRegistry):
                registry = tools
            elif isinstance(tools, (tuple, list)) and not tools:
                registry = ToolRegistry()
            else:
                raise ValidationError(
                    "Agent tools require a ToolRegistry; register functions with an explicit effect"
                )
            names = tuple(registry._tools)
            selected = definition or AgentSpec(name, instructions, names)
            harness = selected if isinstance(selected, AgentHarness) else AgentHarness(selected)
            store = SQLiteStore(db_path)
            try:
                runtime = Runtime(
                    LocalEngine(store, providers={"default": model}, tools=registry), owned=True
                )
            except BaseException:
                store.close()
                raise
        else:
            if model is not None or tools:
                raise ValidationError(
                    "Shared Agent selects components through its fixed definition"
                )
            if not isinstance(runtime, Runtime):
                raise ValidationError("Shared Agent requires a Runtime")
            selected = definition or AgentSpec(name, instructions)
            harness = selected if isinstance(selected, AgentHarness) else AgentHarness(selected)
        self.runtime, self.harness = runtime, harness

    async def open_session(self, session_id, *, command_id, **options):
        if self._closed:
            raise RuntimeClosed("Agent entry is closed")
        return await self.runtime.open_session(
            self.harness, session_id, command_id=command_id, **options
        )

    async def submit(self, input, *, command_id, **options):
        if self._closed:
            raise RuntimeClosed("Agent entry is closed")
        return await self.runtime.submit(self.harness, input, command_id=command_id, **options)

    async def run(self, input, *, command_id, wait_timeout=None, terminal_only=False, **options):
        run = await self.submit(input, command_id=command_id, **options)
        return await run.wait(wait_timeout=wait_timeout, terminal_only=terminal_only)

    async def aclose(self, **options):
        self._closed = True
        return await self.runtime.aclose(**options) if self._owned else None

    async def __aenter__(self):
        if self._closed:
            raise RuntimeClosed("Agent entry is closed")
        self.runtime._check(accepting=True)
        return self

    async def __aexit__(self, kind, error, trace):
        self._closed = True
        if self._owned:
            return await self.runtime.__aexit__(kind, error, trace)
