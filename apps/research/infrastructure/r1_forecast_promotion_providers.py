"""Exact owner-evidence adapters for Research R1 forecast promotion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from apps.equity.application.forecast_baseline_materialize import VersionRef as EquityVersionRef
from apps.equity.application.forecast_baseline_query import (
    ExactForecastBaselineTrialQuery,
)
from apps.research.application.r1_forecast_promotion import (
    ExactEquityTrialResultEvidence,
    ExactEquityTrialResultProvider,
    ExactR1LifecycleAuthorizationEvidence,
    R1PromotionDecisionReceipt,
    R1PromotionEvidenceError,
    R1PromotionLifecycleAction,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionPolicy,
    R1PromotionLifecycleAuthorization,
)

if TYPE_CHECKING:
    from apps.research.infrastructure.r1_forecast_promotion_repository import (
        DjangoR1ForecastPromotionRepository,
    )


class R1PromotionRepositoryConflict(R1PromotionEvidenceError):
    """Raised when one immutable identity is bound to different evidence."""


class R1PromotionRepositoryCorruption(R1PromotionEvidenceError):
    """Raised when restored rows, payloads, headers or foreign keys disagree."""


@dataclass(frozen=True)
class R1LifecycleAuthorizationClaim:
    """Trusted Research-owner input used to claim stable server event clocks."""

    authorization: R1PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]


class R1LifecycleAuthorizationSource(Protocol):
    """Owner-side exact authorization source; it is not a caller command."""

    def get_exact(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> R1LifecycleAuthorizationClaim | None: ...


class ExactEquityTrialOwnerRecordProvider(ExactEquityTrialResultProvider, Protocol):
    """Provide typed Equity evidence plus its opaque owner-row binding."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the database owning opaque Equity row bindings."""
        ...

    def get_owner_record_key(
        self,
        result_ref: R1PromotionVersionRef,
        *,
        content_hash: str,
        recorded_at: datetime,
    ) -> int | None: ...


class DjangoExactEquityTrialResultProvider:
    """Translate the Equity-owned exact query into Research evidence."""

    def __init__(self, query: ExactForecastBaselineTrialQuery) -> None:
        self._query = query

    @property
    def unit_of_work_key(self) -> str:
        """Identify the Equity database used by the exact query."""

        return self._query.unit_of_work_key

    def get_exact(
        self,
        result_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> ExactEquityTrialResultEvidence | None:
        """Return an exact typed trial and its canonical owner receipt hash."""

        record = self._query.get_exact(
            EquityVersionRef(result_ref.stable_id, result_ref.version),
            as_of=as_of,
        )
        if record is None:
            return None
        if (
            record.result.result_id != result_ref.stable_id
            or record.result.result_version != result_ref.version
        ):
            raise R1PromotionRepositoryCorruption("Equity exact query substituted trial identity")
        return ExactEquityTrialResultEvidence.create(
            result=record.result,
            recorded_at=record.recorded_at,
        )

    def get_owner_record_key(
        self,
        result_ref: R1PromotionVersionRef,
        *,
        content_hash: str,
        recorded_at: datetime,
    ) -> int | None:
        """Resolve the opaque FK binding only for the exact sealed owner row."""

        record = self._query.get_exact(
            EquityVersionRef(result_ref.stable_id, result_ref.version),
            as_of=recorded_at,
        )
        if record is None:
            return None
        if (
            record.result.result_id != result_ref.stable_id
            or record.result.result_version != result_ref.version
            or record.result.content_hash != content_hash
            or record.recorded_at != recorded_at
        ):
            return None
        return record.owner_record_key


class DjangoR1PromotionPolicyProvider:
    """Exact policy-provider adapter with the Application protocol signature."""

    def __init__(self, repository: DjangoR1ForecastPromotionRepository) -> None:
        self._repository = repository

    def get_exact(
        self,
        policy_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionPolicy | None:
        return self._repository.get_exact_policy(policy_ref, as_of=as_of)


class DjangoR1DecisionReceiptProvider:
    """Stable decision-receipt adapter with the Application signature."""

    def __init__(self, repository: DjangoR1ForecastPromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        decision_ref: R1PromotionVersionRef,
        policy_ref: R1PromotionVersionRef,
        policy_content_hash: str,
        result_ref: R1PromotionVersionRef,
        result_content_hash: str,
        equity_result_recorded_at: datetime,
        equity_result_record_hash: str,
        decided_at: datetime,
        decision_valid_until: datetime,
    ) -> R1PromotionDecisionReceipt | None:
        self._repository.require_active_unit_of_work()
        return self._repository.claim_decision_receipt(
            decision_ref=decision_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            result_ref=result_ref,
            result_content_hash=result_content_hash,
            equity_result_recorded_at=equity_result_recorded_at,
            equity_result_record_hash=equity_result_record_hash,
            decided_at=decided_at,
            decision_valid_until=decision_valid_until,
        )


class DjangoR1LifecycleAuthorizationProvider:
    """Exact claimed lifecycle-receipt adapter."""

    def __init__(
        self,
        repository: DjangoR1ForecastPromotionRepository,
        *,
        owner_source: R1LifecycleAuthorizationSource,
    ) -> None:
        self._repository = repository
        self._owner_source = owner_source

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> ExactR1LifecycleAuthorizationEvidence | None:
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


def _stable_decision_receipt_id(
    *,
    decision_ref: R1PromotionVersionRef,
    policy_ref: R1PromotionVersionRef,
    result_ref: R1PromotionVersionRef,
    scope_id: str,
) -> str:
    digest = hashlib.sha256(
        "\0".join(
            (
                decision_ref.stable_id,
                decision_ref.version,
                policy_ref.stable_id,
                policy_ref.version,
                result_ref.stable_id,
                result_ref.version,
                scope_id,
            )
        ).encode()
    ).hexdigest()
    return f"r1-decision-receipt:{digest}"


def r1_lifecycle_authorization_claim_id(
    *,
    event_ref: R1PromotionVersionRef,
    authorization: R1PromotionLifecycleAuthorization,
) -> str:
    """Return the canonical owner-authorization identity for an event claim."""

    target = authorization.rollback_target
    digest = hashlib.sha256(
        "\0".join(
            (
                event_ref.stable_id,
                event_ref.version,
                authorization.promotion_scope.scope_id,
                authorization.event_type.value,
                authorization.decision.decision_id,
                authorization.decision.decision_version,
                target.decision_id if target is not None else "",
                target.decision_version if target is not None else "",
            )
        ).encode()
    ).hexdigest()
    return f"r1-lifecycle-authorization:{digest}"


__all__ = [
    "DjangoExactEquityTrialResultProvider",
    "DjangoR1DecisionReceiptProvider",
    "DjangoR1LifecycleAuthorizationProvider",
    "DjangoR1PromotionPolicyProvider",
    "ExactEquityTrialOwnerRecordProvider",
    "R1LifecycleAuthorizationClaim",
    "R1LifecycleAuthorizationSource",
    "R1PromotionRepositoryConflict",
    "R1PromotionRepositoryCorruption",
    "r1_lifecycle_authorization_claim_id",
]
