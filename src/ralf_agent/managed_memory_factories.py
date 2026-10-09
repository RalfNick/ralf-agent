"""Explicit default rule stage; existing memory factories retain client ownership."""

from .errors import ValidationError
from .managed_memory import ManagedMemoryPolicy
from .memory import InMemoryMemory
from .memory_extraction import MemoryAdmissionPolicy
from .ports import is_async_callable
from .runtime_config import component_declaration

ADMISSION = {"fields", "max_facts", "max_value_chars", "expires_at"}


def register_memory_stages(registry):
    from .runtime_builder import _completed, _fields

    def prepare(config, *, asynchronous):
        _fields(config, ADMISSION | {"namespace", "timeout", "memory"})
        admission = MemoryAdmissionPolicy(**{k: v for k, v in config.items() if k in ADMISSION})
        # Validate all declarations before authority/client construction.
        ManagedMemoryPolicy(
            InMemoryMemory(),
            admission=admission,
            namespace=config.get("namespace", "auto-memory"),
            timeout=config.get("timeout", 5),
        )
        target = (
            registry.prepare("memory_store", component_declaration(config["memory"]))
            if "memory" in config
            else None
        )
        if target is not None and not asynchronous and is_async_callable(target[0]):
            raise ValidationError("Async memory target requires sourced-memory-async and abuild")
        return admission, target

    def stage(config, context, admission, memory):
        return ManagedMemoryPolicy(
            memory,
            admission=admission,
            scope=context.scope,
            namespace=config.get("namespace", "auto-memory"),
            timeout=config.get("timeout", 5),
        )

    def construct(config, context):
        admission, target = prepare(config, asynchronous=False)
        memory = (
            context.store.create_memory()
            if target is None
            else _completed(target[0](target[1], context), "Memory stage target factory")
        )
        return stage(config, context, admission, memory)

    async def aconstruct(config, context):
        admission, target = prepare(config, asynchronous=True)
        if target is None:
            memory = context.store.create_memory()
        else:
            factory, options = target
            memory = (
                await factory(options, context)
                if is_async_callable(factory)
                else factory(options, context)
            )
            memory = _completed(memory, "Memory stage target factory")
        return stage(config, context, admission, memory)

    registry.register(
        "stage_policy",
        "sourced-memory",
        construct,
        validator=lambda c: prepare(c, asynchronous=False) and None,
    )
    registry.register_async(
        "stage_policy",
        "sourced-memory-async",
        aconstruct,
        validator=lambda c: prepare(c, asynchronous=True) and None,
    )
