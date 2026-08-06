"""Research-owner evidence and ports for the R4 promotion lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionRepository,
    R4PromotionVersionRef,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventType,
    r4_promotion_lifecycle_reason_hash,
)
from apps.research.domain.r4_promotion_scope_policy import (
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)


@dataclass(frozen=True)
class R4PromotionScopeRef:
    """ID-only stable scope reference accepted at the command boundary."""

    scope_id: str

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R4 promotion lifecycle scope_id")


class R4PromotionLifecycleAction(str, Enum):
    """Application action vocabulary mapped to canonical Domain events."""

    PROMOTE = "promote"
    RETIRE = "retire"
    ROLLBACK = "rollback"

    @property
    def event_type(self) -> R4PromotionLifecycleEventType:
        """Return the immutable event type for this command action."""

        return {
            R4PromotionLifecycleAction.PROMOTE: R4PromotionLifecycleEventType.PROMOTED,
            R4PromotionLifecycleAction.RETIRE: R4PromotionLifecycleEventType.RETIRED,
            R4PromotionLifecycleAction.ROLLBACK: R4PromotionLifecycleEventType.ROLLED_BACK,
        }[self]


@dataclass(frozen=True)
class ExactR4LifecycleAuthorizationEvidence:
    """Research-owned authorization plus stable server event receipt."""

    event_ref: R4PromotionVersionRef
    authorization: R4PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    event_recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_ref: R4PromotionVersionRef,
        authorization: R4PromotionLifecycleAuthorization,
        reason_codes: tuple[str, ...],
        occurred_at: datetime,
        event_recorded_at: datetime,
    ) -> ExactR4LifecycleAuthorizationEvidence:
        """Seal exact Research authority and server-owned event clocks."""

        digest = _exact_authorization_evidence_hash(
            event_ref=event_ref,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            event_recorded_at=event_recorded_at,
        )
        return cls(
            event_ref=event_ref,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            event_recorded_at=event_recorded_at,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "R4 lifecycle evidence occurred_at")
        _require_aware(
            self.event_recorded_at,
            "R4 lifecycle evidence event_recorded_at",
        )
        if not (
            self.authorization.recorded_at <= self.occurred_at <= self.event_recorded_at
            and self.authorization.issued_at <= self.occurred_at < self.authorization.valid_until
        ):
            raise ValueError("R4 lifecycle authorization evidence time chain is invalid")
        if self.authorization.reason_hash != r4_promotion_lifecycle_reason_hash(self.reason_codes):
            raise ValueError("R4 lifecycle authorization evidence reasons were substituted")
        _require_hash(self.content_hash, "R4 lifecycle authorization evidence hash")
        if self.content_hash != exact_r4_lifecycle_authorization_evidence_hash(self):
            raise ValueError("R4 lifecycle authorization evidence hash mismatch")


def _exact_authorization_evidence_hash(
    *,
    event_ref: R4PromotionVersionRef,
    authorization: R4PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    event_recorded_at: datetime,
) -> str:
    target = authorization.rollback_target
    return _hash_payload(
        {
            "schema": "research-r4-lifecycle-authorization-evidence.v1",
            "event": [event_ref.stable_id, event_ref.version],
            "authorization": [
                authorization.authorization_id,
                authorization.authorization_version,
                authorization.content_hash,
            ],
            "action": authorization.event_type.value,
            "scope": [authorization.scope.scope_id, authorization.scope.content_hash],
            "decision": [
                authorization.decision.decision_id,
                authorization.decision.decision_version,
                authorization.decision.content_hash,
            ],
            "rollback_target": (
                None
                if target is None
                else [target.decision_id, target.decision_version, target.content_hash]
            ),
            "reason_codes": list(reason_codes),
            "window": [_utc_text(occurred_at), _utc_text(event_recorded_at)],
        }
    )


def exact_r4_lifecycle_authorization_evidence_hash(
    evidence: ExactR4LifecycleAuthorizationEvidence,
) -> str:
    """Recompute one exact Research lifecycle authorization receipt hash."""

    return _exact_authorization_evidence_hash(
        event_ref=evidence.event_ref,
        authorization=evidence.authorization,
        reason_codes=evidence.reason_codes,
        occurred_at=evidence.occurred_at,
        event_recorded_at=evidence.event_recorded_at,
    )


class ExactR4LifecycleAuthorizationProvider(Protocol):
    """Claim one exact Research authorization and stable event receipt."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the authorization transaction boundary."""

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
        """Return only exact owner evidence for the supplied ID-only request."""


@dataclass(frozen=True)
class R4PromotionLifecycleEventBundle:
    """Atomic lifecycle event plus its Research owner/server receipt."""

    event: R4PromotionLifecycleEvent
    evidence: ExactR4LifecycleAuthorizationEvidence
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event: R4PromotionLifecycleEvent,
        evidence: ExactR4LifecycleAuthorizationEvidence,
    ) -> R4PromotionLifecycleEventBundle:
        """Seal one exact append-only lifecycle persistence unit."""

        digest = _lifecycle_event_bundle_hash(event=event, evidence=evidence)
        return cls(event=event, evidence=evidence, content_hash=digest)

    def __post_init__(self) -> None:
        if (
            (self.event.event_id, self.event.event_version)
            != (self.evidence.event_ref.stable_id, self.evidence.event_ref.version)
            or self.event.authorization != self.evidence.authorization
            or self.event.reason_codes != self.evidence.reason_codes
            or self.event.occurred_at != self.evidence.occurred_at
            or self.event.recorded_at != self.evidence.event_recorded_at
            or self.event.scope != self.evidence.authorization.scope
        ):
            raise ValueError("R4 lifecycle event bundle owner receipt was substituted")
        _require_hash(self.content_hash, "R4 lifecycle event bundle content_hash")
        if self.content_hash != r4_promotion_lifecycle_event_bundle_hash(self):
            raise ValueError("R4 lifecycle event bundle content hash mismatch")


def _lifecycle_event_bundle_hash(
    *,
    event: R4PromotionLifecycleEvent,
    evidence: ExactR4LifecycleAuthorizationEvidence,
) -> str:
    return _hash_payload(
        {
            "schema": "research-r4-promotion-lifecycle-event-bundle.v1",
            "event": [event.event_id, event.event_version, event.content_hash],
            "owner_receipt": [
                evidence.authorization.authorization_id,
                evidence.authorization.authorization_version,
                evidence.content_hash,
                _utc_text(evidence.occurred_at),
                _utc_text(evidence.event_recorded_at),
            ],
        }
    )


def r4_promotion_lifecycle_event_bundle_hash(
    bundle: R4PromotionLifecycleEventBundle,
) -> str:
    """Recompute one exact lifecycle event/receipt bundle hash."""

    return _lifecycle_event_bundle_hash(event=bundle.event, evidence=bundle.evidence)


class R4PromotionLifecycleRepository(R4PromotionDecisionRepository, Protocol):
    """Append-only decision and scope-local lifecycle Phase-A port."""

    def load_lifecycle_history(
        self,
        scope_ref: R4PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        """Load only the exact recorded prefix known at ``as_of``."""

    def get_lifecycle_event_bundle(
        self,
        event_ref: R4PromotionVersionRef,
    ) -> R4PromotionLifecycleEventBundle | None:
        """Return one exact event bundle by immutable identity."""

    def load_lifecycle_stream(
        self,
        scope_ref: R4PromotionScopeRef,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        """Load the complete append-only stream for conflict validation."""

    def append_lifecycle_event_bundle(
        self,
        bundle: R4PromotionLifecycleEventBundle,
    ) -> R4PromotionLifecycleEventBundle:
        """Append or return only the exact idempotent event bundle."""


__all__ = [
    "ExactR4LifecycleAuthorizationEvidence",
    "ExactR4LifecycleAuthorizationProvider",
    "R4PromotionLifecycleAction",
    "R4PromotionLifecycleEventBundle",
    "R4PromotionLifecycleRepository",
    "R4PromotionScopeRef",
    "exact_r4_lifecycle_authorization_evidence_hash",
    "r4_promotion_lifecycle_event_bundle_hash",
]
