"""Semantic contract tests for high-frequency macro fetchers."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.fetchers import (
    high_frequency_fetchers as module,
)
from apps.data_center.infrastructure.macro_sources.fetchers.high_frequency_fetchers import (
    HighFrequencyIndicatorFetcher,
)


class FakeAkshare:
    """AKShare boundary fake with observable calls."""

    def __init__(self, bond_frame: pd.DataFrame) -> None:
        self.bond_frame = bond_frame
        self.fx_calls = 0
        self.commodity_calls = 0

    def bond_zh_us_rate(self) -> pd.DataFrame:
        return self.bond_frame

    def fx_spot_quote(self) -> pd.DataFrame:
        self.fx_calls += 1
        raise AssertionError("spot quote must not be used as central parity")

    def macro_china_commodity_price_index(self) -> pd.DataFrame:
        self.commodity_calls += 1
        raise AssertionError("a different commodity index must not be used as NHCI")


def _bond_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-07-01", "2026-07-02"],
            "中国国债收益率2年": [1.40, 1.41],
            "中国国债收益率5年": [1.55, 1.56],
            "中国国债收益率10年": [1.90, 1.91],
            "美国国债收益率10年": [4.20, 4.21],
            "US10Y misleading duplicate": [99.0, 99.0],
        }
    )


@pytest.fixture
def units(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "resolve_indicator_units",
        lambda indicator_code: ("%", "%"),
    )


def _fetcher(akshare: Any) -> HighFrequencyIndicatorFetcher:
    return HighFrequencyIndicatorFetcher(
        akshare,
        "akshare",
        lambda point: None,
        lambda points: sorted(points, key=lambda point: point.observed_at),
    )


def test_bond_yields_use_exact_country_and_term_columns(units: None) -> None:
    fetcher = _fetcher(FakeAkshare(_bond_frame()))

    cn_points = fetcher.fetch_bond_yield(
        "10Y",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )
    us_points = fetcher.fetch_bond_yield(
        "10Y",
        date(2026, 7, 1),
        date(2026, 7, 2),
        country="US",
    )

    assert [point.value for point in cn_points] == [1.90, 1.91]
    assert [point.value for point in us_points] == [4.20, 4.21]


def test_term_spread_is_derived_from_same_date_yields_in_basis_points(
    units: None,
) -> None:
    fetcher = _fetcher(FakeAkshare(_bond_frame()))

    points = fetcher.fetch_term_spread(
        "10Y",
        "2Y",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    assert [point.code for point in points] == ["CN_TERM_SPREAD_10Y2Y"] * 2
    assert [point.value for point in points] == pytest.approx([50.0, 50.0])


def test_bond_schema_drift_fails_closed(units: None) -> None:
    frame = _bond_frame().rename(columns={"中国国债收益率10年": "中国10年"})

    points = _fetcher(FakeAkshare(frame)).fetch_bond_yield(
        "10Y",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    assert points == []


def test_missing_bond_dataset_does_not_crash_dynamic_spread(units: None) -> None:
    points = _fetcher(FakeAkshare(pd.DataFrame())).fetch_term_spread(
        "10Y",
        "1Y",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    assert points == []


def test_mislabeled_commodity_and_fx_endpoints_are_not_called(units: None) -> None:
    akshare = FakeAkshare(_bond_frame())
    fetcher = _fetcher(akshare)

    assert fetcher.fetch_nhci(date(2026, 7, 1), date(2026, 7, 2)) == []
    assert fetcher.fetch_fx_center_rate(date(2026, 7, 1), date(2026, 7, 2)) == []
    assert akshare.commodity_calls == 0
    assert akshare.fx_calls == 0
