"""Completed full Facts reads at the private original Local adoption boundary.

This validates returned records, preserving finite extension provenance. It does
not alter the native Store inputs, bounded recall, validators or method identity.
"""

import inspect
import json

from .errors import ValidationError
from .recall import _fact_records
from .types import canonical


def facts_read_value(value):
    """Require a completed finite list of unique, versioned fact records."""
    if type(value) is not list or any(type(item) is not dict for item in value):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Facts read requires a completed list of records")
    try:
        return _fact_records(json.loads(canonical(value)))
    except (RecursionError, OverflowError) as exc:
        raise ValidationError("Facts read requires finite JSON records") from exc
