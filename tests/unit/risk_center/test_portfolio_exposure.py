"""Domain tests for conservative industry and ETF exposure bounds."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

import pytest

from apps.risk_center.domain.portfolio_exposure import (
    EffectiveEndState,
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    ExposureOutcome,
    IndustryExposurePolicy,
    IndustryMembership,
    PortfolioAssetKind,
    PortfolioExposureProjection,
    PortfolioRiskAsset,
    assess_portfolio_industry_exposure,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

BUSINESS_DATE = date(2026, 11, 3)
CUTOFF = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
PURPOSE = "portfolio_risk_daily"
INDUSTRY_COVERAGE_BASIS = "official_nav_weight"


def _coverage(
    *,
    fraction: Decimal = Decimal("1"),
    status: CoverageStatus = CoverageStatus.COMPLETE,
    expected: int | None = None,
    observed: int | None = None,
) -> PortfolioRiskCoverage:
    return PortfolioRiskCoverage(
        status=status,
        precision_basis=INDUSTRY_COVERAGE_BASIS,
        reported_weight_fraction=fraction,
        expected_item_count=expected,
        observed_item_count=observed,
    )


def _source(
    source_id: str,
    *,
    coverage: PortfolioRiskCoverage | None = None,
    precision: SourceObservationPrecision = SourceObservationPrecision.DATE,
    observed_on: date = BUSINESS_DATE,
    purpose: str = PURPOSE,
    allowed_purposes: tuple[str, ...] = (PURPOSE,),
    prohibited: bool = False,
    effective_on: date | None = None,
) -> PortfolioRiskSourceEvidence:
    available_at = CUTOFF - timedelta(hours=1)
    return PortfolioRiskSourceEvidence(
        source_id=source_id,
        source_record_id=f"record-{source_id}",
        original_payload_sha256=sha256(source_id.encode("utf-8")).hexdigest(),
        observation_precision=precision,
        observed_at=None if precision is SourceObservationPrecision.DATE else CUTOFF,
        observed_on=observed_on if precision is SourceObservationPrecision.DATE else None,
        available_at=available_at,
        known_at=available_at,
        decision_cutoff=CUTOFF,
        decision_date_cutoff=BUSINESS_DATE,
        valid_until=CUTOFF + timedelta(days=1),
        source_purpose=purpose,
        allowed_purposes=allowed_purposes,
        restrictions=(),
        must_not_use_for_decision=prohibited,
        coverage=coverage or _coverage(),
        effective_on=effective_on,
    )


def _policy(
    *,
    max_weight: Decimal = Decimal("0.30"),
    max_security_weight: Decimal = Decimal("0.30"),
    minimum_industry_coverage: Decimal = Decimal("0.80"),
    minimum_etf_coverage: Decimal = Decimal("0.70"),
    purpose: str = PURPOSE,
    date_purposes: tuple[str, ...] = (PURPOSE,),
) -> IndustryExposurePolicy:
    return IndustryExposurePolicy(
        policy_id="industry-risk",
        policy_version="2026-11-03.1",
        content_sha256="a" * 64,
        taxonomy_id="cn-industry-taxonomy",
        taxonomy_kind="industry",
        provider_id="official-sector-provider",
        provider_version="2026-10",
        effective_from=CUTOFF - timedelta(days=30),
        effective_until=CUTOFF + timedelta(days=30),
        known_at=CUTOFF - timedelta(days=2),
        requested_purpose=purpose,
        date_precision_purposes=date_purposes,
        allowed_observation_precisions=(
            SourceObservationPrecision.DATE,
            SourceObservationPrecision.TIMESTAMP,
        ),
        allowed_source_restrictions=(),
        coverage_precision_basis=INDUSTRY_COVERAGE_BASIS,
        max_industry_weight=max_weight,
        max_security_weight=max_security_weight,
        minimum_industry_coverage=minimum_industry_coverage,
        minimum_etf_lookthrough_coverage=minimum_etf_coverage,
        coverage_weight_tolerance=Decimal("0.001"),
    )


def _membership(
    industry_code: str,
    *,
    source_id: str,
    prohibited: bool = False,
    taxonomy_kind: str = "industry",
) -> IndustryMembership:
    effective_from = date(2025, 1, 1)
    return IndustryMembership(
        taxonomy_id="cn-industry-taxonomy",
        taxonomy_kind=taxonomy_kind,
        provider_id="official-sector-provider",
        provider_version="2026-10",
        industry_code=industry_code,
        effective_from=effective_from,
        effective_end_state=EffectiveEndState.OPEN,
        source_evidence=_source(
            source_id,
            prohibited=prohibited,
            effective_on=effective_from,
        ),
    )


def _equity(
    asset_code: str,
    value: str,
    industry_code: str,
    *,
    membership: IndustryMembership | None = None,
) -> PortfolioRiskAsset:
    return PortfolioRiskAsset(
        asset_code=asset_code,
        kind=PortfolioAssetKind.EQUITY,
        projected_market_value=Decimal(value),
        valuation_evidence=_source(f"valuation-{asset_code}"),
        industry_membership=membership
        or _membership(
            industry_code,
            source_id=f"membership-{asset_code}",
        ),
        etf_report=None,
    )


def _projection(*assets: PortfolioRiskAsset) -> PortfolioExposureProjection:
    return PortfolioExposureProjection(
        portfolio_snapshot_id="snapshot-2026-11-03",
        as_of=CUTOFF,
        business_date=BUSINESS_DATE,
        portfolio_market_value=Decimal("1000"),
        assets=assets,
    )


def test_direct_equities_in_one_industry_breach_the_versioned_limit() -> None:
    assessment = assess_portfolio_industry_exposure(
        policy=_policy(max_weight=Decimal("0.30")),
        projection=_projection(
            _equity("600001.SH", "200", "IND-A"),
            _equity("600002.SH", "150", "IND-A"),
        ),
    )

    assert assessment.outcome is ExposureOutcome.LIMIT_BREACHED
    assert assessment.industry_bounds[0].known_market_value == Decimal("350")
    assert assessment.industry_bounds[0].lower_weight == Decimal("0.35")
    assert "INDUSTRY_RISK_LIMIT_BREACHED" in assessment.reason_codes


def test_partial_etf_remainder_bounds_overlap_without_counting_the_fund_twice() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-510001",
            observed_on=date(2026, 6, 30),
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.85"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.60"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-member-a"),
            ),
            ETFConstituent(
                asset_code="600003.SH",
                weight_fraction=Decimal("0.15"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-B", source_id="etf-member-b"),
            ),
            ETFConstituent(
                asset_code="UNCLASSIFIED-OTHER",
                weight_fraction=Decimal("0.10"),
                kind=ETFConstituentKind.OTHER,
                industry_membership=None,
            ),
        ),
    )
    etf = PortfolioRiskAsset(
        asset_code="510001.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("valuation-510001"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(
            max_weight=Decimal("0.29"),
            minimum_industry_coverage=Decimal("0.90"),
            minimum_etf_coverage=Decimal("0.80"),
        ),
        projection=_projection(_equity("600001.SH", "200", "IND-A"), etf),
    )

    fund_bound = assessment.etf_bounds[0]
    industry_a = next(item for item in assessment.industry_bounds if item.industry_code == "IND-A")
    overlap = assessment.repeated_underlyings[0]
    assert fund_bound.known_industry_market_value == Decimal("75.00")
    assert fund_bound.unknown_market_value == Decimal("25.00")
    assert fund_bound.maximum_industry_market_value == Decimal("85.00")
    etf_industry_a = next(
        item for item in fund_bound.industry_bounds if item.industry_code == "IND-A"
    )
    assert etf_industry_a.known_market_value == Decimal("60.00")
    assert etf_industry_a.unknown_market_value == Decimal("25.00")
    assert etf_industry_a.upper_market_value == Decimal("85.00")
    assert fund_bound.known_security_market_value == Decimal("75.00")
    assert fund_bound.unknown_security_market_value == Decimal("25.00")
    assert fund_bound.maximum_security_market_value == Decimal("100.00")
    assert industry_a.known_market_value == Decimal("260.00")
    assert industry_a.upper_weight == Decimal("0.28500")
    security_a = next(item for item in assessment.security_bounds if item.asset_code == "600001.SH")
    assert security_a.known_market_value == Decimal("260.00")
    assert security_a.upper_weight == Decimal("0.28500")
    assert overlap.direct_market_value == Decimal("200")
    assert overlap.etf_market_value == Decimal("60.00")
    assert overlap.etf_asset_codes == ("510001.SH",)
    assert assessment.source_evidence
    assert all(item.original_payload_sha256 is not None for item in assessment.source_evidence)
    assert assessment.outcome is ExposureOutcome.WITHIN_LIMIT


def test_untrusted_etf_coverage_uses_the_whole_fund_as_unknown_and_blocks() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-510002",
            observed_on=date(2026, 6, 30),
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.80"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.60"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-member-c"),
            ),
        ),
    )
    asset = PortfolioRiskAsset(
        asset_code="510002.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("valuation-510002"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(asset),
    )

    fund_bound = assessment.etf_bounds[0]
    assert fund_bound.known_industry_market_value == Decimal("0")
    assert fund_bound.unknown_market_value == Decimal("100")
    assert fund_bound.maximum_industry_market_value == Decimal("100")
    assert fund_bound.unknown_security_market_value == Decimal("100")
    assert assessment.unknown_security_market_value == Decimal("100")
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "ETF_LOOKTHROUGH_COVERAGE_UNTRUSTED" in assessment.reason_codes


def test_date_precision_is_rejected_for_purposes_outside_the_explicit_allowlist() -> None:
    policy = replace(
        _policy(purpose="intraday_execution", date_purposes=()),
        allowed_observation_precisions=(SourceObservationPrecision.DATE,),
    )
    asset = PortfolioRiskAsset(
        asset_code="600001.SH",
        kind=PortfolioAssetKind.EQUITY,
        projected_market_value=Decimal("200"),
        valuation_evidence=_source(
            "valuation-intraday",
            purpose="official_disclosure",
            allowed_purposes=("intraday_execution",),
        ),
        industry_membership=None,
        etf_report=None,
    )
    assessment = assess_portfolio_industry_exposure(
        policy=policy,
        projection=_projection(asset),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "RISK_SOURCE_DATE_PRECISION_NOT_ALLOWED_FOR_PURPOSE" in assessment.reason_codes
    assert "PROJECTED_ASSET_VALUE_SOURCE_UNQUALIFIED" in assessment.reason_codes


def test_source_prohibition_blocks_an_industry_membership_even_when_value_is_known() -> None:
    asset = _equity(
        "600001.SH",
        "200",
        "IND-A",
        membership=_membership(
            "IND-A",
            source_id="prohibited-industry-fact",
            prohibited=True,
        ),
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(asset),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.unknown_industry_market_value == Decimal("200")
    assert "RISK_SOURCE_PROHIBITED_FOR_DECISION" in assessment.reason_codes


def test_index_membership_cannot_satisfy_an_industry_policy_binding() -> None:
    asset = _equity(
        "600001.SH",
        "200",
        "INDEX-A",
        membership=_membership(
            "INDEX-A",
            source_id="index-membership-fact",
            taxonomy_kind="index",
        ),
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(asset),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.industry_bounds == ()
    assert "INDUSTRY_SOURCE_POLICY_BINDING_MISMATCH" in assessment.reason_codes


def test_partial_coverage_below_policy_minimum_is_blocked_with_real_bounds() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-510003",
            observed_on=date(2026, 6, 30),
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
                industry_membership=_membership("IND-A", source_id="etf-member-d"),
            ),
        ),
    )
    asset = PortfolioRiskAsset(
        asset_code="510003.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("valuation-510003"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(
            minimum_industry_coverage=Decimal("0"),
            minimum_etf_coverage=Decimal("0.70"),
        ),
        projection=_projection(asset),
    )

    fund_bound = assessment.etf_bounds[0]
    assert fund_bound.known_industry_market_value == Decimal("40.00")
    assert fund_bound.unknown_market_value == Decimal("60.00")
    assert fund_bound.maximum_industry_market_value == Decimal("100.00")
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "ETF_LOOKTHROUGH_COVERAGE_BELOW_POLICY_MINIMUM" in assessment.reason_codes


def test_unknown_upper_bound_over_limit_is_not_reported_as_zero_or_pass() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-510004",
            observed_on=date(2026, 6, 30),
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.85"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.60"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-member-e"),
            ),
            ETFConstituent(
                asset_code="600003.SH",
                weight_fraction=Decimal("0.25"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-B", source_id="etf-member-f"),
            ),
        ),
    )
    asset = PortfolioRiskAsset(
        asset_code="510004.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("valuation-510004"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(
            max_weight=Decimal("0.27"),
            minimum_industry_coverage=Decimal("0.80"),
            minimum_etf_coverage=Decimal("0.80"),
        ),
        projection=_projection(_equity("600002.SH", "200", "IND-A"), asset),
    )

    industry_a = next(item for item in assessment.industry_bounds if item.industry_code == "IND-A")
    assert industry_a.lower_weight == Decimal("0.26")
    assert industry_a.upper_weight == Decimal("0.275")
    assert industry_a.outcome is ExposureOutcome.UNKNOWN
    assert assessment.outcome is ExposureOutcome.UNKNOWN
    assert "INDUSTRY_RISK_UPPER_BOUND_EXCEEDS_LIMIT" in assessment.reason_codes


def test_date_only_membership_never_gets_a_synthetic_time() -> None:
    membership = _membership("IND-A", source_id="date-only-membership")

    assert membership.source_evidence.observation_precision is SourceObservationPrecision.DATE
    assert membership.source_evidence.observed_at is None
    assert membership.source_evidence.observed_on == BUSINESS_DATE


def test_policy_cannot_allow_an_unconditional_source_restriction() -> None:
    with pytest.raises(ValueError, match="unconditional source prohibition"):
        replace(_policy(), allowed_source_restrictions=("research_only",))


def test_combined_direct_and_etf_security_exposure_can_breach_its_own_policy_cap() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-510005",
            observed_on=date(2026, 6, 30),
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("0.50"),
                status=CoverageStatus.PARTIAL,
            ),
        ),
        constituents=(
            ETFConstituent(
                asset_code="600001.SH",
                weight_fraction=Decimal("0.50"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=_membership("IND-A", source_id="etf-member-g"),
            ),
        ),
    )
    etf = PortfolioRiskAsset(
        asset_code="510005.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("300"),
        valuation_evidence=_source("valuation-510005"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(
            max_weight=Decimal("0.50"),
            max_security_weight=Decimal("0.30"),
            minimum_industry_coverage=Decimal("0.60"),
            minimum_etf_coverage=Decimal("0.40"),
        ),
        projection=_projection(_equity("600001.SH", "200", "IND-A"), etf),
    )

    industry_a = next(item for item in assessment.industry_bounds if item.industry_code == "IND-A")
    security_a = next(item for item in assessment.security_bounds if item.asset_code == "600001.SH")
    assert industry_a.lower_weight == Decimal("0.35")
    assert security_a.direct_market_value == Decimal("200")
    assert security_a.etf_lookthrough_market_value == Decimal("150.00")
    assert security_a.lower_weight == Decimal("0.35000")
    assert security_a.outcome is ExposureOutcome.LIMIT_BREACHED
    assert assessment.outcome is ExposureOutcome.LIMIT_BREACHED
    assert "SECURITY_RISK_LIMIT_BREACHED" in assessment.reason_codes
