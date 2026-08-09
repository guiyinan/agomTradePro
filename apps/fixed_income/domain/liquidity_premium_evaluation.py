"""Liquidity-premium evaluation orchestration split from its contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.fixed_income.domain.evidence import require_aware, require_sha256
from apps.fixed_income.domain.liquidity_premium import (
    _OWNER_MEASURE_ROLES,
    _PREMIUM_DRIVER_ROLES,
    LiquidityCostEntry,
    LiquidityMeasure,
    LiquidityMeasureRole,
    LiquidityPremiumAssessment,
    LiquidityPremiumBlocker,
    LiquidityPremiumBlockerCode,
    LiquidityPremiumComponent,
    LiquidityPremiumEvidence,
    LiquidityPremiumPolicy,
    LiquidityPremiumStatus,
    MarketSpreadSemantics,
    _blocker,
    _elapsed_seconds,
    _make_result,
    liquidity_premium_input_hash,
)


def evaluate_liquidity_premium(
    evidence: LiquidityPremiumEvidence,
    *,
    policy: LiquidityPremiumPolicy,
    evaluated_at: datetime,
    expected_input_hash: str | None = None,
) -> LiquidityPremiumAssessment:
    """Derive quote age, decompose premium, and deduct exact costs once."""

    require_aware(evaluated_at, "evaluated_at")
    input_hash = liquidity_premium_input_hash(evidence, policy, evaluated_at=evaluated_at)
    blockers: list[LiquidityPremiumBlocker] = []
    if expected_input_hash is not None:
        require_sha256(expected_input_hash, "expected_input_hash")
        if expected_input_hash != input_hash:
            blockers.append(
                _blocker(LiquidityPremiumBlockerCode.INPUT_HASH_MISMATCH, "input hash mismatch")
            )
    if policy.evidence.usability_reason(evaluated_at) is not None:
        blockers.append(
            _blocker(LiquidityPremiumBlockerCode.POLICY_INACTIVE, "policy evidence inactive")
        )
    source_reason = evidence.source.usability_reason(evaluated_at)
    if source_reason == "evidence_from_future":
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.EVIDENCE_FROM_FUTURE,
                "liquidity PIT source from future",
            )
        )
    elif source_reason == "evidence_stale":
        blockers.append(
            _blocker(LiquidityPremiumBlockerCode.EVIDENCE_STALE, "liquidity PIT source stale")
        )
    roles = tuple(measure.role for measure in evidence.measures)
    duplicate_roles = {role for role in roles if roles.count(role) > 1}
    if duplicate_roles:
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.MEASURE_DUPLICATE,
                "duplicate liquidity measure role",
            )
        )
    missing_roles = tuple(
        sorted(
            (role for role in _OWNER_MEASURE_ROLES if role not in set(roles)),
            key=lambda role: role.value,
        )
    )
    if missing_roles:
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.MEASURE_MISSING,
                "required owner measure missing",
            )
        )
    measures: dict[LiquidityMeasureRole, LiquidityMeasure] = {}
    for measure in evidence.measures:
        measures.setdefault(measure.role, measure)
        if measure.subject_id != evidence.subject_id:
            blockers.append(
                _blocker(
                    LiquidityPremiumBlockerCode.SUBJECT_MISMATCH,
                    "measure subject mismatch",
                )
            )
        if measure.currency != evidence.currency:
            blockers.append(
                _blocker(
                    LiquidityPremiumBlockerCode.CURRENCY_MISMATCH,
                    "measure currency mismatch",
                )
            )
        reason = measure.publication.usability_reason(evaluated_at)
        if reason == "evidence_from_future":
            blockers.append(
                _blocker(
                    LiquidityPremiumBlockerCode.EVIDENCE_FROM_FUTURE,
                    "measure Publication from future",
                )
            )
        elif reason == "evidence_stale":
            blockers.append(
                _blocker(
                    LiquidityPremiumBlockerCode.EVIDENCE_STALE,
                    "measure Publication stale",
                )
            )
    values = {role: measure.value for role, measure in measures.items()}
    bid_ask = measures.get(LiquidityMeasureRole.BID_ASK_BP)
    quote_age = _elapsed_seconds(bid_ask.observed_at, evaluated_at) if bid_ask is not None else None
    if quote_age is not None and quote_age > Decimal(policy.maximum_quote_age_seconds):
        blockers.append(
            _blocker(LiquidityPremiumBlockerCode.QUOTE_STALE, "quote age exceeds hard gate")
        )
    turnover = values.get(LiquidityMeasureRole.TURNOVER_RATIO)
    if turnover is not None and turnover < policy.minimum_turnover_ratio:
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.TURNOVER_GATE_FAILED,
                "turnover is below hard gate",
            )
        )
    issue_size = values.get(LiquidityMeasureRole.ISSUE_SIZE)
    if issue_size is not None and issue_size < policy.minimum_issue_size:
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.ISSUE_SIZE_GATE_FAILED,
                "issue size is below hard gate",
            )
        )
    derived_values = dict(values)
    if quote_age is not None:
        derived_values[LiquidityMeasureRole.QUOTE_AGE_SECONDS] = quote_age
    components: list[LiquidityPremiumComponent] = []
    for premium_rule in policy.premium_rules:
        observed = derived_values.get(premium_rule.measure_role)
        if observed is None:
            continue
        if premium_rule.measure_role is LiquidityMeasureRole.QUOTE_AGE_SECONDS:
            unit = "seconds"
        else:
            premium_measure = measures.get(premium_rule.measure_role)
            unit = premium_measure.unit if premium_measure is not None else ""
        if unit != premium_rule.expected_unit:
            blockers.append(
                _blocker(LiquidityPremiumBlockerCode.UNIT_MISMATCH, "premium unit mismatch")
            )
            continue
        components.append(
            LiquidityPremiumComponent(
                measure_role=premium_rule.measure_role,
                observed_unit=unit,
                observed_value=observed,
                reference_value=premium_rule.reference_value,
                coefficient_bp_per_unit=premium_rule.coefficient_bp_per_unit,
                contribution_bp=(observed - premium_rule.reference_value)
                * premium_rule.coefficient_bp_per_unit,
            )
        )
    components_tuple = tuple(sorted(components, key=lambda item: item.measure_role.value))
    model_premium = (
        sum((item.contribution_bp for item in components_tuple), start=Decimal("0"))
        if len(components_tuple) == len(_PREMIUM_DRIVER_ROLES)
        else None
    )
    if model_premium is not None and model_premium < 0 and not policy.allow_negative_model_premium:
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.NEGATIVE_PREMIUM_NOT_ALLOWED,
                "negative model premium is not policy-authorized",
            )
        )
    cost_rule_included = tuple(
        rule.measure_role for rule in policy.cost_rules if rule.already_in_gross_relative_value
    )
    if (
        cost_rule_included != evidence.gross_included_cost_roles
        or policy.gross_cost_treatment_version != evidence.gross_cost_treatment_version
    ):
        blockers.append(
            _blocker(
                LiquidityPremiumBlockerCode.GROSS_COST_TREATMENT_MISMATCH,
                "policy and owner gross included-cost manifest differ",
            )
        )
    costs: list[LiquidityCostEntry] = []
    for cost_rule in policy.cost_rules:
        cost_measure = measures.get(cost_rule.measure_role)
        if cost_measure is None:
            continue
        if cost_measure.unit != cost_rule.expected_unit:
            blockers.append(
                _blocker(LiquidityPremiumBlockerCode.UNIT_MISMATCH, "cost unit mismatch")
            )
            continue
        applied = cost_measure.value * cost_rule.application_multiplier
        costs.append(
            LiquidityCostEntry(
                measure_role=cost_rule.measure_role,
                quoted_unit=cost_measure.unit,
                quoted_cost_bp=cost_measure.value,
                cost_basis=cost_rule.cost_basis,
                quoted_horizon_days=cost_rule.quoted_horizon_days,
                applied_horizon_days=cost_rule.applied_horizon_days,
                application_multiplier=cost_rule.application_multiplier,
                applied_cost_bp=applied,
                already_in_gross_relative_value=(cost_rule.already_in_gross_relative_value),
                deductible_cost_bp=(
                    Decimal("0") if cost_rule.already_in_gross_relative_value else applied
                ),
            )
        )
    costs_tuple = tuple(sorted(costs, key=lambda item: item.measure_role.value))
    spread_roles = (
        LiquidityMeasureRole.MARKET_SPREAD_BP,
        LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP,
        LiquidityMeasureRole.OPTION_COST_BP,
        LiquidityMeasureRole.OTHER_SPREAD_BP,
    )
    implied: Decimal | None = None
    if all(role in values for role in spread_roles):
        residual = (
            values[LiquidityMeasureRole.MARKET_SPREAD_BP]
            - values[LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP]
            - values[LiquidityMeasureRole.OPTION_COST_BP]
            - values[LiquidityMeasureRole.OTHER_SPREAD_BP]
        )
        if policy.market_spread_semantics is MarketSpreadSemantics.INCLUDES_LIQUIDITY_PREMIUM:
            implied = residual
            if (
                model_premium is not None
                and abs(implied - model_premium) > policy.decomposition_tolerance_bp
            ):
                blockers.append(
                    _blocker(
                        LiquidityPremiumBlockerCode.MARKET_SPREAD_IDENTITY_FAILED,
                        "market and model liquidity premium differ",
                    )
                )
            if implied < 0 and not policy.allow_negative_market_implied_premium:
                blockers.append(
                    _blocker(
                        LiquidityPremiumBlockerCode.NEGATIVE_PREMIUM_NOT_ALLOWED,
                        "negative implied premium is not policy-authorized",
                    )
                )
        elif abs(residual) > policy.decomposition_tolerance_bp:
            blockers.append(
                _blocker(
                    LiquidityPremiumBlockerCode.MARKET_SPREAD_IDENTITY_FAILED,
                    "market spread excluding liquidity is not fully decomposed",
                )
            )
    unique_blockers = tuple(sorted(set(blockers), key=lambda item: (item.code.value, item.detail)))
    return _make_result(
        status=(
            LiquidityPremiumStatus.BLOCKED if unique_blockers else LiquidityPremiumStatus.AVAILABLE
        ),
        evidence=evidence,
        policy=policy,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        values=values,
        quote_age_seconds=quote_age,
        components=components_tuple,
        costs=costs_tuple,
        implied_premium=implied,
        missing_roles=missing_roles,
        blockers=unique_blockers,
    )


__all__ = ["evaluate_liquidity_premium"]
