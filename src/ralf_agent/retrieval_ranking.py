"""Pure rank/ID proposals preserve candidate bodies and authority ownership."""

import math
from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .retrieval import RetrievedChunk, _integer, _text, _tokens
from .types import canonical


@dataclass(frozen=True)
class FusionRank:
    chunk_id: str
    score: float

    def __post_init__(self):
        _text(self.chunk_id, "Rank candidate ID")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValidationError("Fusion score must be finite")
        try:
            score = float(self.score)
        except OverflowError:
            raise ValidationError("Fusion score must be finite") from None
        if not math.isfinite(score):
            raise ValidationError("Fusion score must be finite")
        object.__setattr__(self, "score", score)


class RankFusion(Protocol):
    identity: dict

    def fuse(
        self, rankings: dict[str, tuple[str, ...]], *, limit: int
    ) -> tuple[FusionRank, ...]: ...


class Reranker(Protocol):
    identity: dict

    def rerank(
        self, query: str, candidates: tuple[RetrievedChunk, ...], *, limit: int
    ) -> tuple[str, ...]: ...


class AsyncReranker(Protocol):
    identity: dict

    async def rerank(
        self, query: str, candidates: tuple[RetrievedChunk, ...], *, limit: int
    ) -> tuple[str, ...]: ...


class RRFFusion(_JsonValue):
    def __init__(self, *, rank_constant=60, weights=None):
        _integer(rank_constant, "Rank constant", minimum=1)
        if rank_constant > 1000000 or weights is not None and not isinstance(weights, dict):
            raise ValidationError("Invalid fusion configuration")
        weights = {} if weights is None else weights
        for name, weight in weights.items():
            _text(name, "Fusion branch")
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not 0 < weight <= 1000
            ):
                raise ValidationError("Fusion weights must be positive finite values <=1000")
        self._data_json = canonical(
            {"kind": "rrf", "version": "1", "rank_constant": rank_constant, "weights": weights}
        )

    @property
    def identity(self):
        return self.to_dict()

    def fuse(self, rankings, *, limit):
        _integer(limit, "Fusion limit", minimum=1)
        if limit > 256 or not isinstance(rankings, dict) or not 1 <= len(rankings) <= 8:
            raise ValidationError("Fusion requires bounded branch rankings")
        scores = {}
        config = self.to_dict()
        if set(config["weights"]) - set(rankings):
            raise ValidationError("Fusion weights name an unregistered branch")
        for name, ids in rankings.items():
            _text(name, "Ranking branch")
            if (
                not isinstance(ids, (tuple, list))
                or len(ids) > 256
                or any(not isinstance(k, str) or not k for k in ids)
                or len(set(ids)) != len(ids)
            ):
                raise ValidationError("Invalid duplicate/lazy ranking identities")
            for rank, key in enumerate(ids, 1):
                scores[key] = scores.get(key, 0) + config["weights"].get(name, 1) / (
                    config["rank_constant"] + rank
                )
        return tuple(
            FusionRank(key, value)
            for key, value in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        )


def _candidates(query, candidates, limit):
    _text(query, "Rerank query", empty=True)
    _integer(limit, "Rerank limit", minimum=1)
    if (
        limit > 256
        or not isinstance(candidates, (tuple, list))
        or len(candidates) > 256
        or any(not isinstance(c, RetrievedChunk) for c in candidates)
    ):
        raise ValidationError("Rerank requires bounded completed candidates")
    if len(set(c.chunk_id for c in candidates)) != len(candidates):
        raise ValidationError("Duplicate rerank candidates")


class PreserveOrderReranker:
    identity = {"kind": "preserve-order", "version": "1"}

    def rerank(self, query, candidates, *, limit):
        _candidates(query, candidates, limit)
        return tuple(c.chunk_id for c in candidates[:limit])


class TokenOverlapReranker:
    identity = {"kind": "token-overlap", "version": "1"}

    def rerank(self, query, candidates, *, limit):
        _candidates(query, candidates, limit)
        tokens = _tokens(query)
        return tuple(
            c.chunk_id
            for _, c in sorted(
                enumerate(candidates),
                key=lambda pair: (-len(tokens & _tokens(pair[1].text)), pair[0]),
            )[:limit]
        )
