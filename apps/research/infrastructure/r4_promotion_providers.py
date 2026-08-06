"""Concrete Research-owned providers for exact R4 promotion persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionReceipt,
    R4PromotionEvidenceError,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleAction,
    R4PromotionScopeRef,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionLifecycleAuthorization
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy

if TYPE_CHECKING:
    from apps.research.infrastructure.r4_promotion_repository import (
        DjangoR4PromotionRepository,
    )


class R4PromotionRepositoryConflict(R4PromotionEvidenceError):
    """Raised when one immutable identity is bound to different evidence."""


class R4PromotionRepositoryCorruption(R4PromotionEvidenceError):
    """Raised when a persisted header, payload or foreign key was substituted."""


@dataclass(frozen=True)
class R4LifecycleAuthorizationClaim:
    """Trusted Research owner input before server clocks are claimed."""

    authorization: R4PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]


class R4LifecycleAuthorizationSource(Protocol):
    """Resolve exact owner authorization from ID-only lifecycle inputs."""

    def get_exact(
        self,
        *,
        authorization_ref: R4PromotionVersionRef,
        event_ref: R4PromotionVersionRef,
        scope_ref: R4PromotionScopeRef,
        action: R4PromotionLifecycleAction,
        decision_ref: R4PromotionVersionRef,
        rollback_target_ref: R4PromotionVersionRef | None,
    ) -> R4LifecycleAuthorizationClaim | None:
        """Return only a Research-owned exact authorization claim."""


class DjangoR4PromotionPolicyProvider:
    """Exact policy provider backed by the Research R4 repository."""

    def __init__(self, repository: DjangoR4PromotionRepository) -> None:
        self._repository = repository

    def get_exact(
        self,
        policy_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionPolicy | None:
        self._repository.require_active_unit_of_work()
        return self._repository.get_exact_policy(policy_ref, as_of=as_of)


class DjangoR4DecisionReceiptProvider:
    """Stable decision receipt provider sharing the repository UoW."""

    def __init__(self, repository: DjangoR4PromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        decision_ref: R4PromotionVersionRef,
        trial_ref: R4PromotionVersionRef,
        policy_ref: R4PromotionVersionRef,
        policy_content_hash: str,
        portfolio_record_id: str,
        portfolio_record_hash: str,
        portfolio_owner_record_key: str,
        portfolio_recorded_at: datetime,
        current_r3_content_hash: str,
        decided_at: datetime,
        decision_valid_until: datetime,
    ) -> R4PromotionDecisionReceipt | None:
        self._repository.require_active_unit_of_work()
        return self._repository.claim_decision_receipt(
            decision_ref=decision_ref,
            trial_ref=trial_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            portfolio_record_id=portfolio_record_id,
            portfolio_record_hash=portfolio_record_hash,
            portfolio_owner_record_key=portfolio_owner_record_key,
            portfolio_recorded_at=portfolio_recorded_at,
            current_r3_content_hash=current_r3_content_hash,
            decided_at=decided_at,
            decision_valid_until=decision_valid_until,
        )


class DjangoR4LifecycleAuthorizationProvider:
    """Claim stable server clocks for exact Research lifecycle authority."""

    def __init__(
        self,
        repository: DjangoR4PromotionRepository,
        *,
        owner_source: R4LifecycleAuthorizationSource,
    ) -> None:
        self._repository = repository
        self._owner_source = owner_source

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R4PromotionVersionRef,
        event_ref: R4PromotionVersionRef,
        scope_ref: R4PromotionScopeRef,
        action: R4PromotionLifecycleAction,
        decision_ref: R4PromotionVersionRef,
        rollback_target_ref: R4PromotionVersionRef | None,
    ) -> ExactR4LifecycleAuthorizationEvidence | None:
        self._repository.require_active_unit_of_work()
        existing = self._repository.get_exact_lifecycle_authorization(
            authorization_ref=authorization_ref,
            event_ref=event_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )
        if existing is not None:
            return existing
        claim = self._owner_source.get_exact(
            authorization_ref=authorization_ref,
            event_ref=event_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )
        if claim is None:
            return None
        self._repository.claim_lifecycle_authorization(
            event_ref=event_ref,
            authorization=claim.authorization,
            reason_codes=claim.reason_codes,
        )
        return self._repository.get_exact_lifecycle_authorization(
            authorization_ref=authorization_ref,
            event_ref=event_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )


def stable_r4_decision_receipt_id(
    *,
    decision_ref: R4PromotionVersionRef,
    trial_ref: R4PromotionVersionRef,
    policy_ref: R4PromotionVersionRef,
    portfolio_record_id: str,
    scope_id: str,
) -> str:
    """Return a deterministic Research receipt identity."""

    digest = hashlib.sha256(
        "\0".join(
            (
                decision_ref.stable_id,
                decision_ref.version,
                trial_ref.stable_id,
                trial_ref.version,
                policy_ref.stable_id,
                policy_ref.version,
                portfolio_record_id,
                scope_id,
            )
        ).encode()
    ).hexdigest()
    return f"r4-decision-receipt:{digest}"


def r4_lifecycle_authorization_claim_id(
    *,
    event_ref: R4PromotionVersionRef,
    authorization: R4PromotionLifecycleAuthorization,
) -> str:
    """Return the canonical owner authorization identity for an event claim."""

    target = authorization.rollback_target
    digest = hashlib.sha256(
        "\0".join(
            (
                event_ref.stable_id,
                event_ref.version,
                authorization.scope.scope_id,
                authorization.event_type.value,
                authorization.decision.decision_id,
                authorization.decision.decision_version,
                target.decision_id if target is not None else "",
                target.decision_version if target is not None else "",
            )
        ).encode()
    ).hexdigest()
    return f"r4-lifecycle-authorization:{digest}"


__all__ = [
    "DjangoR4DecisionReceiptProvider",
    "DjangoR4LifecycleAuthorizationProvider",
    "DjangoR4PromotionPolicyProvider",
    "R4LifecycleAuthorizationClaim",
    "R4LifecycleAuthorizationSource",
    "R4PromotionRepositoryConflict",
    "R4PromotionRepositoryCorruption",
    "r4_lifecycle_authorization_claim_id",
    "stable_r4_decision_receipt_id",
]
