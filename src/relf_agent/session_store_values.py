"""Completed Session data values at the original Local adoption boundary.

These checks validate adapter outputs; they do not validate raw Store inputs or
change the published Store methods. A duplicate append may return an earlier
original revision than the revision observed immediately before its retry.
"""

import inspect
import json

from .errors import ValidationError
from .types import canonical


def _dispose(value):
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()


def session_read_value(value):
    """Require a completed full read and detach its finite dictionary messages."""
    if type(value) is not tuple or len(value) != 2:
        _dispose(value)
        raise ValidationError("Session read requires a completed revision/messages tuple")
    revision, messages = value
    if (
        type(revision) is not int
        or revision < 0
        or type(messages) is not list
        or any(type(message) is not dict for message in messages)
    ):
        _dispose(revision)
        _dispose(messages)
        raise ValidationError("Session read requires an integer revision and dictionary messages")
    try:
        messages = json.loads(canonical(messages))
    except (RecursionError, OverflowError) as exc:
        raise ValidationError("Session read messages require finite JSON data") from exc
    return revision, messages


def session_append_revision(value, observed_revision):
    """Accept a completed new-write or original duplicate revision, never a lazy ACK."""
    if (
        type(observed_revision) is not int
        or observed_revision < 0
        or type(value) is not int
        or not 1 <= value <= observed_revision + 1
    ):
        _dispose(value)
        raise ValidationError("Session append requires a completed committed revision")
    return value
