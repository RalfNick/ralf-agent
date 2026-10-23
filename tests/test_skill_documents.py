"""Pure standard-frontmatter parsing is bounded and grants no permissions."""

import builtins

import pytest

import relf_agent as r
from relf_agent.errors import RalfError, ValidationError


def api():
    value = getattr(r, "ParsedSkillDocument", None)
    parser = getattr(r, "YamlSkillDocumentParser", None)
    assert value is not None and parser is not None, "public Skill document/parser APIs are missing"
    assert getattr(r, "SkillDocumentParser", None) is not None
    return value, parser


def parse(text, parent="help"):
    _, cls = api()
    return cls(version="1").parse(text, parent_name=parent)


def doc(header="name: help\ndescription: Reference", body="Original\n"):
    return "---\n" + header + "\n---\n" + body


def test_public_value_default_metadata_and_detached_optional_information():
    Value, _ = api()
    skill = r.SkillSpec("help", "Reference", "Original")
    metadata = {
        "license": "Apache-2.0",
        "compatibility": "Python",
        "allowed-tools": "forbidden_danger",
        "metadata": {"author": "App", "version": "1"},
    }
    value = Value(skill, metadata)
    metadata["metadata"]["author"] = "Changed"
    snapshot = value.to_dict()
    assert set(snapshot) == {"skill", "metadata"}
    assert (
        snapshot["skill"] == skill.to_dict() and snapshot["metadata"]["metadata"]["author"] == "App"
    )
    snapshot["metadata"]["metadata"]["author"] = "Changed"
    assert value.to_dict()["metadata"]["metadata"]["author"] == "App"
    assert Value(skill).to_dict()["metadata"] == {}
    with pytest.raises((AttributeError, TypeError)):
        value.skill = r.SkillSpec("help", "Reference", "Changed")


@pytest.mark.parametrize(
    "metadata",
    [
        True,
        [],
        {"extra": "x"},
        {"license": ""},
        {"compatibility": "x" * 501},
        {"metadata": {"n": 1}},
        {"metadata": {True: "x"}},
        {"metadata": {"x": "v" * 4097}},
        {"metadata": {"x" * 257: "v"}},
        {"metadata": {str(i): "x" for i in range(65)}},
        {"allowed-tools": "x" * 4097},
        {"license": "\u3000"},
        {"license": "\x00"},
    ],
)
def test_invalid_optional_metadata_refuses(metadata):
    Value, _ = api()
    with pytest.raises(RalfError):
        Value(r.SkillSpec("help", "Reference", "Original"), metadata)


def test_metadata_aggregate_limit_is_not_only_per_field():
    Value, _ = api()
    with pytest.raises(RalfError):
        Value(
            r.SkillSpec("help", "Reference", "Original"),
            {"metadata": {str(i): "x" * 4096 for i in range(20)}},
        )


def test_value_never_executes_custom_copy_hook():
    Value, _ = api()
    touched = []

    class Deferred(str):
        def __deepcopy__(self, memo):
            touched.append(True)
            return "forged"

    with pytest.raises(RalfError):
        Value(r.SkillSpec("help", "Reference", "Original"), {"license": Deferred("Apache")})
    assert touched == []


@pytest.mark.parametrize(
    "header,description",
    [
        ("name: help\ndescription: Reference", "Reference"),
        ("name: 'help'\ndescription: \"Quoted: 中文 🙂\"", "Quoted: 中文 🙂"),
        ("name: help\ndescription: |\n  First line\n  Second line", "First line\nSecond line\n"),
        ("name: help\ndescription: >-\n  First line\n  second line", "First line second line"),
    ],
)
def test_native_full_yaml_scalar_forms_preserve_markdown(header, description):
    value = parse(doc(header, "# Body\n\n原文 🙂\n"))
    assert value.skill.name == "help" and value.skill.description == description
    assert value.skill.instructions == "# Body\n\n原文 🙂\n"
    assert value.skill.version == "1"


@pytest.mark.parametrize(
    "ending,bom", [("\n", False), ("\r\n", False), ("\n", True), ("\r\n", True)]
)
def test_bom_and_crlf_frontmatter_are_accepted(ending, bom):
    text = doc().replace("\n", ending)
    value = parse(("\ufeff" if bom else "") + text)
    assert value.skill.instructions == "Original" + ending


def test_optional_standard_metadata_is_information_and_version_only():
    text = doc(
        'name: help\ndescription: Reference\nlicense: Apache-2.0\ncompatibility: Python\nallowed-tools: forbidden_danger\nmetadata:\n  author: app\n  version: "2"'
    )
    value = parse(text)
    assert value.skill.version == "2"
    assert value.to_dict()["metadata"]["allowed-tools"] == "forbidden_danger"
    assert value.skill.instructions == "Original\n"


@pytest.mark.parametrize(
    "header",
    [
        "name: other\ndescription: Reference",
        "name: Help\ndescription: Reference",
        "name: pdf--help\ndescription: Reference",
        "description: Reference",
        "name: help",
        "name: help\ndescription: true",
        "name: help\ndescription: null",
        "name: help\ndescription: ''",
        "name: help\ndescription: Reference\nextra: x",
        "name: help\ndescription: Reference\nmetadata:\n  version: 2",
        "name: help\ndescription: Reference\nmetadata:\n  version: ''",
        "name: help\ndescription: Reference\nname: help",
        "name: help\ndescription: Reference\nmetadata:\n  key: first\n  key: second",
        "name: help\ndescription: Reference\nmetadata:\n  ? [a,b]\n  : x",
        "name: help\ndescription: Reference\nmetadata: !!python/object/apply:os.system ['touch unsafe']",
    ],
)
def test_malformed_or_nonstandard_frontmatter_refuses(header):
    with pytest.raises(RalfError):
        parse(doc(header))


@pytest.mark.parametrize(
    "text",
    [
        "name: help\ndescription: Reference",
        "\n" + doc(),
        "---\nname: help\ndescription: Reference",
        doc(body=" \n"),
        doc().replace("---\nOriginal", "...\nOriginal"),
        doc("name: help\ndescription: Reference\n...\nname: help\ndescription: Second"),
        doc('name: help\ndescription: "\ud800"'),
    ],
)
def test_invalid_document_envelope_and_empty_body_refuse(text):
    with pytest.raises(RalfError):
        parse(text)


@pytest.mark.parametrize("version", [True, "", "\u3000", "x" * 257, "\x00"])
def test_parser_behavior_identity_requires_explicit_bounded_text(version):
    _, cls = api()
    with pytest.raises(ValidationError):
        cls(version=version)


def test_parser_identity_is_detached_and_pins_dependency_and_behavior():
    import yaml

    _, cls = api()
    parser = cls(version="app-1")
    identity = parser.identity
    assert identity["behavior_version"] == "app-1" and yaml.__version__ in str(identity)
    identity["behavior_version"] = "changed"
    assert parser.identity["behavior_version"] == "app-1"


@pytest.mark.parametrize("kind", ["alias", "cycle", "depth", "events", "header", "description"])
def test_yaml_work_and_input_limits_refuse_before_adoption(kind):
    if kind == "alias":
        header = "name: &name help\ndescription: Reference\nmetadata:\n" + "".join(
            f"  k{i}: *name\n" for i in range(33)
        )
    elif kind == "cycle":
        header = "name: help\ndescription: Reference\nmetadata: &cycle {x: *cycle}"
    elif kind == "depth":
        header = "name: help\ndescription: Reference\nmetadata: " + "[" * 17 + "x" + "]" * 17
    elif kind == "events":
        header = (
            "name: help\ndescription: Reference\nmetadata: ["
            + ",".join("x" for _ in range(4200))
            + "]"
        )
    elif kind == "header":
        header = "name: help\ndescription: Reference\n#" + "x" * 65536
    else:
        header = "name: help\ndescription: " + "字" * 1025
    with pytest.raises(RalfError):
        parse(doc(header))


def test_missing_optional_dependency_is_clear_and_does_not_change_core(monkeypatch):
    _, cls = api()
    original = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "yaml":
            raise ModuleNotFoundError("optional dependency unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_module)
    with pytest.raises(ValidationError, match="(?i)yaml|skills"):
        cls(version="1")
    assert r.SkillSpec("help", "Reference", "Original").name == "help"


def test_alias_cycle_is_refused_before_yaml_value_construction(monkeypatch):
    import yaml

    _, cls = api()
    parser = cls(version="1")
    calls = []
    original = yaml.load

    def load(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(yaml, "load", load)
    with pytest.raises(RalfError):
        parser.parse(
            doc("name: help\ndescription: Reference\nmetadata: &cycle {x: *cycle}"),
            parent_name="help",
        )
    assert calls == []


def test_markdown_body_can_include_horizontal_rules_and_frontmatter_like_text():
    body = "name: another\n\n---\n\ndescription: Documentation\n"
    assert parse(doc(body=body)).skill.instructions == body


def test_yaml_shared_alias_expansion_refuses_before_plain_copy(monkeypatch):
    import relf_agent.skill_documents as module

    parser = module.YamlSkillDocumentParser(version="1")
    original = module._plain
    copied = []

    def plain(value):
        if type(value) is dict and "name" in value:
            copied.append(True)
        return original(value)

    monkeypatch.setattr(module, "_plain", plain)
    text = "---\nname: help\ndescription: Reference\nmetadata:\n"
    text += "  a: &a [" + "x" * 4096 + "]\n"
    for number in range(1, 10):
        previous = "a" if number == 1 else f"a{number - 1}"
        text += f"  a{number}: &a{number} [*{previous}, *{previous}]\n"
    text += "---\nBody"
    with pytest.raises(module.ValidationError):
        parser.parse(text, parent_name="help")
    assert copied == []
