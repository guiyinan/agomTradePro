"""Domain tests for conservative industry and ETF exposure bounds."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
    _source_qualification_reasons,
    assess_portfolio_industry_exposure,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _AS_OF as ETF_AS_OF,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _BUSINESS_DATE as ETF_BUSINESS_DATE,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _PURPOSE as ETF_PURPOSE,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _evidence as _etf_report_evidence,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _qualification as _qualify_etf_report_clock,
)
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _report as _etf_report,
)
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _AS_OF as TIMESTAMP_AS_OF,
)
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _BUSINESS_DATE as TIMESTAMP_BUSINESS_DATE,
)
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _PURPOSE as TIMESTAMP_PURPOSE,
)
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _evidence as _timestamp_valuation_evidence,
)
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _qualify as _qualify_timestamp_valuation,
)

BUSINESS_DATE = date(2026, 11, 3)
CUTOFF = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
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
    allowed_source_restrictions: tuple[str, ...] = (),
    coverage_precision_basis: str = INDUSTRY_COVERAGE_BASIS,
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
        allowed_source_restrictions=allowed_source_restrictions,
        coverage_precision_basis=coverage_precision_basis,
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


def test_complete_coverage_rejects_inconsistent_explicit_item_counts() -> None:
    with pytest.raises(ValueError, match="complete coverage item counts must match"):
        PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis=INDUSTRY_COVERAGE_BASIS,
            reported_weight_fraction=Decimal("1"),
            expected_item_count=2,
            observed_item_count=1,
        )


def test_complete_coverage_keeps_absent_item_counts_unknown() -> None:
    coverage = PortfolioRiskCoverage(
        status=CoverageStatus.COMPLETE,
        precision_basis=INDUSTRY_COVERAGE_BASIS,
        reported_weight_fraction=Decimal("1"),
        expected_item_count=None,
        observed_item_count=None,
    )

    assert coverage.expected_item_count is None
    assert coverage.observed_item_count is None


def test_typed_timestamp_valuation_proof_is_qualified_by_its_source_role() -> None:
    source_evidence = _timestamp_valuation_evidence()
    timestamp_qualification = _qualify_timestamp_valuation(evidence=source_evidence)
    assert timestamp_qualification.qualified is True, timestamp_qualification.reason_codes
    proof = timestamp_qualification.proof
    assert proof is not None
    qualified_evidence = replace(source_evidence, policy_clock_proof=proof)
    membership = _membership("IND-A", source_id="membership-timestamp-proof")
    membership_evidence = replace(
        _source(
            "membership-timestamp-proof",
            purpose=TIMESTAMP_PURPOSE,
            allowed_purposes=(TIMESTAMP_PURPOSE,),
            effective_on=membership.effective_from,
        ),
        decision_cutoff=TIMESTAMP_AS_OF,
        decision_date_cutoff=TIMESTAMP_BUSINESS_DATE,
    )
    membership = replace(membership, source_evidence=membership_evidence)
    asset = PortfolioRiskAsset(
        asset_code="600036.SH",
        kind=PortfolioAssetKind.EQUITY,
        projected_market_value=Decimal("200"),
        valuation_evidence=qualified_evidence,
        industry_membership=membership,
        etf_report=None,
    )
    policy = _policy(
        purpose=TIMESTAMP_PURPOSE,
        date_purposes=(TIMESTAMP_PURPOSE,),
    )
    projection = PortfolioExposureProjection(
        portfolio_snapshot_id="snapshot-timestamp-valuation-proof",
        as_of=TIMESTAMP_AS_OF,
        business_date=TIMESTAMP_BUSINESS_DATE,
        portfolio_market_value=Decimal("1000"),
        assets=(asset,),
    )

    assessment = assess_portfolio_industry_exposure(policy=policy, projection=projection)

    assert assessment.industry_bounds[0].known_market_value == Decimal("200")
    assert "PROJECTED_ASSET_VALUE_SOURCE_UNQUALIFIED" not in assessment.reason_codes
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" not in assessment.reason_codes

    wrong_role_reasons = _source_qualification_reasons(
        evidence=qualified_evidence,
        policy=policy,
        as_of=TIMESTAMP_AS_OF,
        business_date=TIMESTAMP_BUSINESS_DATE,
        expected_source_kind="industry_membership",
    )
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in wrong_role_reasons


def test_disclosed_etf_clock_proof_is_qualified_and_keeps_partial_remainder() -> None:
    etf_evidence = _etf_report_evidence()
    report = _etf_report(etf_evidence)
    qualification = _qualify_etf_report_clock(evidence=etf_evidence, report=report)
    assert qualification.reason_codes == (), qualification.reason_codes
    proof = qualification.proof
    assert proof is not None
    qualified_evidence = replace(etf_evidence, policy_clock_proof=proof)
    qualified_report = replace(report, source_evidence=qualified_evidence)
    valuation_evidence = replace(
        _source(
            "valuation-510050",
            purpose=ETF_PURPOSE,
            allowed_purposes=(ETF_PURPOSE,),
        ),
        observed_on=ETF_BUSINESS_DATE,
        decision_cutoff=ETF_AS_OF,
        decision_date_cutoff=ETF_BUSINESS_DATE,
    )
    asset = PortfolioRiskAsset(
        asset_code="510050.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=valuation_evidence,
        industry_membership=None,
        etf_report=qualified_report,
    )
    policy = _policy(
        purpose=ETF_PURPOSE,
        date_purposes=(ETF_PURPOSE,),
        minimum_etf_coverage=Decimal("0.80"),
        allowed_source_restrictions=("close_snapshot_only",),
        coverage_precision_basis="portfolio_weight",
    )
    projection = PortfolioExposureProjection(
        portfolio_snapshot_id="snapshot-disclosed-etf-proof",
        as_of=ETF_AS_OF,
        business_date=ETF_BUSINESS_DATE,
        portfolio_market_value=Decimal("100"),
        assets=(asset,),
    )

    assessment = assess_portfolio_industry_exposure(policy=policy, projection=projection)

    bound = assessment.etf_bounds[0]
    assert bound.reported_coverage_fraction == Decimal("0.4456")
    assert bound.unknown_market_value == Decimal("100")
    assert "ETF_LOOKTHROUGH_COVERAGE_BELOW_POLICY_MINIMUM" in assessment.reason_codes
    assert "ETF_LOOKTHROUGH_SOURCE_UNQUALIFIED" not in assessment.reason_codes
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" not in bound.reason_codes
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" not in bound.reason_codes

    wrong_role_reasons = _source_qualification_reasons(
        evidence=qualified_evidence,
        policy=policy,
        as_of=ETF_AS_OF,
        business_date=ETF_BUSINESS_DATE,
        expected_source_kind="valuation",
    )
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in wrong_role_reasons


def test_industry_nav_coverage_minimum_still_rejects_unclassified_market_value() -> None:
    """Known row-count-complete memberships do not waive the portfolio NAV floor."""

    unclassified_asset = PortfolioRiskAsset(
        asset_code="600002.SH",
        kind=PortfolioAssetKind.EQUITY,
        projected_market_value=Decimal("500"),
        valuation_evidence=_source("valuation-unclassified-600002"),
        industry_membership=None,
        etf_report=None,
    )
    assessment = assess_portfolio_industry_exposure(
        policy=_policy(
            max_weight=Decimal("1"),
            max_security_weight=Decimal("1"),
            minimum_industry_coverage=Decimal("0.90"),
        ),
        projection=_projection(
            _equity("600001.SH", "500", "C070101"),
            unclassified_asset,
        ),
    )

    assert assessment.industry_coverage_fraction == Decimal("0.5")
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "INDUSTRY_CLASSIFICATION_COVERAGE_BELOW_POLICY_MINIMUM" in assessment.reason_codes


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
                expected=4,
                observed=3,
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


def test_complete_etf_report_with_missing_disclosed_rows_is_fully_unknown() -> None:
    report = ETFConstituentReport(
        report_date=date(2026, 6, 30),
        source_evidence=_source(
            "etf-holdings-incomplete-complete",
            observed_on=date(2026, 6, 30),
            effective_on=date(2026, 6, 30),
            coverage=_coverage(
                fraction=Decimal("1"),
                status=CoverageStatus.COMPLETE,
                expected=1,
                observed=1,
            ),
        ),
        constituents=(),
    )
    asset = PortfolioRiskAsset(
        asset_code="510006.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("100"),
        valuation_evidence=_source("valuation-incomplete-complete"),
        industry_membership=None,
        etf_report=report,
    )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(asset),
    )

    bound = assessment.etf_bounds[0]
    assert bound.known_industry_market_value == Decimal("0")
    assert bound.unknown_market_value == Decimal("100")
    assert bound.unknown_security_market_value == Decimal("100")
    assert assessment.unknown_industry_market_value == Decimal("100")
    assert assessment.unknown_security_market_value == Decimal("100")
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "ETF_LOOKTHROUGH_COVERAGE_UNTRUSTED" in assessment.reason_codes


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


def test_future_policy_and_zero_value_asset_remain_explicitly_blocked() -> None:
    """An unused zero-value row cannot conceal a policy that is future or not yet known."""

    future_policy = replace(
        _policy(),
        effective_from=CUTOFF + timedelta(seconds=1),
        effective_until=CUTOFF + timedelta(days=1),
        known_at=CUTOFF + timedelta(seconds=2),
    )
    assessment = assess_portfolio_industry_exposure(
        policy=future_policy,
        projection=_projection(_equity("600000.SH", "0", "IND-ZERO")),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.industry_bounds == ()
    assert "INDUSTRY_RISK_POLICY_NOT_EFFECTIVE" in assessment.reason_codes
    assert "INDUSTRY_RISK_POLICY_NOT_KNOWN_AT_CUTOFF" in assessment.reason_codes
    assert "INDUSTRY_CLASSIFICATION_COVERAGE_BELOW_POLICY_MINIMUM" in assessment.reason_codes


@pytest.mark.parametrize(
    ("invalidity", "expected_reason"),
    (
        ("unknown_end", "INDUSTRY_MEMBERSHIP_EFFECTIVE_END_UNKNOWN"),
        ("expired_membership", "INDUSTRY_MEMBERSHIP_NOT_EFFECTIVE_AT_SNAPSHOT"),
        ("wrong_date_cutoff", "INDUSTRY_SOURCE_DATE_CUTOFF_MISMATCH"),
    ),
)
def test_membership_window_and_cutoff_failures_keep_value_unknown(
    invalidity: str,
    expected_reason: str,
) -> None:
    """Membership period or date-cutoff contradictions never become a classified row."""

    membership = _membership("IND-A", source_id=f"membership-{invalidity}")
    if invalidity == "unknown_end":
        membership = replace(membership, effective_end_state=EffectiveEndState.UNKNOWN)
    elif invalidity == "expired_membership":
        start = BUSINESS_DATE - timedelta(days=10)
        end = BUSINESS_DATE - timedelta(days=1)
        membership = replace(
            membership,
            effective_from=start,
            effective_end_state=EffectiveEndState.BOUNDED,
            effective_until=end,
            source_evidence=replace(membership.source_evidence, effective_on=start),
        )
    else:
        membership = replace(
            membership,
            source_evidence=replace(
                membership.source_evidence,
                decision_date_cutoff=BUSINESS_DATE - timedelta(days=1),
            ),
        )

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(_equity("600003.SH", "200", "IND-A", membership=membership)),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.industry_bounds == ()
    assert assessment.unknown_industry_market_value == Decimal("200")
    assert expected_reason in assessment.reason_codes


def test_date_clock_proof_for_a_different_equity_cannot_classify_this_holding() -> None:
    """A valid source proof remains pinned to its own asset identity."""

    from tests.unit.risk_center.test_portfolio_risk_date_snapshot_clock import (
        _decision as date_snapshot_decision,
    )

    qualification = date_snapshot_decision()
    assert qualification.qualified is True
    assert qualification.proof is not None
    membership = _membership("IND-A", source_id="proof-for-another-equity")
    source_evidence = replace(
        membership.source_evidence,
        policy_clock_proof=qualification.proof.to_domain(),
    )
    membership = replace(membership, source_evidence=source_evidence)

    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(_equity("600037.SH", "200", "IND-A", membership=membership)),
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.unknown_industry_market_value == Decimal("200")
    assert "INDUSTRY_CLOCK_PROOF_ASSET_MISMATCH" in assessment.reason_codes


def test_etf_without_a_disclosure_keeps_the_fund_value_unknown() -> None:
    """An ETF with a qualified price but no holdings report is not treated as zero exposure."""

    asset = PortfolioRiskAsset(
        asset_code="510006.SH",
        kind=PortfolioAssetKind.ETF,
        projected_market_value=Decimal("250"),
        valuation_evidence=_source("valuation-510006-no-report"),
        industry_membership=None,
        etf_report=None,
    )
    assessment = assess_portfolio_industry_exposure(
        policy=_policy(minimum_industry_coverage=Decimal("0")),
        projection=_projection(asset),
    )

    bound = assessment.etf_bounds[0]
    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert assessment.reason_codes.count("ETF_LOOKTHROUGH_SOURCE_MISSING") == 1
    assert bound.known_industry_market_value == Decimal("0")
    assert bound.unknown_market_value == Decimal("250")
    assert bound.maximum_industry_market_value == Decimal("250")
    assert bound.maximum_security_market_value == Decimal("250")
    assert bound.reason_codes == ("ETF_LOOKTHROUGH_SOURCE_MISSING",)
