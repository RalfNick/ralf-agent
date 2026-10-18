"""Executable fingerprints for explicit pure Python plugin registrations.

No arbitrary object repr/state or globals are serialized. Captured configuration
must be JSON and immutable; other deployment dependencies belong in identity.
"""

import dis
import inspect
import types
from functools import lru_cache

from .errors import ValidationError
from .types import canonical, digest


def _constant(value):
    if type(value) is types.CodeType:
        return _code(value)
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) is complex:
        return {"complex": [value.real, value.imag]}
    if value is Ellipsis:
        return {"ellipsis": True}
    if type(value) is tuple or type(value) is frozenset:
        values = [_constant(v) for v in value]
        return {
            "kind": type(value).__name__,
            "values": sorted(values, key=canonical) if type(value) is frozenset else values,
        }
    if (
        value is None
        or type(value) is str
        or type(value) is int
        or type(value) is float
        or type(value) is bool
    ):
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


def _super_capture(cls, target, seen, depth):
    if not inspect.isclass(cls) or "super" not in target.__code__.co_names:
        raise ValidationError("Opaque class captures are not executable configuration")
    instructions = list(dis.get_instructions(target))
    for index, instruction in enumerate(instructions):
        if instruction.argval != "__class__" or instruction.opname not in {
            "LOAD_DEREF",
            "LOAD_CLASSDEREF",
            "STORE_DEREF",
            "DELETE_DEREF",
        }:
            continue
        # Python 3.12+ emits an implicit class/self pair for LOAD_SUPER_ATTR.
        # Bit 1 distinguishes explicit two-argument super from the compiler pair.
        if not (
            instruction.opname == "LOAD_DEREF"
            and index > 0
            and index + 2 < len(instructions)
            and instructions[index - 1].opname == "LOAD_GLOBAL"
            and instructions[index - 1].argval == "super"
            and instructions[index + 1].opname in {"LOAD_FAST", "LOAD_DEREF"}
            and target.__code__.co_argcount > 0
            and instructions[index + 1].argval == target.__code__.co_varnames[0]
            and (
                instructions[index + 1].opname == "LOAD_FAST"
                or instructions[index + 1].argval in target.__code__.co_cellvars
            )
            and instructions[index + 2].opname == "LOAD_SUPER_ATTR"
            and not instructions[index + 2].arg & 2
        ):
            raise ValidationError("Only the compiler closure for zero-argument super is supported")
    bases = []
    for base in cls.__mro__[1:]:
        methods = {}
        for name in target.__code__.co_names:
            value = vars(base).get(name)
            if value is None:
                continue
            descriptor = type(value).__name__
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            if not inspect.isfunction(value):
                raise ValidationError("super requires verifiable Python base methods")
            methods[name] = {
                "descriptor": descriptor,
                "function": _function(value, seen, depth + 1),
            }
        bases.append({"module": base.__module__, "name": base.__qualname__, "methods": methods})
    return {"super_class": {"module": cls.__module__, "name": cls.__qualname__, "bases": bases}}


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
            _super_capture(item, target, seen, depth)
            if name == "__class__"
            else {"function": _function(item, seen, depth + 1)}
            if inspect.isfunction(item)
            else item
            for name, item in zip(target.__code__.co_freevars, captured, strict=True)
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


def _plain_digest(code):
    """Reuse only immutable, uncaptured code; return no mutable cache value."""
    return digest(
        {
            "algorithm": "python-code-v1",
            "function": {
                "code": _code(code),
                "defaults": None,
                "keyword_defaults": None,
                "captured": [],
                "wrapped": None,
            },
        }
    )


_cached_plain_digest = lru_cache(maxsize=1024)(_plain_digest)


def _defaults_digest(code, defaults_snapshot, keyword_defaults_snapshot):
    """Reuse code with immutable snapshots of primitive JSON defaults only."""
    return digest(
        {
            "algorithm": "python-code-v1",
            "function": {
                "code": _code(code),
                "defaults": defaults_snapshot[1],
                "keyword_defaults": None
                if keyword_defaults_snapshot[1] is None
                else dict(keyword_defaults_snapshot[1]),
                "captured": [],
                "wrapped": None,
            },
        }
    )


_cached_defaults_digest = lru_cache(maxsize=1024)(_defaults_digest)
_DEFAULT_PRIMITIVES = (str, int, float, bool, type(None))
_DEFAULT_CACHE_CHARS = 8192


def _simple_defaults(defaults, keyword_defaults):
    # Complex JSON remains on the original path, including numeric dictionary keys.
    if (defaults is not None and type(defaults) is not tuple) or (
        keyword_defaults is not None and type(keyword_defaults) is not dict
    ):
        return False
    return all(
        any(type(value) is primitive for primitive in _DEFAULT_PRIMITIVES)
        for value in defaults or ()
    ) and all(
        type(key) is str and any(type(value) is primitive for primitive in _DEFAULT_PRIMITIVES)
        for key, value in (keyword_defaults or {}).items()
    )


def _cacheable_constant(value, depth=0):
    """Inspect exact immutable data before CodeType hashing can run callbacks.

    CodeType accepts arbitrary constants and some metadata subclasses. Even a
    cache miss hashes those objects before calling the pinned digest helper.
    Anything outside this bounded data tree stays on the original uncached path.
    """
    if depth > 64:
        return False
    kind = type(value)
    if (
        value is None
        or value is Ellipsis
        or kind is str
        or kind is int
        or kind is float
        or kind is bool
        or kind is bytes
        or kind is complex
    ):
        return True
    if kind is tuple or kind is frozenset:
        return all(_cacheable_constant(item, depth + 1) for item in value)
    if kind is not types.CodeType:
        return False
    if not all(
        type(item) is int
        for item in (
            value.co_argcount,
            value.co_posonlyargcount,
            value.co_kwonlyargcount,
            value.co_nlocals,
            value.co_stacksize,
            value.co_flags,
            value.co_firstlineno,
        )
    ) or not all(
        type(item) is bytes for item in (value.co_code, value.co_linetable, value.co_exceptiontable)
    ):
        return False
    if not all(type(item) is str for item in (value.co_name, value.co_filename, value.co_qualname)):
        return False
    if not all(
        type(names) is tuple and all(type(name) is str for name in names)
        for names in (value.co_names, value.co_varnames, value.co_freevars, value.co_cellvars)
    ):
        return False
    return type(value.co_consts) is tuple and _cacheable_constant(value.co_consts, depth + 1)


def _cache_helpers():
    return tuple(
        (
            method,
            getattr(method, "__code__", None),
            getattr(method, "__defaults__", None),
            None
            if getattr(method, "__kwdefaults__", None) is None
            else dict(method.__kwdefaults__),
            getattr(method, "__closure__", None),
            getattr(method, "__wrapped__", None),
        )
        for method in (
            _constant,
            _code,
            _function,
            canonical,
            digest,
            inspect.isfunction,
            _plain_digest,
            _cached_plain_digest,
            getattr(_cached_plain_digest, "__wrapped__", None),
            _defaults_digest,
            _cached_defaults_digest,
            getattr(_cached_defaults_digest, "__wrapped__", None),
            _simple_defaults,
            _cacheable_constant,
        )
    ) + ((types, types.CodeType), _DEFAULT_PRIMITIVES, _DEFAULT_CACHE_CHARS)


_CACHE_HELPERS = _cache_helpers()
_CACHE_GUARD = (_cache_helpers, _cache_helpers.__code__)


def executable_digest(method):
    try:
        target = getattr(method, "__func__", method)
        if (
            (_cache_helpers, getattr(_cache_helpers, "__code__", None)) == _CACHE_GUARD
            and _cache_helpers() == _CACHE_HELPERS
            and inspect.isfunction(target)
            and target.__closure__ is None
            and getattr(target, "__wrapped__", None) is None
            and _cacheable_constant(target.__code__)
        ):
            if target.__defaults__ is None and target.__kwdefaults__ is None:
                return _cached_plain_digest(target.__code__)
            if _simple_defaults(target.__defaults__, target.__kwdefaults__):
                # JSON strings distinguish equal Python primitives such as True/1
                # and positive/negative zero; snapshots retain no mutable defaults.
                defaults, keywords = target.__defaults__, target.__kwdefaults__
                defaults_json, keywords_json = canonical(defaults), canonical(keywords)
                if len(defaults_json) + len(keywords_json) <= _DEFAULT_CACHE_CHARS:
                    return _cached_defaults_digest(
                        target.__code__,
                        (defaults_json, defaults),
                        (
                            keywords_json,
                            None if keywords is None else tuple(sorted(keywords.items())),
                        ),
                    )
        return digest({"algorithm": "python-code-v1", "function": _function(method, set())})
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("Custom context captured configuration must be JSON") from None
