"""Application-level sector score queries."""

from __future__ import annotations

from typing import Any

from apps.sector.application.repository_provider import get_sector_repository
from apps.sector.application.use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
)


def get_sector_score_payload(
    *,
    sector_identifier: str,
    regime: str | None = None,
    lookback_days: int = 20,
    level: str = "SW1",
) -> dict[str, Any] | None:
    """Return one sector's latest computed score from the rotation use case."""

    result = AnalyzeSectorRotationUseCase(get_sector_repository()).execute(
        AnalyzeSectorRotationRequest(
            regime=regime,
            lookback_days=lookback_days,
            level=level,
            top_n=1000,
        )
    )
    normalized = sector_identifier.strip()
    for score in result.top_sectors:
        if normalized in {score.sector_code, score.sector_name}:
            return {
                "rank": score.rank,
                "sector_code": score.sector_code,
                "sector_name": score.sector_name,
                "total_score": score.total_score,
                "momentum_score": score.momentum_score,
                "relative_strength_score": score.relative_strength_score,
                "regime_fit_score": score.regime_fit_score,
                "regime": result.regime,
                "analysis_date": result.analysis_date.isoformat(),
                "data_source": result.data_source,
            }
    return None
