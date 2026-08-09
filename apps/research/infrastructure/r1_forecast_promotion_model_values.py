"""ORM value projections for the Research R1 promotion repository."""

from __future__ import annotations

from apps.research.application.r1_forecast_promotion import (
    ExactR1LifecycleAuthorizationEvidence,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionReceipt,
    R1PromotionLifecycleEventBundle,
)
from apps.research.domain.r1_forecast_promotion import R1ForecastPromotionPolicy
from apps.research.infrastructure.r1_forecast_promotion_codec import (
    encode_r1_lifecycle_authorization_evidence,
    encode_r1_lifecycle_event_bundle,
    encode_r1_promotion_decision_bundle,
    encode_r1_promotion_policy,
)


def policy_model_values(policy: R1ForecastPromotionPolicy) -> dict[str, object]:
    """Project one canonical policy into ORM field values."""

    scope = policy.promotion_scope
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "owner": policy.owner,
        "capability": policy.capability,
        "purpose": policy.purpose,
        "status": policy.status.value,
        "scope_id": scope.scope_id,
        "scope_content_hash": scope.content_hash,
        "subject_code": scope.subject_code,
        "industry_code": scope.industry_code,
        "candidate_scenario": scope.candidate_scenario,
        "horizon_quarters": scope.horizon_quarters,
        "calendar_schedule_hash": scope.calendar_schedule_hash,
        "metric_codes": list(scope.metric_codes),
        "approved_at": policy.approved_at,
        "recorded_at": policy.recorded_at,
        "active_from": policy.active_from,
        "active_until": policy.active_until,
        "canonical_payload": encode_r1_promotion_policy(policy),
        "content_hash": policy.content_hash,
        "research_only": policy.research_only,
        "must_not_use_for_decision": policy.must_not_use_for_decision,
        "must_not_execute": policy.must_not_execute,
    }


def decision_receipt_model_values(
    receipt: R1PromotionDecisionReceipt,
) -> dict[str, object]:
    """Project one decision receipt into ORM field values."""

    return {
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "decision_id": receipt.decision_ref.stable_id,
        "decision_version": receipt.decision_ref.version,
        "policy_content_hash": receipt.policy_content_hash,
        "result_content_hash": receipt.result_content_hash,
        "equity_result_recorded_at": receipt.equity_result_recorded_at,
        "equity_result_record_hash": receipt.equity_result_record_hash,
        "owner": receipt.owner,
        "capability": receipt.capability,
        "purpose": receipt.purpose,
        "decided_at": receipt.decided_at,
        "recorded_at": receipt.recorded_at,
        "decision_valid_until": receipt.decision_valid_until,
        "content_hash": receipt.content_hash,
    }


def decision_bundle_model_values(
    bundle: R1ForecastPromotionDecisionBundle,
) -> dict[str, object]:
    """Project one decision bundle into ORM field values."""

    decision = bundle.decision
    return {
        "decision_id": decision.decision_id,
        "decision_version": decision.decision_version,
        "owner": decision.owner,
        "capability": decision.capability,
        "purpose": decision.purpose,
        "scope_id": decision.promotion_scope.scope_id,
        "scope_content_hash": decision.promotion_scope.content_hash,
        "outcome": decision.outcome.value,
        "decided_at": decision.decided_at,
        "recorded_at": decision.recorded_at,
        "valid_until": decision.valid_until,
        "canonical_payload": encode_r1_promotion_decision_bundle(bundle),
        "decision_content_hash": decision.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "research_only": decision.research_only,
        "must_not_use_for_decision": decision.must_not_use_for_decision,
        "must_not_execute": decision.must_not_execute,
    }


def lifecycle_receipt_model_values(
    evidence: ExactR1LifecycleAuthorizationEvidence,
) -> dict[str, object]:
    """Project lifecycle authorization evidence into ORM field values."""

    authorization = evidence.authorization
    return {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "event_id": evidence.event_ref.stable_id,
        "event_version": evidence.event_ref.version,
        "owner": authorization.owner,
        "capability": authorization.capability,
        "purpose": authorization.purpose,
        "scope_id": authorization.promotion_scope.scope_id,
        "scope_content_hash": authorization.promotion_scope.content_hash,
        "event_type": authorization.event_type.value,
        "reason_codes": list(evidence.reason_codes),
        "reason_hash": authorization.reason_hash,
        "authorization_issued_at": authorization.issued_at,
        "authorization_recorded_at": authorization.recorded_at,
        "authorization_valid_until": authorization.valid_until,
        "occurred_at": evidence.occurred_at,
        "event_recorded_at": evidence.event_recorded_at,
        "authorization_content_hash": authorization.content_hash,
        "evidence_content_hash": evidence.content_hash,
        "canonical_payload": encode_r1_lifecycle_authorization_evidence(evidence),
    }


def lifecycle_event_model_values(
    bundle: R1PromotionLifecycleEventBundle,
) -> dict[str, object]:
    """Project one lifecycle event bundle into ORM field values."""

    event = bundle.event
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "scope_id": event.promotion_scope.scope_id,
        "scope_content_hash": event.promotion_scope.content_hash,
        "stream_id": event.stream_id,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "reason_codes": list(event.reason_codes),
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash or "",
        "event_content_hash": event.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "canonical_payload": encode_r1_lifecycle_event_bundle(bundle),
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_execute": event.must_not_execute,
    }


def model_value_subset(model: object, values: dict[str, object]) -> dict[str, object]:
    """Read back the projected fields from one persisted ORM model."""

    return {name: getattr(model, name) for name in values}
