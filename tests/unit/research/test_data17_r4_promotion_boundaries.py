"""DATA-17 boundary coverage for the R4 promotion Domain contracts.

The cases in this module use the public R4 factories and dataclass replacement
to exercise the rejection boundaries that are useful to a caller.  They keep
the evidence graph real and assert the reason returned by each guard.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecisionOutcome,
    R4PromotionGateCode,
    R4PromotionGateOutcome,
    create_r4_promotion_decision,
)
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionMethodSummaryEvidence,
    R4PromotionR3AttestationEvidence,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEventType,
    R4PromotionLifecycleState,
    create_r4_promotion_lifecycle_event,
    create_r4_promotion_lifecycle_root,
    derive_r4_promotion_lifecycle_state,
    r4_promotion_lifecycle_reason_hash,
    r4_promotion_stream_id,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    R4PromotionStudyRegistration,
)
from apps.research.domain.r4_promotion_trial import (
    R4PromotionTrialSeal,
    R4PromotionTrialState,
)
from tests.unit.portfolio.macro_risk_rolling_factories import build_study
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    DECISION_RECORDED_AT,
    portfolio_record,
    portfolio_record_seal,
    promotion_decision,
    promotion_policy,
    promotion_scope,
    promotion_trial,
    r3_evidence,
    study_registration,
)


def _other_policy() -> R4PromotionPolicy:
    """Build a second valid R4 scope with a matching Portfolio study."""

    study_family_id = "r4-rolling-study-2"
    scope = R4PromotionScope.create(
        study_family_id=study_family_id,
        universe_policy_id="cn-two-asset-research-universe",
        factor_policy_id="growth-inflation-factor-family",
        split_policy_id="walk-forward-embargo-research",
        cost_semantics_id="gross-return-cost-separate",
    )
    registration = R4PromotionStudyRegistration.create(
        study_family_id=study_family_id,
        study_id=study_family_id,
        universe_policy_id=scope.universe_policy_id,
        asset_codes=("asset-a", "asset-b"),
        factor_policy_id=scope.factor_policy_id,
        factor_codes=("growth", "inflation"),
        split_policy_id=scope.split_policy_id,
        split_policy_version="r4-walk-forward.v1",
        cost_semantics_id=scope.cost_semantics_id,
        cost_semantics_version="gross-cost-reported-separately.v1",
    )
    return promotion_policy(scope=scope, registration=registration)


def _unrelated_scope() -> R4PromotionScope:
    """Return a valid scope used only to test cross-scope rejection."""

    return R4PromotionScope.create(
        study_family_id="r4-unrelated-family",
        universe_policy_id="unrelated-universe",
        factor_policy_id="unrelated-factor",
        split_policy_id="unrelated-split",
        cost_semantics_id="unrelated-cost",
    )


def _registration_with(registration: R4PromotionStudyRegistration, **changes):
    """Re-seal a registration after changing one exact binding."""

    values = {
        "study_family_id": registration.study_family_id,
        "study_id": registration.study_id,
        "universe_policy_id": registration.universe_policy_id,
        "asset_codes": registration.asset_codes,
        "factor_policy_id": registration.factor_policy_id,
        "factor_codes": registration.factor_codes,
        "split_policy_id": registration.split_policy_id,
        "split_policy_version": registration.split_policy_version,
        "cost_semantics_id": registration.cost_semantics_id,
        "cost_semantics_version": registration.cost_semantics_version,
    }
    values.update(changes)
    return R4PromotionStudyRegistration.create(**values)


def _other_decision():
    """Build one real decision in the alternative scope."""

    policy = _other_policy()
    record = portfolio_record(study=build_study(study_id="r4-rolling-study-2"))
    seal = portfolio_record_seal(record=record)
    trial = promotion_trial(policy=policy, record_seal=seal)
    return promotion_decision(
        decision_id="r4-promotion-decision-other-scope",
        decision_version="decision.other.v1",
        policy=policy,
        trial=trial,
        decided_at=DECIDED_AT,
        recorded_at=DECISION_RECORDED_AT,
    )


def _authorization(
    decision,
    *,
    event_type: R4PromotionLifecycleEventType = R4PromotionLifecycleEventType.PROMOTED,
    rollback_target=None,
    reason_codes: tuple[str, ...] = ("research_policy_approved",),
    issued_at: datetime | None = None,
    recorded_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> R4PromotionLifecycleAuthorization:
    """Create an authorization with a window suitable for the decision."""

    issued = issued_at or (decision.recorded_at + timedelta(minutes=1))
    recorded = recorded_at or (issued + timedelta(minutes=1))
    valid = valid_until or (recorded + timedelta(hours=1))
    return R4PromotionLifecycleAuthorization.create(
        authorization_id=f"r4-boundary-auth-{event_type.value}",
        authorization_version="authorization.boundary.v1",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reason_codes,
        issued_at=issued,
        recorded_at=recorded,
        valid_until=valid,
    )


def _root(decision, *, authorization=None, occurred_at=None, recorded_at=None):
    """Create a valid first lifecycle event for a decision."""

    auth = authorization or _authorization(decision)
    occurred = occurred_at or (auth.recorded_at + timedelta(minutes=1))
    recorded = recorded_at or (occurred + timedelta(minutes=1))
    return create_r4_promotion_lifecycle_root(
        event_id=f"r4-boundary-root-{decision.decision_id}",
        event_version="event.boundary.v1",
        decision=decision,
        authorization=auth,
        reason_codes=("research_policy_approved",),
        occurred_at=occurred,
        recorded_at=recorded,
    )


def _promote(previous_events, decision, *, suffix: str):
    """Append a valid replacement promotion."""

    previous = previous_events[-1]
    auth = _authorization(
        decision,
        reason_codes=("replacement_policy_approved",),
        issued_at=max(previous.recorded_at, decision.recorded_at) + timedelta(minutes=1),
    )
    occurred = auth.recorded_at + timedelta(minutes=1)
    return create_r4_promotion_lifecycle_event(
        event_id=f"r4-boundary-promote-{suffix}",
        event_version="event.boundary.v1",
        previous_events=previous_events,
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        authorization=auth,
        reason_codes=("replacement_policy_approved",),
        occurred_at=occurred,
        recorded_at=occurred + timedelta(minutes=1),
    )


def _rollback(previous_events, decision, target, *, suffix: str):
    """Append a valid rollback event."""

    previous = previous_events[-1]
    auth = _authorization(
        decision,
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        rollback_target=target,
        reason_codes=("replacement_regression",),
        issued_at=previous.recorded_at + timedelta(minutes=1),
    )
    occurred = auth.recorded_at + timedelta(minutes=1)
    return create_r4_promotion_lifecycle_event(
        event_id=f"r4-boundary-rollback-{suffix}",
        event_version="event.boundary.v1",
        previous_events=previous_events,
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        decision=decision,
        rollback_target=target,
        authorization=auth,
        reason_codes=("replacement_regression",),
        occurred_at=occurred,
        recorded_at=occurred + timedelta(minutes=1),
    )


def _record_with(record: R4PromotionPortfolioRecordSeal, **changes):
    """Re-seal a record after changing one promotion-facing field."""

    values = {
        "owner_record_key": record.owner_record_key,
        "record_id": record.record_id,
        "record_version": record.record_version,
        "record_hash": record.record_hash,
        "study_id": record.study_id,
        "study_version": record.study_version,
        "study_content_hash": record.study_content_hash,
        "artifact_hash": record.artifact_hash,
        "r3_attestation_hash": record.r3_attestation_hash,
        "split_contract_hash": record.split_contract_hash,
        "split_policy_version": record.split_policy_version,
        "record_subhashes": record.record_subhashes,
        "evaluated_at": record.evaluated_at,
        "recorded_at": record.recorded_at,
        "valid_until": record.valid_until,
        "producer_code_version": record.producer_code_version,
        "dependency_lock_hash": record.dependency_lock_hash,
        "cost_semantics_version": record.cost_semantics_version,
        "windows": record.windows,
        "window_metrics": record.window_metrics,
        "method_summaries": record.method_summaries,
        "exposure_point_hashes": record.exposure_point_hashes,
        "regime_summary_hashes": record.regime_summary_hashes,
        "regime_covered_fold_ids": record.regime_covered_fold_ids,
        "artifact_evidence_complete": record.artifact_evidence_complete,
        "artifact_eligible": record.artifact_eligible,
        "artifact_blockers": record.artifact_blockers,
        "record_r3_attestation": record.record_r3_attestation,
    }
    values.update(changes)
    return R4PromotionPortfolioRecordSeal.create(**values)


def _summary_with(summary: R4PromotionMethodSummaryEvidence, *, window_count: int):
    """Re-seal one summary with a different fold count."""

    return R4PromotionMethodSummaryEvidence.create(
        method=summary.method,
        window_count=window_count,
        compounded_gross_return=summary.compounded_gross_return,
        realized_variance=summary.realized_variance,
        maximum_drawdown=summary.maximum_drawdown,
        total_turnover=summary.total_turnover,
        total_expected_cost=summary.total_expected_cost,
        cost_semantics_version=summary.cost_semantics_version,
        source_content_hash=summary.source_content_hash,
    )


def test_scope_rejects_invalid_authority_target_and_identity() -> None:
    scope = promotion_scope()

    with pytest.raises(ValueError, match="authority is invalid"):
        replace(scope, owner="portfolio")
    with pytest.raises(ValueError, match="target must be macro-factor"):
        replace(scope, target_method=MacroRiskCandidateKind.EQUAL_WEIGHT)
    with pytest.raises(ValueError, match="identity or content hash mismatch"):
        replace(scope, content_hash="0" * 64)


@pytest.mark.parametrize("bad", ("", "has whitespace", "x" * 193))
def test_scope_factory_rejects_unbounded_semantic_tokens(bad: str) -> None:
    with pytest.raises(ValueError, match="study_family_id must be a bounded token"):
        R4PromotionScope.create(
            study_family_id=bad,
            universe_policy_id="universe",
            factor_policy_id="factor",
            split_policy_id="split",
            cost_semantics_id="cost",
        )


def test_scope_hash_and_decimal_datetime_helpers_fail_closed() -> None:
    policy = promotion_policy()

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(policy.scope, content_hash="A" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        policy.is_active_at(datetime(2026, 2, 1))
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(policy, minimum_regime_coverage_ratio=Decimal("NaN"))


def test_registration_requires_nonempty_unique_ordered_codes_and_exact_hash() -> None:
    registration = study_registration()

    with pytest.raises(ValueError, match="asset_codes must be unique and ordered"):
        replace(registration, asset_codes=("asset-b", "asset-a"))
    with pytest.raises(ValueError, match="factor_codes must be unique and ordered"):
        replace(registration, factor_codes=("growth", "growth"))
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(registration, content_hash="0" * 64)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("owner", "portfolio", "authority or status is invalid"),
        ("reference_methods", (), "references must be all non-target"),
        ("minimum_fold_count", 1, "minimum_fold_count must be at least two"),
        ("minimum_fold_count", True, "minimum_fold_count must be at least two"),
        (
            "minimum_regime_coverage_ratio",
            Decimal("0"),
            "minimum_regime_coverage_ratio must be within",
        ),
        (
            "minimum_regime_coverage_ratio",
            Decimal("1.1"),
            "minimum_regime_coverage_ratio must be within",
        ),
        ("minimum_relative_net_return", Decimal("-0.01"), "cannot be negative"),
        ("maximum_relative_drawdown_increase", Decimal("-0.01"), "cannot be negative"),
        ("maximum_relative_volatility_increase", Decimal("-0.01"), "cannot be negative"),
        ("maximum_relative_cost_increase", Decimal("-0.01"), "cannot be negative"),
        ("decision_validity_seconds", 0, "within one year"),
        ("decision_validity_seconds", True, "within one year"),
        ("active_until", datetime(2025, 1, 1, tzinfo=UTC), "receipt/active window is invalid"),
        ("research_only", False, "must remain research-only"),
    ),
)
def test_policy_rejects_each_explicit_gate_boundary(field, value, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(promotion_policy(), **{field: value})


def test_policy_rejects_registration_and_reference_authority_substitution() -> None:
    policy = promotion_policy()
    changed_registration = _registration_with(
        policy.registration,
        study_id="r4-rolling-study-1-other",
    )
    with pytest.raises(ValueError, match="registration does not match"):
        replace(policy, registration=changed_registration)

    with pytest.raises(ValueError, match="references must be all non-target"):
        replace(
            policy,
            reference_methods=(MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,),
        )


def test_policy_window_requires_aware_clocks_and_monotonic_receipt() -> None:
    policy = promotion_policy()

    with pytest.raises(ValueError, match="policy approved_at"):
        replace(policy, approved_at=datetime(2025, 12, 1))
    with pytest.raises(ValueError, match="receipt/active window is invalid"):
        replace(policy, recorded_at=policy.active_from + timedelta(seconds=1))


def test_policy_active_boundary_is_half_open() -> None:
    policy = promotion_policy()

    assert policy.is_active_at(policy.recorded_at) is False
    assert policy.is_active_at(policy.active_from) is True
    assert policy.is_active_at(policy.active_until) is False


def test_r3_evidence_rejects_authority_window_retirement_and_hash_tampering() -> None:
    evidence = r3_evidence()

    with pytest.raises(ValueError, match="authority is invalid"):
        replace(evidence, owner="portfolio")
    with pytest.raises(ValueError, match="validity is invalid"):
        replace(evidence, valid_until=evidence.approved_at)
    with pytest.raises(ValueError, match="retirement is invalid"):
        replace(evidence, retired_at=evidence.approved_at)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(evidence, content_hash="0" * 64)


def test_r3_active_and_effective_validity_honor_retirement_boundary() -> None:
    evidence = r3_evidence()
    retired = R4PromotionR3AttestationEvidence.create(
        artifact_id=evidence.artifact_id,
        artifact_version=evidence.artifact_version,
        artifact_content_hash=evidence.artifact_content_hash,
        decision_id=evidence.decision_id,
        decision_version=evidence.decision_version,
        decision_content_hash=evidence.decision_content_hash,
        approved_at=evidence.approved_at,
        valid_until=evidence.valid_until,
        retired_at=evidence.approved_at + timedelta(days=10),
        attestation_hash=evidence.attestation_hash,
    )

    assert retired.is_active_at(retired.approved_at) is True
    assert retired.is_active_at(retired.retired_at) is False
    assert retired.effective_valid_until == retired.retired_at


def test_window_evidence_rejects_ordered_codes_time_and_hash_boundaries() -> None:
    window = portfolio_record_seal().windows[0]

    with pytest.raises(ValueError, match="asset_codes must be unique and ordered"):
        replace(window, asset_codes=("asset-b", "asset-a"))
    with pytest.raises(ValueError, match="factor_codes must be unique and ordered"):
        replace(window, factor_codes=("growth", "growth"))
    with pytest.raises(ValueError, match="selection must precede evaluation"):
        replace(window, selection_as_of=window.evaluation_as_of)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(window, content_hash="0" * 64)


def test_window_metric_evidence_rejects_empty_returns_risk_cost_and_hash() -> None:
    metric = portfolio_record_seal().window_metrics[0]

    with pytest.raises(ValueError, match="requires period returns"):
        replace(metric, period_returns=())
    with pytest.raises(ValueError, match="risk metrics are invalid"):
        replace(metric, maximum_drawdown=Decimal("1.1"))
    with pytest.raises(ValueError, match="turnover/cost cannot be negative"):
        replace(metric, expected_cost=Decimal("-0.01"))
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(metric, content_hash="0" * 64)


def test_method_summary_evidence_rejects_count_risk_cost_and_hash() -> None:
    summary = portfolio_record_seal().method_summaries[0]

    with pytest.raises(ValueError, match="window_count must be positive"):
        replace(summary, window_count=0)
    with pytest.raises(ValueError, match="risk metrics are invalid"):
        replace(summary, realized_variance=Decimal("-0.1"))
    with pytest.raises(ValueError, match="turnover/cost cannot be negative"):
        replace(summary, total_turnover=Decimal("-0.1"))
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(summary, content_hash="0" * 64)


def test_record_seal_rejects_owner_time_order_and_all_collection_invariants() -> None:
    record = portfolio_record_seal()
    metric = record.window_metrics
    summaries = record.method_summaries

    with pytest.raises(ValueError, match="Portfolio-owned"):
        replace(record, owner="research")
    with pytest.raises(ValueError, match="time window is invalid"):
        replace(record, recorded_at=record.valid_until)
    with pytest.raises(ValueError, match="subhashes must be complete and ordered"):
        replace(record, record_subhashes=tuple(reversed(record.record_subhashes)))
    with pytest.raises(ValueError, match="windows must be unique and ordered"):
        replace(record, windows=(record.windows[0], record.windows[0]))
    with pytest.raises(ValueError, match="window metrics must be unique and ordered"):
        replace(record, window_metrics=(metric[0], metric[0]))
    with pytest.raises(ValueError, match="method summaries must be unique and ordered"):
        replace(record, method_summaries=(summaries[0], summaries[0]))
    with pytest.raises(ValueError, match="exposure_point_hashes must be unique and ordered"):
        replace(record, exposure_point_hashes=(record.exposure_point_hashes[0],) * 2)
    with pytest.raises(ValueError, match="regime_summary_hashes must be unique and ordered"):
        replace(record, regime_summary_hashes=(record.regime_summary_hashes[0],) * 2)
    with pytest.raises(ValueError, match="regime fold coverage must be unique and ordered"):
        replace(record, regime_covered_fold_ids=("fold-1", "fold-1"))
    with pytest.raises(ValueError, match="unknown fold"):
        replace(record, regime_covered_fold_ids=("missing-fold",))


def test_record_seal_rejects_states_blockers_r3_and_usage_contract() -> None:
    record = portfolio_record_seal()
    blocker = ("missing_evidence", "fixture boundary", None)

    with pytest.raises(ValueError, match="artifact states must be boolean"):
        replace(record, artifact_eligible=1)
    with pytest.raises(ValueError, match="artifact blockers must be unique and ordered"):
        replace(record, artifact_blockers=(blocker, blocker))
    with pytest.raises(ValueError, match="R3 attestation hash was substituted"):
        replace(record, r3_attestation_hash="f" * 64)
    with pytest.raises(ValueError, match="remain research_only"):
        replace(record, usage_scope="decision")
    with pytest.raises(ValueError, match="authorize decisions or execution"):
        replace(record, must_not_execute=False)
    with pytest.raises(ValueError, match="Portfolio record seal hash mismatch"):
        replace(record, content_hash="0" * 64)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("owner", "portfolio", "authority is invalid"),
        ("capability", "r5", "authority is invalid"),
        ("observed_fold_count", 0, "observed_fold_count must be positive"),
        ("observed_fold_count", True, "observed_fold_count must be positive"),
        ("regime_coverage_ratio", Decimal("-0.1"), "coverage must be within"),
        ("regime_coverage_ratio", Decimal("1.1"), "coverage must be within"),
        (
            "available_methods",
            (MacroRiskCandidateKind.EQUAL_WEIGHT,) * 2,
            "available methods must be unique",
        ),
        ("blocker_codes", ("z", "a"), "blockers must be unique and ordered"),
        ("state", R4PromotionTrialState.BLOCKED, "state must be derived from blockers"),
        ("valid_until", datetime(2026, 3, 15, tzinfo=UTC), "knowledge/validity window is invalid"),
        ("research_only", False, "must remain research-only"),
    ),
)
def test_trial_seal_rejects_derived_state_boundaries(field, value, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(promotion_trial(), **{field: value})


def test_trial_creation_rejects_unavailable_record_and_preregistered_bindings() -> None:
    policy = promotion_policy()
    record = portfolio_record_seal()
    current = r3_evidence()

    with pytest.raises(ValueError, match="owner record is unavailable"):
        R4PromotionTrialSeal.create(
            trial_id="unavailable-record",
            trial_version="trial.v1",
            policy=policy,
            portfolio_record=record,
            current_r3_attestation=current,
            evaluated_at=record.valid_until,
        )
    with pytest.raises(ValueError, match="study identity is outside"):
        promotion_trial(
            policy=policy,
            record_seal=portfolio_record_seal(
                record=portfolio_record(study=build_study(study_id="other-study"))
            ),
        )

    split = _registration_with(policy.registration, split_policy_version="split.other.v1")
    with pytest.raises(ValueError, match="split policy differs"):
        promotion_trial(policy=promotion_policy(registration=split))
    cost = _registration_with(policy.registration, cost_semantics_version="cost.other.v1")
    with pytest.raises(ValueError, match="cost semantics differ"):
        promotion_trial(policy=promotion_policy(registration=cost))
    assets = _registration_with(policy.registration, asset_codes=("asset-a", "asset-c"))
    with pytest.raises(ValueError, match="universe or factor family differs"):
        promotion_trial(policy=promotion_policy(registration=assets))


def test_trial_rejects_substituted_r3_and_preserves_research_only_contract() -> None:
    trial = promotion_trial()
    current = trial.current_r3_attestation
    substituted = R4PromotionR3AttestationEvidence.create(
        artifact_id=current.artifact_id,
        artifact_version=current.artifact_version,
        artifact_content_hash=current.artifact_content_hash,
        decision_id=current.decision_id,
        decision_version=current.decision_version,
        decision_content_hash=current.decision_content_hash,
        approved_at=current.approved_at,
        valid_until=current.valid_until,
        retired_at=current.retired_at,
        attestation_hash="d" * 64,
    )
    with pytest.raises(ValueError, match="current R3 evidence was substituted"):
        replace(trial, current_r3_attestation=substituted)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(trial, content_hash="0" * 64)


def test_trial_blockers_report_each_missing_evidence_family() -> None:
    record = portfolio_record_seal()
    incomplete = _record_with(record, artifact_evidence_complete=False)
    trial = promotion_trial(record_seal=incomplete)
    assert trial.state is R4PromotionTrialState.BLOCKED
    assert "portfolio_artifact_incomplete" in trial.blocker_codes

    ineligible = portfolio_record_seal(
        record=portfolio_record(study=build_study(minimum_regime_windows=3))
    )
    trial = promotion_trial(record_seal=ineligible)
    assert "portfolio_artifact_ineligible" in trial.blocker_codes

    trial = promotion_trial(policy=promotion_policy(minimum_fold_count=3))
    assert "minimum_fold_count_not_met" in trial.blocker_codes

    low_coverage = _record_with(record, regime_covered_fold_ids=("fold-1",))
    trial = promotion_trial(record_seal=low_coverage)
    assert "minimum_regime_coverage_not_met" in trial.blocker_codes

    trial = promotion_trial(
        record_seal=_record_with(record, method_summaries=record.method_summaries[:-1])
    )
    assert "required_method_family_incomplete" in trial.blocker_codes

    trial = promotion_trial(
        record_seal=_record_with(record, window_metrics=record.window_metrics[:-1])
    )
    assert "window_metric_family_incomplete" in trial.blocker_codes

    summaries = (
        _summary_with(record.method_summaries[0], window_count=1),
        *record.method_summaries[1:],
    )
    trial = promotion_trial(record_seal=_record_with(record, method_summaries=summaries))
    assert "method_summary_fold_count_mismatch" in trial.blocker_codes


def test_relative_evidence_rejects_target_substitution_and_bad_volatility() -> None:
    evidence = promotion_decision().relative_method_evidence[0]

    with pytest.raises(ValueError, match="target must be macro-factor"):
        replace(evidence, target_method=MacroRiskCandidateKind.EQUAL_WEIGHT)
    with pytest.raises(ValueError, match="reference cannot equal"):
        replace(evidence, reference_method=evidence.target_method)
    with pytest.raises(ValueError, match="volatility cannot be negative"):
        replace(evidence, target_volatility=Decimal("-0.1"))
    with pytest.raises(ValueError, match="relative method evidence hash mismatch"):
        replace(evidence, content_hash="0" * 64)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        (
            {
                "gate_code": R4PromotionGateCode.RELATIVE_NET_RETURN,
                "reference_method": None,
                "passes": False,
                "reason_code": "relative_net_return_not_met",
                "observed_value": Decimal("0"),
                "required_value": Decimal("0"),
            },
            "relative gate requires exactly one",
        ),
        (
            {
                "gate_code": R4PromotionGateCode.TRIAL_READY,
                "reference_method": None,
                "passes": 1,
                "reason_code": "",
                "observed_value": Decimal("1"),
                "required_value": Decimal("1"),
            },
            "passes must be boolean",
        ),
        (
            {
                "gate_code": R4PromotionGateCode.TRIAL_READY,
                "reference_method": None,
                "passes": False,
                "reason_code": "wrong",
                "observed_value": Decimal("0"),
                "required_value": Decimal("1"),
            },
            "reason does not match",
        ),
        (
            {
                "gate_code": R4PromotionGateCode.TRIAL_READY,
                "reference_method": None,
                "passes": True,
                "reason_code": "",
                "observed_value": None,
                "required_value": Decimal("1"),
            },
            "requires an observed value",
        ),
    ),
)
def test_gate_outcome_enforces_state_reason_and_observation_contract(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        R4PromotionGateOutcome(**kwargs)


def test_decision_rejects_authority_policy_reason_validity_and_research_contract() -> None:
    decision = promotion_decision()
    rejected = promotion_decision(
        policy=promotion_policy(minimum_relative_net_return=Decimal("0.5"))
    )

    with pytest.raises(ValueError, match="authority is invalid"):
        replace(decision, owner="portfolio")
    with pytest.raises(ValueError, match="policy or scope was substituted"):
        replace(decision, scope=_unrelated_scope())
    with pytest.raises(ValueError, match="reasons must match"):
        replace(rejected, reason_codes=("caller_substituted",))
    with pytest.raises(ValueError, match="validity is outside"):
        replace(decision, valid_until=decision.valid_until + timedelta(days=30))
    with pytest.raises(ValueError, match="must remain research-only"):
        replace(decision, must_not_execute=False)


def test_decision_factory_rejects_policy_or_trial_outside_their_windows() -> None:
    policy = promotion_policy()
    trial = promotion_trial(policy=policy)

    with pytest.raises(ValueError, match="policy is unavailable or inactive"):
        create_r4_promotion_decision(
            decision_id="before-policy",
            decision_version="decision.v1",
            policy=policy,
            trial=trial,
            as_of=policy.recorded_at - timedelta(seconds=1),
            recorded_at=policy.recorded_at,
        )
    with pytest.raises(ValueError, match="trial is unavailable or inactive"):
        create_r4_promotion_decision(
            decision_id="after-trial",
            decision_version="decision.v1",
            policy=policy,
            trial=trial,
            as_of=trial.valid_until,
            recorded_at=trial.valid_until,
        )


def test_decision_without_target_summary_is_rejected_with_missing_relative_gates() -> None:
    record = portfolio_record_seal()
    target = promotion_scope().target_method
    without_target = tuple(item for item in record.method_summaries if item.method is not target)
    trial = promotion_trial(record_seal=_record_with(record, method_summaries=without_target))
    decision = promotion_decision(trial=trial)

    assert decision.outcome is R4PromotionDecisionOutcome.REJECTED
    assert any("relative_net_return" in code for code in decision.reason_codes)


def test_lifecycle_identity_reason_and_authorization_boundaries() -> None:
    decision = promotion_decision()
    identity = R4PromotionDecisionIdentity.from_decision(decision)

    with pytest.raises(ValueError, match="time window is invalid"):
        replace(identity, valid_until=identity.recorded_at)
    with pytest.raises(ValueError, match="non-empty, unique and ordered"):
        r4_promotion_lifecycle_reason_hash(())
    with pytest.raises(ValueError, match="non-empty, unique and ordered"):
        r4_promotion_lifecycle_reason_hash(("z", "a"))

    auth = _authorization(decision)
    with pytest.raises(ValueError, match="authority is invalid"):
        replace(auth, owner="portfolio")
    with pytest.raises(ValueError, match="crosses scopes"):
        replace(auth, scope=_unrelated_scope())
    with pytest.raises(ValueError, match="receipt window is invalid"):
        replace(auth, issued_at=decision.recorded_at - timedelta(seconds=1))
    rollback_auth = _authorization(
        decision,
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        rollback_target=decision,
    )
    with pytest.raises(ValueError, match="exact scope-local target"):
        replace(rollback_auth, rollback_target=None)
    with pytest.raises(ValueError, match="non-rollback.*rollback target"):
        replace(auth, rollback_target=identity)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(auth, content_hash="0" * 64)


def test_lifecycle_event_rejects_local_stream_sequence_clock_and_flags() -> None:
    decision = promotion_decision()
    root = _root(decision)
    other = _other_decision()
    other_root = _root(other)

    with pytest.raises(ValueError, match="stream identity is invalid"):
        replace(root, stream_id="wrong-stream")
    with pytest.raises(ValueError, match="crosses scopes"):
        replace(root, scope=other.scope, stream_id=r4_promotion_stream_id(other.scope))
    with pytest.raises(ValueError, match="sequence must be positive"):
        replace(root, sequence=0)
    with pytest.raises(ValueError, match="record cannot predate"):
        replace(root, recorded_at=root.occurred_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="root must be an unlinked promotion"):
        replace(root, event_type=R4PromotionLifecycleEventType.RETIRED)
    with pytest.raises(ValueError, match="non-root.*previous hash"):
        replace(root, sequence=2)
    with pytest.raises(ValueError, match="can reference only approved"):
        replace(
            root,
            decision=promotion_decision(
                policy=promotion_policy(minimum_relative_net_return=Decimal("0.5"))
            ),
        )
    with pytest.raises(ValueError, match="non-rollback.*rollback target"):
        replace(root, rollback_target=R4PromotionDecisionIdentity.from_decision(decision))
    with pytest.raises(ValueError, match="must remain research-only"):
        replace(root, must_not_use_for_decision=False)
    with pytest.raises(ValueError, match="authorization does not match"):
        replace(
            root,
            authorization=_authorization(
                decision,
                event_type=R4PromotionLifecycleEventType.RETIRED,
            ),
        )
    assert other_root.scope != root.scope


def test_lifecycle_event_rejects_rollback_target_and_authorization_activity() -> None:
    decision = promotion_decision()
    root = _root(decision)
    replacement = promotion_decision(
        decision_id="r4-boundary-second",
        decision_version="decision.second.v1",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    promoted = _promote((root,), replacement, suffix="second")
    with pytest.raises(ValueError, match="rollback target is invalid or inactive"):
        replace(
            promoted, event_type=R4PromotionLifecycleEventType.ROLLED_BACK, rollback_target=None
        )

    with pytest.raises(ValueError, match="decision is inactive"):
        _root(
            decision,
            authorization=_authorization(
                decision,
                issued_at=decision.valid_until - timedelta(minutes=2),
                recorded_at=decision.valid_until - timedelta(minutes=1),
                valid_until=decision.valid_until + timedelta(hours=1),
            ),
            occurred_at=decision.valid_until,
            recorded_at=decision.valid_until + timedelta(minutes=1),
        )
    auth = _authorization(decision)
    with pytest.raises(ValueError, match="authorization was unavailable"):
        _root(
            decision,
            authorization=auth,
            occurred_at=auth.recorded_at - timedelta(microseconds=1),
            recorded_at=auth.recorded_at,
        )
    with pytest.raises(ValueError, match="authorization is inactive"):
        _root(
            decision,
            authorization=_authorization(
                decision,
                valid_until=decision.recorded_at + timedelta(minutes=3),
            ),
            occurred_at=decision.recorded_at + timedelta(minutes=4),
            recorded_at=decision.recorded_at + timedelta(minutes=5),
        )


def test_lifecycle_append_enforces_scope_clock_stack_and_authorization_binding() -> None:
    decision = promotion_decision()
    root = _root(decision)
    replacement = promotion_decision(
        decision_id="r4-boundary-second-append",
        decision_version="decision.second.append.v1",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    other = _other_decision()

    with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
        create_r4_promotion_lifecycle_event(
            event_id="clock-backwards",
            event_version="event.boundary.v1",
            previous_events=(root,),
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=replacement,
            rollback_target=None,
            authorization=_authorization(replacement),
            reason_codes=("replacement_policy_approved",),
            occurred_at=root.occurred_at - timedelta(seconds=1),
            recorded_at=root.recorded_at,
        )
    with pytest.raises(ValueError, match="append across scopes"):
        create_r4_promotion_lifecycle_event(
            event_id="cross-scope",
            event_version="event.boundary.v1",
            previous_events=(root,),
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=other,
            rollback_target=None,
            authorization=_authorization(other),
            reason_codes=("replacement_policy_approved",),
            occurred_at=max(root.recorded_at, replacement.recorded_at) + timedelta(minutes=2),
            recorded_at=max(root.recorded_at, replacement.recorded_at) + timedelta(minutes=3),
        )
    with pytest.raises(ValueError, match="rollback cannot cross scopes"):
        create_r4_promotion_lifecycle_event(
            event_id="cross-scope-target",
            event_version="event.boundary.v1",
            previous_events=(root, _promote((root,), replacement, suffix="target")),
            event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
            decision=replacement,
            rollback_target=other,
            authorization=_authorization(
                replacement,
                event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
                rollback_target=replacement,
                reason_codes=("replacement_regression",),
            ),
            reason_codes=("replacement_regression",),
            occurred_at=root.recorded_at + timedelta(hours=1),
            recorded_at=root.recorded_at + timedelta(hours=1, minutes=1),
        )

    with pytest.raises(ValueError, match="active decision again"):
        create_r4_promotion_lifecycle_event(
            event_id="duplicate-active",
            event_version="event.boundary.v1",
            previous_events=(root,),
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=decision,
            rollback_target=None,
            authorization=_authorization(decision),
            reason_codes=("replacement_policy_approved",),
            occurred_at=root.recorded_at + timedelta(minutes=2),
            recorded_at=root.recorded_at + timedelta(minutes=3),
        )
    with pytest.raises(ValueError, match="retirement must target"):
        create_r4_promotion_lifecycle_event(
            event_id="wrong-retirement",
            event_version="event.boundary.v1",
            previous_events=(root,),
            event_type=R4PromotionLifecycleEventType.RETIRED,
            decision=replacement,
            rollback_target=None,
            authorization=_authorization(
                replacement,
                event_type=R4PromotionLifecycleEventType.RETIRED,
            ),
            reason_codes=("methodology_retired",),
            occurred_at=max(root.recorded_at, replacement.recorded_at) + timedelta(minutes=2),
            recorded_at=max(root.recorded_at, replacement.recorded_at) + timedelta(minutes=3),
        )


def test_lifecycle_replay_rejects_empty_future_and_discontinuous_prefixes() -> None:
    decision = promotion_decision()
    root = _root(decision)

    with pytest.raises(ValueError, match="chain cannot be empty"):
        derive_r4_promotion_lifecycle_state((), evaluated_at=root.recorded_at)
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r4_promotion_lifecycle_state(
            (root,), evaluated_at=root.recorded_at - timedelta(microseconds=1)
        )
    with pytest.raises(ValueError, match="chain is discontinuous"):
        derive_r4_promotion_lifecycle_state((root, root), evaluated_at=root.recorded_at)
    expired = derive_r4_promotion_lifecycle_state(
        (root,), evaluated_at=decision.valid_until + timedelta(seconds=1)
    )
    assert expired.state is R4PromotionLifecycleState.EXPIRED


def test_lifecycle_rollback_and_retirement_have_exact_stack_semantics() -> None:
    first = promotion_decision()
    second = promotion_decision(
        decision_id="r4-boundary-stack-second",
        decision_version="decision.stack.second.v1",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    root = _root(first)
    promoted = _promote((root,), second, suffix="stack-second")
    rollback = _rollback((root, promoted), second, first, suffix="stack-first")
    state = derive_r4_promotion_lifecycle_state(
        (root, promoted, rollback), evaluated_at=rollback.recorded_at
    )
    assert state.state is R4PromotionLifecycleState.ROLLED_BACK
    assert state.active_decision == root.decision

    retirement_auth = _authorization(
        first,
        event_type=R4PromotionLifecycleEventType.RETIRED,
        reason_codes=("methodology_retired",),
        issued_at=rollback.recorded_at + timedelta(minutes=1),
    )
    retired = create_r4_promotion_lifecycle_event(
        event_id="r4-boundary-retired",
        event_version="event.boundary.v1",
        previous_events=(root, promoted, rollback),
        event_type=R4PromotionLifecycleEventType.RETIRED,
        decision=first,
        rollback_target=None,
        authorization=retirement_auth,
        reason_codes=("methodology_retired",),
        occurred_at=retirement_auth.recorded_at + timedelta(minutes=1),
        recorded_at=retirement_auth.recorded_at + timedelta(minutes=2),
    )
    retired_state = derive_r4_promotion_lifecycle_state(
        (root, promoted, rollback, retired), evaluated_at=retired.recorded_at
    )
    assert retired_state.state is R4PromotionLifecycleState.RETIRED
    assert retired_state.active_decision is None
