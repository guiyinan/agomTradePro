"""Canonical active-provider replay for Research R1 forecast promotion."""

from __future__ import annotations

from datetime import datetime

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult
from apps.research.application.r1_forecast_promotion import (
    AppendR1PromotionLifecycleCommand,
    EvaluateR1ForecastPromotionCommand,
    ExactEquityTrialResultEvidence,
    ExactEquityTrialResultProvider,
    ExactR1LifecycleAuthorizationEvidence,
    ExactR1PromotionPolicyProvider,
    R1ForecastPromotionDecisionBundle,
    R1ForecastPromotionRepository,
    R1PromotionDecisionReceipt,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
    _require_aware,
    exact_equity_trial_result_record_hash,
    exact_r1_lifecycle_authorization_evidence_hash,
    r1_promotion_decision_receipt_hash,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1ForecastTrialPromotionSeal,
    R1PromotionDecisionIdentity,
    R1PromotionDecisionOutcome,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleState,
    derive_r1_promotion_lifecycle_state,
    r1_forecast_promotion_decision_valid_until,
    r1_promotion_stream_id,
)


class R1ActiveForecastPromotionProvider:
    """Resolve one exact active promotion by scope and knowledge time."""

    def __init__(
        self,
        *,
        policy_provider: ExactR1PromotionPolicyProvider,
        trial_result_provider: ExactEquityTrialResultProvider,
        repository: R1ForecastPromotionRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._trial_result_provider = trial_result_provider
        self._repository = repository

    def get_active(
        self,
        scope_ref: R1PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundle | None:
        """Replay the recorded prefix and fail closed on any exact-evidence gap."""

        _require_aware(as_of, "active R1 promotion as_of")
        history = self._repository.load_lifecycle_history(
            scope_ref,
            as_of=as_of,
        )
        if not history or any(event.recorded_at > as_of for event in history):
            return None
        try:
            snapshot = derive_r1_promotion_lifecycle_state(
                history,
                evaluated_at=as_of,
            )
        except ValueError:
            return None
        active_identity = snapshot.active_decision
        if (
            snapshot.state
            not in {
                R1PromotionLifecycleState.PROMOTED,
                R1PromotionLifecycleState.ROLLED_BACK,
            }
            or active_identity is None
        ):
            return None
        decision_ref = R1PromotionVersionRef(
            active_identity.decision_id,
            active_identity.decision_version,
        )
        bundle = self._repository.get_decision_bundle(
            decision_ref,
            as_of=as_of,
        )
        if bundle is None:
            return None
        decision = bundle.decision
        try:
            canonical_bundle = R1ForecastPromotionDecisionBundle.create(
                decision=decision,
                receipt=bundle.receipt,
            )
        except ValueError:
            return None
        if (
            bundle != canonical_bundle
            or R1PromotionDecisionIdentity.from_decision(decision) != active_identity
            or decision.promotion_scope.scope_id != scope_ref.scope_id
            or decision.outcome is not R1PromotionDecisionOutcome.APPROVED
            or not decision.recorded_at <= as_of < decision.valid_until
        ):
            return None
        policy_ref = R1PromotionVersionRef(
            decision.policy.policy_id,
            decision.policy.policy_version,
        )
        policy = self._policy_provider.get_exact(policy_ref, as_of=as_of)
        if (
            policy is None
            or policy != decision.policy
            or not policy.recorded_at <= as_of
            or not policy.active_from <= as_of < policy.active_until
        ):
            return None
        result_ref = R1PromotionVersionRef(
            decision.trial.result_id,
            decision.trial.result_version,
        )
        result_evidence = self._trial_result_provider.get_exact(
            result_ref,
            as_of=as_of,
        )
        if result_evidence is None:
            return None
        result = result_evidence.result
        try:
            result_seal = R1ForecastTrialPromotionSeal.from_result(result)
        except ValueError:
            return None
        if (
            result_seal != decision.trial
            or result_evidence.recorded_at != bundle.receipt.equity_result_recorded_at
            or result_evidence.record_hash != bundle.receipt.equity_result_record_hash
            or result_evidence.record_hash != exact_equity_trial_result_record_hash(result_evidence)
            or not result_evidence.recorded_at <= as_of
            or not result.evaluated_at <= as_of < result.valid_until
        ):
            return None
        return bundle


def _lifecycle_authorization_matches(
    *,
    evidence: ExactR1LifecycleAuthorizationEvidence,
    command: AppendR1PromotionLifecycleCommand,
    decision: R1ForecastPromotionDecision,
    rollback_target: R1ForecastPromotionDecision | None,
) -> bool:
    authorization = evidence.authorization
    target_identity = (
        R1PromotionDecisionIdentity.from_decision(rollback_target)
        if rollback_target is not None
        else None
    )
    return (
        evidence.event_ref == command.output_event_ref
        and (
            authorization.authorization_id,
            authorization.authorization_version,
        )
        == (
            command.authorization_ref.stable_id,
            command.authorization_ref.version,
        )
        and authorization.owner == "research"
        and authorization.capability == "r1"
        and authorization.purpose == "valuation"
        and authorization.event_type is command.action.event_type
        and authorization.promotion_scope.scope_id == command.scope_ref.scope_id
        and authorization.decision == R1PromotionDecisionIdentity.from_decision(decision)
        and authorization.rollback_target == target_identity
        and evidence.authorization.recorded_at <= evidence.occurred_at
        and evidence.content_hash == exact_r1_lifecycle_authorization_evidence_hash(evidence)
    )


def _lifecycle_event_matches_evidence(
    *,
    event: R1PromotionLifecycleEvent,
    evidence: ExactR1LifecycleAuthorizationEvidence,
    command: AppendR1PromotionLifecycleCommand,
    decision: R1ForecastPromotionDecision,
    rollback_target: R1ForecastPromotionDecision | None,
) -> bool:
    target_identity = (
        R1PromotionDecisionIdentity.from_decision(rollback_target)
        if rollback_target is not None
        else None
    )
    return (
        (event.event_id, event.event_version)
        == (command.output_event_ref.stable_id, command.output_event_ref.version)
        and event.promotion_scope.scope_id == command.scope_ref.scope_id
        and event.stream_id == r1_promotion_stream_id(decision.promotion_scope)
        and event.event_type is command.action.event_type
        and event.decision == R1PromotionDecisionIdentity.from_decision(decision)
        and event.rollback_target == target_identity
        and event.authorization == evidence.authorization
        and event.reason_codes == evidence.reason_codes
        and event.occurred_at == evidence.occurred_at
        and event.recorded_at == evidence.event_recorded_at
    )


def _decision_receipt_matches(
    *,
    receipt: R1PromotionDecisionReceipt,
    command: EvaluateR1ForecastPromotionCommand,
    policy: R1ForecastPromotionPolicy,
    result_evidence: ExactEquityTrialResultEvidence,
    result: ForecastBaselineTrialResult,
) -> bool:
    return (
        receipt.decision_ref == command.output_decision_ref
        and receipt.policy_ref == command.policy_ref
        and receipt.policy_content_hash == policy.content_hash
        and receipt.result_ref == command.equity_result_ref
        and receipt.result_content_hash == result.content_hash
        and receipt.equity_result_recorded_at == result_evidence.recorded_at
        and receipt.equity_result_record_hash == result_evidence.record_hash
        and receipt.owner == "research"
        and receipt.capability == "r1"
        and receipt.purpose == "valuation"
        and receipt.decided_at == command.as_of
        and receipt.decision_valid_until
        == r1_forecast_promotion_decision_valid_until(
            policy=policy,
            result=result,
            as_of=command.as_of,
        )
        and receipt.content_hash == r1_promotion_decision_receipt_hash(receipt)
    )
