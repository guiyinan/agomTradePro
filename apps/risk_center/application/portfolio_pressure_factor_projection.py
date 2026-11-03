"""Source-qualified industry loadings for Risk Center Scenario exposures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetInputs
from apps.risk_center.application.portfolio_risk_snapshot import (
    PortfolioRiskAssessmentResult,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    ETFExposureBound,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    MacroPathParameters,
    ParametricShock,
    ParametricShockParameters,
    ScenarioRevision,
    ShockUnit,
    scenario_factor_loading_attribute,
)


@dataclass(frozen=True, slots=True)
class PressureHeldAsset:
    """One actual holding aggregated once and paired with its exact risk input."""

    asset_code: str
    quantity: Decimal
    available_quantity: Decimal | None
    market_value: Decimal
    quantity_unit: str
    asset_input: PortfolioRiskAssetInputs
    scenario_attributes: tuple[tuple[str, str], ...]


def portfolio_scenario_factor_targets(
    revision: ScenarioRevision,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Find industry factors and validate every persisted exit assumption."""

    targets: set[str] = set()
    reasons: list[str] = []
    parameters = revision.parameters
    if isinstance(parameters, ParametricShockParameters):
        for shock in parameters.shocks:
            if shock.shock_kind.startswith("exit_"):
                reasons.extend(validate_exit_shock_assumption(shock))
            if shock.target_kind == "factor" and (
                shock.shock_kind in {"return", "price", "spread_return"}
                or shock.shock_kind.startswith("exit_")
            ):
                targets.add(shock.target)
    elif isinstance(parameters, MacroPathParameters):
        targets.update(
            item.target for item in parameters.asset_impacts if item.target_kind == "factor"
        )
    return tuple(sorted(targets)), _ordered_unique(tuple(reasons))


def validate_exit_shock_assumption(shock: ParametricShock) -> tuple[str, ...]:
    """Accept only explicit downside liquidity, halt, and limit-lock assumptions."""

    if shock.shock_kind not in {
        "exit_liquidity_change",
        "exit_halt",
        "exit_limit_down_lock",
    }:
        return ("PORTFOLIO_PRESSURE_EXIT_SHOCK_KIND_UNSUPPORTED",)
    if shock.horizon_days > 3650:
        return ("PORTFOLIO_PRESSURE_EXIT_SHOCK_HORIZON_UNSUPPORTED",)
    if shock.shock_kind == "exit_liquidity_change":
        if (
            shock.unit is not ShockUnit.PERCENT
            or shock.magnitude < Decimal("-1")
            or shock.magnitude > Decimal("0")
        ):
            return ("PORTFOLIO_PRESSURE_EXIT_LIQUIDITY_CHANGE_INVALID",)
        return ()
    if shock.unit is not ShockUnit.PERCENT or shock.magnitude != Decimal("-1"):
        return ("PORTFOLIO_PRESSURE_EXIT_LOCK_REQUIRES_MINUS_100_PERCENT",)
    return ()


def build_scenario_factor_attributes(
    *,
    held_assets: tuple[PressureHeldAsset, ...],
    factor_targets: tuple[str, ...],
    assessment: PortfolioRiskAssessmentResult,
    as_of_time: datetime,
) -> tuple[dict[str, tuple[tuple[str, str], ...]], tuple[str, ...]]:
    """Bind direct industry membership and per-ETF upper bounds to holdings."""

    attributes_by_asset: dict[str, tuple[tuple[str, str], ...]] = {}
    if not factor_targets:
        for item in held_assets:
            attributes_by_asset[item.asset_code] = (
                (("asset_class", item.asset_input.kind.value),)
                if item.asset_input.kind is not None
                else ()
            )
        return attributes_by_asset, ()

    projected = assessment.exposure_projection
    industry = assessment.industry_assessment
    if (
        projected is None
        or industry is None
        or industry.portfolio_snapshot_id != projected.portfolio_snapshot_id
        or industry.as_of != as_of_time
        or any(
            reason.startswith(
                (
                    "RISK_SOURCE_",
                    "INDUSTRY_SOURCE_",
                    "ETF_LOOKTHROUGH_SOURCE_",
                )
            )
            for reason in industry.reason_codes
        )
        or any(reason.startswith("INDUSTRY_RISK_POLICY_") for reason in industry.reason_codes)
    ):
        return {}, ("PORTFOLIO_PRESSURE_INDUSTRY_ASSESSMENT_UNAVAILABLE",)
    industry_evidence = set(industry.source_evidence)
    exposure_by_code = {item.asset_code: item for item in projected.assets}
    etf_bound_by_code = {item.asset_code: item for item in industry.etf_bounds}
    if len(etf_bound_by_code) != len(industry.etf_bounds):
        return {}, ("PORTFOLIO_PRESSURE_ETF_BOUND_IDENTITY_CONFLICT",)
    blockers: list[str] = []
    for item in held_assets:
        source = item.asset_input
        exposure_asset = exposure_by_code.get(item.asset_code)
        values: list[tuple[str, str]] = []
        if source.kind is None or exposure_asset is None:
            blockers.append("PORTFOLIO_PRESSURE_FACTOR_ASSET_UNKNOWN")
            continue
        values.append(("asset_class", source.kind.value))
        if source.kind is PortfolioAssetKind.EQUITY:
            membership = source.industry_membership
            if (
                membership is None
                or membership.source_evidence not in industry_evidence
                or not _membership_source_usable(
                    membership=membership,
                    business_date=projected.business_date,
                    as_of_time=as_of_time,
                )
                or not any(
                    bound.industry_code == membership.industry_code
                    for bound in industry.industry_bounds
                )
            ):
                blockers.append("PORTFOLIO_PRESSURE_INDUSTRY_MEMBERSHIP_UNKNOWN")
                continue
            values.append(("factor", membership.industry_code))
            values.extend(
                scenario_factor_loading_attribute(
                    target,
                    Decimal("1") if target == membership.industry_code else Decimal("0"),
                )
                for target in factor_targets
            )
        else:
            bound = etf_bound_by_code.get(item.asset_code)
            report = source.etf_report
            if (
                report is None
                or report.source_evidence not in industry_evidence
                or not _source_usable_for_projection(
                    evidence=report.source_evidence,
                    business_date=projected.business_date,
                    as_of_time=as_of_time,
                )
                or report.report_date > projected.business_date
                or bound is None
                or bound.report_date != report.report_date
                or bound.reason_codes
                or bound.source_id != report.source_evidence.source_id
                or exposure_asset.projected_market_value is None
                or exposure_asset.projected_market_value <= 0
                or bound.unknown_market_value is None
            ):
                blockers.append("PORTFOLIO_PRESSURE_ETF_INDUSTRY_BOUND_UNKNOWN")
                continue
            for target in factor_targets:
                loading = etf_upper_industry_loading(
                    bound=bound,
                    projected_market_value=exposure_asset.projected_market_value,
                    industry_code=target,
                )
                if loading is None:
                    blockers.append("PORTFOLIO_PRESSURE_ETF_INDUSTRY_BOUND_UNKNOWN")
                    continue
                values.append(scenario_factor_loading_attribute(target, loading))
        attributes_by_asset[item.asset_code] = tuple(values)
    return attributes_by_asset, _ordered_unique(tuple(blockers))


def etf_upper_industry_loading(
    *,
    bound: ETFExposureBound,
    projected_market_value: Decimal,
    industry_code: str,
) -> Decimal | None:
    """Use the ETF's conservative upper exposure, rounded upward exactly."""

    if bound.unknown_market_value is None or projected_market_value <= 0 or bound.reason_codes:
        return None
    upper_by_industry = {
        item.industry_code: item.upper_market_value for item in bound.industry_bounds
    }
    if len(upper_by_industry) != len(bound.industry_bounds):
        return None
    upper_value = upper_by_industry.get(industry_code, bound.unknown_market_value)
    if upper_value < 0:
        return None
    exact_ratio = Fraction(upper_value) / Fraction(projected_market_value)
    if exact_ratio >= 1:
        return Decimal("1")
    if exact_ratio <= 0:
        return Decimal("0")
    with localcontext() as context:
        context.prec = 50
        loading = upper_value / projected_market_value
        while Fraction(loading) < exact_ratio:
            loading = loading.next_plus(context)
    return min(Decimal("1"), loading)


def _membership_source_usable(
    *,
    membership: IndustryMembership,
    business_date: date,
    as_of_time: datetime,
) -> bool:
    """Require effective dates and original clocks used by A assessment."""

    if (
        membership.effective_from > business_date
        or (membership.effective_until is not None and business_date > membership.effective_until)
        or membership.effective_end_state is EffectiveEndState.UNKNOWN
    ):
        return False
    return _source_usable_for_projection(
        evidence=membership.source_evidence,
        business_date=business_date,
        as_of_time=as_of_time,
    )


def _source_usable_for_projection(
    *,
    evidence: PortfolioRiskSourceEvidence,
    business_date: date,
    as_of_time: datetime,
) -> bool:
    """Fail closed on missing clocks, restrictions, invalidity, or future evidence."""

    if (
        evidence.original_payload_sha256 is None
        or evidence.decision_cutoff != as_of_time
        or evidence.observation_precision is SourceObservationPrecision.UNKNOWN
        or evidence.available_at is None
        or evidence.known_at is None
        or evidence.valid_until is None
        or evidence.available_at > as_of_time
        or evidence.known_at > as_of_time
        or as_of_time >= evidence.valid_until
        or evidence.must_not_use_for_decision
        or evidence.restrictions
        or _prohibited_purpose(evidence.source_purpose)
    ):
        return False
    if evidence.observation_precision is SourceObservationPrecision.TIMESTAMP:
        return evidence.observed_at is not None and evidence.observed_at <= as_of_time
    return (
        evidence.observation_precision is SourceObservationPrecision.DATE
        and evidence.observed_on is not None
        and evidence.observed_on <= business_date
        and evidence.decision_date_cutoff == business_date
    )


def _prohibited_purpose(value: str) -> bool:
    """Recognize unconditional source-purpose restrictions without guessing policy."""

    normalized = value.lower()
    return normalized.startswith(("must_not_", "research_only", "observation_only"))


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    """Retain reason order while removing duplicates."""

    return tuple(dict.fromkeys(values))


__all__ = [
    "PressureHeldAsset",
    "build_scenario_factor_attributes",
    "etf_upper_industry_loading",
    "portfolio_scenario_factor_targets",
    "validate_exit_shock_assumption",
]
