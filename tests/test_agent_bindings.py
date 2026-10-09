"""H1 declarations and scoped host registry; all fixtures are local."""

import importlib

import pytest

from ralf_agent import AgentSpec, ModelResponse, Scope, WorkflowSpec
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError


def api(name):
    try:
        return importlib.import_module("ralf_agent." + name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"H1 public module is missing: {exc.name}")


class Provider:
    def __init__(self, label="one"):
        self.label = label

    @property
    def identity(self):
        return {"kind": "binding-provider", "label": self.label, "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output=self.label)


def test_definitions_detach_nested_input_and_preserve_original_spec():
    values = api("binding_types")
    definitions = api("binding_definitions")
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    spec = AgentSpec("a", "Answer", output_schema=schema)
    source = {"mode": "ref", "component_id": "model-a", "version": "1"}
    bindings = values.AgentBindingDescriptor(provider=source)
    definition = definitions.AgentDefinition(spec, bindings)
    source["component_id"] = "changed"
    definition.spec.output_schema["type"] = "null"
    result = definition.to_dict()
    result["bindings"]["provider"]["component_id"] = "also changed"
    assert definition.to_dict()["bindings"]["provider"]["component_id"] == "model-a"
    assert definition.spec.output_schema["type"] == "object"
    assert spec.provider == "default"


@pytest.mark.parametrize(
    "source",
    [
        None,
        {"mode": "latest"},
        {"mode": "ref", "component_id": "a"},
        {"mode": "inherit", "version": "1"},
        {"mode": "disabled", "secret": "x"},
        {"mode": "ref", "component_id": "", "version": "1"},
    ],
)
def test_invalid_choice_fails_with_validation_error(source):
    values = api("binding_types")
    with pytest.raises(ValidationError):
        values.AgentBindingDescriptor(provider=source)


@pytest.mark.parametrize("role", ["provider", "decision_policy", "context"])
def test_required_role_cannot_disable(role):
    values = api("binding_types")
    with pytest.raises(ValidationError):
        values.AgentBindingDescriptor(**{role: values.BindingSelection.disabled()})


def test_unknown_role_and_nonfinite_selector_are_rejected():
    values = api("binding_types")
    with pytest.raises(ValidationError):
        values.AgentBindingDescriptor(execution_authority={"mode": "inherit"})
    with pytest.raises(ValidationError):
        values.BindingSelection.ref("model", "1", selector={"limit": float("nan")})


def test_definition_codec_roundtrips_versioned_wrapper_and_sequence_paths():
    values, definitions = api("binding_types"), api("binding_definitions")
    spec = AgentSpec("one", "Answer")
    bindings = values.AgentBindingDescriptor(provider=values.BindingSelection.ref("model", "1"))
    wrapped = definitions.AgentDefinition(spec, bindings)
    restored = definitions.decode_definition(wrapped.to_dict())
    assert restored.spec == spec
    assert restored.bindings.to_dict() == bindings.to_dict()
    sequence = WorkflowSpec("steps", [spec, AgentSpec("two", "Answer")])
    bound = definitions.BoundDefinition(sequence, {"sequence/steps/1": bindings})
    restored = definitions.decode_definition(bound.to_dict())
    assert restored.definition == sequence
    assert restored.agent_bindings["sequence/steps/1"].provider.component_id == "model"
    with pytest.raises(ValidationError):
        definitions.BoundDefinition(sequence, {"sequence/steps/8": bindings})
    with pytest.raises(ValidationError):
        definitions.decode_definition({**wrapped.to_dict(), "schema_version": True})
    with pytest.raises(ValidationError):
        definitions.decode_definition({**wrapped.to_dict(), "unexpected": "field"})


def test_catalog_scopes_reference_and_refuses_replacement():
    values, catalog_api = api("binding_types"), api("binding_catalog")
    scope = Scope("workspace", "principal")
    catalog = catalog_api.BindingCatalog(scope=scope)
    provider = Provider()
    catalog.register("provider", "model", "1", provider)
    selection = values.BindingSelection.ref("model", "1")
    component, record = catalog.resolve("provider", selection, scope)
    assert component is provider
    assert record["component_id"] == "model" and record["identity"]["label"] == "one"
    record["identity"]["label"] = "mutated"
    assert catalog.resolve("provider", selection, scope)[1]["identity"]["label"] == "one"
    with pytest.raises(AuthorizationDenied):
        catalog.resolve("provider", selection, Scope("other", "principal"))
    with pytest.raises(DefinitionMismatch):
        catalog.register("provider", "model", "1", Provider("different"))
    provider.label = "drifted"
    with pytest.raises(DefinitionMismatch):
        catalog.resolve("provider", selection, scope)


def test_catalog_rejects_unknown_role_lazy_context_and_unsafe_selector():
    values, catalog_api = api("binding_types"), api("binding_catalog")
    catalog = catalog_api.BindingCatalog(scope=Scope())
    with pytest.raises(ValidationError):
        catalog.register("policy", "allow", "1", object())

    class LazyContext:
        identity = {"kind": "lazy-context"}

        async def assemble(self, history, references, max_chars):
            return history, {}

    with pytest.raises(ValidationError):
        catalog.register("context", "ctx", "1", LazyContext())
    catalog.register("provider", "model", "1", Provider())
    with pytest.raises(ValidationError):
        catalog.resolve(
            "provider",
            values.BindingSelection.ref("model", "1", selector={"namespace": "x"}),
            Scope(),
        )


def test_tool_set_is_detached_and_names_cannot_repeat():
    values, catalog_api = api("binding_types"), api("binding_catalog")
    catalog = catalog_api.BindingCatalog(scope=Scope())
    names = ["read"]
    catalog.register("tool_set", "lookup", "1", names)
    names.append("write")
    component, _ = catalog.resolve("tool_set", values.BindingSelection.ref("lookup", "1"), Scope())
    assert component == ("read",)
    with pytest.raises(ValidationError):
        catalog.register("tool_set", "bad", "1", ["read", "read"])


@pytest.mark.parametrize("mode", [[], {}, 1, True])
def test_constructor_rejects_nonscalar_mode_with_public_error(mode):
    with pytest.raises(ValidationError):
        api("binding_types").BindingSelection(mode)


@pytest.mark.parametrize("role", [[], {}, None, True])
def test_catalog_rejects_nonscalar_role_with_public_error(role):
    catalog = api("binding_catalog").BindingCatalog(scope=Scope())
    with pytest.raises(ValidationError):
        catalog.register(role, "model", "1", Provider())
