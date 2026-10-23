"""Finite UTF-8 result adoption shared by fixed business-tool transports."""

import json

from .types import canonical


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def decode_output(raw):
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    canonical(result).encode("utf-8")
    return result
