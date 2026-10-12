"""One final review pass: bounded public values and strict parser-result adoption."""

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError


@pytest.mark.parametrize("kind", ["shared_graph", "large_string", "too_many", "unknown"])
def test_public_metadata_rejects_before_recursive_copy(monkeypatch, kind):
    import ralf_agent.skill_documents as module

    node = "x"
    for _ in range(14):
        node = [node, node]
    metadata = {
        "shared_graph": {"metadata": {"key": node}},
        "large_string": {"license": "x" * 1048576},
        "too_many": {"metadata": {str(i): "x" for i in range(65)}},
        "unknown": {"unexpected": node},
    }[kind]
    calls, original = [], module._plain

    def plain(value, *args, **kwargs):
        calls.append(True)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(module, "_plain", plain)
    with pytest.raises(ValidationError):
        r.ParsedSkillDocument(r.SkillSpec("help", "Reference", "Body"), metadata)
    assert calls == []


def documents(root, count):
    paths = []
    for number in range(count):
        name = f"skill-{number}"
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text("tiny")
        paths.append(f"{name}/SKILL.md")
    return paths


@pytest.mark.parametrize("kind", ["per_document", "aggregate"])
def test_parsed_body_capacity_stops_before_next_parse(tmp_path, kind):
    calls = []
    payload = "x" * (1025 if kind == "per_document" else 16777216)

    class Parser:
        identity = {"kind": "expanding-review-parser", "version": "1"}

        def parse(self, text, *, parent_name):
            calls.append(parent_name)
            return r.ParsedSkillDocument(r.SkillSpec(parent_name, "Reference", payload))

    paths = documents(tmp_path, 6)
    with pytest.raises(ValidationError):
        r.FileSkillDocumentCatalog(
            tmp_path,
            version="1",
            paths=paths,
            parser=Parser(),
            max_bytes=1024 if kind == "per_document" else 16777216,
        )
    assert len(calls) == (1 if kind == "per_document" else 4)


@pytest.mark.parametrize(
    "kind", ["description", "version", "wrong_skill", "missing_skill", "metadata", "metadata_json"]
)
def test_malformed_exact_parser_results_refuse_at_adoption(tmp_path, monkeypatch, kind):
    import ralf_agent.filesystem_skill_documents as module

    paths = documents(tmp_path, 1)
    allocated, original = [], module.FileSystemWorkspace

    def allocate(*args, **kwargs):
        value = original(*args, **kwargs)
        allocated.append(value)
        return value

    monkeypatch.setattr(module, "FileSystemWorkspace", allocate)

    class Parser:
        identity = {"kind": "malformed-exact-result-parser", "version": "1"}

        def parse(self, text, *, parent_name):
            value = r.ParsedSkillDocument(r.SkillSpec(parent_name, "Reference", "Body"))
            if kind in {"description", "version"}:
                value.skill.__dict__[kind] = ""
            elif kind == "wrong_skill":
                value.__dict__["skill"] = object()
            elif kind == "missing_skill":
                del value.__dict__["skill"]
            else:
                value.__dict__["_metadata_json"] = (
                    '{"unexpected":"accepted"}' if kind == "metadata" else "[broken"
                )
            return value

    with pytest.raises(ValidationError):
        port = r.FileSkillDocumentCatalog(tmp_path, version="1", paths=paths, parser=Parser())
        port.close()  # close if a malformed result was incorrectly accepted
    assert allocated[0]._root_fd is None


@pytest.mark.parametrize("field", ["description", "version"])
def test_public_value_revalidates_nested_exact_skill(field):
    skill = r.SkillSpec("help", "Reference", "Body")
    skill.__dict__[field] = ""
    with pytest.raises(ValidationError):
        r.ParsedSkillDocument(skill)
