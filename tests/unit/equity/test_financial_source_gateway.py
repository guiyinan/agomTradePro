"""Tests for the Data Center-backed equity financial gateway."""

from datetime import date
from decimal import Decimal

import pytest

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.equity.infrastructure import financial_source_gateway as gateway_module
from apps.equity.infrastructure.financial_source_gateway import TushareFinancialGateway


class _FactRepository:
    """Small financial fact repository fake for gateway tests."""

    def __init__(self, facts: list[FinancialFact]) -> None:
        self._facts = facts

    def get_facts(self, asset_code: str, *, limit: int) -> list[FinancialFact]:
        """Return configured facts while preserving the repository signature."""

        assert asset_code == "000001.SZ"
        assert limit >= 80
        return self._facts


@pytest.mark.parametrize("raw_value", ["NaN", "Infinity", "bad-value", None, ""])
def test_safe_decimal_rejects_invalid_or_non_finite_values(raw_value: object) -> None:
    """Invalid financial values should normalize to a finite zero."""

    assert TushareFinancialGateway._safe_decimal(raw_value) == Decimal("0")


def test_fetch_defaults_missing_optional_metrics_after_single_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sparse fact groups should produce a complete, typed financial record."""

    period_end = date(2025, 12, 31)
    facts = [
        FinancialFact(
            asset_code="000001.SZ",
            period_end=period_end,
            period_type=FinancialPeriodType.ANNUAL,
            metric_code="revenue",
            value=125.5,
            source="tushare",
            report_date=date(2026, 3, 20),
        )
    ]
    monkeypatch.setattr(
        gateway_module,
        "get_financial_fact_repository",
        lambda: _FactRepository(facts),
    )

    batch = TushareFinancialGateway(token="test-token").fetch("000001.SZ")

    assert batch.source_provider == "tushare"
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.report_date == date(2026, 3, 20)
    assert record.revenue == Decimal("125.5")
    assert record.net_profit == Decimal("0.0")
    assert record.revenue_growth is None
    assert record.roe == 0.0
    assert record.debt_ratio == 0.0
