"""Explicit Sandbox admission uses the original History and actual Tool owner."""

import asyncio
import copy
from dataclasses import asdict

import pytest

import relf_agent as r
from relf_agent.errors import RalfError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import effective_step
from relf_agent.temporal_state import validate_manifest

from .test_sandbox_binding_execution import Reader
from .test_sandbox_bindings import registered as registered


def runtime_for(registry, *, catalog=None, **options):
    return TemporalRuntime(
        providers={"default": Reader()}, tools=registry, binding_catalog=catalog, **options
    )


def test_default_native_sandbox_publishes_recognized_protocol_and_original_tool_owner(registered):
    registry, _ = registered
    runtime = runtime_for(registry)
    manifest = runtime.manifest
    assert manifest["sandbox_binding_protocol"] == 1 and manifest["binding_protocol"] == 4
    assert (
        manifest["tool_execution_protocol"]["version"] == 1 and runtime.tool_execution is not None
    )
    assert validate_manifest(manifest) == manifest


def test_sandbox_role_selects_and_disables_only_original_native_grants(registered):
    registry, _ = registered
    catalog = r.BindingCatalog(scope=r.Scope())
    catalog.register(
        "sandbox", "a", "1", r.SandboxBindingResource(registry, names=["a_sandbox_run"])
    )
    runtime = runtime_for(registry, catalog=catalog)
    step = asdict(
        r.AgentSpec("reader", "Run", tools=("a_sandbox_run", "b_sandbox_run", "business"))
    )
    chosen = effective_step(
        step,
        runtime.manifest,
        r.AgentBindingDescriptor(sandbox=r.BindingSelection.ref("a", "1")).to_dict(),
    )
    assert chosen["tools"] == ["a_sandbox_run", "business"]
    disabled = effective_step(
        step,
        runtime.manifest,
        r.AgentBindingDescriptor(sandbox=r.BindingSelection.disabled()).to_dict(),
    )
    assert disabled["tools"] == ["business"]


@pytest.mark.parametrize("change", ["missing", "bool", "future", "binding", "owner", "native"])
def test_inconsistent_or_unsupported_sandbox_protocol_is_rejected(registered, change):
    registry, _ = registered
    manifest = copy.deepcopy(runtime_for(registry).manifest)
    if change == "missing":
        manifest.pop("sandbox_binding_protocol", None)
    elif change in {"bool", "future"}:
        manifest["sandbox_binding_protocol"] = True if change == "bool" else 2
    elif change == "binding":
        manifest["binding_protocol"] = 3
    elif change == "owner":
        manifest.pop("tool_execution_protocol", None)
    else:
        manifest["tools"]["a_sandbox_run"]["config"]["source"]["provider"]["isolation"][
            "network"
        ] = "host"
    with pytest.raises(RalfError):
        validate_manifest(manifest)


def test_native_profile_is_accepted_with_original_custom_context_and_tool_owner(registered):
    registry, _ = registered
    runtime = runtime_for(
        registry, context_reads=True, tool_execution=r.ToolExecutionOwner(version="custom")
    )
    assert runtime.manifest["binding_protocol"] == 4
    assert (
        "context_read_protocol" in runtime.manifest
        and "tool_execution_protocol" in runtime.manifest
    )
    asyncio.run(runtime.close_context_execution(wait_timeout=1))
