"""Alpha application DTOs."""

from dataclasses import dataclass, field
from typing import Any

from apps.alpha.domain.entities import AlphaResult, StockScore


@dataclass(frozen=True)
class StockScoreDTO:
    """Serializable Alpha stock score."""

    code: str
    score: float
    rank: int
    factors: dict[str, float]
    source: str
    confidence: float

    @classmethod
    def from_domain(cls, score: StockScore) -> "StockScoreDTO":
        """Build a DTO from a stock score entity."""
        return cls(
            code=score.code,
            score=score.score,
            rank=score.rank,
            factors=dict(score.factors),
            source=score.source,
            confidence=score.confidence,
        )


@dataclass(frozen=True)
class AlphaResultDTO:
    """Serializable Alpha result."""

    success: bool
    source: str
    timestamp: str
    status: str
    scores: list[StockScoreDTO]
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_domain(cls, result: AlphaResult) -> "AlphaResultDTO":
        """Build a DTO from an Alpha result entity."""
        return cls(
            success=result.success,
            source=result.source,
            timestamp=result.timestamp,
            status=result.status,
            scores=[StockScoreDTO.from_domain(score) for score in result.scores],
            error_message=result.error_message,
            metadata=dict(result.metadata),
        )
