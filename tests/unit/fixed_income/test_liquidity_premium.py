"""Premium decomposition and once-only cost coverage for R5 liquidity evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.fixed_income.domain.evidence import EvidenceRole, ExactEvidence, canonical_hash
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityCostEntry,
    LiquidityCostRule,
    LiquidityMeasure,
    LiquidityMeasureRole,
    LiquidityPremiumBlocker,
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


def _rebind_evidence(
    evidence: LiquidityPremiumEvidence,
    *,
    measures: tuple[LiquidityMeasure, ...] | None = None,
    source: ExactEvidence | None = None,
) -> LiquidityPremiumEvidence:
    rebound_measures = evidence.measures if measures is None else measures
    rebound_source = evidence.source if source is None else source
    upstreams = tuple(
        sorted(
            {
                *(item.seal_hash for item in rebound_measures),
                evidence.gross_inclusion_manifest_hash,
            }
        )
    )
    return replace(
        evidence,
        measures=rebound_measures,
        source=replace(rebound_source, upstream_hashes=upstreams),
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


def test_liquidity_blocker_and_measure_reject_invalid_boundaries() -> None:
    invalid: Any = "invalid"
    with pytest.raises(ValueError, match="code is invalid"):
        LiquidityPremiumBlocker(code=invalid, detail="invalid")

    measure = _evidence().measures[0]
    invalid_publication = _exact(
        role=EvidenceRole.POLICY,
        evidence_id="policy",
        version="v1",
        subject_id=measure.subject_id,
        observed_at=measure.observed_at,
        available_at=measure.available_at,
        content_hash=measure.record_hash,
        curve_role=f"liquidity:{measure.role.value}",
    )
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"role": invalid}, "role is invalid"),
        ({"role": LiquidityMeasureRole.QUOTE_AGE_SECONDS}, "must be derived"),
        ({"value": Decimal("-1")}, "cannot be negative"),
        ({"available_at": measure.observed_at - timedelta(seconds=1)}, "cannot precede"),
        ({"publication": invalid_publication}, "requires Publication"),
        (
            {"publication": replace(measure.publication, curve_role="liquidity:other")},
            "identity/clocks/role",
        ),
        ({"record_hash": _digest("unbound")}, "not bound"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(measure, **kwargs)

    turnover = next(
        item for item in _evidence().measures if item.role is LiquidityMeasureRole.TURNOVER_RATIO
    )
    issue_size = next(
        item for item in _evidence().measures if item.role is LiquidityMeasureRole.ISSUE_SIZE
    )
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        replace(turnover, value=Decimal("1.1"))
    with pytest.raises(ValueError, match="positive"):
        replace(issue_size, value=Decimal("0"))


def test_liquidity_rules_and_policy_reject_invalid_boundaries() -> None:
    policy = _policy()
    invalid: Any = "invalid"
    premium_rule = policy.premium_rules[0]
    cost_rule = policy.cost_rules[0]

    with pytest.raises(ValueError, match="not a premium driver"):
        replace(premium_rule, measure_role=LiquidityMeasureRole.MARKET_SPREAD_BP)
    with pytest.raises(ValueError, match="cost rule role is invalid"):
        replace(cost_rule, measure_role=LiquidityMeasureRole.BID_ASK_BP)
    with pytest.raises(ValueError, match="gross traded notional"):
        replace(cost_rule, cost_basis=invalid)
    with pytest.raises(ValueError, match="horizons must be positive"):
        replace(cost_rule, quoted_horizon_days=0)
    with pytest.raises(ValueError, match="multiplier must be positive"):
        replace(cost_rule, application_multiplier=Decimal("0"))

    wrong_role_evidence = _exact(
        role=EvidenceRole.EXACT_PIT_INPUT,
        evidence_id=policy.policy_id,
        version=policy.policy_version,
        subject_id=policy.policy_id,
        observed_at=_OBSERVED_AT,
        available_at=_AVAILABLE_AT,
        content_hash=_digest("wrong-policy-role"),
        curve_role="liquidity_premium_policy",
    )
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"market_spread_semantics": invalid}, "semantics are invalid"),
        ({"premium_rules": policy.premium_rules[:-1]}, "canonical driver roles"),
        ({"cost_rules": policy.cost_rules[:-1]}, "canonical cost roles"),
        ({"decomposition_tolerance_bp": Decimal("-1")}, "cannot be negative"),
        ({"maximum_quote_age_seconds": 0}, "quote age must be positive"),
        ({"minimum_turnover_ratio": Decimal("2")}, r"\[0, 1\]"),
        ({"minimum_issue_size": Decimal("0")}, "issue size must be positive"),
        ({"evidence": wrong_role_evidence}, "requires Research evidence"),
        ({"evidence": replace(policy.evidence, curve_role="other")}, "identity mismatch"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(policy, **kwargs)


def test_liquidity_evidence_rejects_unsealed_or_noncanonical_inputs() -> None:
    evidence = _evidence()
    wrong_role_source = _exact(
        role=EvidenceRole.PUBLICATION,
        evidence_id=evidence.evidence_id,
        version=evidence.evidence_version,
        subject_id=evidence.subject_id,
        observed_at=_OBSERVED_AT,
        available_at=_AVAILABLE_AT,
        content_hash=_digest("wrong-source-role"),
        curve_role="liquidity_premium",
    )
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"source": wrong_role_source}, "requires exact PIT"),
        ({"source": replace(evidence.source, curve_role="other")}, "identity mismatch"),
        ({"measures": tuple(reversed(evidence.measures))}, "canonical role order"),
        (
            {"gross_included_cost_roles": (LiquidityMeasureRole.BID_ASK_BP,)},
            "canonical valid costs",
        ),
        ({"gross_inclusion_manifest_hash": _digest("wrong")}, "manifest hash mismatch"),
        (
            {
                "source": replace(
                    evidence.source,
                    upstream_hashes=(evidence.gross_inclusion_manifest_hash,),
                )
            },
            "attest all measures",
        ),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(evidence, **kwargs)

    gross = next(
        item
        for item in evidence.measures
        if item.role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP
    )
    unbound_gross = replace(gross, publication=replace(gross.publication, upstream_hashes=()))
    measures = tuple(
        unbound_gross if item.role is gross.role else item for item in evidence.measures
    )
    with pytest.raises(ValueError, match="does not attest"):
        replace(evidence, measures=measures)


def test_liquidity_component_and_cost_entry_enforce_replay_identities() -> None:
    result = evaluate_liquidity_premium(_evidence(), policy=_policy(), evaluated_at=_EVALUATED_AT)
    component = result.premium_components[0]
    invalid: Any = "invalid"
    with pytest.raises(ValueError, match="non-driver"):
        replace(component, measure_role=LiquidityMeasureRole.MARKET_SPREAD_BP)
    with pytest.raises(ValueError, match="identity failed"):
        replace(component, contribution_bp=component.contribution_bp + Decimal("1"))

    cost = result.cost_entries[0]
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"measure_role": LiquidityMeasureRole.BID_ASK_BP}, "role is invalid"),
        ({"cost_basis": invalid}, "basis is invalid"),
        ({"quoted_horizon_days": 0}, "horizons must be positive"),
        ({"quoted_cost_bp": Decimal("-1")}, "cannot be negative"),
        ({"applied_cost_bp": cost.applied_cost_bp + Decimal("1")}, "not recomputable"),
        ({"deductible_cost_bp": Decimal("0")}, "omitted or deducted twice"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(cost, **kwargs)

    included = LiquidityCostEntry(
        measure_role=cost.measure_role,
        quoted_unit=cost.quoted_unit,
        quoted_cost_bp=cost.quoted_cost_bp,
        cost_basis=cost.cost_basis,
        quoted_horizon_days=cost.quoted_horizon_days,
        applied_horizon_days=cost.applied_horizon_days,
        application_multiplier=cost.application_multiplier,
        applied_cost_bp=cost.applied_cost_bp,
        already_in_gross_relative_value=True,
        deductible_cost_bp=Decimal("0"),
    )
    assert included.deductible_cost_bp == Decimal("0")


def test_liquidity_assessment_rejects_tampered_replay_and_safety_fields() -> None:
    result = evaluate_liquidity_premium(_evidence(), policy=_policy(), evaluated_at=_EVALUATED_AT)
    invalid: Any = "invalid"
    blocker = LiquidityPremiumBlocker(
        code=LiquidityPremiumBlockerCode.INPUT_HASH_MISMATCH,
        detail="tampered",
    )
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"market_spread_semantics": invalid}, "semantics are invalid"),
        ({"decomposition_tolerance_bp": Decimal("-1")}, "cannot be negative"),
        ({"minimum_turnover_ratio": Decimal("2")}, r"\[0, 1\]"),
        ({"minimum_issue_size": Decimal("0")}, "must be positive"),
        ({"quote_observed_at": None}, "must be all-or-none"),
        ({"quote_age_seconds": Decimal("-1")}, "cannot be negative"),
        ({"turnover_ratio": Decimal("2")}, r"\[0, 1\]"),
        ({"issue_size": Decimal("0")}, "must be positive"),
        ({"evaluated_at": result.evaluated_at + timedelta(seconds=1)}, "not recomputable"),
        ({"research_only": False}, "must remain research-only"),
        ({"maximum_quote_age_seconds": 0}, "quote age must be positive"),
        ({"premium_rules": result.premium_rules[:-1]}, "exact driver universe"),
        (
            {"premium_components": result.premium_components + (result.premium_components[0],)},
            "canonical driver subset",
        ),
        (
            {
                "premium_components": (
                    replace(result.premium_components[0], observed_unit="other"),
                    *result.premium_components[1:],
                )
            },
            "replay exact policy rules",
        ),
        ({"turnover_ratio": Decimal("0.3")}, "turnover driver differs"),
        ({"issue_size": Decimal("1001")}, "issue-size driver differs"),
        (
            {"model_liquidity_premium_bp": result.model_liquidity_premium_bp + Decimal("1")},
            "model premium is not recomputable",
        ),
        ({"cost_rules": result.cost_rules[:-1]}, "exact cost universe"),
        (
            {"cost_entries": result.cost_entries + (result.cost_entries[0],)},
            "canonical cost subset",
        ),
        (
            {
                "cost_entries": (
                    replace(result.cost_entries[0], quoted_unit="other"),
                    *result.cost_entries[1:],
                )
            },
            "replay exact policy rules",
        ),
        (
            {"gross_included_cost_roles": (LiquidityMeasureRole.TRANSACTION_COST_BP,)},
            "manifest and cost ledger",
        ),
        ({"total_deductible_cost_bp": Decimal("5")}, "total is not recomputable"),
        ({"net_relative_value_bp": Decimal("9")}, "net relative value is not recomputable"),
        ({"market_implied_liquidity_premium_bp": Decimal("4")}, "not recomputable"),
        (
            {
                "missing_roles": (
                    LiquidityMeasureRole.TURNOVER_RATIO,
                    LiquidityMeasureRole.BID_ASK_BP,
                )
            },
            "must be unique and canonical",
        ),
        ({"blockers": (blocker, blocker)}, "must be unique and canonical"),
        ({"blockers": (blocker,)}, "available liquidity output is incomplete"),
        ({"maximum_quote_age_seconds": 30}, "violates quote-age gate"),
        ({"minimum_turnover_ratio": Decimal("0.3")}, "violates turnover gate"),
        ({"minimum_issue_size": Decimal("1001")}, "violates issue-size gate"),
        ({"output_hash": "0" * 64}, "output hash mismatch"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(result, **kwargs)


def test_liquidity_evaluator_reports_hash_clock_identity_and_gate_failures() -> None:
    evidence = _evidence()
    policy = _policy()

    mismatch = evaluate_liquidity_premium(
        evidence,
        policy=policy,
        evaluated_at=_EVALUATED_AT,
        expected_input_hash="0" * 64,
    )
    assert LiquidityPremiumBlockerCode.INPUT_HASH_MISMATCH in {
        item.code for item in mismatch.blockers
    }
    with pytest.raises(ValueError, match="expected_input_hash"):
        evaluate_liquidity_premium(
            evidence,
            policy=policy,
            evaluated_at=_EVALUATED_AT,
            expected_input_hash="bad",
        )

    inactive_policy = replace(
        policy,
        evidence=replace(
            policy.evidence,
            valid_until=_EVALUATED_AT - timedelta(microseconds=1),
        ),
    )
    inactive = evaluate_liquidity_premium(
        evidence, policy=inactive_policy, evaluated_at=_EVALUATED_AT
    )
    assert LiquidityPremiumBlockerCode.POLICY_INACTIVE in {item.code for item in inactive.blockers}

    future_source = replace(
        evidence.source,
        observed_at=_EVALUATED_AT + timedelta(seconds=1),
        available_at=_EVALUATED_AT + timedelta(seconds=2),
    )
    future = evaluate_liquidity_premium(
        _rebind_evidence(evidence, source=future_source),
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )
    assert LiquidityPremiumBlockerCode.EVIDENCE_FROM_FUTURE in {
        item.code for item in future.blockers
    }

    stale_source = replace(
        evidence.source,
        valid_until=_EVALUATED_AT - timedelta(microseconds=1),
    )
    stale = evaluate_liquidity_premium(
        _rebind_evidence(evidence, source=stale_source),
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )
    assert LiquidityPremiumBlockerCode.EVIDENCE_STALE in {item.code for item in stale.blockers}

    duplicated_measures = tuple(
        sorted(
            (*evidence.measures, evidence.measures[0]),
            key=lambda item: item.role.value,
        )
    )
    duplicated = evaluate_liquidity_premium(
        _rebind_evidence(evidence, measures=duplicated_measures),
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )
    assert LiquidityPremiumBlockerCode.MEASURE_DUPLICATE in {
        item.code for item in duplicated.blockers
    }

    target = evidence.measures[0]
    wrong_subject = replace(
        target,
        subject_id="other-bond",
        publication=replace(target.publication, subject_id="other-bond"),
    )
    wrong_currency = replace(
        target,
        currency="USD",
        publication=replace(target.publication, currency="USD"),
    )
    for changed, expected in (
        (wrong_subject, LiquidityPremiumBlockerCode.SUBJECT_MISMATCH),
        (wrong_currency, LiquidityPremiumBlockerCode.CURRENCY_MISMATCH),
    ):
        measures = tuple(changed if item is target else item for item in evidence.measures)
        result = evaluate_liquidity_premium(
            _rebind_evidence(evidence, measures=measures),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
        assert expected in {item.code for item in result.blockers}

    non_quote = next(
        item
        for item in evidence.measures
        if item.role is LiquidityMeasureRole.FINANCING_CARRY_COST_BP
    )
    future_publication = replace(
        non_quote.publication,
        observed_at=_EVALUATED_AT + timedelta(seconds=1),
        available_at=_EVALUATED_AT + timedelta(seconds=2),
    )
    future_measure = replace(
        non_quote,
        observed_at=future_publication.observed_at,
        available_at=future_publication.available_at,
        publication=future_publication,
    )
    stale_publication = replace(
        non_quote.publication,
        valid_until=_EVALUATED_AT - timedelta(microseconds=1),
    )
    stale_measure = replace(non_quote, publication=stale_publication)
    for changed, expected in (
        (future_measure, LiquidityPremiumBlockerCode.EVIDENCE_FROM_FUTURE),
        (stale_measure, LiquidityPremiumBlockerCode.EVIDENCE_STALE),
    ):
        measures = tuple(changed if item is non_quote else item for item in evidence.measures)
        result = evaluate_liquidity_premium(
            _rebind_evidence(evidence, measures=measures),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
        assert expected in {item.code for item in result.blockers}

    by_role = {item.role: item for item in evidence.measures}
    altered_values = (
        (
            LiquidityMeasureRole.TURNOVER_RATIO,
            Decimal("0.05"),
            LiquidityPremiumBlockerCode.TURNOVER_GATE_FAILED,
        ),
        (
            LiquidityMeasureRole.ISSUE_SIZE,
            Decimal("100"),
            LiquidityPremiumBlockerCode.ISSUE_SIZE_GATE_FAILED,
        ),
    )
    for role, value, expected in altered_values:
        changed = replace(by_role[role], value=value)
        measures = tuple(changed if item.role is role else item for item in evidence.measures)
        result = evaluate_liquidity_premium(
            _rebind_evidence(evidence, measures=measures),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
        assert expected in {item.code for item in result.blockers}


def test_liquidity_evaluator_reports_units_negative_premiums_and_identities() -> None:
    evidence = _evidence()
    policy = _policy()
    by_role = {item.role: item for item in evidence.measures}

    for role in (
        LiquidityMeasureRole.TURNOVER_RATIO,
        LiquidityMeasureRole.FINANCING_CARRY_COST_BP,
    ):
        changed = replace(by_role[role], unit="wrong-unit")
        measures = tuple(changed if item.role is role else item for item in evidence.measures)
        result = evaluate_liquidity_premium(
            _rebind_evidence(evidence, measures=measures),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
        assert LiquidityPremiumBlockerCode.UNIT_MISMATCH in {item.code for item in result.blockers}

    negative_rules = tuple(
        (
            replace(rule, coefficient_bp_per_unit=Decimal("-10"))
            if rule.measure_role is LiquidityMeasureRole.BID_ASK_BP
            else rule
        )
        for rule in policy.premium_rules
    )
    negative_model = evaluate_liquidity_premium(
        _evidence(market_spread="-12"),
        policy=replace(policy, premium_rules=negative_rules),
        evaluated_at=_EVALUATED_AT,
    )
    assert LiquidityPremiumBlockerCode.NEGATIVE_PREMIUM_NOT_ALLOWED in {
        item.code for item in negative_model.blockers
    }

    treatment_mismatch = evaluate_liquidity_premium(
        evidence,
        policy=replace(policy, gross_cost_treatment_version="v2"),
        evaluated_at=_EVALUATED_AT,
    )
    assert LiquidityPremiumBlockerCode.GROSS_COST_TREATMENT_MISMATCH in {
        item.code for item in treatment_mismatch.blockers
    }

    with pytest.raises(ValueError, match="market/model liquidity premium identity"):
        evaluate_liquidity_premium(
            _evidence(market_spread="11"),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
    with pytest.raises(ValueError, match="market/model liquidity premium identity"):
        evaluate_liquidity_premium(
            _evidence(market_spread="5"),
            policy=policy,
            evaluated_at=_EVALUATED_AT,
        )
    with pytest.raises(ValueError, match="excluding premium is not decomposed"):
        evaluate_liquidity_premium(
            evidence,
            policy=_policy(semantics=MarketSpreadSemantics.EXCLUDES_LIQUIDITY_PREMIUM),
            evaluated_at=_EVALUATED_AT,
        )
