"""Application-level query helpers for cross-app regime access."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.regime.application.repository_provider import (
    build_macro_repository_adapter,
    get_regime_diagnostic_repository,
    get_regime_repository,
)
from apps.regime.application.use_cases import (
    CalculateRegimeRequest,
    CalculateRegimeUseCase,
)


def get_regime_diagnostic_count() -> int:
    """Return regime log count for operational diagnostics."""

    return get_regime_diagnostic_repository().get_regime_count()


def get_latest_regime_observed_at() -> date | None:
    """Return latest regime observation date for operational diagnostics."""

    return get_regime_diagnostic_repository().get_latest_observed_at()


def get_latest_regime_cache_payload() -> dict[str, Any] | None:
    """Return the latest regime snapshot in cache-warmup payload shape."""

    latest = get_regime_repository().get_latest_snapshot()
    if latest is None:
        return None
    return {
        "regime": latest.dominant_regime,
        "observed_at": str(latest.observed_at),
        "confidence": latest.confidence,
    }


def get_latest_regime_diagnostic_payload() -> dict[str, Any] | None:
    """Return latest regime snapshot in data-connection diagnostic shape."""

    latest = get_regime_repository().get_latest_snapshot()
    if latest is None:
        return None
    return {
        "observed_at": latest.observed_at,
        "dominant_regime": latest.dominant_regime,
        "confidence": latest.confidence,
    }


def get_regime_distribution_payload(
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Return regime count and distribution for a date range."""

    snapshots = get_regime_repository().get_snapshots_in_range(
        start_date=start_date,
        end_date=end_date,
    )
    distribution: dict[str, int] = {}
    for snapshot in snapshots:
        distribution[snapshot.dominant_regime] = (
            distribution.get(snapshot.dominant_regime, 0) + 1
        )
    return {"count": len(snapshots), "distribution": distribution}


def calculate_regime_diagnostic_payload(as_of_date: date) -> dict[str, Any]:
    """Run the legacy regime calculation path for operational diagnostics."""

    result = CalculateRegimeUseCase(
        repository=build_macro_repository_adapter(),
        regime_repository=get_regime_repository(),
    ).execute(request=CalculateRegimeRequest(as_of_date=as_of_date))
    return {
        "success": result.success,
        "dominant_regime": result.snapshot.dominant_regime
        if result.snapshot is not None
        else None,
        "error": result.error,
    }


def get_growth_series(
    *,
    indicator_code: str,
    end_date: date,
    use_pit: bool = False,
    full: bool = False,
) -> list[Any]:
    """Return growth indicator series through the regime macro adapter boundary."""

    repo = build_macro_repository_adapter()
    series = (
        repo.get_growth_series_full(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
        )
        if full
        else repo.get_growth_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
        )
    )
    return list(series or [])


def get_inflation_series(
    *,
    indicator_code: str,
    end_date: date,
    use_pit: bool = False,
    full: bool = False,
) -> list[Any]:
    """Return inflation indicator series through the regime macro adapter boundary."""

    repo = build_macro_repository_adapter()
    series = (
        repo.get_inflation_series_full(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
        )
        if full
        else repo.get_inflation_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
        )
    )
    return list(series or [])
