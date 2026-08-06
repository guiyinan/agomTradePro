"""Premium decomposition and once-only cost coverage for R5 liquidity evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.fixed_income.domain.evidence import EvidenceRole, ExactEvidence, canonical_hash
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityCostRule,
    LiquidityMeasure,
    LiquidityMeasureRole,
    LiquidityPremiumBlockerCode,
    LiquidityPremiumEvidence,
    LiquidityPremiumPolicy,
    LiquidityPremiumRule,
    LiquidityPremiumStatus,
    MarketSpreadSemantics,
    evaluate_liquidity_premium,
)

_EVALUATED_AT = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_OBSERVED_AT = _EVALUATED_AT - timedelta(seconds=60)
_AVAILABLE_AT = _OBSERVED_AT + timedelta(seconds=10)
_VALID_UNTIL = _EVALUATED_AT + timedelta(days=1)
_SUBJECT = "bond-a"


def _digest(value: str) -> str:
    return canonical_hash({"value": value})


def _exact(
    *,
    role: EvidenceRole,
    evidence_id: str,
    version: str,
    subject_id: str,
    observed_at: datetime,
    available_at: datetime,
    content_hash: str,
    curve_role: str,
    upstream_hashes: tuple[str, ...] = (),
) -> ExactEvidence:
    return ExactEvidence(
        role=role,
        owner="research" if role is EvidenceRole.POLICY else "data_center",
        evidence_id=evidence_id,
        version=version,
        subject_id=subject_id,
        content_hash=content_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=_VALID_UNTIL,
        currency=None if role is EvidenceRole.POLICY else "CNY",
        curve_role=curve_role,
        upstream_hashes=tuple(sorted(upstream_hashes)),
    )


def _policy(
    *,
    semantics: MarketSpreadSemantics = MarketSpreadSemantics.INCLUDES_LIQUIDITY_PREMIUM,
) -> LiquidityPremiumPolicy:
    unit_by_role = {
        LiquidityMeasureRole.BID_ASK_BP: "bp",
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: "bp",
        LiquidityMeasureRole.ISSUE_SIZE: "CNY",
        LiquidityMeasureRole.QUOTE_AGE_SECONDS: "seconds",
        LiquidityMeasureRole.TURNOVER_RATIO: "ratio",
    }
    reference_by_role = {
        LiquidityMeasureRole.BID_ASK_BP: Decimal("0"),
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: Decimal("0"),
        LiquidityMeasureRole.ISSUE_SIZE: Decimal("1000"),
        LiquidityMeasureRole.QUOTE_AGE_SECONDS: Decimal("60"),
        LiquidityMeasureRole.TURNOVER_RATIO: Decimal("0.2"),
    }
    coefficient_by_role = {
        LiquidityMeasureRole.BID_ASK_BP: Decimal("1"),
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: Decimal("1"),
        LiquidityMeasureRole.ISSUE_SIZE: Decimal("0"),
        LiquidityMeasureRole.QUOTE_AGE_SECONDS: Decimal("0"),
        LiquidityMeasureRole.TURNOVER_RATIO: Decimal("0"),
    }
    premium_rules = tuple(
        LiquidityPremiumRule(
            measure_role=role,
            expected_unit=unit_by_role[role],
            reference_value=reference_by_role[role],
            coefficient_bp_per_unit=coefficient_by_role[role],
        )
        for role in sorted(unit_by_role, key=lambda item: item.value)
    )
    cost_roles = (
        LiquidityMeasureRole.FINANCING_CARRY_COST_BP,
        LiquidityMeasureRole.LIQUIDATION_COST_BP,
        LiquidityMeasureRole.MARKET_IMPACT_COST_BP,
        LiquidityMeasureRole.TRANSACTION_COST_BP,
    )
    cost_rules = tuple(
        LiquidityCostRule(
            measure_role=role,
            expected_unit="bp",
            cost_basis=LiquidityCostBasis.GROSS_TRADED_NOTIONAL,
            quoted_horizon_days=30,
            applied_horizon_days=30,
            application_multiplier=Decimal("1"),
            already_in_gross_relative_value=False,
        )
        for role in sorted(cost_roles, key=lambda item: item.value)
    )
    return LiquidityPremiumPolicy(
        policy_id="liquidity-policy",
        policy_version="v1",
        market_spread_semantics=semantics,
        premium_rules=premium_rules,
        cost_rules=cost_rules,
        decomposition_tolerance_bp=Decimal("0.01"),
        maximum_quote_age_seconds=120,
        minimum_turnover_ratio=Decimal("0.1"),
        minimum_issue_size=Decimal("500"),
        allow_negative_model_premium=False,
        allow_negative_market_implied_premium=False,
        gross_cost_treatment_version="v1",
        evidence=_exact(
            role=EvidenceRole.POLICY,
            evidence_id="liquidity-policy",
            version="v1",
            subject_id="liquidity-policy",
            observed_at=_OBSERVED_AT - timedelta(days=1),
            available_at=_AVAILABLE_AT - timedelta(days=1),
            content_hash=_digest("liquidity-policy"),
            curve_role="liquidity_premium_policy",
        ),
    )


def _raw_values(
    *, market_spread: str = "10", gross: str = "12"
) -> dict[LiquidityMeasureRole, Decimal]:
    return {
        LiquidityMeasureRole.BID_ASK_BP: Decimal("2"),
        LiquidityMeasureRole.TURNOVER_RATIO: Decimal("0.2"),
        LiquidityMeasureRole.ISSUE_SIZE: Decimal("1000"),
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: Decimal("1"),
        LiquidityMeasureRole.MARKET_SPREAD_BP: Decimal(market_spread),
        LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP: Decimal("4"),
        LiquidityMeasureRole.OPTION_COST_BP: Decimal("2"),
        LiquidityMeasureRole.OTHER_SPREAD_BP: Decimal("1"),
        LiquidityMeasureRole.FINANCING_CARRY_COST_BP: Decimal("1"),
        LiquidityMeasureRole.TRANSACTION_COST_BP: Decimal("1"),
        LiquidityMeasureRole.MARKET_IMPACT_COST_BP: Decimal("1"),
        LiquidityMeasureRole.LIQUIDATION_COST_BP: Decimal("1"),
        LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP: Decimal(gross),
    }


def _unit(role: LiquidityMeasureRole) -> str:
    if role is LiquidityMeasureRole.TURNOVER_RATIO:
        return "ratio"
    if role is LiquidityMeasureRole.ISSUE_SIZE:
        return "CNY"
    return "bp"


def _evidence(
    *,
    omitted_role: LiquidityMeasureRole | None = None,
    market_spread: str = "10",
    gross: str = "12",
) -> LiquidityPremiumEvidence:
    values = _raw_values(market_spread=market_spread, gross=gross)
    if omitted_role is not None:
        values.pop(omitted_role)
    included_roles: tuple[LiquidityMeasureRole, ...] = ()
    treatment_version = "v1"
    gross_record_hash = _digest("measure-gross_relative_value_bp")
    gross_manifest = canonical_hash(
        {
            "subject_id": _SUBJECT,
            "currency": "CNY",
            "measure_role": LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP,
            "gross_record_hash": gross_record_hash,
            "observed_at": _OBSERVED_AT,
            "available_at": _AVAILABLE_AT,
            "included_cost_roles": included_roles,
            "treatment_version": treatment_version,
        }
    )
    measures: list[LiquidityMeasure] = []
    for role in sorted(values, key=lambda item: item.value):
        record_hash = (
            gross_record_hash
            if role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP
            else _digest(f"measure-{role.value}")
        )
        upstreams = (
            (gross_manifest,) if role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP else ()
        )
        publication = _exact(
            role=EvidenceRole.PUBLICATION,
            evidence_id=f"measure-{role.value}",
            version="v1",
            subject_id=_SUBJECT,
            observed_at=_OBSERVED_AT,
            available_at=_AVAILABLE_AT,
            content_hash=record_hash,
            curve_role=f"liquidity:{role.value}",
            upstream_hashes=upstreams,
        )
        measures.append(
            LiquidityMeasure(
                subject_id=_SUBJECT,
                currency="CNY",
                role=role,
                value=values[role],
                unit=_unit(role),
                observed_at=_OBSERVED_AT,
                available_at=_AVAILABLE_AT,
                record_hash=record_hash,
                publication=publication,
            )
        )
    measure_tuple = tuple(measures)
    upstreams = tuple(sorted((*(item.seal_hash for item in measure_tuple), gross_manifest)))
    return LiquidityPremiumEvidence(
        evidence_id="liquidity-input",
        evidence_version="v1",
        subject_id=_SUBJECT,
        currency="CNY",
        measures=measure_tuple,
        gross_included_cost_roles=included_roles,
        gross_cost_treatment_version=treatment_version,
        gross_inclusion_manifest_hash=gross_manifest,
        source=_exact(
            role=EvidenceRole.EXACT_PIT_INPUT,
            evidence_id="liquidity-input",
            version="v1",
            subject_id=_SUBJECT,
            observed_at=_OBSERVED_AT,
            available_at=_AVAILABLE_AT,
            content_hash=_digest("liquidity-input"),
            curve_role="liquidity_premium",
            upstream_hashes=upstreams,
        ),
    )


def test_liquidity_premium_separates_compensation_from_once_only_costs() -> None:
    result = evaluate_liquidity_premium(
        _evidence(),
        policy=_policy(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is LiquidityPremiumStatus.AVAILABLE
    assert result.quote_age_seconds == Decimal("60")
    assert result.model_liquidity_premium_bp == Decimal("3")
    assert result.market_implied_liquidity_premium_bp == Decimal("3")
    assert result.total_deductible_cost_bp == Decimal("4")
    assert result.net_relative_value_bp == Decimal("8")
    assert result.output_hash == result.calculated_output_hash


def test_negative_gross_relative_value_is_valid_but_not_defaulted() -> None:
    result = evaluate_liquidity_premium(
        _evidence(gross="-2"),
        policy=_policy(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is LiquidityPremiumStatus.AVAILABLE
    assert result.gross_relative_value_bp == Decimal("-2")
    assert result.net_relative_value_bp == Decimal("-6")


def test_missing_cost_evidence_blocks_with_none_instead_of_zero_placeholder() -> None:
    result = evaluate_liquidity_premium(
        _evidence(omitted_role=LiquidityMeasureRole.LIQUIDATION_COST_BP),
        policy=_policy(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is LiquidityPremiumStatus.BLOCKED
    assert LiquidityPremiumBlockerCode.MEASURE_MISSING in {
        blocker.code for blocker in result.blockers
    }
    assert result.total_deductible_cost_bp is None
    assert result.net_relative_value_bp is None


def test_missing_quote_driver_returns_blocked_partial_components() -> None:
    result = evaluate_liquidity_premium(
        _evidence(omitted_role=LiquidityMeasureRole.BID_ASK_BP),
        policy=_policy(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is LiquidityPremiumStatus.BLOCKED
    assert LiquidityPremiumBlockerCode.MEASURE_MISSING in {
        blocker.code for blocker in result.blockers
    }
    assert result.quote_observed_at is None
    assert result.quote_age_seconds is None
    assert result.model_liquidity_premium_bp is None


def test_excluded_market_spread_has_complete_identity_and_no_implied_premium() -> None:
    result = evaluate_liquidity_premium(
        _evidence(market_spread="7"),
        policy=_policy(semantics=MarketSpreadSemantics.EXCLUDES_LIQUIDITY_PREMIUM),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is LiquidityPremiumStatus.AVAILABLE
    assert result.model_liquidity_premium_bp == Decimal("3")
    assert result.market_implied_liquidity_premium_bp is None


def test_quote_age_is_derived_from_source_clock_not_request_filled() -> None:
    stale_at = _EVALUATED_AT + timedelta(seconds=61)
    result = evaluate_liquidity_premium(
        _evidence(),
        policy=_policy(),
        evaluated_at=stale_at,
    )

    assert result.status is LiquidityPremiumStatus.BLOCKED
    assert LiquidityPremiumBlockerCode.QUOTE_STALE in {blocker.code for blocker in result.blockers}
    assert result.quote_age_seconds == Decimal("121")
    assert (
        replace(result, output_hash=result.output_hash).calculated_output_hash == result.output_hash
    )
