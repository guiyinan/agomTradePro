from __future__ import annotations

from datetime import date

import pytest

from apps.filter.domain.entities import (
    FilterResult,
    FilterSeries,
    FilterType,
)
from apps.filter.infrastructure.models import FilterResultModel
from apps.filter.infrastructure.repositories import (
    DjangoFilterRepository,
    HPFilterAdapter,
)


def test_hp_adapter_uses_statsmodels_trend_not_cycle() -> None:
    adapter = HPFilterAdapter()
    adapter.hpfilter = lambda values, *, lamb: (
        [900.0] * len(values),
        [100.0 + index for index in range(len(values))],
    )

    result = adapter.filter_expanding([1.0, 2.0, 3.0, 4.0])

    assert result == [1.0, 2.0, 3.0, 103.0]


def test_hp_adapter_rejects_invalid_financial_inputs() -> None:
    adapter = HPFilterAdapter()

    with pytest.raises(ValueError, match="lambda"):
        adapter.filter_expanding([1.0, 2.0, 3.0, 4.0], lamb=float("nan"))
    with pytest.raises(ValueError, match="observations"):
        adapter.filter_expanding([1.0, 2.0, float("inf"), 4.0])


@pytest.mark.django_db
def test_repository_round_trips_zero_kalman_slope() -> None:
    repository = DjangoFilterRepository()
    series = FilterSeries(
        indicator_code="CN_TEST_ZERO_SLOPE",
        filter_type=FilterType.KALMAN,
        params={"level_variance": 0.1},
        results=[
            FilterResult(
                date=date(2026, 7, 1),
                original_value=10.0,
                filtered_value=9.5,
                trend=9.5,
                slope=0.0,
            )
        ],
        calculated_at=date(2026, 7, 2),
    )

    repository.save_filter_results(series)
    persisted = FilterResultModel._default_manager.get(indicator_code="CN_TEST_ZERO_SLOPE")
    restored = repository.get_filter_results(
        "CN_TEST_ZERO_SLOPE",
        FilterType.KALMAN,
    )

    assert persisted.trend_slope == 0
    assert restored[0].slope == 0.0


@pytest.mark.parametrize("limit", [0, -1, True, 2001])
@pytest.mark.django_db
def test_macro_indicator_query_rejects_invalid_limit(limit: int) -> None:
    repository = DjangoFilterRepository()

    with pytest.raises(ValueError, match="1 to 2000"):
        repository.get_macro_indicator_data("CN_PMI", limit=limit)


@pytest.mark.django_db
def test_macro_indicator_query_rejects_empty_code_and_reverse_dates() -> None:
    repository = DjangoFilterRepository()

    with pytest.raises(ValueError, match="indicator_code"):
        repository.get_macro_indicator_data(" ")
    with pytest.raises(ValueError, match="start_date"):
        repository.get_macro_indicator_data(
            "CN_PMI",
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
        )
