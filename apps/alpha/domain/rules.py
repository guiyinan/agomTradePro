"""Alpha domain rules."""

from apps.alpha.domain.entities import AlphaResult, StockScore


def is_actionable_score(
    score: StockScore, min_score: float = 0.0, min_confidence: float = 0.5
) -> bool:
    """Return whether a stock score is actionable under simple threshold rules."""
    return score.score > min_score and score.confidence >= min_confidence


def is_reliable_result(result: AlphaResult, max_staleness_days: int = 3) -> bool:
    """Return whether an Alpha result is fresh enough for downstream use."""
    if not result.success or result.status == "unavailable":
        return False
    if result.staleness_days is None:
        return True
    return result.staleness_days <= max_staleness_days
