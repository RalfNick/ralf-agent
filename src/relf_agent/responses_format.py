"""Pure explicit native strict-Schema subset, without remote reference resolution."""

from referencing import Registry
from referencing.exceptions import NoSuchResource

from .errors import ValidationError


def _deny_retrieval(uri):
    raise NoSuchResource(ref=uri)


LOCAL_SCHEMA_REGISTRY = Registry(retrieve=_deny_retrieval)

_ALLOWED = {
    "type",
    "$defs",
    "$ref",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "anyOf",
    "enum",
    "description",
    "title",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
}


def validate_strict_schema(schema):
    if schema.get("type") != "object" or "anyOf" in schema:
        raise ValidationError("Native structured output requires a root object")

    def visit(node, depth=0):
        if not isinstance(node, dict) or depth > 16 or set(node) - _ALLOWED:
            raise ValidationError("Schema exceeds the supported native subset")
        kind = node.get("type")
        # Schema-bearing keywords have meaning even without an explicit type.
        # Visit their contents independently before checking the native subset.
        if "properties" in node:
            for value in node["properties"].values():
                visit(value, depth + 1)
        if kind == "object" or isinstance(kind, list) and "object" in kind:
            properties = node.get("properties")
            if (
                not isinstance(properties, dict)
                or node.get("additionalProperties") is not False
                or set(node.get("required", [])) != set(properties)
            ):
                raise ValidationError(
                    "Native objects require all properties and reject additional properties"
                )
        elif "properties" in node or "required" in node or "additionalProperties" in node:
            raise ValidationError("Native object constraints require an explicit object type")
        if "$ref" in node:
            reference = node["$ref"]
            if not isinstance(reference, str) or not (
                reference == "#" or reference.startswith("#/")
            ):
                raise ValidationError("Native Schema references must be local")
            target = schema
            for part in reference[2:].split("/") if reference != "#" else []:
                key = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    raise ValidationError("Native Schema reference is unavailable")
                target = target[key]
            if not isinstance(target, dict):
                raise ValidationError("Native reference must resolve to a Schema")
        if "$defs" in node:
            for value in node["$defs"].values():
                visit(value, depth + 1)
        if "items" in node:
            visit(node["items"], depth + 1)
        if "anyOf" in node:
            for value in node["anyOf"]:
                visit(value, depth + 1)

    visit(schema)
