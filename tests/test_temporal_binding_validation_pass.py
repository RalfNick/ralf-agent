"""A scoped Coding4 projection validates the original descriptor once per pass."""

import json
import sys
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, BindingSelection, Scope
from relf_agent.binding_types import AgentBindingDescriptor
from relf_agent.temporal_bindings import effective_manifest, validate_bindings, validate_descriptor
from relf_agent.types import canonical, submission_request
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest


def binding_inputs(*, composition=False):
    # A History wire is plain JSON, without Python fixture object aliases.
    manifest = json.loads(canonical(coding_session_manifest(composition=composition)))
    descriptor = AgentBindingDescriptor(runner=BindingSelection.ref("native", "1")).to_dict()
    request = submission_request(AgentSpec("agent", "Answer", tools=["coding"]), "question")
    request["agent_bindings"] = {"agent": descriptor}
    return request, manifest, asdict(Scope())


def descriptor_calls(operation):
    calls = 0
    code = validate_descriptor.__code__
    previous = sys.getprofile()

    def observe(frame, event, arg):
        nonlocal calls
        if event == "call" and frame.f_code is code:
            calls += 1

    sys.setprofile(observe)
    try:
        result = operation()
    finally:
        sys.setprofile(previous)
    return calls, result


@pytest.mark.parametrize("composition", [False, True])
def test_coding_four_combines_scoped_validation_and_projection(composition):
    request, manifest, scope = binding_inputs(composition=composition)
    before = canonical([request, manifest])
    expected = canonical(effective_manifest(manifest, request["agent_bindings"]["agent"]))
    calls, value = descriptor_calls(lambda: validate_bindings(request, manifest, scope))
    assert value is None
    assert calls == 2  # One scoped projection, one original selected_session_data read.
    assert canonical([request, manifest]) == before
    assert canonical(effective_manifest(manifest, request["agent_bindings"]["agent"])) == expected


def scoped_context_inputs():
    from tests.test_temporal_memory_bindings import setup

    request, manifest, scope = binding_inputs()
    original, _, _, _ = setup()
    manifest["binding_catalog"]["records"].update(
        json.loads(canonical(original.manifest["binding_catalog"]["records"]))
    )
    request["agent_bindings"]["agent"]["context"] = BindingSelection.ref("plain", "1").to_dict()
    return request, manifest, scope


@pytest.mark.parametrize("replace_public_projection", [False, True])
def test_foreign_scope_is_rejected_before_even_a_replaced_public_projection(
    monkeypatch, replace_public_projection
):
    from relf_agent import temporal_bindings as bindings
    from relf_agent.errors import AuthorizationDenied

    request, manifest, _ = scoped_context_inputs()
    called = []
    if replace_public_projection:
        monkeypatch.setattr(
            bindings, "effective_manifest", lambda *args, **kwargs: called.append(True) or {}
        )
    before = canonical([request, manifest])
    with pytest.raises(AuthorizationDenied, match="Scope"):
        bindings.validate_bindings(request, manifest, asdict(Scope(principal="foreign")))
    assert called == []
    assert canonical([request, manifest]) == before


@pytest.mark.parametrize("composition", [False, True])
def test_legacy_coding_three_keeps_both_validation_passes(composition):
    from relf_agent.temporal_deployment_protocol import CODING_SOURCE_FILES, validate_protocol

    request, manifest, scope = binding_inputs(composition=composition)
    manifest.pop("session_deployment_protocol")
    manifest["deployment_admission_protocol"].update(
        version=3, implementation={name: "e" * 64 for name in CODING_SOURCE_FILES}
    )
    validate_protocol(manifest)
    calls, value = descriptor_calls(lambda: validate_bindings(request, manifest, scope))
    assert value is None
    assert calls == 3


def test_default_binding_release_keeps_both_validation_passes():
    from tests.test_temporal_memory_bindings import setup

    runtime, _, _, _ = setup()
    request = submission_request(AgentSpec("agent", "Answer"), "question")
    request["agent_bindings"] = {"agent": AgentBindingDescriptor().to_dict()}
    calls, value = descriptor_calls(
        lambda: validate_bindings(request, runtime.manifest, asdict(Scope()))
    )
    assert value is None
    assert calls == 3


@pytest.mark.parametrize("where", ["request", "manifest", "selections", "descriptor"])
def test_custom_dict_inputs_keep_the_original_observable_validation_path(where):
    observed = []

    class ObservedDict(dict):
        def get(self, name, default=None):
            observed.append(name)
            return super().get(name, default)

    request, manifest, scope = binding_inputs()
    if where == "request":
        request = ObservedDict(request)
    elif where == "manifest":
        manifest = ObservedDict(manifest)
    elif where == "selections":
        request["agent_bindings"] = ObservedDict(request["agent_bindings"])
    else:
        request["agent_bindings"]["agent"] = ObservedDict(request["agent_bindings"]["agent"])
    calls, value = descriptor_calls(lambda: validate_bindings(request, manifest, scope))
    assert value is None
    assert calls == 3
    assert observed


@pytest.mark.parametrize("fault", ["native_version", "source_inventory"])
def test_public_projection_still_rejects_invalid_full_coding_declarations(fault):
    from relf_agent.errors import DefinitionMismatch

    request, manifest, scope = binding_inputs()
    if fault == "native_version":
        manifest["coding_execution_protocol"]["version"] = 7
    else:
        manifest["coding_execution_protocol"]["implementation"]["create_supervision"][
            "module_sources"
        ].pop("component_fingerprint")
    before = canonical([request, manifest])
    with pytest.raises(DefinitionMismatch):
        effective_manifest(manifest, request["agent_bindings"]["agent"], scope=scope)
    assert canonical([request, manifest]) == before


def test_public_scoped_projection_matches_original_projection_and_stays_detached():
    request, manifest, scope = scoped_context_inputs()
    descriptor = request["agent_bindings"]["agent"]
    before = canonical([request, manifest])
    original = effective_manifest(manifest, descriptor)
    projected = effective_manifest(manifest, descriptor, scope=scope)
    assert canonical(projected) == canonical(original)
    projected["tools"].clear()
    assert manifest["tools"]
    assert canonical([request, manifest]) == before


@pytest.mark.parametrize("fault", ["cycle", "alias", "nonfinite", "bound"])
def test_bounded_json_eligibility_falls_back_without_accepting_unusual_shapes(fault):
    from relf_agent.temporal_bindings import _plain_binding_inputs

    value = {}
    if fault == "cycle":
        value["cycle"] = value
    elif fault == "alias":
        shared = []
        value.update(first=shared, second=shared)
    elif fault == "nonfinite":
        value["number"] = float("inf")
    else:
        value["items"] = [None] * 32769
    assert _plain_binding_inputs(value, {}) is False


def test_custom_scope_keeps_the_original_observable_validation_path():
    comparisons = []

    class ObservedScope(dict):
        def __ne__(self, other):
            comparisons.append(True)
            return super().__ne__(other)

    request, manifest, scope = scoped_context_inputs()
    calls, value = descriptor_calls(
        lambda: validate_bindings(request, manifest, ObservedScope(scope))
    )
    assert value is None
    assert calls == 3
    assert comparisons


def test_absent_bindings_do_not_scan_the_coding_manifest_for_fast_path_eligibility():
    from relf_agent.temporal_bindings import _plain_binding_inputs

    request, manifest, scope = binding_inputs()
    request["agent_bindings"].clear()
    code = _plain_binding_inputs.__code__
    scanned = []
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call" and frame.f_code is code:
            scanned.append(True)

    sys.setprofile(observe)
    try:
        validate_bindings(request, manifest, scope)
    finally:
        sys.setprofile(previous)
    assert scanned == []
