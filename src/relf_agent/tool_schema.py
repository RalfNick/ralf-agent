"""Pure bounded JSON Schema inference; postponed annotations never execute code."""

import ast
import inspect
import json
import types
import typing

from jsonschema import Draft202012Validator

from .errors import ValidationError
from .types import canonical

_NAMES = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "None": type(None),
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "List": list,
    "Dict": dict,
    "Tuple": tuple,
    "Optional": typing.Optional,
    "Union": typing.Union,
    "Literal": typing.Literal,
    "Annotated": typing.Annotated,
}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
    ):
        return node.attr
    raise ValidationError("Annotation name requires an explicit Schema")


def _enum(values):
    if (
        not values
        or len(values) > 64
        or any(type(v) not in {str, int, float, bool, type(None)} for v in values)
    ):
        raise ValidationError("Literal requires bounded JSON scalar values")
    if len({type(v) for v in values}) != 1 or len({canonical(v) for v in values}) != len(values):
        raise ValidationError("Literal requires unique values of one JSON scalar type")
    return {"enum": list(values)}


def _generic(kind, parts):
    if kind is typing.Annotated and parts:
        return parts[0]
    if kind is typing.Optional and len(parts) == 1:
        return {"anyOf": [parts[0], {"type": "null"}]}
    if kind in {typing.Union, types.UnionType} and len(parts) >= 2:
        return {"anyOf": parts}
    if kind is list and len(parts) == 1:
        return {"type": "array", "items": parts[0]}
    if kind is dict and len(parts) == 2 and parts[0] == {"type": "string"}:
        return {"type": "object", "additionalProperties": parts[1]}
    if kind is tuple and parts:
        return {
            "type": "array",
            "prefixItems": parts,
            "minItems": len(parts),
            "maxItems": len(parts),
        }
    raise ValidationError("Annotation shape requires an explicit Schema")


def _node(node, depth):
    if depth > 16:
        raise ValidationError("Annotation exceeds nesting limit")
    if isinstance(node, ast.Constant) and node.value is None:
        return {"type": "null"}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _schema(node.value, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return {"anyOf": [_node(node.left, depth + 1), _node(node.right, depth + 1)]}
    if isinstance(node, ast.Subscript):
        kind = _NAMES.get(_name(node.value))
        parts = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if kind is typing.Literal:
            if any(not isinstance(n, ast.Constant) for n in parts):
                raise ValidationError("Literal must contain constants")
            return _enum([n.value for n in parts])
        if kind is typing.Annotated and len(parts) >= 2:
            return _node(parts[0], depth + 1)
        return _generic(kind, [_node(n, depth + 1) for n in parts])
    name = _name(node)
    if name not in _NAMES:
        raise ValidationError("Annotation name requires an explicit Schema")
    return _schema(_NAMES[name], depth + 1)


def _schema(annotation, depth=0):
    if depth > 16:
        raise ValidationError("Annotation exceeds nesting limit")
    if isinstance(annotation, str):
        if len(annotation) > 4096:
            raise ValidationError("Annotation exceeds text limit")
        try:
            tree = ast.parse(annotation, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise ValidationError("Invalid postponed annotation") from exc
        if sum(1 for _ in ast.walk(tree)) > 256:
            raise ValidationError("Annotation exceeds node limit")
        return _node(tree.body, depth + 1)
    scalar = {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}
    if annotation is None:
        return {"type": "null"}
    for python_type, json_type in scalar.items():
        if annotation is python_type:
            return {"type": json_type}
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return _enum(args)
    if origin is typing.Annotated:
        return _schema(args[0], depth + 1)
    return _generic(origin, [_schema(a, depth + 1) for a in args])


def function_signature(function, context_parameter=None):
    if not (inspect.isfunction(function) or inspect.ismethod(function)):
        raise ValidationError("Typed registration requires a Python function or bound method")
    signature = inspect.signature(function)
    if len(signature.parameters) > 64 or any(
        p.kind not in {p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY}
        for p in signature.parameters.values()
    ):
        raise ValidationError("Typed tools require bounded keyword-callable parameters")
    if context_parameter is not None and (
        not isinstance(context_parameter, str) or context_parameter not in signature.parameters
    ):
        raise ValidationError("Context parameter must name a function parameter")
    return signature


def default_values(signature, context_parameter=None):
    values = {}
    for name, p in signature.parameters.items():
        if name != context_parameter and p.default is not inspect.Parameter.empty:
            values[name] = json.loads(canonical(p.default))
    return values


def infer_tool_schema(function, *, context_parameter=None):
    signature = function_signature(function, context_parameter)
    properties, required = {}, []
    defaults = default_values(signature, context_parameter)
    for name, p in signature.parameters.items():
        if name == context_parameter:
            continue
        if p.annotation is inspect.Parameter.empty:
            raise ValidationError("Parameter requires a type annotation or explicit Schema")
        schema = _schema(p.annotation)
        if name in defaults and not Draft202012Validator(schema).is_valid(defaults[name]):
            raise ValidationError("Default does not match inferred parameter Schema")
        properties[name] = schema
        if p.default is inspect.Parameter.empty:
            required.append(name)
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if len(canonical(schema)) > 65536:
        raise ValidationError("Inferred Schema exceeds limit")
    return schema
