"""Financial boundary cases for portfolio-risk domain projections."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_capacity import CapacityValue
from apps.risk_center.domain.portfolio_exposure import (
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    ExposureOutcome,
    PortfolioAssetKind,
    PortfolioRiskAsset,
    assess_portfolio_industry_exposure,
)
from apps.risk_center.domain.portfolio_risk_identity import (
    IdentityBasis,
    PortfolioRiskIdentityBinding,
)
from apps.risk_center.domain.portfolio_risk_sources import CoverageStatus
from tests.unit.risk_center.test_portfolio_capacity import _evaluate as _evaluate_capacity
from tests.unit.risk_center.test_portfolio_capacity import _observation as _capacity_observation
from tests.unit.risk_center.test_portfolio_capacity import _order as _capacity_order
from tests.unit.risk_center.test_portfolio_capacity import _policy as _capacity_policy
from tests.unit.risk_center.test_portfolio_capacity import _usage as _capacity_usage
from tests.unit.risk_center.test_portfolio_exposure import (
    BUSINESS_DATE,
    _coverage,
    _equity,
    _membership,
)
from tests.unit.risk_center.test_portfolio_exposure import _policy as _industry_policy
from tests.unit.risk_center.test_portfolio_exposure import (
    _projection,
    _source,
)


@pytest.mark.parametrize(
    ("ledger_security_id", "source_security_id", "basis"),
    [
        (None, "security:600001", "ledger"),
        ("security:600001", "security:600002", "ledger"),
        ("security:600001", "security:600001", "pinned_policy_source_mapping"),
    ],
)
def test_identity_binding_cannot_omit_or_override_a_known_ledger_identity(
    ledger_security_id: str | None,
    source_security_id: str,
    basis: IdentityBasis,
) -> None:
    """Only an absent ledger identity may use a unique policy-pinned source mapping."""

    with pytest.raises(ValueError):
        PortfolioRiskIdentityBinding(
            asset_code="600001.SH",
            ledger_security_id=ledger_security_id,
            source_security_id=source_security_id,
            basis=basis,
        )


def test_pinned_identity_mapping_preserves_the_missing_ledger_identity() -> None:
    """A policy pin records the unresolved ledger field rather than inventing it."""

    binding = PortfolioRiskIdentityBinding(
        asset_code="600001.SH",
        ledger_security_id=None,
        source_security_id="cn-equity:SH:600001",
        basis="pinned_policy_source_mapping",
    )

    assert binding.ledger_security_id is None
    assert binding.source_security_id == "cn-equity:SH:600001"


def test_multiple_partial_etfs_aggregate_one_underlying_and_keep_each_residual_bounded() -> None:
    """ETF residuals remain conservative while a shared stock is counted once per fund."""

    report_one = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-one",
            observed_on=BUSINESS_DATE,
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.40"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.40"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-one-member"),
            ),
        ),
    )
    report_two = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-two",
            observed_on=BUSINESS_DATE,
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.25"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.25"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-two-member"),
            ),
        ),
    )
    etf_one = PortfolioRiskAsset(
        asset_code="510001.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("etf-one-valuation"),
        industry_membership=None,
        etf_report=report_one,
    )
    etf_two = PortfolioRiskAsset(
        asset_code="510002.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("200"),
        valuation_evidence=_source("etf-two-valuation"),
        industry_membership=None,
        etf_report=report_two,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_industry_policy(
            max_weight=Decimal("0.55"),
            max_security_weight=Decimal("0.55"),
            minimum_industry_coverage=Decimal("0.50"),
            minimum_etf_coverage=Decimal("0.20"),
        ),
        projection=_projection(
            _equity("600001.SH", "200", "IND-A"),
            etf_one,
            etf_two,
        ),
    )

    overlap = assessment.repeated_underlyings[0]
    security = assessment.security_bounds[0]
    assert assessment.outcome is ExposureOutcome.WITHIN_LIMIT
    assert assessment.unknown_industry_market_value == Decimal("210.00")
    assert overlap.direct_market_value == Decimal("200")
    assert overlap.etf_market_value == Decimal("90.00")
    assert overlap.etf_asset_codes == ("510001.SH", "510002.SH")
    assert security.known_market_value == Decimal("290.00")
    assert security.lower_weight == Decimal("0.29000")
    assert security.upper_weight == Decimal("0.50000")
    assert tuple(item.unknown_market_value for item in assessment.etf_bounds) == (
        Decimal("60.00"),
        Decimal("150.00"),
    )


def test_known_etf_security_without_industry_membership_is_not_unknown_security_value() -> None:
    """Unknown taxonomy widens industry risk while retaining exact named-security exposure."""

    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-known-security",
            observed_on=BUSINESS_DATE,
            effective_on=date(2026, 6, 30),
            coverage=_coverage(fraction=Decimal("1"), status=CoverageStatus.COMPLETE),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.60"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=None,
            ),
            ETFConstituent(
                asset_code="cash-component",
                weight_fraction=Decimal("0.40"),
                kind=ETFConstituentKind.CASH,
                industry_membership=None,
            ),
        ),
    )
    etf = PortfolioRiskAsset(
        asset_code="510003.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("etf-known-security-valuation"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_industry_policy(
            minimum_industry_coverage=Decimal("0"),
            minimum_etf_coverage=Decimal("0.70"),
        ),
        projection=_projection(etf),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "INDUSTRY_MEMBERSHIP_UNKNOWN" in assessment.reason_codes
    assert assessment.unknown_industry_market_value == Decimal("60.00")
    assert assessment.unknown_security_market_value == Decimal("0")
    assert len(assessment.security_bounds) == 1
    assert assessment.security_bounds[0].asset_code == "600001.SH"
    assert assessment.security_bounds[0].lower_weight == Decimal("0.06000")
    assert assessment.security_bounds[0].upper_weight == Decimal("0.06000")


@pytest.mark.parametrize(
    ("reported_volume", "expected_window_capacity"),
    [
        ("10000", "200"),
        ("10003", "200"),
        ("10013", "200.25"),
    ],
)
def test_capacity_floors_to_exact_increment_before_gross_session_usage(
    reported_volume: str,
    expected_window_capacity: str,
) -> None:
    """Floor the market budget to its increment, then count fills and both sides gross."""

    result = _evaluate_capacity(
        observation=_capacity_observation(
            volume=CapacityValue(Decimal(reported_volume), "share"),
        ),
        policy=_capacity_policy(
            participation=Decimal("0.10"),
            increment=Decimal("0.25"),
        ),
        usage=_capacity_usage(
            used=CapacityValue(Decimal("10.1"), "share"),
            active_orders=(
                _capacity_order(
                    "active-buy",
                    side="buy",
                    volume=CapacityValue(Decimal("20.2"), "share"),
                ),
                _capacity_order(
                    "active-sell",
                    side="sell",
                    volume=CapacityValue(Decimal("30.3"), "share"),
                ),
            ),
            proposed_orders=(
                _capacity_order(
                    "proposed-buy",
                    side="buy",
                    volume=CapacityValue(Decimal("200"), "share"),
                ),
            ),
        ),
    )

    expected_budget = Decimal(expected_window_capacity)
    expected_remaining = expected_budget - Decimal("10.1") - Decimal("20.2") - Decimal("30.3")
    assert result.window_capacity == expected_budget
    assert result.used_capacity == Decimal("10.1")
    assert result.reserved_buy_capacity == Decimal("20.2")
    assert result.reserved_sell_capacity == Decimal("30.3")
    assert result.remaining_capacity == expected_remaining
    assert result.allowed_new_capacity == expected_remaining
    assert result.status == "partial"
