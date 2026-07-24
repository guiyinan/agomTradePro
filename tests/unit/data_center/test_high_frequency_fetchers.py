"""Risk-driven tests for high-frequency macro source parsing and failure paths."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.base import DataValidationError
from apps.data_center.infrastructure.macro_sources.fetchers.high_frequency_fetchers import (
    HighFrequencyIndicatorFetcher,
)


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


def _fetcher(ak, validate=lambda point: None) -> HighFrequencyIndicatorFetcher:
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
                "中国国债收益率10年": [1.8, 2.0, 9.9],
                "美国国债收益率10年": [4.2, 4.3, 9.9],
            }
        )

    fetcher = _fetcher(SimpleNamespace(bond_zh_us_rate=bond_zh_us_rate))

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
        _fetcher(ak).fetch_bond_yield(
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
            "中国国债收益率10年": [-1.0, 2.0],
        }
    )

    def reject_negative(point) -> None:
        if point.value < 0:
            raise DataValidationError("negative yield")

    points = _fetcher(
        SimpleNamespace(bond_zh_us_rate=lambda: frame),
        validate=reject_negative,
    ).fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 2))
    broken = _fetcher(
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
    fetcher = _fetcher(SimpleNamespace())
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
    fetcher = _fetcher(SimpleNamespace(bond_zh_us_rate=lambda: pd.DataFrame()))

    assert fetcher.fetch_term_spread() == []


def test_nhci_filters_range_and_skips_invalid_values() -> None:
    """Commodity index parsing accepts numeric rows and rejects invalid facts."""
    frame = pd.DataFrame(
        [
            ["2026-01-01", "100.5"],
            ["2026-01-02", "-1"],
            ["2026-01-03", "not-a-number"],
        ],
        columns=["日期", "指数"],
    )

    def reject_negative(point) -> None:
        if point.value < 0:
            raise DataValidationError("negative index")

    points = _fetcher(
        SimpleNamespace(macro_china_commodity_price_index=lambda: frame),
        validate=reject_negative,
    ).fetch_nhci(date(2026, 1, 1), date(2026, 1, 3))

    assert [(point.value, point.unit) for point in points] == [(100.5, "指数")]


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
    fetcher = _fetcher(SimpleNamespace(fx_spot_quote=lambda: frame))

    assert (
        fetcher.fetch_fx_center_rate(
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        == expected
    )


def test_fx_center_rate_returns_valid_current_quote() -> None:
    """The spot-only provider produces one explicitly sourced current fact."""
    frame = pd.DataFrame([["USD/CNY", "7.25"]], columns=["pair", "bid"])

    points = _fetcher(SimpleNamespace(fx_spot_quote=lambda: frame)).fetch_fx_center_rate(
        date.today(), date.today()
    )

    assert len(points) == 1
    assert points[0].code == "CN_FX_CENTER"
    assert points[0].value == 7.25
    assert points[0].observed_at == date.today()


def test_unavailable_high_frequency_series_are_explicit_noops() -> None:
    """Unsupported live series return no facts instead of fabricated substitutes."""
    fetcher = _fetcher(SimpleNamespace())
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
                "中国国债收益率10年": [2.0],
            }
        )

    fetcher = _fetcher(SimpleNamespace(bond_zh_us_rate=bond_zh_us_rate))
    fetcher.fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 1))
    fetcher.clear_cache()
    fetcher.fetch_bond_yield("10Y", date(2026, 1, 1), date(2026, 1, 1))

    assert calls["count"] == 2
