"""Pure catalog bindings intersect original grants and borrow registry resources."""

import asyncio

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError


def api():
    resource = getattr(r, "SkillBindingResource", None)
    assert resource is not None, "public SkillBindingResource is missing"
    from relf_agent.binding_skills import select_skill_tools

    return resource, select_skill_tools


@pytest.fixture
def registered():
    registry, ports, sources = r.ToolRegistry(), [], []

    async def build():
        for prefix in ("a_", "b_"):
            port = r.InMemorySkillCatalog([r.SkillSpec("help", "Reference", prefix)], version="1")
            source = r.SkillToolSource(port, version="1")
            ports.append(port)
            sources.append(source)
            await r.register_tool_source(
                registry,
                source,
                prefix=prefix,
                policies={
                    name: r.ToolPolicy("1", effect="read_only")
                    for name in ("skill_list", "skill_get")
                },
            )

    asyncio.run(build())
    registry.register(r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "ok")
    yield registry, ports
    for source in sources:
        asyncio.run(source.aclose())
    for port in ports:
        port.close()


def test_resource_filters_only_skill_grants_and_retains_original_order(registered):
    registry, ports = registered
    Resource, select = api()
    resource = Resource(registry, names=["a_skill_list", "a_skill_get"])
    names = ("b_skill_get", "business", "a_skill_get", "a_skill_list")
    assert select(names, registry.manifests(names), resource.identity) == (
        "business",
        "a_skill_get",
        "a_skill_list",
    )
    assert resource.registry is registry
    assert resource.identity["kind"] == "skill-binding-resource"
    assert (
        not hasattr(resource, "close")
        and ports[0].get(r.Scope(), "help")["skill"]["instructions"] == "a_"
    )


def test_disabled_skills_retains_business_and_unrelated_workspace(registered):
    registry, _ = registered
    _, select = api()
    registry.register(
        r.ToolSpec("workspace_business", "Business", {"type": "object"}), lambda a, c: "ok"
    )
    names = ("a_skill_get", "business", "workspace_business", "b_skill_list")
    assert select(names, registry.manifests(names)) == ("business", "workspace_business")


def test_choice_never_grants_absent_skill(registered):
    registry, _ = registered
    Resource, select = api()
    resource = Resource(registry, names=["a_skill_get"])
    names = ("business", "b_skill_get")
    with pytest.raises(AuthorizationDenied):
        select(names, registry.manifests(names), resource.identity)


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["business"],
        ["a_skill_get", "b_skill_get"],
        ["a_skill_get", "a_skill_get"],
        "a_skill_get",
        [True],
        ["x" * 129],
        ["a\n"],
        ["x"] * 257,
    ],
)
def test_invalid_resource_names_or_sources_refuse(registered, names):
    registry, _ = registered
    Resource, _ = api()
    with pytest.raises(ValidationError):
        Resource(registry, names=names)


def test_identity_is_detached_and_registration_change_refuses(registered, monkeypatch):
    registry, _ = registered
    Resource, _ = api()
    resource = Resource(registry, names=["a_skill_get"])
    changed = resource.identity
    changed["source"]["catalog"]["behavior_version"] = "changed"
    assert resource.identity != changed
    original = registry.manifests

    def manifests(names):
        value = original(names)
        value["a_skill_get"]["cost"] += 1
        return value

    monkeypatch.setattr(registry, "manifests", manifests)
    with pytest.raises(DefinitionMismatch):
        _ = resource.identity


@pytest.mark.parametrize("change", ["effect", "digest", "version", "maximum", "name", "key"])
def test_native_source_record_requires_exact_plain_valid_fields(registered, monkeypatch, change):
    registry, _ = registered
    Resource, _ = api()
    original = registry.manifests

    def manifests(names):
        value = original(names)
        record = value["a_skill_get"]
        source = record["config"]["source"]
        if change == "effect":
            record["effect"] = "unqueryable_write"
        elif change == "digest":
            source["catalog"]["catalog_digest"] = "bad"
        elif change == "version":
            source["version"] = True
        elif change == "maximum":
            source["max_entries"] = True
        elif change == "name":
            record["config"]["remote_tool"]["name"] = "business"
        else:
            source["unexpected"] = 1
        return value

    monkeypatch.setattr(registry, "manifests", manifests)
    with pytest.raises((ValidationError, r.SkillError)):
        Resource(registry, names=["a_skill_get"])


def test_canonical_bool_int_difference_is_not_same_grant(registered):
    registry, _ = registered
    Resource, select = api()
    resource = Resource(registry, names=["a_skill_get"])
    names = ("a_skill_get", "business")
    values = registry.manifests(names)
    assert values["a_skill_get"]["cost"] == 1
    values["a_skill_get"]["cost"] = True
    with pytest.raises(DefinitionMismatch):
        select(names, values, resource.identity)


def test_resource_registry_snapshots_do_not_execute_copy_hooks(registered, monkeypatch):
    registry, _ = registered
    Resource, _ = api()
    touched = []

    class Deferred(str):
        def __deepcopy__(self, memo):
            touched.append(True)
            return "forged"

    original = registry.manifests

    def manifests(names):
        value = original(names)
        value["a_skill_get"]["config"]["source"]["catalog"]["version"] = Deferred("1")
        return value

    monkeypatch.setattr(registry, "manifests", manifests)
    with pytest.raises((ValidationError, r.SkillError)):
        Resource(registry, names=["a_skill_get"])
    assert touched == []


@pytest.mark.parametrize("bad", [{"kind": "wrong"}, None, [], True])
def test_malformed_resource_or_duplicate_grants_refuse(registered, bad):
    registry, _ = registered
    _, select = api()
    if bad is None:
        with pytest.raises(ValidationError):
            select(["a_skill_get", "a_skill_get"], registry.manifests(["a_skill_get"]))
    else:
        with pytest.raises((ValidationError, r.SkillError)):
            select(["a_skill_get"], registry.manifests(["a_skill_get"]), bad)
