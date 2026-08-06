"""Exact ORM value projections for Research R4 promotion evidence."""

from __future__ import annotations

from django.db import models

from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleEventBundle,
)
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy
from apps.research.infrastructure.r4_promotion_codec import (
    encode_r4_lifecycle_authorization_evidence,
    encode_r4_lifecycle_event_bundle,
    encode_r4_promotion_decision_bundle,
    encode_r4_promotion_decision_receipt,
    encode_r4_promotion_policy,
)


def _policy_model_values(policy: R4PromotionPolicy) -> dict[str, object]:
    scope = policy.scope
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "owner": policy.owner,
        "capability": policy.capability,
        "purpose": policy.purpose,
        "status": policy.status.value,
        "scope_id": scope.scope_id,
        "scope_content_hash": scope.content_hash,
        "study_family_id": scope.study_family_id,
        "target_method": scope.target_method.value,
        "universe_policy_id": scope.universe_policy_id,
        "factor_policy_id": scope.factor_policy_id,
        "split_policy_id": scope.split_policy_id,
        "cost_semantics_id": scope.cost_semantics_id,
        "approved_at": policy.approved_at,
        "recorded_at": policy.recorded_at,
        "active_from": policy.active_from,
        "active_until": policy.active_until,
        "canonical_payload": encode_r4_promotion_policy(policy),
        "content_hash": policy.content_hash,
        "research_only": policy.research_only,
        "must_not_use_for_decision": policy.must_not_use_for_decision,
        "must_not_execute": policy.must_not_execute,
    }


def _decision_receipt_model_values(
    receipt: R4PromotionDecisionReceipt,
) -> dict[str, object]:
    return {
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "decision_id": receipt.decision_ref.stable_id,
        "decision_version": receipt.decision_ref.version,
        "trial_id": receipt.trial_ref.stable_id,
        "trial_version": receipt.trial_ref.version,
        "policy_content_hash": receipt.policy_content_hash,
        "portfolio_record_id": receipt.portfolio_record_id,
        "portfolio_record_hash": receipt.portfolio_record_hash,
        "portfolio_owner_record_key": receipt.portfolio_owner_record_key,
        "portfolio_recorded_at": receipt.portfolio_recorded_at,
        "current_r3_content_hash": receipt.current_r3_content_hash,
        "owner": receipt.owner,
        "capability": receipt.capability,
        "purpose": receipt.purpose,
        "decided_at": receipt.decided_at,
        "recorded_at": receipt.recorded_at,
        "decision_valid_until": receipt.decision_valid_until,
        "canonical_payload": encode_r4_promotion_decision_receipt(receipt),
        "content_hash": receipt.content_hash,
    }


def _decision_bundle_model_values(
    bundle: R4PromotionDecisionBundle,
) -> dict[str, object]:
    decision = bundle.decision
    trial = decision.trial
    record = trial.portfolio_record
    return {
        "decision_id": decision.decision_id,
        "decision_version": decision.decision_version,
        "trial_id": trial.trial_id,
        "trial_version": trial.trial_version,
        "trial_content_hash": trial.content_hash,
        "policy_content_hash": decision.policy.content_hash,
        "portfolio_record_id": record.record_id,
        "portfolio_record_hash": record.record_hash,
        "portfolio_owner_record_key": record.owner_record_key,
        "current_r3_content_hash": trial.current_r3_attestation.content_hash,
        "owner": decision.owner,
        "capability": decision.capability,
        "purpose": decision.purpose,
        "scope_id": decision.scope.scope_id,
        "scope_content_hash": decision.scope.content_hash,
        "outcome": decision.outcome.value,
        "decided_at": decision.decided_at,
        "recorded_at": decision.recorded_at,
        "valid_until": decision.valid_until,
        "canonical_payload": encode_r4_promotion_decision_bundle(bundle),
        "decision_content_hash": decision.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "research_only": decision.research_only,
        "must_not_use_for_decision": decision.must_not_use_for_decision,
        "must_not_execute": decision.must_not_execute,
    }


def _lifecycle_receipt_model_values(
    evidence: ExactR4LifecycleAuthorizationEvidence,
) -> dict[str, object]:
    authorization = evidence.authorization
    target = authorization.rollback_target
    return {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "event_id": evidence.event_ref.stable_id,
        "event_version": evidence.event_ref.version,
        "decision_content_hash": authorization.decision.content_hash,
        "rollback_target_content_hash": "" if target is None else target.content_hash,
        "owner": authorization.owner,
        "capability": authorization.capability,
        "purpose": authorization.purpose,
        "scope_id": authorization.scope.scope_id,
        "scope_content_hash": authorization.scope.content_hash,
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
        "canonical_payload": encode_r4_lifecycle_authorization_evidence(evidence),
    }


def _lifecycle_event_model_values(
    bundle: R4PromotionLifecycleEventBundle,
) -> dict[str, object]:
    event = bundle.event
    target = event.rollback_target
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "decision_content_hash": event.decision.content_hash,
        "rollback_target_content_hash": "" if target is None else target.content_hash,
        "scope_id": event.scope.scope_id,
        "scope_content_hash": event.scope.content_hash,
        "stream_id": event.stream_id,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "reason_codes": list(event.reason_codes),
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash or "",
        "event_content_hash": event.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "canonical_payload": encode_r4_lifecycle_event_bundle(bundle),
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_execute": event.must_not_execute,
    }


def _model_value_subset(
    model: models.Model,
    expected: dict[str, object],
) -> dict[str, object]:
    return {field_name: getattr(model, field_name) for field_name in expected}


__all__ = [
    "_decision_bundle_model_values",
    "_decision_receipt_model_values",
    "_lifecycle_event_model_values",
    "_lifecycle_receipt_model_values",
    "_model_value_subset",
    "_policy_model_values",
]
