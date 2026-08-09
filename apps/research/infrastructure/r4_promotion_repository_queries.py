"""ORM query helpers for the Research R4 promotion repository."""

from __future__ import annotations

from datetime import datetime

from django.db import models

from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleEventBundle,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionLifecycleAuthorizationReceiptModel,
    R4PromotionLifecycleEventModel,
    R4PromotionPolicyModel,
)
from apps.research.infrastructure.r4_promotion_providers import (
    R4PromotionRepositoryConflict,
    R4PromotionRepositoryCorruption,
)


class R4PromotionRepositoryQueryMixin:
    """Provide collision and exact-identity ORM queries for the repository."""

    _using: str

    def _policy_from_model(self, model: R4PromotionPolicyModel) -> R4PromotionPolicy:
        raise NotImplementedError

    def _decision_bundle_from_model(
        self,
        model: R4PromotionDecisionBundleModel,
    ) -> R4PromotionDecisionBundle:
        raise NotImplementedError

    def _decision_receipt_from_model(
        self,
        model: R4PromotionDecisionReceiptModel,
    ) -> R4PromotionDecisionReceipt:
        raise NotImplementedError

    def _get_policy_by_identity(
        self,
        policy_id: str,
        policy_version: str,
    ) -> R4PromotionPolicyModel | None:
        return (
            R4PromotionPolicyModel._default_manager.using(self._using)
            .filter(policy_id=policy_id, policy_version=policy_version)
            .first()
        )

    def _get_policy_collision(
        self,
        policy: R4PromotionPolicy,
    ) -> R4PromotionPolicyModel | None:
        rows = tuple(
            R4PromotionPolicyModel._default_manager.using(self._using).filter(
                models.Q(policy_id=policy.policy_id, policy_version=policy.policy_version)
                | models.Q(content_hash=policy.content_hash)
            )
        )
        if len(rows) != 1:
            return None
        return rows[0]

    def _get_policy_model(
        self,
        policy_ref: R4PromotionVersionRef,
        content_hash: str,
    ) -> R4PromotionPolicyModel:
        model = (
            R4PromotionPolicyModel._default_manager.using(self._using)
            .filter(
                policy_id=policy_ref.stable_id,
                policy_version=policy_ref.version,
                content_hash=content_hash,
            )
            .first()
        )
        if model is None:
            raise R4PromotionRepositoryCorruption("exact R4 policy row is unavailable")
        self._policy_from_model(model)
        return model

    def _get_receipt_by_decision(
        self,
        decision_ref: R4PromotionVersionRef,
    ) -> R4PromotionDecisionReceiptModel | None:
        return (
            R4PromotionDecisionReceiptModel._default_manager.using(self._using)
            .filter(
                decision_id=decision_ref.stable_id,
                decision_version=decision_ref.version,
            )
            .select_related("policy")
            .first()
        )

    def _get_decision_receipt_collision(
        self,
        receipt: R4PromotionDecisionReceipt,
    ) -> R4PromotionDecisionReceiptModel | None:
        rows = tuple(
            R4PromotionDecisionReceiptModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    receipt_id=receipt.receipt_id,
                    receipt_version=receipt.receipt_version,
                )
                | models.Q(
                    decision_id=receipt.decision_ref.stable_id,
                    decision_version=receipt.decision_ref.version,
                )
                | models.Q(content_hash=receipt.content_hash)
            )
            .select_related("policy")
        )
        return rows[0] if len(rows) == 1 else None

    def _get_decision_bundle_collision(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundleModel | None:
        decision = bundle.decision
        rows = tuple(
            R4PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    decision_id=decision.decision_id,
                    decision_version=decision.decision_version,
                )
                | models.Q(decision_content_hash=decision.content_hash)
                | models.Q(bundle_content_hash=bundle.content_hash)
                | models.Q(receipt__content_hash=bundle.receipt.content_hash)
            )
            .select_related("receipt", "policy")
        )
        return rows[0] if len(rows) == 1 else None

    def _get_lifecycle_receipt_by_event(
        self,
        event_ref: R4PromotionVersionRef,
    ) -> R4PromotionLifecycleAuthorizationReceiptModel | None:
        return (
            R4PromotionLifecycleAuthorizationReceiptModel._default_manager.using(self._using)
            .filter(event_id=event_ref.stable_id, event_version=event_ref.version)
            .select_related(
                "decision",
                "decision__receipt",
                "decision__policy",
                "rollback_target",
            )
            .first()
        )

    def _get_lifecycle_receipt_collision(
        self,
        evidence: ExactR4LifecycleAuthorizationEvidence,
    ) -> R4PromotionLifecycleAuthorizationReceiptModel | None:
        authorization = evidence.authorization
        rows = tuple(
            R4PromotionLifecycleAuthorizationReceiptModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    authorization_id=authorization.authorization_id,
                    authorization_version=authorization.authorization_version,
                )
                | models.Q(
                    event_id=evidence.event_ref.stable_id,
                    event_version=evidence.event_ref.version,
                )
                | models.Q(authorization_content_hash=authorization.content_hash)
                | models.Q(evidence_content_hash=evidence.content_hash)
            )
            .select_related("decision", "decision__receipt", "decision__policy")
        )
        return rows[0] if len(rows) == 1 else None

    def _get_lifecycle_event_collision(
        self,
        bundle: R4PromotionLifecycleEventBundle,
    ) -> R4PromotionLifecycleEventModel | None:
        event = bundle.event
        query = (
            models.Q(event_id=event.event_id, event_version=event.event_version)
            | models.Q(stream_id=event.stream_id, sequence=event.sequence)
            | models.Q(event_content_hash=event.content_hash)
            | models.Q(bundle_content_hash=bundle.content_hash)
            | models.Q(receipt__evidence_content_hash=bundle.evidence.content_hash)
        )
        if event.previous_event_hash is not None:
            query |= models.Q(
                stream_id=event.stream_id,
                previous_event__event_content_hash=event.previous_event_hash,
            )
        rows = tuple(
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(query)
            .select_related("receipt", "decision", "rollback_target", "previous_event")
        )
        return rows[0] if len(rows) == 1 else None

    def _get_decision_model_for_identity(
        self,
        identity: R4PromotionDecisionIdentity,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundleModel:
        model = (
            R4PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                decision_id=identity.decision_id,
                decision_version=identity.decision_version,
                decision_content_hash=identity.content_hash,
                recorded_at__lte=as_of,
            )
            .select_related("receipt", "policy")
            .first()
        )
        if model is None:
            raise R4PromotionRepositoryCorruption("exact R4 lifecycle decision is unavailable")
        restored = self._decision_bundle_from_model(model)
        if R4PromotionDecisionIdentity.from_decision(restored.decision) != identity:
            raise R4PromotionRepositoryCorruption("R4 lifecycle decision identity mismatch")
        return model

    def _match_decision_receipt(
        self,
        model: R4PromotionDecisionReceiptModel,
        requested: tuple[
            R4PromotionVersionRef,
            R4PromotionVersionRef,
            str,
            str,
            str,
            str,
            datetime,
            str,
            datetime,
            datetime,
        ],
    ) -> R4PromotionDecisionReceipt:
        receipt = self._decision_receipt_from_model(model)
        actual = (
            receipt.trial_ref,
            receipt.policy_ref,
            receipt.policy_content_hash,
            receipt.portfolio_record_id,
            receipt.portfolio_record_hash,
            receipt.portfolio_owner_record_key,
            receipt.portfolio_recorded_at,
            receipt.current_r3_content_hash,
            receipt.decided_at,
            receipt.decision_valid_until,
        )
        if actual != requested:
            raise R4PromotionRepositoryConflict("R4 decision receipt identity conflict")
        return receipt
