"""Conservative industry and ETF look-through exposure calculations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    ETFExposureBound,
    ETFIndustryExposureBound,
    ExposureOutcome,
    IndustryExposureBound,
    IndustryExposurePolicy,
    IndustryMembership,
    PortfolioAssetKind,
    PortfolioExposureProjection,
    PortfolioIndustryExposureAssessment,
    PortfolioRiskAsset,
    RepeatedUnderlyingExposure,
    SecurityExposureBound,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


def assess_portfolio_industry_exposure(
    *,
    policy: IndustryExposurePolicy,
    projection: PortfolioExposureProjection,
) -> PortfolioIndustryExposureAssessment:
    """Calculate industry bounds and repeated stock/ETF exposure fail-closed."""

    reasons: list[str] = []
    source_ids: set[str] = set()
    industry_values: dict[str, Decimal] = {}
    direct_values: dict[str, Decimal] = {}
    etf_values_by_asset: dict[str, Decimal] = {}
    etf_sources_by_asset: dict[str, set[str]] = {}
    etf_bounds: list[ETFExposureBound] = []
    unknown_value = Decimal("0")
    unknown_security_value = Decimal("0")
    unbounded_unknown = False
    total_risk_asset_value = Decimal("0")
    known_industry_value = Decimal("0")
    total_etf_value = Decimal("0")
    covered_etf_value = Decimal("0")
    hard_block = False

    _qualify_policy(policy, projection.as_of, reasons)
    hard_block = bool(reasons)
    if projection.portfolio_market_value is None:
        reasons.append("PORTFOLIO_NAV_UNKNOWN")
        hard_block = True

    for asset in projection.assets:
        value = _qualified_value(
            asset=asset,
            policy=policy,
            projection=projection,
            source_ids=source_ids,
            reasons=reasons,
        )
        if value is None:
            unbounded_unknown = True
            hard_block = True
            continue
        if value == 0:
            continue
        total_risk_asset_value += value
        if asset.kind is PortfolioAssetKind.EQUITY:
            direct_values[asset.asset_code] = value
            membership_reason_start = len(reasons)
            membership = _usable_membership(
                asset.industry_membership,
                policy=policy,
                business_date=projection.business_date,
                as_of=projection.as_of,
                source_ids=source_ids,
                reasons=reasons,
            )
            if membership is None:
                unknown_value += value
                if _has_hard_membership_failure(reasons[membership_reason_start:]):
                    hard_block = True
                continue
            industry_code = membership.industry_code
            industry_values[industry_code] = (
                industry_values.get(industry_code, Decimal("0")) + value
            )
            known_industry_value += value
            continue

        total_etf_value += value
        bound, mapped, unknown, unknown_security, coverage_value, blocked = _assess_etf(
            asset=asset,
            value=value,
            policy=policy,
            projection=projection,
            industry_values=industry_values,
            etf_values_by_asset=etf_values_by_asset,
            etf_sources_by_asset=etf_sources_by_asset,
            source_ids=source_ids,
            reasons=reasons,
        )
        etf_bounds.append(bound)
        known_industry_value += mapped
        unknown_value += unknown
        unknown_security_value += unknown_security
        covered_etf_value += coverage_value
        hard_block = hard_block or blocked

    portfolio_value = projection.portfolio_market_value
    industry_coverage = (
        known_industry_value / total_risk_asset_value if total_risk_asset_value > 0 else None
    )
    etf_coverage = covered_etf_value / total_etf_value if total_etf_value > 0 else None
    if industry_coverage is None or industry_coverage < policy.minimum_industry_coverage:
        reasons.append("INDUSTRY_CLASSIFICATION_COVERAGE_BELOW_POLICY_MINIMUM")
        hard_block = True

    bound_codes = tuple(sorted(industry_values))
    industry_bounds = tuple(
        _industry_bound(
            industry_code=code,
            known_value=industry_values[code],
            unknown_value=None if unbounded_unknown else unknown_value,
            portfolio_value=portfolio_value,
            maximum_weight=policy.max_industry_weight,
        )
        for code in bound_codes
    )
    security_codes = tuple(sorted(set(direct_values) | set(etf_values_by_asset)))
    security_bounds = tuple(
        _security_bound(
            asset_code=code,
            direct_value=direct_values.get(code, Decimal("0")),
            etf_value=etf_values_by_asset.get(code, Decimal("0")),
            etf_asset_codes=tuple(sorted(etf_sources_by_asset.get(code, set()))),
            unknown_value=None if unbounded_unknown else unknown_security_value,
            portfolio_value=portfolio_value,
            maximum_weight=policy.max_security_weight,
        )
        for code in security_codes
    )

    unknown_upper = (
        None if unbounded_unknown or portfolio_value is None else unknown_value / portfolio_value
    )
    unknown_security_upper = (
        None
        if unbounded_unknown or portfolio_value is None
        else unknown_security_value / portfolio_value
    )
    definite_industry_breach = any(
        bound.lower_weight is not None and bound.lower_weight > bound.maximum_weight
        for bound in industry_bounds
    )
    definite_security_breach = any(
        bound.lower_weight is not None and bound.lower_weight > bound.maximum_weight
        for bound in security_bounds
    )
    uncertain_industry_breach = any(
        bound.upper_weight is not None and bound.upper_weight > bound.maximum_weight
        for bound in industry_bounds
    ) or (unknown_upper is not None and unknown_upper > policy.max_industry_weight)
    uncertain_security_breach = any(
        bound.upper_weight is not None and bound.upper_weight > bound.maximum_weight
        for bound in security_bounds
    ) or (
        unknown_security_upper is not None and unknown_security_upper > policy.max_security_weight
    )
    if definite_industry_breach or definite_security_breach:
        if definite_industry_breach:
            reasons.append("INDUSTRY_RISK_LIMIT_BREACHED")
        if definite_security_breach:
            reasons.append("SECURITY_RISK_LIMIT_BREACHED")
        outcome = ExposureOutcome.LIMIT_BREACHED
    elif hard_block:
        outcome = ExposureOutcome.BLOCKED
    elif uncertain_industry_breach or uncertain_security_breach or unbounded_unknown:
        if uncertain_industry_breach:
            reasons.append("INDUSTRY_RISK_UPPER_BOUND_EXCEEDS_LIMIT")
        if uncertain_security_breach:
            reasons.append("SECURITY_RISK_UPPER_BOUND_EXCEEDS_LIMIT")
        outcome = ExposureOutcome.UNKNOWN
    else:
        outcome = ExposureOutcome.WITHIN_LIMIT

    overlaps = tuple(
        RepeatedUnderlyingExposure(
            asset_code=asset_code,
            direct_market_value=direct_values.get(asset_code, Decimal("0")),
            etf_market_value=etf_values_by_asset[asset_code],
            etf_asset_codes=tuple(sorted(etf_sources_by_asset[asset_code])),
        )
        for asset_code in sorted(etf_values_by_asset)
        if direct_values.get(asset_code, Decimal("0")) > 0 and etf_values_by_asset[asset_code] > 0
    )
    if overlaps:
        reasons.append("DIRECT_AND_ETF_UNDERLYING_OVERLAP_PRESENT")

    source_evidence = _collect_source_evidence(projection)
    return PortfolioIndustryExposureAssessment(
        portfolio_snapshot_id=projection.portfolio_snapshot_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_sha256=policy.content_sha256,
        as_of=projection.as_of,
        outcome=outcome,
        industry_bounds=industry_bounds,
        security_bounds=security_bounds,
        etf_bounds=tuple(etf_bounds),
        repeated_underlyings=overlaps,
        unknown_industry_market_value=None if unbounded_unknown else unknown_value,
        unknown_security_market_value=(None if unbounded_unknown else unknown_security_value),
        industry_coverage_fraction=industry_coverage,
        etf_lookthrough_coverage_fraction=etf_coverage,
        reason_codes=tuple(dict.fromkeys(reasons)),
        source_ids=tuple(sorted({item.source_id for item in source_evidence})),
        source_evidence=source_evidence,
    )


def _collect_source_evidence(
    projection: PortfolioExposureProjection,
) -> tuple[PortfolioRiskSourceEvidence, ...]:
    evidence_items: list[PortfolioRiskSourceEvidence] = []
    for asset in projection.assets:
        if asset.valuation_evidence is not None:
            evidence_items.append(asset.valuation_evidence)
        if asset.industry_membership is not None:
            evidence_items.append(asset.industry_membership.source_evidence)
        if asset.etf_report is not None:
            evidence_items.append(asset.etf_report.source_evidence)
            for row in asset.etf_report.constituents:
                if row.industry_membership is not None:
                    evidence_items.append(row.industry_membership.source_evidence)
    unique_evidence: dict[tuple[str, str, str | None], PortfolioRiskSourceEvidence] = {}
    for evidence in evidence_items:
        identity = (
            evidence.source_id,
            evidence.source_record_id,
            evidence.original_payload_sha256,
        )
        unique_evidence[identity] = evidence
    return tuple(
        sorted(
            unique_evidence.values(),
            key=lambda evidence: (
                evidence.source_id,
                evidence.source_record_id,
                evidence.original_payload_sha256 or "",
            ),
        )
    )


def _qualify_policy(
    policy: IndustryExposurePolicy,
    as_of: datetime,
    reasons: list[str],
) -> None:
    if policy.effective_from > as_of or (
        policy.effective_until is not None and as_of >= policy.effective_until
    ):
        reasons.append("INDUSTRY_RISK_POLICY_NOT_EFFECTIVE")
    if policy.known_at > as_of:
        reasons.append("INDUSTRY_RISK_POLICY_NOT_KNOWN_AT_CUTOFF")


def _qualified_value(
    *,
    asset: PortfolioRiskAsset,
    policy: IndustryExposurePolicy,
    projection: PortfolioExposureProjection,
    source_ids: set[str],
    reasons: list[str],
) -> Decimal | None:
    value = asset.projected_market_value
    evidence = asset.valuation_evidence
    if value is None or evidence is None:
        reasons.append("PROJECTED_ASSET_VALUE_UNKNOWN")
        return None
    source_ids.add(evidence.source_id)
    qualification_reasons = _source_qualification_reasons(
        evidence=evidence,
        policy=policy,
        as_of=projection.as_of,
        business_date=projection.business_date,
    )
    if qualification_reasons:
        reasons.extend(qualification_reasons)
        reasons.append("PROJECTED_ASSET_VALUE_SOURCE_UNQUALIFIED")
        return None
    return value


def _usable_membership(
    membership: IndustryMembership | None,
    *,
    policy: IndustryExposurePolicy,
    business_date: date,
    as_of: datetime,
    source_ids: set[str],
    reasons: list[str],
) -> IndustryMembership | None:
    if membership is None:
        reasons.append("INDUSTRY_MEMBERSHIP_UNKNOWN")
        return None
    evidence = membership.source_evidence
    source_ids.add(evidence.source_id)
    if (
        membership.taxonomy_id != policy.taxonomy_id
        or membership.taxonomy_kind != policy.taxonomy_kind
        or membership.provider_id != policy.provider_id
        or membership.provider_version != policy.provider_version
    ):
        reasons.append("INDUSTRY_SOURCE_POLICY_BINDING_MISMATCH")
        return None
    if membership.effective_end_state is EffectiveEndState.UNKNOWN:
        reasons.append("INDUSTRY_MEMBERSHIP_EFFECTIVE_END_UNKNOWN")
        return None
    if membership.effective_from > business_date or (
        membership.effective_until is not None and business_date > membership.effective_until
    ):
        reasons.append("INDUSTRY_MEMBERSHIP_NOT_EFFECTIVE_AT_SNAPSHOT")
        return None
    if evidence.decision_date_cutoff != business_date:
        reasons.append("INDUSTRY_SOURCE_DATE_CUTOFF_MISMATCH")
        return None
    qualification_reasons = _source_qualification_reasons(
        evidence=evidence,
        policy=policy,
        as_of=as_of,
        business_date=business_date,
    )
    if qualification_reasons:
        reasons.extend(qualification_reasons)
        reasons.append("INDUSTRY_SOURCE_UNQUALIFIED")
        return None
    return membership


def _assess_etf(
    *,
    asset: PortfolioRiskAsset,
    value: Decimal,
    policy: IndustryExposurePolicy,
    projection: PortfolioExposureProjection,
    industry_values: dict[str, Decimal],
    etf_values_by_asset: dict[str, Decimal],
    etf_sources_by_asset: dict[str, set[str]],
    source_ids: set[str],
    reasons: list[str],
) -> tuple[ETFExposureBound, Decimal, Decimal, Decimal, Decimal, bool]:
    report = asset.etf_report
    if report is None:
        reason_codes: tuple[str, ...] = ("ETF_LOOKTHROUGH_SOURCE_MISSING",)
        reasons.extend(reason_codes)
        bound = _unknown_etf_bound(asset.asset_code, value, None, None, reason_codes)
        return bound, Decimal("0"), value, value, Decimal("0"), True

    source = report.source_evidence
    source_ids.add(source.source_id)
    qualification_reasons = list(
        _source_qualification_reasons(
            evidence=source,
            policy=policy,
            as_of=projection.as_of,
            business_date=projection.business_date,
        )
    )
    if report.report_date > projection.business_date:
        qualification_reasons.append("ETF_REPORT_DATE_AFTER_SNAPSHOT")
    coverage = source.coverage
    trusted, coverage_fraction = _trusted_etf_coverage(
        report=report,
        policy=policy,
    )
    if qualification_reasons or not trusted:
        untrusted_reasons = list(qualification_reasons)
        if not trusted:
            untrusted_reasons.append("ETF_LOOKTHROUGH_COVERAGE_UNTRUSTED")
        reason_codes = tuple(dict.fromkeys(untrusted_reasons))
        if qualification_reasons:
            reason_codes = tuple(
                dict.fromkeys((*reason_codes, "ETF_LOOKTHROUGH_SOURCE_UNQUALIFIED"))
            )
        reasons.extend(reason_codes)
        bound = _unknown_etf_bound(
            asset.asset_code,
            value,
            report.report_date,
            coverage.status,
            reason_codes,
            source_id=source.source_id,
            reported_coverage_fraction=coverage.reported_weight_fraction,
        )
        return bound, Decimal("0"), value, value, Decimal("0"), True

    hard_block = coverage_fraction < policy.minimum_etf_lookthrough_coverage
    if hard_block:
        reasons.append("ETF_LOOKTHROUGH_COVERAGE_BELOW_POLICY_MINIMUM")
    classified_value = Decimal("0")
    known_security_value = Decimal("0")
    etf_industry_values: dict[str, Decimal] = {}
    actual_reported_fraction = sum(
        (row.weight_fraction for row in report.constituents),
        Decimal("0"),
    )
    uncovered_fraction = max(
        Decimal("1") - coverage_fraction,
        Decimal("1") - actual_reported_fraction,
    )
    unknown_component_value = value * uncovered_fraction
    unknown_security_component_value = value * uncovered_fraction
    for row in report.constituents:
        component_value = value * row.weight_fraction
        if row.kind is ETFConstituentKind.CASH:
            continue
        if row.kind is ETFConstituentKind.OTHER:
            unknown_component_value += component_value
            unknown_security_component_value += component_value
            reasons.append("ETF_COMPONENT_KIND_UNSUPPORTED_FOR_INDUSTRY")
            continue
        known_security_value += component_value
        etf_values_by_asset[row.asset_code] = (
            etf_values_by_asset.get(row.asset_code, Decimal("0")) + component_value
        )
        etf_sources_by_asset.setdefault(row.asset_code, set()).add(asset.asset_code)
        membership_reason_start = len(reasons)
        membership = _usable_membership(
            row.industry_membership,
            policy=policy,
            business_date=projection.business_date,
            as_of=projection.as_of,
            source_ids=source_ids,
            reasons=reasons,
        )
        if membership is None:
            unknown_component_value += component_value
            if _has_hard_membership_failure(reasons[membership_reason_start:]):
                hard_block = True
            continue
        industry_values[membership.industry_code] = (
            industry_values.get(membership.industry_code, Decimal("0")) + component_value
        )
        etf_industry_values[membership.industry_code] = (
            etf_industry_values.get(membership.industry_code, Decimal("0")) + component_value
        )
        classified_value += component_value

    if (
        unknown_component_value < 0
        or classified_value + unknown_component_value > value
        or known_security_value + unknown_security_component_value > value
    ):
        reason_codes = ("ETF_LOOKTHROUGH_WEIGHT_RECONCILIATION_FAILED",)
        reasons.extend(reason_codes)
        bound = _unknown_etf_bound(
            asset.asset_code,
            value,
            report.report_date,
            coverage.status,
            reason_codes,
            source_id=source.source_id,
            reported_coverage_fraction=coverage_fraction,
        )
        return bound, Decimal("0"), value, value, Decimal("0"), True

    etf_industry_bounds = tuple(
        ETFIndustryExposureBound(
            industry_code=industry_code,
            known_market_value=known_value,
            unknown_market_value=unknown_component_value,
            upper_market_value=known_value + unknown_component_value,
        )
        for industry_code, known_value in sorted(etf_industry_values.items())
    )
    maximum_industry_value = max(
        (unknown_component_value, *(bound.upper_market_value for bound in etf_industry_bounds))
    )
    result = ETFExposureBound(
        asset_code=asset.asset_code,
        report_date=report.report_date,
        coverage_status=coverage.status,
        reported_coverage_fraction=coverage_fraction,
        known_industry_market_value=classified_value,
        unknown_market_value=unknown_component_value,
        maximum_industry_market_value=maximum_industry_value,
        industry_bounds=etf_industry_bounds,
        known_security_market_value=known_security_value,
        unknown_security_market_value=unknown_security_component_value,
        maximum_security_market_value=known_security_value + unknown_security_component_value,
        source_id=source.source_id,
        reason_codes=(),
    )
    return (
        result,
        classified_value,
        unknown_component_value,
        unknown_security_component_value,
        value * coverage_fraction,
        hard_block,
    )


def _trusted_etf_coverage(
    *,
    report: ETFConstituentReport,
    policy: IndustryExposurePolicy,
) -> tuple[bool, Decimal]:
    coverage: PortfolioRiskCoverage = report.source_evidence.coverage
    fraction = coverage.reported_weight_fraction
    if (
        coverage.status is CoverageStatus.UNKNOWN
        or coverage.precision_basis != policy.coverage_precision_basis
        or fraction is None
    ):
        return False, Decimal("0")
    if coverage.observed_item_count is not None and coverage.observed_item_count != len(
        report.constituents
    ):
        return False, Decimal("0")
    if coverage.expected_item_count is not None and coverage.expected_item_count < len(
        report.constituents
    ):
        return False, Decimal("0")
    actual_fraction = sum(
        (row.weight_fraction for row in report.constituents),
        Decimal("0"),
    )
    if abs(actual_fraction - fraction) > policy.coverage_weight_tolerance:
        return False, Decimal("0")
    if coverage.status is CoverageStatus.COMPLETE and fraction != Decimal("1"):
        return False, Decimal("0")
    if coverage.status is CoverageStatus.PARTIAL and fraction >= Decimal("1"):
        return False, Decimal("0")
    return True, fraction


def _source_qualification_reasons(
    *,
    evidence: PortfolioRiskSourceEvidence,
    policy: IndustryExposurePolicy,
    as_of: datetime,
    business_date: date,
) -> tuple[str, ...]:
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=policy.requested_purpose,
        allowed_observation_precisions=policy.allowed_observation_precisions,
        as_of=as_of,
        allowed_restrictions=policy.allowed_source_restrictions,
    )
    reasons = list(qualification.reason_codes)
    if evidence.observation_precision is SourceObservationPrecision.DATE:
        if policy.requested_purpose not in policy.date_precision_purposes:
            reasons.append("RISK_SOURCE_DATE_PRECISION_NOT_ALLOWED_FOR_PURPOSE")
        if evidence.decision_date_cutoff != business_date:
            reasons.append("RISK_SOURCE_DATE_CUTOFF_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _has_hard_membership_failure(reason_codes: list[str]) -> bool:
    return bool(reason_codes)


def _unknown_etf_bound(
    asset_code: str,
    value: Decimal,
    report_date: date | None,
    coverage_status: CoverageStatus | None,
    reason_codes: tuple[str, ...],
    *,
    source_id: str | None = None,
    reported_coverage_fraction: Decimal | None = None,
) -> ETFExposureBound:
    return ETFExposureBound(
        asset_code=asset_code,
        report_date=report_date,
        coverage_status=coverage_status,
        reported_coverage_fraction=reported_coverage_fraction,
        known_industry_market_value=Decimal("0"),
        unknown_market_value=value,
        maximum_industry_market_value=value,
        industry_bounds=(),
        known_security_market_value=Decimal("0"),
        unknown_security_market_value=value,
        maximum_security_market_value=value,
        source_id=source_id,
        reason_codes=reason_codes,
    )


def _industry_bound(
    *,
    industry_code: str,
    known_value: Decimal,
    unknown_value: Decimal | None,
    portfolio_value: Decimal | None,
    maximum_weight: Decimal,
) -> IndustryExposureBound:
    lower = known_value / portfolio_value if portfolio_value is not None else None
    upper = (
        (known_value + unknown_value) / portfolio_value
        if portfolio_value is not None and unknown_value is not None
        else None
    )
    if lower is not None and lower > maximum_weight:
        outcome = ExposureOutcome.LIMIT_BREACHED
    elif upper is not None and upper > maximum_weight:
        outcome = ExposureOutcome.UNKNOWN
    elif upper is None:
        outcome = ExposureOutcome.BLOCKED
    else:
        outcome = ExposureOutcome.WITHIN_LIMIT
    return IndustryExposureBound(
        industry_code=industry_code,
        known_market_value=known_value,
        unknown_market_value=unknown_value,
        lower_weight=lower,
        upper_weight=upper,
        maximum_weight=maximum_weight,
        outcome=outcome,
    )


def _security_bound(
    *,
    asset_code: str,
    direct_value: Decimal,
    etf_value: Decimal,
    etf_asset_codes: tuple[str, ...],
    unknown_value: Decimal | None,
    portfolio_value: Decimal | None,
    maximum_weight: Decimal,
) -> SecurityExposureBound:
    known_value = direct_value + etf_value
    lower = known_value / portfolio_value if portfolio_value is not None else None
    upper = (
        (known_value + unknown_value) / portfolio_value
        if portfolio_value is not None and unknown_value is not None
        else None
    )
    if lower is not None and lower > maximum_weight:
        outcome = ExposureOutcome.LIMIT_BREACHED
    elif upper is not None and upper > maximum_weight:
        outcome = ExposureOutcome.UNKNOWN
    elif upper is None:
        outcome = ExposureOutcome.BLOCKED
    else:
        outcome = ExposureOutcome.WITHIN_LIMIT
    return SecurityExposureBound(
        asset_code=asset_code,
        direct_market_value=direct_value,
        etf_lookthrough_market_value=etf_value,
        known_market_value=known_value,
        unknown_market_value=unknown_value,
        lower_weight=lower,
        upper_weight=upper,
        maximum_weight=maximum_weight,
        etf_asset_codes=etf_asset_codes,
        outcome=outcome,
    )


__all__ = (
    "ETFConstituent",
    "ETFConstituentKind",
    "ETFConstituentReport",
    "ETFExposureBound",
    "ETFIndustryExposureBound",
    "EffectiveEndState",
    "ExposureOutcome",
    "IndustryExposureBound",
    "IndustryMembership",
    "IndustryExposurePolicy",
    "PortfolioAssetKind",
    "PortfolioExposureProjection",
    "PortfolioIndustryExposureAssessment",
    "PortfolioRiskAsset",
    "RepeatedUnderlyingExposure",
    "SecurityExposureBound",
    "assess_portfolio_industry_exposure",
)
