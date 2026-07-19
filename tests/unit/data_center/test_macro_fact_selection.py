"""Tests for canonical decision-series selection."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.entities import MacroFact
from apps.data_center.infrastructure.macro_fact_selection import (
    select_macro_fact_series,
)


def _fact(
    *,
    source: str,
    value: float,
    revision_number: int = 0,
    provider_name: str = "provider",
) -> MacroFact:
    return MacroFact(
        indicator_code="CN_TEST",
        reporting_period=date(2026, 7, 1),
        value=value,
        unit="%",
        source=source,
        revision_number=revision_number,
        fetched_at=datetime(2026, 7, 20, tzinfo=UTC),
        extra={"provider_name": provider_name, "source_type": source}
        if provider_name
        else {"source_type": source},
    )


def test_explicit_source_selects_canonical_revision_without_mixing_sources():
    selection = select_macro_fact_series(
        [
            _fact(source="akshare", value=10.0, revision_number=1, provider_name=""),
            _fact(source="akshare", value=1.0),
            _fact(source="tushare", value=1.1),
        ],
        preferred_source="akshare",
    )

    assert selection.is_consistent is True
    assert selection.source == "akshare"
    assert [fact.value for fact in selection.facts] == [1.0]


def test_unconfigured_inconsistent_sources_are_blocked():
    selection = select_macro_fact_series(
        [
            _fact(source="akshare", value=120.0),
            _fact(source="tushare", value=100.0),
        ],
        tolerance=0.01,
    )

    assert selection.is_consistent is False
    assert selection.facts == []
    assert selection.max_difference_ratio == pytest.approx(1 / 6)
    assert "disagree" in selection.blocked_reason


def test_unconfigured_consistent_sources_choose_one_complete_series():
    selection = select_macro_fact_series(
        [
            _fact(source="akshare", value=100.0),
            _fact(source="tushare", value=100.5),
        ],
        tolerance=0.01,
    )

    assert selection.is_consistent is True
    assert selection.source == "akshare"
    assert [fact.value for fact in selection.facts] == [100.0]
