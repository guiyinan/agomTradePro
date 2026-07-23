"""Contract tests for the AKShare macro routing adapter."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.infrastructure.macro_sources.akshare_adapter import (
    AKShareAdapter,
)
from apps.data_center.infrastructure.macro_sources.base import (
    DataSourceUnavailableError,
    DataValidationError,
    MacroDataPoint,
)


class _UniversalFetcher:
    """Return one canonical point for every routed fetch method."""

    def __init__(self, point: MacroDataPoint) -> None:
        self.point = point

    def __getattr__(self, name: str):
        if not name.startswith("fetch_"):
            raise AttributeError(name)

        def fetch(*args, **kwargs):
            return [self.point]

        return fetch


def _adapter_with_universal_fetchers(point: MacroDataPoint) -> AKShareAdapter:
    adapter = AKShareAdapter()
    fetcher = _UniversalFetcher(point)
    adapter._base_fetcher = fetcher
    adapter._economic_fetcher = fetcher
    adapter._trade_fetcher = fetcher
    adapter._financial_fetcher = fetcher
    adapter._other_fetcher = fetcher
    adapter._high_frequency_fetcher = fetcher
    adapter._weekly_fetcher = fetcher
    adapter._pmi_subitems_fetcher = fetcher
    return adapter


@pytest.mark.parametrize("indicator_code", sorted(AKShareAdapter.SUPPORTED_INDICATORS))
def test_every_supported_indicator_routes_to_canonical_points(indicator_code: str) -> None:
    point = MacroDataPoint(
        code=indicator_code,
        value=1.0,
        observed_at=date(2026, 7, 1),
        source="akshare",
    )
    adapter = _adapter_with_universal_fetchers(point)

    assert adapter.fetch(
        indicator_code,
        date(2026, 1, 1),
        date(2026, 7, 1),
    ) == [point]


@pytest.mark.parametrize(
    ("raw_points", "expected_detail"),
    [
        ({"code": "CN_PMI"}, "dict"),
        ([{"code": "CN_PMI"}], "第 0 项"),
    ],
)
def test_fetcher_result_must_match_macro_point_contract(
    raw_points: object,
    expected_detail: str,
) -> None:
    with pytest.raises(DataSourceUnavailableError, match=expected_detail):
        AKShareAdapter._require_macro_data_points("CN_PMI", raw_points)


def test_adapter_validation_and_deduplication_match_macro_contract() -> None:
    newer = MacroDataPoint(
        code="CN_PMI",
        value=50.1,
        observed_at=date(2026, 7, 1),
        source="akshare",
    )
    duplicate = MacroDataPoint(
        code="CN_PMI",
        value=49.9,
        observed_at=date(2026, 7, 1),
        source="akshare",
    )
    older = MacroDataPoint(
        code="CN_PMI",
        value=49.5,
        observed_at=date(2026, 6, 1),
        source="akshare",
    )

    AKShareAdapter._validate_data_point(newer)
    assert AKShareAdapter._sort_and_deduplicate([newer, older, duplicate]) == [
        older,
        newer,
    ]

    invalid = MacroDataPoint(
        code="",
        value=1.0,
        observed_at=date(2026, 7, 1),
        source="akshare",
    )
    with pytest.raises(DataValidationError, match="指标代码不能为空"):
        AKShareAdapter._validate_data_point(invalid)
