"""Executable fingerprints for explicit pure Python plugin registrations.

No arbitrary object repr/state or globals are serialized. Captured configuration
must be JSON and immutable; other deployment dependencies belong in identity.
"""

import inspect
import types

from .errors import ValidationError
from .types import canonical, digest


def _constant(value):
    if isinstance(value, types.CodeType):
        return _code(value)
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) is complex:
        return {"complex": [value.real, value.imag]}
    if value is Ellipsis:
        return {"ellipsis": True}
    if type(value) in {tuple, frozenset}:
        values = [_constant(v) for v in value]
        return {
            "kind": type(value).__name__,
            "values": sorted(values, key=canonical) if type(value) is frozenset else values,
        }
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ValidationError("Context implementation contains unsupported executable constants")


def _code(code):
    return {
        "bytecode": code.co_code.hex(),
        "constants": [_constant(c) for c in code.co_consts],
        "names": code.co_names,
        "locals": code.co_varnames,
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
        "args": [code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount],
        "flags": code.co_flags,
        "exceptiontable": code.co_exceptiontable.hex(),
    }


def _function(method, seen, depth=0):
    target = getattr(method, "__func__", method)
    if not inspect.isfunction(target):
        target = getattr(type(target), "__call__", None)  # noqa: B004 -- fingerprint the real callable-object entry point
    if not inspect.isfunction(target):
        raise ValidationError("Custom context registration requires verifiable Python code")
    if id(target) in seen or depth > 16:
        raise ValidationError("Context implementation capture/wrapper cycle or depth exceeded")
    seen.add(id(target))
    try:
        captured = (
            []
            if target.__closure__ is None
            else [cell.cell_contents for cell in target.__closure__]
        )
        captured = [
            {"function": _function(item, seen, depth + 1)} if inspect.isfunction(item) else item
            for item in captured
        ]
        wrapped = getattr(target, "__wrapped__", None)
        return {
            "code": _code(target.__code__),
            "defaults": target.__defaults__,
            "keyword_defaults": target.__kwdefaults__,
            "captured": captured,
            "wrapped": None if wrapped is None else _function(wrapped, seen, depth + 1),
        }
    finally:
        seen.remove(id(target))


def executable_digest(method):
    try:
        return digest({"algorithm": "python-code-v1", "function": _function(method, set())})
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("Custom context captured configuration must be JSON") from None
