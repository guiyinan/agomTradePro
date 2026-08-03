"""T5 summary, placeholder, and function contracts for prompt macro data."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.prompt.infrastructure.adapters.macro_adapter import (
    FunctionExecutor,
    MacroDataAdapter,
)


def _adapter() -> MacroDataAdapter:
    """Build an adapter without constructing the ORM repository."""
    adapter = MacroDataAdapter.__new__(MacroDataAdapter)
    adapter.macro_repository = MagicMock()
    return adapter


def test_indicator_value_and_series_normalize_missing_and_timestamp_data() -> None:
    """Indicator reads must distinguish missing dates/rows and serialize series."""
    adapter = _adapter()
    adapter.macro_repository.get_latest_observation.return_value = None
    assert adapter.get_indicator_value("PMI") is None

    adapter.macro_repository.get_latest_observation.return_value = SimpleNamespace(value="51.2")
    assert adapter.get_indicator_value("PMI") == 51.2

    adapter.macro_repository.get_series.return_value = [
        SimpleNamespace(
            reporting_period=date(2026, 6, 1),
            value="50.1",
            published_at=datetime(2026, 6, 2),
        ),
        SimpleNamespace(
            reporting_period=date(2026, 7, 1),
            value=51.2,
            published_at=None,
        ),
    ]
    series = adapter.get_indicator_series(
        "PMI",
        date(2026, 6, 1),
        date(2026, 7, 1),
    )
    assert series == [
        {
            "date": "2026-06-01",
            "value": 50.1,
            "published_at": "2026-06-02T00:00:00",
        },
        {"date": "2026-07-01", "value": 51.2, "published_at": None},
    ]


def test_current_trend_requires_published_series_and_does_not_use_raw_facts() -> None:
    """Default/current trend reads fail closed when publication has no rows."""

    adapter = _adapter()
    adapter.macro_repository.get_latest_observation_date.return_value = date(2026, 7, 1)
    adapter.macro_repository.get_published_series.return_value = []
    adapter.macro_repository.get_series.return_value = [
        SimpleNamespace(reporting_period=date(2026, 6, 1), value=50.0, published_at=None),
        SimpleNamespace(reporting_period=date(2026, 7, 1), value=60.0, published_at=None),
    ]

    assert adapter._calculate_change("CN_PMI", None) == ("0.0", "stable")
    adapter.macro_repository.get_published_series.assert_called_once()
    adapter.macro_repository.get_series.assert_not_called()


def test_historical_trend_keeps_point_in_time_raw_series() -> None:
    """Explicit as-of trend reads retain PIT semantics for historical research."""

    adapter = _adapter()
    adapter.macro_repository.get_series.return_value = [
        SimpleNamespace(reporting_period=date(2026, 6, 1), value=50.0, published_at=None),
        SimpleNamespace(reporting_period=date(2026, 7, 1), value=60.0, published_at=None),
    ]

    result = adapter.calculate_trend("CN_PMI", "3m", date(2026, 7, 1))

    assert result["trend"] == "up"
    adapter.macro_repository.get_series.assert_called_once()
    adapter.macro_repository.get_published_series.assert_not_called()


def test_macro_summary_formats_up_down_stable_and_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Macro summaries must format trend words and handle no available indicators."""
    adapter = _adapter()
    values = {"CN_PMI": 51.2, "CN_CPI": 1.0, "OTHER": 3.0}
    trends = {
        "CN_PMI": ("+1.0", "up"),
        "CN_CPI": ("-0.2", "down"),
        "OTHER": ("0.0", "stable"),
    }
    monkeypatch.setattr(adapter, "get_indicator_value", lambda code, _date=None: values.get(code))
    monkeypatch.setattr(adapter, "_calculate_change", lambda code, _date=None: trends[code])

    result = adapter.get_macro_summary(
        date(2026, 7, 25),
        ["CN_PMI", "CN_CPI", "OTHER", "MISSING"],
    )
    assert result["as_of_date"] == "2026-07-25"
    assert result["indicators"]["PMI"]["trend"] == "up"
    assert "PMI为51.2，上升" in result["summary"]
    assert "CPI为1.0，下降" in result["summary"]
    assert "OTHER为3.0，持平" in result["summary"]

    monkeypatch.setattr(adapter, "get_indicator_value", lambda *_args: None)
    assert adapter.get_macro_summary(indicators=["MISSING"])["summary"] == ""


def test_placeholder_resolution_supports_special_direct_mapped_and_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder lookup must use summary, direct code, display name, then None."""
    adapter = _adapter()
    monkeypatch.setattr(adapter, "get_macro_summary", lambda _date=None: {"summary": "macro"})
    assert adapter.resolve_placeholder("MACRO_DATA") == {"summary": "macro"}

    def get_value(code: str, _date: date | None = None) -> float | None:
        return {"DIRECT": 1.0, "CN_PMI": 51.2}.get(code)

    monkeypatch.setattr(adapter, "get_indicator_value", get_value)
    assert adapter.resolve_placeholder("DIRECT") == 1.0
    assert adapter.resolve_placeholder("PMI") == 51.2
    assert adapter.resolve_placeholder("UNKNOWN") is None


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        ([], ("0.0", "stable")),
        ([{"value": 1}], ("0.0", "stable")),
        ([{"value": 1}, {"value": 2}], ("+1.0", "up")),
        ([{"value": 2}, {"value": 1}], ("-1.0", "down")),
        ([{"value": 1}, {"value": 1.005}], ("+0.0", "stable")),
    ],
)
def test_change_calculation_covers_missing_and_trend_thresholds(
    series: list[dict[str, float]],
    expected: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change calculation must use two observations and stable thresholds."""
    adapter = _adapter()
    adapter.macro_repository.get_latest_observation_date.return_value = (
        date(2026, 7, 1) if series else None
    )
    monkeypatch.setattr(adapter, "get_indicator_series", lambda *_args, **_kwargs: series)
    assert adapter._calculate_change("PMI", None) == expected


def test_function_executor_dispatches_latest_series_and_trend_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Function placeholders must validate parameters and classify trend percentages."""
    adapter = _adapter()
    executor = FunctionExecutor(adapter)
    calculator = MagicMock()
    executor.set_trend_calculator(calculator)
    assert executor.trend_calculator is calculator

    monkeypatch.setattr(adapter, "get_indicator_value", lambda *_args: 51.2)
    assert executor.execute_function("LATEST", {"indicator": "PMI"}) == 51.2
    with pytest.raises(ValueError, match="indicator"):
        executor.execute_function("LATEST", {})

    captured: list[tuple[date, date]] = []

    def series(
        _indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, float]]:
        captured.append((start_date, end_date))
        return [{"value": 100}, {"value": 102}]

    monkeypatch.setattr(adapter, "get_indicator_series", series)
    as_of = date(2026, 7, 25)
    assert (
        len(
            executor.execute_function(
                "SERIES",
                {"indicator": "PMI", "days": 10, "as_of_date": as_of},
            )
        )
        == 2
    )
    assert captured[-1] == (date(2026, 7, 15), as_of)
    with pytest.raises(ValueError, match="indicator"):
        executor.execute_function("SERIES", {})

    up = executor.execute_function(
        "TREND",
        {"indicator": "PMI", "period": "1m", "as_of_date": as_of},
    )
    assert up["trend"] == "up"
    assert up["change_pct"] == 2.0

    monkeypatch.setattr(
        adapter,
        "get_indicator_series",
        lambda *_args, **_kwargs: [{"value": 100}, {"value": 98}],
    )
    assert executor.execute_function("TREND", {"indicator": "PMI"})["trend"] == "down"
    monkeypatch.setattr(
        adapter,
        "get_indicator_series",
        lambda *_args, **_kwargs: [{"value": 0}, {"value": 0}],
    )
    assert executor.execute_function("TREND", {"indicator": "PMI"})["trend"] == "flat"
    monkeypatch.setattr(adapter, "get_indicator_series", lambda *_args, **_kwargs: [])
    assert executor.execute_function("TREND", {"indicator": "PMI"})["trend"] == "unknown"
    with pytest.raises(ValueError, match="indicator"):
        executor.execute_function("TREND", {})
    with pytest.raises(ValueError, match="Unknown"):
        executor.execute_function("UNSUPPORTED", {})
