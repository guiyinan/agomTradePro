"""Alpha domain services."""

from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.rules import is_actionable_score, is_reliable_result


def select_actionable_scores(
    result: AlphaResult,
    *,
    min_score: float = 0.0,
    min_confidence: float = 0.5,
    max_staleness_days: int = 3,
) -> list[StockScore]:
    """Return actionable scores from a reliable Alpha result."""
    if not is_reliable_result(result, max_staleness_days=max_staleness_days):
        return []
    return [
        score
        for score in result.scores
        if is_actionable_score(score, min_score=min_score, min_confidence=min_confidence)
    ]
