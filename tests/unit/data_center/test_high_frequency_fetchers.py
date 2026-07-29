"""Semantic and risk-driven contracts for high-frequency macro fetchers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.base import DataValidationError
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


@pytest.fixture(autouse=True)
def deterministic_macro_metadata(monkeypatch) -> None:
    """Keep infrastructure tests independent from runtime metadata persistence."""
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.base.get_runtime_macro_publication_lags",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.high_frequency_fetchers.resolve_indicator_units",
        lambda code: (
            "BP" if "SPREAD" in code else ("指数" if code == "CN_NHCI" else "%"),
            "BP" if "SPREAD" in code else ("指数" if code == "CN_NHCI" else "%"),
        ),
    )


def _sort_points(points):
    return sorted(points, key=lambda point: point.observed_at)


def _risk_fetcher(ak, validate=lambda point: None) -> HighFrequencyIndicatorFetcher:
    return HighFrequencyIndicatorFetcher(
        ak=ak,
        source_name="akshare-test",
        validate_fn=validate,
        sort_dedup_fn=_sort_points,
    )


def test_bond_yield_maps_columns_filters_dates_and_reuses_cache() -> None:
    """Bond data is normalized once and date bounds are applied inclusively."""
    calls = {"count": 0}

    def bond_zh_us_rate():
        calls["count"] += 1
        return pd.DataFrame(
            {
                "日期": ["2026-01-01", "2026-01-02", "bad-date"],
                "中国国债收益率2年": [1.2, 1.3, 9.9],
                "中国国债收益率5年": [1.5, 1.6, 9.9],
                "中国国债收益率10年": [1.8, 2.0, 9.9],
                "美国国债收益率10年": [4.2, 4.3, 9.9],
            }
        )

    fetcher = _risk_fetcher(SimpleNamespace(bond_zh_us_rate=bond_zh_us_rate))

    cn_points = fetcher.fetch_bond_yield(
        "10Y",
        date(2026, 1, 2),
        date(2026, 1, 2),
    )
    us_points = fetcher.fetch_us_bond_10y(
        date(2026, 1, 1),
        date(2026, 1, 1),
    )

    assert calls["count"] == 1
    assert [(point.value, point.observed_at) for point in cn_points] == [(2.0, date(2026, 1, 2))]
    assert cn_points[0].unit == "%"
    assert us_points[0].value == 4.2
    assert us_points[0].source == "akshare-test"


def test_bond_yield_rejects_unknown_indicator_without_calling_provider() -> None:
    """Unsupported country/term combinations fail closed before network access."""
    ak = SimpleNamespace(
        bond_zh_us_rate=lambda: (_ for _ in ()).throw(AssertionError("provider must not be called"))
    )

    assert (
        _risk_fetcher(ak).fetch_bond_yield(
            "30Y",
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        == []
    )


def test_bond_yield_skips_validation_failure_and_provider_exception() -> None:
    """Invalid facts are skipped and an unavailable provider returns no facts."""
    frame = pd.DataFrame(
        {
            "日期": ["2026-01-01", "2026-01-02"],
            "中国国债收益率2年": [1.2, 1.3],
            "中国国债收益率5年": [1.5, 1.6],
            "中国国债收益率10年": [-1.0, 2.0],
            "美国国债收益率10年": [4.2, 4.3],
        }
    )

    def reject_negative(point) -> None:
        if point.value < 0:
            raise DataValidationError("negative yield")

    points = _risk_fetcher(
        SimpleNamespace(bond_zh_us_rate=lambda: frame),
        validate=reject_negative,
    ).fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 2))
    broken = _risk_fetcher(
        SimpleNamespace(
            bond_zh_us_rate=lambda: (_ for _ in ()).throw(ConnectionError("upstream unavailable"))
        )
    )

    assert [point.value for point in points] == [2.0]
    assert (
        broken.fetch_bond_yield(
            "10Y",
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        == []
    )


def test_term_spread_calculates_dynamic_pair_in_basis_points() -> None:
    """A non-precomputed curve pair is derived and converted from percent to BP."""
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "CN_BOND_10Y": [2.0, 2.1],
            "CN_BOND_1Y": [1.5, 1.4],
        }
    )
    fetcher = _risk_fetcher(SimpleNamespace())
    fetcher._bond_cache = frame

    points = fetcher.fetch_term_spread(
        long_term="10Y",
        short_term="1Y",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
    )

    assert len(points) == 1
    assert points[0].code == "CN_TERM_SPREAD_10Y1Y"
    assert points[0].value == pytest.approx(70.0)
    assert points[0].unit == "BP"


def test_term_spread_fails_closed_when_curve_data_is_missing() -> None:
    """Missing source data cannot produce a fabricated spread."""
    fetcher = _risk_fetcher(SimpleNamespace(bond_zh_us_rate=lambda: pd.DataFrame()))

    assert fetcher.fetch_term_spread() == []


def test_nhci_rejects_the_wrong_commodity_index_endpoint() -> None:
    """The generic commodity index must not be mislabeled as the NHCI series."""
    provider = SimpleNamespace(
        macro_china_commodity_price_index=lambda: (_ for _ in ()).throw(
            AssertionError("mislabeled provider must not be called")
        )
    )

    assert _risk_fetcher(provider).fetch_nhci(date(2026, 1, 1), date(2026, 1, 3)) == []


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (pd.DataFrame(), []),
        (pd.DataFrame([["EUR/CNY", "7.8"]]), []),
        (pd.DataFrame([["USD/CNY", "invalid"]]), []),
    ],
)
def test_fx_center_rate_rejects_empty_missing_and_malformed_quotes(
    frame: pd.DataFrame,
    expected: list[object],
) -> None:
    """A current FX quote is published only when USD/CNY is present and numeric."""
    fetcher = _risk_fetcher(SimpleNamespace(fx_spot_quote=lambda: frame))

    assert (
        fetcher.fetch_fx_center_rate(
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        == expected
    )


def test_fx_spot_quote_is_not_published_as_the_center_rate() -> None:
    """A spot bid/ask endpoint cannot stand in for the official center rate."""
    provider = SimpleNamespace(
        fx_spot_quote=lambda: (_ for _ in ()).throw(
            AssertionError("spot provider must not be called")
        )
    )

    assert _risk_fetcher(provider).fetch_fx_center_rate(date.today(), date.today()) == []


def test_unavailable_high_frequency_series_are_explicit_noops() -> None:
    """Unsupported live series return no facts instead of fabricated substitutes."""
    fetcher = _risk_fetcher(SimpleNamespace())
    start = date(2026, 1, 1)
    end = date(2026, 1, 2)

    assert fetcher.fetch_credit_spread(start, end) == []
    assert fetcher.fetch_corp_bond_yield("AAA", start, end) == []
    assert fetcher.fetch_usd_index(start, end) == []
    assert fetcher.fetch_vix_index(start, end) == []


def test_clear_cache_forces_next_bond_provider_call() -> None:
    """Cache invalidation is observable and does not retain stale bond data."""
    calls = {"count": 0}

    def bond_zh_us_rate():
        calls["count"] += 1
        return pd.DataFrame(
            {
                "日期": ["2026-01-01"],
                "中国国债收益率2年": [1.2],
                "中国国债收益率5年": [1.5],
                "中国国债收益率10年": [2.0],
                "美国国债收益率10年": [4.2],
            }
        )

    fetcher = _risk_fetcher(SimpleNamespace(bond_zh_us_rate=bond_zh_us_rate))
    fetcher.fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 1))
    fetcher.clear_cache()
    fetcher.fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 1))

    assert calls["count"] == 2
