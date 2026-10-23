"""A full release check rejects owner changes made by registration getters."""

import pytest

from relf_agent.binding_catalog import BindingCatalog
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.tools import ToolRegistry
from relf_agent.types import Scope


class OfflineProvider:
    identity = {"kind": "release-reentrancy-provider", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("Release validation must not call the Provider")


class ReentrantContext:
    def __init__(self):
        self.mutation = None
        self.fired = False

    @property
    def identity(self):
        if self.mutation is not None and not self.fired:
            self.fired = True
            self.mutation()
        return {"kind": "release-reentrancy-context", "version": "1"}

    def assemble(self, history, references, max_chars):
        raise AssertionError("Release validation must not assemble Context")


class LateGetterContext(ReentrantContext):
    def __init__(self):
        super().__init__()
        self.late_mutation = None
        self.late_reads = 0

    @property
    def validate_request(self):
        if self.late_mutation is not None:
            self.late_reads += 1
            if self.late_reads == 2:
                self.late_mutation()
        return None


def environment(context=None, *, provider=None):
    context = ReentrantContext() if context is None else context
    runtime = TemporalRuntime(
        providers={"offline": OfflineProvider() if provider is None else provider},
        tools=ToolRegistry(),
        context_builder=context,
        binding_catalog=BindingCatalog(scope=Scope()),
    )
    assert runtime.manifest["kernel"] == "temporal-3"
    runtime.validate_release()
    return runtime, context


def test_first_release_check_rejects_same_content_catalog_replacement():
    runtime, context = environment()
    replacement = BindingCatalog(scope=Scope())
    context.mutation = lambda: setattr(runtime, "binding_catalog", replacement)

    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()

    assert context.fired
    assert runtime.binding_catalog is replacement


def test_first_release_check_rejects_same_identity_provider_replacement():
    runtime, context = environment()
    replacement = OfflineProvider()
    context.mutation = lambda: runtime.providers.__setitem__("offline", replacement)

    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()

    assert context.fired
    assert runtime.providers["offline"] is replacement


def test_first_release_check_rejects_same_identity_context_replacement():
    runtime, context = environment()
    replacement = ReentrantContext()
    context.mutation = lambda: setattr(runtime, "context", replacement)

    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()

    assert context.fired
    assert runtime.context is replacement


def test_first_release_check_rejects_in_place_provider_code_replacement():
    runtime, context = environment()
    method = OfflineProvider.complete
    original_code = method.__code__

    async def changed_complete(self, messages, tools):
        raise AssertionError("The changed Provider must not be called either")

    context.mutation = lambda: setattr(method, "__code__", changed_complete.__code__)
    try:
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()
        assert context.fired
    finally:
        method.__code__ = original_code


def test_non_mutating_identity_getter_keeps_release_valid():
    runtime, context = environment()
    context.mutation = lambda: None

    result = runtime.validate_release()

    assert context.fired
    assert result["kernel"] == "temporal-3"
    assert result["context_builder"] == {
        "kind": "release-reentrancy-context",
        "version": "1",
    }
    assert result["providers"] == {
        "offline": {"kind": "release-reentrancy-provider", "version": "1"}
    }


def test_release_result_is_detached_from_original_manifest():
    runtime, _ = environment()
    expected = runtime.manifest
    result = runtime.validate_release()
    result["providers"]["offline"]["kind"] = "caller-changed"
    result["binding_catalog"]["scope"]["principal"] = "caller-changed"

    assert runtime.manifest == expected
    assert runtime.validate_release() == expected


def test_exit_getter_cannot_replace_already_checked_provider():
    context = LateGetterContext()
    runtime, _ = environment(context)
    replacement = OfflineProvider()
    context.mutation = lambda: setattr(
        context, "late_mutation", lambda: runtime.providers.__setitem__("offline", replacement)
    )

    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()

    assert context.late_reads == 2
    assert runtime.providers["offline"] is replacement


def test_exit_getter_cannot_replace_already_checked_provider_code():
    context = LateGetterContext()
    runtime, _ = environment(context)
    method = OfflineProvider.complete
    original_code = method.__code__

    async def changed_complete(self, messages, tools):
        raise AssertionError("The late changed Provider must not be called")

    context.mutation = lambda: setattr(
        context, "late_mutation", lambda: setattr(method, "__code__", changed_complete.__code__)
    )
    try:
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()
        assert context.late_reads == 2
    finally:
        method.__code__ = original_code


def test_exit_getter_cannot_replace_provider_method_with_instance_alias():
    context = LateGetterContext()
    runtime, _ = environment(context)
    provider = runtime.providers["offline"]
    alias = OfflineProvider().complete
    context.mutation = lambda: setattr(
        context, "late_mutation", lambda: setattr(provider, "complete", alias)
    )

    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()

    assert context.late_reads == 2
    assert provider.complete is alias


def test_exit_getter_cannot_change_async_callable_provider_entry_code():
    class AsyncCompletion:
        async def __call__(self, messages, tools):
            raise AssertionError("Release validation must not call the callable Provider")

    context = LateGetterContext()
    provider = OfflineProvider()
    provider.complete = AsyncCompletion()
    runtime, _ = environment(context, provider=provider)
    method = AsyncCompletion.__call__
    original_code = method.__code__

    async def changed_complete(self, messages, tools):
        raise AssertionError("The changed callable Provider must not be called")

    context.mutation = lambda: setattr(
        context, "late_mutation", lambda: setattr(method, "__code__", changed_complete.__code__)
    )
    try:
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()
        assert context.late_reads == 2
    finally:
        method.__code__ = original_code
