"""New composition freezes declarations without rewriting legacy requests."""

from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError
from ralf_agent.types import submission_request


def api():
    assert hasattr(r, "AgentHarness"), "Missing additive AgentHarness composition"
    return r.AgentHarness, r.RunRef


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "bound"])
def test_composition_preserves_original_submission_and_detaches_schema(kind):
    Harness, _ = api()
    spec = r.AgentSpec("a", "A", output_schema={"type": "object"})
    original = {
        "agent": spec,
        "sequence": r.WorkflowSpec("s", [spec]),
        "graph": r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=spec)]),
        "team": r.TeamSpec("t", {"a": spec}),
        "dynamic": r.DynamicWorkflowSpec("d", {"a": spec}),
        "bound": r.AgentDefinition(spec, r.AgentBindingDescriptor()),
    }[kind]
    expected = submission_request(original, "q")
    harness = Harness(original)
    spec.output_schema["type"] = "integer"
    assert submission_request(harness.definition, "q") == expected
    if kind in {"agent", "bound"}:
        detached = harness.definition
        (detached.spec if kind == "bound" else detached).output_schema["type"] = "string"
        assert submission_request(harness.definition, "q") == expected


def test_large_native_schema_retains_legacy_supported_shape():
    Harness, _ = api()
    spec = r.AgentSpec("large", "A", output_schema={"description": "x" * 1100000})
    assert submission_request(Harness(spec).definition, "q") == submission_request(spec, "q")


def test_reference_exact_roundtrip_and_detachment():
    _, Ref = api()
    ref = Ref("local-fixture", "w", "p", "run", "a" * 64)
    value = ref.to_dict()
    value["run_id"] = "other"
    assert ref.run_id == "run"
    assert Ref.from_dict(asdict(ref)) == ref


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("release_digest", "bad"),
        ("run_id", ""),
        ("authority_locator", "https://user:secret@host"),
    ],
)
def test_invalid_locator_is_refused(field, value):
    _, Ref = api()
    record = {
        "schema_version": 1,
        "authority_locator": "local-fixture",
        "workspace": "w",
        "principal": "p",
        "run_id": "r",
        "release_digest": "a" * 64,
    }
    record[field] = value
    with pytest.raises(ValidationError):
        Ref.from_dict(record)


def test_unknown_reference_fields_are_refused():
    _, Ref = api()
    with pytest.raises(ValidationError):
        Ref.from_dict({"unknown": True})
