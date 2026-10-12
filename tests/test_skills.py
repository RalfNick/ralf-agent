"""Public immutable catalogs and strict portable reference-instruction snapshots."""

import copy
import hashlib
import importlib
from dataclasses import FrozenInstanceError

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, ValidationError

SCOPE = r.Scope()


def api(name):
    value = getattr(r, name, None)
    assert value is not None, f"public {name} is missing"
    return value


def spec(name="help", description="Reference", instructions="Use approved tools.", version="1"):
    return api("SkillSpec")(name, description, instructions, version)


def catalog(skills=None, **options):
    return api("InMemorySkillCatalog")(
        [spec()] if skills is None else skills, version="1", **options
    )


def test_public_memory_skill_catalog_and_scope():
    assert api("SkillCatalogPort") is not None
    port = catalog()
    try:
        listed = port.list(SCOPE)
        got = port.get(SCOPE, "help")
        assert (
            listed["scope"] == got["scope"] == {"workspace": "default", "principal": "local-owner"}
        )
        assert listed["kind"] == "skill-list" and got["kind"] == "skill-instructions"
        assert listed["catalog_digest"] == got["catalog_digest"] == port.identity["catalog_digest"]
        assert got["skill"]["instructions"] == "Use approved tools."
        assert got["skill"]["sha256"] == hashlib.sha256(b"Use approved tools.").hexdigest()
        assert listed["skills"] == [{k: v for k, v in got["skill"].items() if k != "instructions"}]
        with pytest.raises(AuthorizationDenied):
            port.get(r.Scope("other", "owner"), "help")
    finally:
        port.close()


def test_specs_are_frozen_and_catalog_snapshots_are_detached():
    entry = spec()
    with pytest.raises(FrozenInstanceError):
        entry.instructions = "changed"
    originals = [entry]
    port = catalog(originals)
    originals.clear()
    initial = port.identity
    initial["catalog_digest"] = "changed"
    got = port.get(SCOPE, "help")
    got["skill"]["instructions"] = "changed"
    listed = port.list(SCOPE)
    listed["skills"][0]["description"] = "changed"
    assert port.get(SCOPE, "help")["skill"] == entry.to_dict()
    assert port.list(SCOPE)["skills"][0]["description"] == "Reference"
    assert port.identity["catalog_digest"] != "changed"
    port.close()


def test_order_pagination_and_empty_catalog_have_stable_digest():
    items = [spec("beta"), spec("alpha"), spec("gamma")]
    port, other = catalog(items), catalog(list(reversed(items)))
    assert port.identity == other.identity
    first = port.list(SCOPE, max_entries=2)
    assert [s["name"] for s in first["skills"]] == ["alpha", "beta"]
    assert first["total"] == 3 and first["next_offset"] == 2
    final = port.list(SCOPE, max_entries=2, offset=2)
    assert [s["name"] for s in final["skills"]] == ["gamma"] and final["next_offset"] is None
    assert port.list(SCOPE, offset=3)["skills"] == []
    empty = catalog([])
    assert empty.list(SCOPE)["total"] == 0 and empty.list(SCOPE)["next_offset"] is None
    for value in (port, other, empty):
        value.close()


@pytest.mark.parametrize("change", ["description", "instructions", "version"])
def test_changed_reference_metadata_or_body_changes_catalog_identity(change):
    values = {"name": "help", "description": "Reference", "instructions": "Body", "version": "1"}
    first = catalog([spec(**values)])
    values[change] = "different"
    second = catalog([spec(**values)])
    assert first.identity["catalog_digest"] != second.identity["catalog_digest"]
    first.close()
    second.close()


@pytest.mark.parametrize(
    "name", [None, True, "", "Bad", "a_b", "a--b", "-a", "a-", "a" * 65, "\ud800"]
)
def test_invalid_skill_names_refused(name):
    with pytest.raises(ValidationError):
        spec(name=name)


@pytest.mark.parametrize("version", [None, True, 1, "", "\x00", "x" * 257, "\ud800"])
def test_invalid_skill_versions_refused(version):
    with pytest.raises(ValidationError):
        spec(version=version)


@pytest.mark.parametrize("description", ["", " ", True, "\x00", "é" * 2049])
def test_invalid_descriptions_refused(description):
    with pytest.raises(ValidationError):
        spec(description=description)


@pytest.mark.parametrize("instructions", ["", "  ", False, "\x00", "\ud800", "x" * (16777216 + 1)])
def test_invalid_instructions_refused(instructions):
    with pytest.raises(ValidationError):
        spec(instructions=instructions)


@pytest.mark.parametrize(
    "option,value",
    [
        ("max_skills", True),
        ("max_skills", 0),
        ("max_skills", 1001),
        ("max_bytes", True),
        ("max_bytes", 0),
        ("max_bytes", 16777217),
    ],
)
def test_typed_catalog_limits(option, value):
    with pytest.raises(ValidationError):
        catalog(**{option: value})


def test_duplicate_invalid_and_over_capacity_catalogs_refused():
    with pytest.raises(ValidationError):
        catalog([spec(), spec()])
    with pytest.raises(ValidationError):
        catalog([spec(), spec("other")], max_skills=1)
    with pytest.raises(ValidationError):
        catalog([spec()], max_bytes=2)
    with pytest.raises(ValidationError):
        catalog([{"name": "help"}])
    touched = []

    def lazy():
        touched.append(True)
        yield spec()

    generator = lazy()
    try:
        with pytest.raises(ValidationError):
            catalog(generator)
        assert touched == []
    finally:
        generator.close()


def test_total_instruction_capacity_is_independent_of_entry_limit():
    body = "x" * 1048576
    with pytest.raises(ValidationError):
        catalog([spec("entry-" + str(i), instructions=body) for i in range(65)], max_skills=1000)


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("list", {"max_entries": True}),
        ("list", {"offset": True}),
        ("list", {"offset": -1}),
        ("list", {"offset": 1001}),
        ("get", {"name": "help", "max_bytes": True}),
        ("get", {"name": "help", "max_bytes": 1}),
    ],
)
def test_invalid_read_limits_refused(method, kwargs):
    port = catalog()
    try:
        with pytest.raises((ValidationError, api("SkillError"))):
            getattr(port, method)(SCOPE, **kwargs)
    finally:
        port.close()


def test_unknown_skill_and_closed_catalog_refuse_new_reads():
    port = catalog()
    with pytest.raises(api("SkillError")):
        port.get(SCOPE, "unknown")
    port.close()
    port.close()
    for method, kwargs in (("list", {}), ("get", {"name": "help"})):
        with pytest.raises(api("SkillError")):
            getattr(port, method)(SCOPE, **kwargs)


@pytest.mark.parametrize("part", ["scope", "catalog_digest", "sha256", "bytes", "instructions"])
def test_get_snapshot_validator_refuses_forged_original_evidence(part):
    helpers = importlib.import_module("ralf_agent.skills")
    port = catalog()
    value = port.get(SCOPE, "help")
    if part in {"scope", "catalog_digest"}:
        value[part] = {"workspace": "other", "principal": "owner"} if part == "scope" else "0" * 64
    else:
        value["skill"][part] = True if part == "bytes" else "forged"
    with pytest.raises(api("SkillError")):
        helpers.validate_skill_get(
            value, SCOPE, "help", catalog_digest=port.identity["catalog_digest"], max_bytes=1048576
        )
    port.close()


def test_list_validator_detaches_and_rejects_boolean_numeric_or_wrong_pagination():
    helpers = importlib.import_module("ralf_agent.skills")
    port = catalog()
    original = port.list(SCOPE)
    accepted = helpers.validate_skill_list(
        original, SCOPE, catalog_digest=port.identity["catalog_digest"], max_entries=100, offset=0
    )
    accepted["skills"].clear()
    assert original["skills"]
    for key, value in (("total", True), ("next_offset", True), ("total", 0), ("next_offset", 1)):
        bad = copy.deepcopy(original)
        bad[key] = value
        with pytest.raises(api("SkillError")):
            helpers.validate_skill_list(
                bad,
                SCOPE,
                catalog_digest=port.identity["catalog_digest"],
                max_entries=100,
                offset=0,
            )
    port.close()


@pytest.mark.parametrize("field", ["description", "instructions", "version"])
def test_unicode_whitespace_is_not_a_reference_value(field):
    with pytest.raises(ValidationError):
        spec(**{field: "\u3000\u00a0"})


def test_null_offset_is_not_an_implicit_first_page():
    port = catalog()
    try:
        with pytest.raises(ValidationError):
            port.list(SCOPE, offset=None)
    finally:
        port.close()
