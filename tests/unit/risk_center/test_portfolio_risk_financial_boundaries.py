"""Financial boundaries for identity aggregation and configured account limits."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_exposure import (
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
)
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_snapshot import value_held_quantity
from apps.risk_center.domain.portfolio_risk_sources import CoverageStatus
from tests.unit.risk_center.test_portfolio_exposure import (
    BUSINESS_DATE,
    _coverage,
    _equity,
    _projection,
    _source,
)


def test_zero_quantity_has_known_zero_value_without_a_market_price() -> None:
    """An empty position does not need a price to establish zero exposure."""

    assert value_held_quantity(Decimal("0"), None) == Decimal("0")


def test_duplicate_portfolio_asset_rows_must_be_aggregated_before_projection() -> None:
    """The projection boundary rejects duplicate asset rows that could double-count NAV."""

    with pytest.raises(ValueError, match="aggregated by asset_code"):
        _projection(
            _equity("600001.SH", "100", "IND-A"),
            _equity("600001.SH", "50", "IND-A"),
        )


def test_duplicate_underlying_rows_in_one_etf_report_are_rejected() -> None:
    """Repeated constituent rows cannot inflate a security's reported ETF weight."""

    report_date = date(2026, 6, 30)
    source = _source(
        "etf-duplicate-constituent-report",
        observed_on=BUSINESS_DATE,
        effective_on=report_date,
        coverage=_coverage(fraction=Decimal("1"), status=CoverageStatus.COMPLETE),
    )

    with pytest.raises(ValueError, match="duplicate asset codes"):
        ETFConstituentReport(
            report_date=report_date,
            source_evidence=source,
            constituents=(
                ETFConstituent(
                    asset_code="600001.SH",
                    weight_fraction=Decimal("0.60"),
                    kind=ETFConstituentKind.EQUITY,
                    industry_membership=None,
                ),
                ETFConstituent(
                    asset_code="600001.SH",
                    weight_fraction=Decimal("0.40"),
                    kind=ETFConstituentKind.EQUITY,
                    industry_membership=None,
                ),
            ),
        )


def test_native_limits_keep_zero_and_one_as_valid_exact_fraction_boundaries() -> None:
    """Native account limits are fractions in [0, 1], including strict zero and full NAV."""

    limits = PortfolioRiskNativeAccountLimits(
        max_single_weight=Decimal("1"),
        max_total_weight=Decimal("0"),
        reason_codes=(),
        basis="simulated_account_percent_fields",
    )
    assert limits.max_single_weight == Decimal("1")
    assert limits.max_total_weight == Decimal("0")

    with pytest.raises(ValueError, match="max_total_weight"):
        PortfolioRiskNativeAccountLimits(
            max_single_weight=Decimal("1"),
            max_total_weight=Decimal("1.000001"),
            reason_codes=(),
            basis="simulated_account_percent_fields",
        )
