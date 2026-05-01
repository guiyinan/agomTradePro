"""Application-level query helpers for cross-app regime access."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.regime.application.repository_provider import build_macro_repository_adapter


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
