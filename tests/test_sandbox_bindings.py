"""Sandbox role restricts original registered tool grants, never executes or owns."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError, ValidationError

from .test_sandbox_tools import Provider


def api():
    resource = getattr(r, "SandboxBindingResource", None)
    assert resource is not None, "Missing original SandboxBindingResource"
    from ralf_agent.binding_sandbox import select_sandbox_tools

    return resource, select_sandbox_tools


@pytest.fixture
def registered():
    registry, ports, sources = r.ToolRegistry(), [], []

    async def build():
        for prefix in ("a_", "b_"):
            port = Provider()
            port.identity = {**port.identity, "host": prefix}
            source = r.SandboxToolSource(port, version="1")
            ports.append(port)
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=prefix,
                policies={
                    "sandbox_run": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                },
            )

    asyncio.run(build())
    registry.register(r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "ok")
    yield registry, ports
    for source in sources:
        asyncio.run(source.aclose())


def test_pure_resource_selection_preserves_order_and_unrelated_grants(registered):
    registry, ports = registered
    Resource, select = api()
    resource = Resource(registry, names=["a_sandbox_run"])
    names = ("b_sandbox_run", "business", "a_sandbox_run")
    assert select(names, registry.manifests(names), resource.identity) == (
        "business",
        "a_sandbox_run",
    )
    assert select(names, registry.manifests(names)) == ("business",)
    assert resource.registry is registry and not hasattr(resource, "aclose")
    assert all(p.calls == [] and not p.closed for p in ports)


def test_absent_original_grant_is_never_added(registered):
    registry, _ = registered
    Resource, select = api()
    resource = Resource(registry, names=["a_sandbox_run"])
    names = ("business", "b_sandbox_run")
    with pytest.raises(AuthorizationDenied):
        select(names, registry.manifests(names), resource.identity)


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["business"],
        ["a_sandbox_run", "b_sandbox_run"],
        ["a_sandbox_run"] * 2,
        "a_sandbox_run",
        [True],
    ],
)
def test_resource_requires_exact_original_native_source_names(registered, names):
    registry, _ = registered
    Resource, _ = api()
    with pytest.raises(ValidationError):
        Resource(registry, names=names)


def test_published_registration_and_provider_drift_refuses(registered):
    registry, ports = registered
    Resource, _ = api()
    resource = Resource(registry, names=["a_sandbox_run"])
    identity = resource.identity
    identity["source"]["provider"]["host"] = "changed"
    assert identity != resource.identity
    ports[0].identity = {**ports[0].identity, "host": "changed"}
    with pytest.raises(DefinitionMismatch):
        _ = resource.identity


@pytest.mark.parametrize(
    "field", ["effect", "policy", "version", "limit", "implementation", "name", "isolation"]
)
def test_forged_native_manifest_refuses_before_copy_or_execution(registered, monkeypatch, field):
    registry, ports = registered
    Resource, _ = api()
    original = registry.manifests

    def manifests(names):
        values = original(names)
        value = values["a_sandbox_run"]
        source = value["config"]["source"]
        if field == "effect":
            value["effect"] = "unqueryable_write"
        elif field == "policy":
            value["requires_approval"] = False
        elif field == "version":
            source["version"] = True
        elif field == "limit":
            source["max_timeout"] = True
        elif field == "implementation":
            source["implementation"]["call_tool"] = "bad"
        elif field == "name":
            value["config"]["remote_tool"]["name"] = "business"
        else:
            source["provider"]["isolation"]["network"] = "host"
        return values

    monkeypatch.setattr(registry, "manifests", manifests)
    with pytest.raises(RalfError):
        Resource(registry, names=["a_sandbox_run"])
    assert ports[0].calls == []
