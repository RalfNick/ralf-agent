"""Pure typed policy declaration for finite physical resource constants."""

import math

from .errors import DefinitionMismatch
from .types import canonical


def policy_value(value):
    """Preserve exact builtin types; executable subclasses are never policy data."""
    active = set()

    def walk(item, depth):
        if depth > 64:
            raise DefinitionMismatch("Coding resource policy exceeds its finite depth")
        kind = type(item)
        if item is None or kind in (str, bool, int):
            return item
        if kind is float:
            if not math.isfinite(item):
                raise DefinitionMismatch("Coding resource policy requires finite numbers")
            return item
        if kind not in (dict, list, tuple, frozenset):
            raise DefinitionMismatch("Coding resource policy requires exact builtin data")
        if id(item) in active:
            raise DefinitionMismatch("Coding resource policy cannot contain cycles")
        active.add(id(item))
        try:
            if kind is dict:
                if any(type(key) is not str for key in item):
                    raise DefinitionMismatch("Coding resource policy requires exact string keys")
                return {"dict": {key: walk(child, depth + 1) for key, child in item.items()}}
            result = [walk(child, depth + 1) for child in item]
            if kind is frozenset:
                result.sort(key=canonical)
            return {kind.__name__: result}
        finally:
            active.remove(id(item))

    return walk(value, 0)
