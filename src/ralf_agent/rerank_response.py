"""Detached ranking proposals and explicit usage; never a business verdict."""

import math

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .types import canonical


def finite_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("Rerank score must be finite numeric data")
    try:
        value = float(value)
    except OverflowError:
        raise ValidationError("Rerank score must be finite numeric data") from None
    if not math.isfinite(value):
        raise ValidationError("Rerank score must be finite numeric data")
    return value


def rerank_usage(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"search_units"}:
        raise ValidationError("Rerank usage requires search_units")
    units = finite_score(value["search_units"])
    if units < 0:
        raise ValidationError("Rerank search units must be nonnegative")
    return {"search_units": units}


class RerankResponse(_JsonValue):
    def __init__(self, ids, scores, usage=None):
        if (
            not isinstance(ids, (list, tuple))
            or len(ids) > 256
            or any(not isinstance(k, str) or not k.strip() for k in ids)
            or len(set(ids)) != len(ids)
            or not isinstance(scores, (list, tuple))
            or len(scores) != len(ids)
        ):
            raise ValidationError(
                "Rerank report requires unique bounded IDs and corresponding scores"
            )
        scores = [finite_score(score) for score in scores]
        if any(a < b for a, b in zip(scores, scores[1:], strict=False)):
            raise ValidationError("Rerank scores must follow descending response order")
        self._data_json = canonical(
            {"ids": list(ids), "scores": scores, "usage": rerank_usage(usage)}
        )
