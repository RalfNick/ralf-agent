"""Immutable keyword-function bridge over the existing authorized tool executor."""

import copy
import inspect
import json
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .component_fingerprint import _code
from .errors import DefinitionMismatch, ValidationError
from .responses_format import LOCAL_SCHEMA_REGISTRY
from .tool_schema import default_values, function_signature, infer_tool_schema
from .types import canonical, digest


def _function_identity(function):
    target = getattr(function, "__func__", function)
    return {
        "module": target.__module__,
        "name": target.__qualname__,
        "code": digest(_code(target.__code__)),
    }


@dataclass(frozen=True, init=False)
class TypedFunctionHandler:
    function: object = field(repr=False)
    context_parameter: str | None
    _schema_json: str = field(repr=False)
    _defaults_json: str = field(repr=False)
    _function_json: str = field(repr=False)

    def __init__(self, function, schema, context_parameter):
        signature = function_signature(function, context_parameter)
        defaults = default_values(signature, context_parameter)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValidationError("Invalid typed tool Schema") from exc
        parameters = set(signature.parameters) - {context_parameter}
        if (
            not isinstance(schema, dict)
            or schema.get("type") != "object"
            or not isinstance(schema.get("properties"), dict)
            or set(schema["properties"]) != parameters
            or schema.get("additionalProperties") is not False
        ):
            raise ValidationError("Typed Schema must declare exactly the callable parameters")
        validator = Draft202012Validator(schema, registry=LOCAL_SCHEMA_REGISTRY)
        try:
            for name, value in defaults.items():
                if not validator.evolve(schema=schema["properties"][name]).is_valid(value):
                    raise ValidationError("Default does not match typed parameter Schema")
        except Exception as exc:
            raise ValidationError(
                "Typed defaults require locally resolvable parameter Schemas"
            ) from exc
        object.__setattr__(self, "function", function)
        object.__setattr__(self, "context_parameter", context_parameter)
        object.__setattr__(self, "_schema_json", canonical(schema))
        object.__setattr__(self, "_defaults_json", canonical(defaults))
        object.__setattr__(self, "_function_json", canonical(_function_identity(function)))

    @property
    def implementation_identity(self):
        return {
            "kind": "typed-python-function",
            "version": "1",
            "function": json.loads(self._function_json),
            "schema_digest": digest(json.loads(self._schema_json)),
            "defaults_digest": digest(json.loads(self._defaults_json)),
            "context_parameter": self.context_parameter,
            "bridge_code": digest(
                [_code(type(self).__call__.__code__), _code(type(self).resolve_arguments.__code__)]
            ),
        }

    def resolve_arguments(self, arguments):
        if canonical(_function_identity(self.function)) != self._function_json:
            raise DefinitionMismatch("Typed tool implementation changed")
        if not isinstance(arguments, dict) or self.context_parameter in arguments:
            raise ValidationError("Typed arguments cannot replace host context")
        validator = Draft202012Validator(
            json.loads(self._schema_json), registry=LOCAL_SCHEMA_REGISTRY
        )
        if not validator.is_valid(arguments):
            raise ValidationError("Typed arguments do not match Schema")
        values = {**json.loads(self._defaults_json), **copy.deepcopy(arguments)}
        if not validator.is_valid(values):
            raise ValidationError("Effective typed arguments do not match Schema")
        return values

    def __call__(self, arguments, context):
        values = self.resolve_arguments(arguments)
        if self.context_parameter is not None:
            values[self.context_parameter] = context
        return self.function(**values)


def register_function(
    registry,
    function,
    *,
    name=None,
    description=None,
    version="1",
    effect=None,
    requires_approval=False,
    cost=1,
    config=None,
    input_schema=None,
    context_parameter=None,
    reconciler=None,
):
    from .tools import ToolSpec

    if not isinstance(effect, str):
        raise ValidationError("Declare a supported string tool effect")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValidationError("Tool name must be non-empty text")
    if not isinstance(version, str) or not version.strip():
        raise ValidationError("Tool version must be non-empty text")
    if description is not None and not isinstance(description, str):
        raise ValidationError("Tool description must be text")
    if type(requires_approval) is not bool or (config is not None and not isinstance(config, dict)):
        raise ValidationError("Tool approval/config metadata has an invalid type")
    function_signature(function, context_parameter)
    schema = (
        infer_tool_schema(function, context_parameter=context_parameter)
        if input_schema is None
        else copy.deepcopy(input_schema)
    )
    handler = TypedFunctionHandler(function, schema, context_parameter)
    spec = ToolSpec(
        name or function.__name__,
        description if description is not None else (inspect.getdoc(function) or function.__name__),
        schema,
        version,
        effect,
        requires_approval,
        cost,
        {} if config is None else config,
    )
    registry.register(spec, handler, reconciler=reconciler)
    return function
