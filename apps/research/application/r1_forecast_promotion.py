"""ID-only application contracts for exact Research R1 promotion evidence."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1ForecastTrialPromotionSeal,
    R1PromotionDecisionIdentity,
    R1PromotionDecisionOutcome,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventType,
    R1PromotionLifecycleState,
    create_r1_forecast_promotion_decision,
    create_r1_promotion_lifecycle_event,
    create_r1_promotion_lifecycle_root,
    derive_r1_promotion_lifecycle_state,
    r1_forecast_promotion_decision_valid_until,
    r1_promotion_lifecycle_reason_hash,
    r1_promotion_stream_id,
)


def _require_token(value: str, field_name: str) -> None:
    if not value or len(value) > 192 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "canonical datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class R1PromotionVersionRef:
    """Stable ID/version pair accepted at the untrusted command boundary."""

    stable_id: str
    version: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "R1 promotion stable_id")
        _require_token(self.version, "R1 promotion version")


@dataclass(frozen=True)
class R1PromotionScopeRef:
    """ID-only semantic stream reference accepted by lifecycle commands."""

    scope_id: str

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R1 promotion lifecycle scope_id")


class R1PromotionLifecycleAction(str, Enum):
    """Application command vocabulary mapped explicitly to Domain events."""

    PROMOTE = "promote"
    RETIRE = "retire"
    ROLLBACK = "rollback"

    @property
    def event_type(self) -> R1PromotionLifecycleEventType:
        """Return the exact Domain transition represented by this action."""

        return {
            R1PromotionLifecycleAction.PROMOTE: R1PromotionLifecycleEventType.PROMOTED,
            R1PromotionLifecycleAction.RETIRE: R1PromotionLifecycleEventType.RETIRED,
            R1PromotionLifecycleAction.ROLLBACK: R1PromotionLifecycleEventType.ROLLED_BACK,
        }[self]


@dataclass(frozen=True)
class ExactR1LifecycleAuthorizationEvidence:
    """Research-owned authorization plus stable server event receipt."""

    event_ref: R1PromotionVersionRef
    authorization: R1PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    event_recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_ref: R1PromotionVersionRef,
        authorization: R1PromotionLifecycleAuthorization,
        reason_codes: tuple[str, ...],
        occurred_at: datetime,
        event_recorded_at: datetime,
    ) -> ExactR1LifecycleAuthorizationEvidence:
        """Seal the exact owner evidence without accepting it in a command."""

        return cls(
            event_ref=event_ref,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            event_recorded_at=event_recorded_at,
            content_hash=_lifecycle_authorization_evidence_hash_values(
                event_ref=event_ref,
                authorization=authorization,
                reason_codes=reason_codes,
                occurred_at=occurred_at,
                event_recorded_at=event_recorded_at,
            ),
        )

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "lifecycle evidence occurred_at")
        _require_aware(self.event_recorded_at, "lifecycle evidence event_recorded_at")
        if not (
            self.authorization.recorded_at <= self.occurred_at <= self.event_recorded_at
            and self.authorization.issued_at <= self.occurred_at < self.authorization.valid_until
        ):
            raise ValueError("R1 lifecycle authorization evidence time chain is invalid")
        if self.authorization.reason_hash != r1_promotion_lifecycle_reason_hash(self.reason_codes):
            raise ValueError("R1 lifecycle authorization evidence reasons were substituted")
        _require_hash(self.content_hash, "lifecycle authorization evidence content_hash")
        if self.content_hash != exact_r1_lifecycle_authorization_evidence_hash(self):
            raise ValueError("R1 lifecycle authorization evidence content hash mismatch")


def _lifecycle_authorization_evidence_hash_values(
    *,
    event_ref: R1PromotionVersionRef,
    authorization: R1PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    event_recorded_at: datetime,
) -> str:
    target = authorization.rollback_target
    return _canonical_hash(
        {
            "schema": "research-r1-lifecycle-authorization-evidence.v1",
            "event": [event_ref.stable_id, event_ref.version],
            "authorization": [
                authorization.authorization_id,
                authorization.authorization_version,
                authorization.content_hash,
            ],
            "action": authorization.event_type.value,
            "scope": [
                authorization.promotion_scope.scope_id,
                authorization.promotion_scope.content_hash,
            ],
            "decision": [
                authorization.decision.decision_id,
                authorization.decision.decision_version,
                authorization.decision.content_hash,
            ],
            "rollback_target": (
                [target.decision_id, target.decision_version, target.content_hash]
                if target is not None
                else None
            ),
            "reason_codes": list(reason_codes),
            "window": [_utc_text(occurred_at), _utc_text(event_recorded_at)],
        }
    )


def exact_r1_lifecycle_authorization_evidence_hash(
    evidence: ExactR1LifecycleAuthorizationEvidence,
) -> str:
    """Recompute one exact authorization/event-receipt digest."""

    return _lifecycle_authorization_evidence_hash_values(
        event_ref=evidence.event_ref,
        authorization=evidence.authorization,
        reason_codes=evidence.reason_codes,
        occurred_at=evidence.occurred_at,
        event_recorded_at=evidence.event_recorded_at,
    )


@dataclass(frozen=True)
class ExactEquityTrialResultEvidence:
    """Equity owner-row receipt for one exact immutable trial result."""

    result: ForecastBaselineTrialResult
    owner: str
    recorded_at: datetime
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        result: ForecastBaselineTrialResult,
        recorded_at: datetime,
    ) -> ExactEquityTrialResultEvidence:
        """Seal the owner-row receipt separately from result evaluation time."""

        digest = _equity_trial_record_hash_values(
            result_id=result.result_id,
            result_version=result.result_version,
            result_content_hash=result.content_hash,
            owner="equity",
            recorded_at=recorded_at,
        )
        return cls(
            result=result,
            owner="equity",
            recorded_at=recorded_at,
            record_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "equity" or self.result.owner != self.owner:
            raise ValueError("exact Equity trial result owner is invalid")
        _require_aware(self.recorded_at, "Equity trial owner recorded_at")
        if self.recorded_at < self.result.evaluated_at:
            raise ValueError("Equity trial owner receipt predates evaluation")
        _require_hash(self.record_hash, "Equity trial owner record_hash")
        if self.record_hash != exact_equity_trial_result_record_hash(self):
            raise ValueError("Equity trial owner record hash mismatch")


def _equity_trial_record_hash_values(
    *,
    result_id: str,
    result_version: str,
    result_content_hash: str,
    owner: str,
    recorded_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "schema": "research-r1-exact-equity-trial-owner-record.v1",
            "owner": owner,
            "result": [
                result_id,
                result_version,
                result_content_hash,
            ],
            "recorded_at": _utc_text(recorded_at),
        }
    )


def exact_equity_trial_result_record_hash(
    evidence: ExactEquityTrialResultEvidence,
) -> str:
    """Recompute an exact Equity owner-row receipt digest."""

    return _equity_trial_record_hash_values(
        result_id=evidence.result.result_id,
        result_version=evidence.result.result_version,
        result_content_hash=evidence.result.content_hash,
        owner=evidence.owner,
        recorded_at=evidence.recorded_at,
    )


@dataclass(frozen=True)
class R1PromotionDecisionReceipt:
    """Stable Research-owner receipt claimed atomically for one output identity."""

    receipt_id: str
    receipt_version: str
    decision_ref: R1PromotionVersionRef
    policy_ref: R1PromotionVersionRef
    policy_content_hash: str
    result_ref: R1PromotionVersionRef
    result_content_hash: str
    equity_result_recorded_at: datetime
    equity_result_record_hash: str
    owner: str
    capability: str
    purpose: str
    decided_at: datetime
    recorded_at: datetime
    decision_valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        receipt_version: str,
        decision_ref: R1PromotionVersionRef,
        policy_ref: R1PromotionVersionRef,
        policy_content_hash: str,
        result_ref: R1PromotionVersionRef,
        result_content_hash: str,
        equity_result_recorded_at: datetime,
        equity_result_record_hash: str,
        decided_at: datetime,
        recorded_at: datetime,
        decision_valid_until: datetime,
    ) -> R1PromotionDecisionReceipt:
        """Seal one server-issued receipt; no command may supply these fields."""

        digest = _decision_receipt_hash_values(
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            decision_ref=decision_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            result_ref=result_ref,
            result_content_hash=result_content_hash,
            equity_result_recorded_at=equity_result_recorded_at,
            equity_result_record_hash=equity_result_record_hash,
            owner="research",
            capability="r1",
            purpose="valuation",
            decided_at=decided_at,
            recorded_at=recorded_at,
            decision_valid_until=decision_valid_until,
        )
        return cls(
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            decision_ref=decision_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            result_ref=result_ref,
            result_content_hash=result_content_hash,
            equity_result_recorded_at=equity_result_recorded_at,
            equity_result_record_hash=equity_result_record_hash,
            owner="research",
            capability="r1",
            purpose="valuation",
            decided_at=decided_at,
            recorded_at=recorded_at,
            decision_valid_until=decision_valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "R1 promotion decision receipt_id")
        _require_token(self.receipt_version, "R1 promotion decision receipt_version")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("R1 promotion decision receipt authority is invalid")
        _require_hash(self.policy_content_hash, "decision receipt policy_content_hash")
        _require_hash(self.result_content_hash, "decision receipt result_content_hash")
        _require_aware(
            self.equity_result_recorded_at,
            "decision receipt Equity result recorded_at",
        )
        _require_hash(
            self.equity_result_record_hash,
            "decision receipt Equity result record_hash",
        )
        if self.equity_result_record_hash != _equity_trial_record_hash_values(
            result_id=self.result_ref.stable_id,
            result_version=self.result_ref.version,
            result_content_hash=self.result_content_hash,
            owner="equity",
            recorded_at=self.equity_result_recorded_at,
        ):
            raise ValueError("decision receipt Equity result owner record mismatch")
        _require_aware(self.decided_at, "decision receipt decided_at")
        _require_aware(self.recorded_at, "decision receipt recorded_at")
        _require_aware(
            self.decision_valid_until,
            "decision receipt decision_valid_until",
        )
        if not (
            self.equity_result_recorded_at
            <= self.decided_at
            <= self.recorded_at
            < self.decision_valid_until
        ):
            raise ValueError("R1 promotion decision receipt knowledge-time chain is invalid")
        _require_hash(self.content_hash, "decision receipt content_hash")
        if self.content_hash != r1_promotion_decision_receipt_hash(self):
            raise ValueError("R1 promotion decision receipt content hash mismatch")


def _decision_receipt_hash_values(
    *,
    receipt_id: str,
    receipt_version: str,
    decision_ref: R1PromotionVersionRef,
    policy_ref: R1PromotionVersionRef,
    policy_content_hash: str,
    result_ref: R1PromotionVersionRef,
    result_content_hash: str,
    equity_result_recorded_at: datetime,
    equity_result_record_hash: str,
    owner: str,
    capability: str,
    purpose: str,
    decided_at: datetime,
    recorded_at: datetime,
    decision_valid_until: datetime,
) -> str:
    return _canonical_hash(
        {
            "schema": "research-r1-promotion-decision-owner-receipt.v1",
            "identity": [receipt_id, receipt_version],
            "authority": [owner, capability, purpose],
            "decision": [decision_ref.stable_id, decision_ref.version],
            "policy": [
                policy_ref.stable_id,
                policy_ref.version,
                policy_content_hash,
            ],
            "result": [
                result_ref.stable_id,
                result_ref.version,
                result_content_hash,
                _utc_text(equity_result_recorded_at),
                equity_result_record_hash,
            ],
            "window": [
                _utc_text(decided_at),
                _utc_text(recorded_at),
                _utc_text(decision_valid_until),
            ],
        }
    )


def r1_promotion_decision_receipt_hash(receipt: R1PromotionDecisionReceipt) -> str:
    """Recompute one Research owner decision receipt digest."""

    return _decision_receipt_hash_values(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        decision_ref=receipt.decision_ref,
        policy_ref=receipt.policy_ref,
        policy_content_hash=receipt.policy_content_hash,
        result_ref=receipt.result_ref,
        result_content_hash=receipt.result_content_hash,
        equity_result_recorded_at=receipt.equity_result_recorded_at,
        equity_result_record_hash=receipt.equity_result_record_hash,
        owner=receipt.owner,
        capability=receipt.capability,
        purpose=receipt.purpose,
        decided_at=receipt.decided_at,
        recorded_at=receipt.recorded_at,
        decision_valid_until=receipt.decision_valid_until,
    )


class ExactR1PromotionPolicyProvider(Protocol):
    """Read one exact Research-owned policy at a knowledge-time boundary."""

    def get_exact(
        self,
        policy_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionPolicy | None: ...


class ExactEquityTrialResultProvider(Protocol):
    """Read one exact Equity trial plus its owner-row receipt at knowledge time."""

    def get_exact(
        self,
        result_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> ExactEquityTrialResultEvidence | None: ...


class ResearchOwnerReceiptProvider(Protocol):
    """Atomically return the stable winner receipt for one decision identity."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the transaction boundary used by this provider."""
        ...

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
    ) -> R1PromotionDecisionReceipt | None: ...


class ExactR1LifecycleAuthorizationProvider(Protocol):
    """Atomically claim or return the stable owner receipt for an event ID."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the transaction boundary used by this provider."""
        ...

    def get_exact(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> ExactR1LifecycleAuthorizationEvidence | None: ...


@dataclass(frozen=True)
class R1PromotionLifecycleEventBundle:
    """Atomic lifecycle event and stable owner/server receipt evidence."""

    event: R1PromotionLifecycleEvent
    evidence: ExactR1LifecycleAuthorizationEvidence
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event: R1PromotionLifecycleEvent,
        evidence: ExactR1LifecycleAuthorizationEvidence,
    ) -> R1PromotionLifecycleEventBundle:
        """Seal the exact lifecycle persistence unit."""

        return cls(
            event=event,
            evidence=evidence,
            content_hash=_lifecycle_event_bundle_hash_values(
                event=event,
                evidence=evidence,
            ),
        )

    def __post_init__(self) -> None:
        if (
            (self.event.event_id, self.event.event_version)
            != (self.evidence.event_ref.stable_id, self.evidence.event_ref.version)
            or self.event.authorization != self.evidence.authorization
            or self.event.reason_codes != self.evidence.reason_codes
            or self.event.occurred_at != self.evidence.occurred_at
            or self.event.recorded_at != self.evidence.event_recorded_at
            or self.event.promotion_scope != self.evidence.authorization.promotion_scope
        ):
            raise ValueError("R1 lifecycle event bundle owner receipt was substituted")
        _require_hash(self.content_hash, "R1 lifecycle event bundle content_hash")
        if self.content_hash != r1_promotion_lifecycle_event_bundle_hash(self):
            raise ValueError("R1 lifecycle event bundle content hash mismatch")


def _lifecycle_event_bundle_hash_values(
    *,
    event: R1PromotionLifecycleEvent,
    evidence: ExactR1LifecycleAuthorizationEvidence,
) -> str:
    return _canonical_hash(
        {
            "schema": "research-r1-promotion-lifecycle-event-bundle.v1",
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


def r1_promotion_lifecycle_event_bundle_hash(
    bundle: R1PromotionLifecycleEventBundle,
) -> str:
    """Recompute one exact lifecycle event/receipt bundle digest."""

    return _lifecycle_event_bundle_hash_values(
        event=bundle.event,
        evidence=bundle.evidence,
    )


@dataclass(frozen=True)
class R1ForecastPromotionDecisionBundle:
    """Atomic decision plus Research receipt sealing the Equity owner row."""

    decision: R1ForecastPromotionDecision
    receipt: R1PromotionDecisionReceipt
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        decision: R1ForecastPromotionDecision,
        receipt: R1PromotionDecisionReceipt,
    ) -> R1ForecastPromotionDecisionBundle:
        """Seal the complete atomic persistence unit."""

        return cls(
            decision=decision,
            receipt=receipt,
            content_hash=_decision_bundle_hash_values(
                decision=decision,
                receipt=receipt,
            ),
        )

    def __post_init__(self) -> None:
        if (
            self.receipt.decision_ref
            != R1PromotionVersionRef(
                self.decision.decision_id,
                self.decision.decision_version,
            )
            or self.receipt.policy_ref
            != R1PromotionVersionRef(
                self.decision.policy.policy_id,
                self.decision.policy.policy_version,
            )
            or self.receipt.policy_content_hash != self.decision.policy.content_hash
            or self.receipt.result_ref
            != R1PromotionVersionRef(
                self.decision.trial.result_id,
                self.decision.trial.result_version,
            )
            or self.receipt.result_content_hash != self.decision.trial.result_content_hash
            or self.receipt.decided_at != self.decision.decided_at
            or self.receipt.recorded_at != self.decision.recorded_at
            or self.receipt.decision_valid_until != self.decision.valid_until
        ):
            raise ValueError("R1 promotion decision bundle receipt was substituted")
        expected_equity_record_hash = _equity_trial_record_hash_values(
            result_id=self.decision.trial.result_id,
            result_version=self.decision.trial.result_version,
            result_content_hash=self.decision.trial.result_content_hash,
            owner="equity",
            recorded_at=self.receipt.equity_result_recorded_at,
        )
        if self.receipt.equity_result_record_hash != expected_equity_record_hash:
            raise ValueError("R1 promotion decision bundle Equity receipt is invalid")
        if not (
            self.decision.trial.evaluated_at
            <= self.receipt.equity_result_recorded_at
            <= self.decision.decided_at
            <= self.decision.recorded_at
            <= self.decision.valid_until
        ):
            raise ValueError("R1 promotion decision bundle knowledge-time chain is invalid")
        _require_hash(self.content_hash, "R1 promotion decision bundle content_hash")
        if self.content_hash != r1_forecast_promotion_decision_bundle_hash(self):
            raise ValueError("R1 promotion decision bundle content hash mismatch")


def _decision_bundle_hash_values(
    *,
    decision: R1ForecastPromotionDecision,
    receipt: R1PromotionDecisionReceipt,
) -> str:
    return _canonical_hash(
        {
            "schema": "research-r1-forecast-promotion-decision-bundle.v1",
            "decision": [
                decision.decision_id,
                decision.decision_version,
                decision.content_hash,
            ],
            "research_receipt": [
                receipt.receipt_id,
                receipt.receipt_version,
                receipt.content_hash,
                _utc_text(receipt.recorded_at),
            ],
            "equity_result_owner_record": [
                _utc_text(receipt.equity_result_recorded_at),
                receipt.equity_result_record_hash,
            ],
        }
    )


def r1_forecast_promotion_decision_bundle_hash(
    bundle: R1ForecastPromotionDecisionBundle,
) -> str:
    """Recompute the atomic decision/receipt bundle digest."""

    return _decision_bundle_hash_values(
        decision=bundle.decision,
        receipt=bundle.receipt,
    )


class R1ForecastPromotionRepository(Protocol):
    """Append-only decision persistence; conflicts must fail rather than replace."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the repository transaction boundary."""
        ...

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap owner receipt claim and child bundle append atomically."""
        ...

    def append_decision_bundle(
        self,
        bundle: R1ForecastPromotionDecisionBundle,
    ) -> R1ForecastPromotionDecisionBundle: ...

    def get_decision_bundle(
        self,
        decision_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundle | None: ...

    def load_lifecycle_history(
        self,
        scope_ref: R1PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R1PromotionLifecycleEvent, ...]: ...

    def get_lifecycle_event_bundle(
        self,
        event_ref: R1PromotionVersionRef,
    ) -> R1PromotionLifecycleEventBundle | None: ...

    def load_lifecycle_stream(
        self,
        scope_ref: R1PromotionScopeRef,
    ) -> tuple[R1PromotionLifecycleEvent, ...]: ...

    def append_lifecycle_event_bundle(
        self,
        bundle: R1PromotionLifecycleEventBundle,
    ) -> R1PromotionLifecycleEventBundle: ...


@dataclass(frozen=True)
class EvaluateR1ForecastPromotionCommand:
    """ID-only request; outcome, hashes and receipt time are owner-resolved."""

    output_decision_ref: R1PromotionVersionRef
    policy_ref: R1PromotionVersionRef
    equity_result_ref: R1PromotionVersionRef
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "R1 promotion command as_of")


@dataclass(frozen=True)
class AppendR1PromotionLifecycleCommand:
    """ID-only lifecycle request; authorization and clocks are provider-owned."""

    output_event_ref: R1PromotionVersionRef
    scope_ref: R1PromotionScopeRef
    action: R1PromotionLifecycleAction
    decision_ref: R1PromotionVersionRef
    authorization_ref: R1PromotionVersionRef
    rollback_target_ref: R1PromotionVersionRef | None

    def __post_init__(self) -> None:
        if self.action is R1PromotionLifecycleAction.ROLLBACK:
            if self.rollback_target_ref is None:
                raise ValueError("rollback lifecycle command requires a target ref")
        elif self.rollback_target_ref is not None:
            raise ValueError("non-rollback lifecycle command cannot carry a target ref")


class R1PromotionEvidenceError(ValueError):
    """Raised when exact owner evidence is missing, late or substituted."""


class EvaluateR1ForecastPromotionUseCase:
    """Re-read exact owner evidence and append one deterministic decision."""

    def __init__(
        self,
        *,
        policy_provider: ExactR1PromotionPolicyProvider,
        trial_result_provider: ExactEquityTrialResultProvider,
        receipt_provider: ResearchOwnerReceiptProvider,
        repository: R1ForecastPromotionRepository,
    ) -> None:
        self._policy_provider = policy_provider
        self._trial_result_provider = trial_result_provider
        self._receipt_provider = receipt_provider
        self._repository = repository
        if receipt_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError("decision receipt provider and repository use different units of work")

    def execute(
        self,
        command: EvaluateR1ForecastPromotionCommand,
    ) -> R1ForecastPromotionDecision:
        """Resolve ID-only inputs, derive the result, and require exact append."""

        policy = self._policy_provider.get_exact(
            command.policy_ref,
            as_of=command.as_of,
        )
        if policy is None or (
            policy.policy_id,
            policy.policy_version,
        ) != (command.policy_ref.stable_id, command.policy_ref.version):
            raise R1PromotionEvidenceError("exact R1 promotion policy is unavailable")
        result_evidence = self._trial_result_provider.get_exact(
            command.equity_result_ref,
            as_of=command.as_of,
        )
        if result_evidence is None:
            raise R1PromotionEvidenceError("exact Equity trial result is unavailable")
        result = result_evidence.result
        if (
            (result.result_id, result.result_version)
            != (
                command.equity_result_ref.stable_id,
                command.equity_result_ref.version,
            )
            or result_evidence.recorded_at > command.as_of
            or result.evaluated_at > result_evidence.recorded_at
            or result_evidence.record_hash != exact_equity_trial_result_record_hash(result_evidence)
        ):
            raise R1PromotionEvidenceError(
                "Equity trial result identity or owner receipt is invalid"
            )
        with self._repository.atomic():
            return self._append_atomic(command, policy, result_evidence)

    def _append_atomic(
        self,
        command: EvaluateR1ForecastPromotionCommand,
        policy: R1ForecastPromotionPolicy,
        result_evidence: ExactEquityTrialResultEvidence,
    ) -> R1ForecastPromotionDecision:
        result = result_evidence.result
        receipt = self._receipt_provider.get_exact(
            decision_ref=command.output_decision_ref,
            policy_ref=command.policy_ref,
            policy_content_hash=policy.content_hash,
            result_ref=command.equity_result_ref,
            result_content_hash=result.content_hash,
            equity_result_recorded_at=result_evidence.recorded_at,
            equity_result_record_hash=result_evidence.record_hash,
            decided_at=command.as_of,
            decision_valid_until=r1_forecast_promotion_decision_valid_until(
                policy=policy,
                result=result,
                as_of=command.as_of,
            ),
        )
        if receipt is None or not _decision_receipt_matches(
            receipt=receipt,
            command=command,
            policy=policy,
            result_evidence=result_evidence,
            result=result,
        ):
            raise R1PromotionEvidenceError("exact Research owner decision receipt is unavailable")
        decision = create_r1_forecast_promotion_decision(
            decision_id=command.output_decision_ref.stable_id,
            decision_version=command.output_decision_ref.version,
            policy=policy,
            result=result,
            as_of=command.as_of,
            recorded_at=receipt.recorded_at,
        )
        bundle = R1ForecastPromotionDecisionBundle.create(
            decision=decision,
            receipt=receipt,
        )
        persisted = self._repository.append_decision_bundle(bundle)
        if persisted != bundle:
            raise R1PromotionEvidenceError(
                "promotion repository did not preserve the exact decision bundle"
            )
        return persisted.decision


class AppendR1PromotionLifecycleEventUseCase:
    """Re-read decisions, history and owner authorization before exact append."""

    def __init__(
        self,
        *,
        authorization_provider: ExactR1LifecycleAuthorizationProvider,
        repository: R1ForecastPromotionRepository,
    ) -> None:
        self._authorization_provider = authorization_provider
        self._repository = repository
        if authorization_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError(
                "lifecycle authorization provider and repository use different units of work"
            )

    def execute(
        self,
        command: AppendR1PromotionLifecycleCommand,
    ) -> R1PromotionLifecycleEvent:
        """Build one legal scope-local event without caller-owned evidence."""

        with self._repository.atomic():
            return self._append_atomic(command)

    def _append_atomic(
        self,
        command: AppendR1PromotionLifecycleCommand,
    ) -> R1PromotionLifecycleEvent:
        """Claim the stable receipt and append its child in one unit of work."""

        evidence = self._authorization_provider.get_exact(
            authorization_ref=command.authorization_ref,
            event_ref=command.output_event_ref,
            scope_ref=command.scope_ref,
            action=command.action,
            decision_ref=command.decision_ref,
            rollback_target_ref=command.rollback_target_ref,
        )
        if evidence is None:
            raise R1PromotionEvidenceError("exact Research lifecycle authorization is unavailable")
        knowledge_at = evidence.occurred_at
        decision_bundle = self._load_decision_bundle(command.decision_ref, knowledge_at)
        decision = decision_bundle.decision
        if decision.promotion_scope.scope_id != command.scope_ref.scope_id:
            raise R1PromotionEvidenceError("lifecycle decision scope was substituted")
        rollback_target: R1ForecastPromotionDecision | None = None
        if command.rollback_target_ref is not None:
            rollback_target = self._load_decision_bundle(
                command.rollback_target_ref,
                knowledge_at,
            ).decision
            if rollback_target.promotion_scope != decision.promotion_scope:
                raise R1PromotionEvidenceError("lifecycle rollback target crosses scopes")
        if not _lifecycle_authorization_matches(
            evidence=evidence,
            command=command,
            decision=decision,
            rollback_target=rollback_target,
        ):
            raise R1PromotionEvidenceError("exact Research lifecycle authorization is unavailable")
        existing_bundle = self._repository.get_lifecycle_event_bundle(command.output_event_ref)
        if existing_bundle is not None:
            existing = existing_bundle.event
            if not _lifecycle_event_matches_evidence(
                event=existing,
                evidence=evidence,
                command=command,
                decision=decision,
                rollback_target=rollback_target,
            ):
                raise R1PromotionEvidenceError("lifecycle output identity has conflicting evidence")
            if existing_bundle != R1PromotionLifecycleEventBundle.create(
                event=existing,
                evidence=evidence,
            ):
                raise R1PromotionEvidenceError(
                    "existing lifecycle event bundle receipt was substituted"
                )
            full_stream = self._repository.load_lifecycle_stream(command.scope_ref)
            if existing not in full_stream:
                raise R1PromotionEvidenceError(
                    "existing lifecycle event is missing from its stream"
                )
            try:
                derive_r1_promotion_lifecycle_state(
                    full_stream,
                    evaluated_at=max(item.recorded_at for item in full_stream),
                )
            except ValueError as error:
                raise R1PromotionEvidenceError(
                    "existing lifecycle stream failed canonical replay"
                ) from error
            return existing
        history = self._repository.load_lifecycle_history(
            command.scope_ref,
            as_of=knowledge_at,
        )
        if any(event.recorded_at > knowledge_at for event in history):
            raise R1PromotionEvidenceError("lifecycle history contains future evidence")
        if not history:
            if command.action is not R1PromotionLifecycleAction.PROMOTE:
                raise R1PromotionEvidenceError("R1 lifecycle stream must start with promotion")
            event = create_r1_promotion_lifecycle_root(
                event_id=command.output_event_ref.stable_id,
                event_version=command.output_event_ref.version,
                decision=decision,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        else:
            event = create_r1_promotion_lifecycle_event(
                event_id=command.output_event_ref.stable_id,
                event_version=command.output_event_ref.version,
                previous_events=history,
                event_type=command.action.event_type,
                decision=decision,
                rollback_target=rollback_target,
                authorization=evidence.authorization,
                reason_codes=evidence.reason_codes,
                occurred_at=evidence.occurred_at,
                recorded_at=evidence.event_recorded_at,
            )
        bundle = R1PromotionLifecycleEventBundle.create(
            event=event,
            evidence=evidence,
        )
        persisted = self._repository.append_lifecycle_event_bundle(bundle)
        if persisted != bundle:
            raise R1PromotionEvidenceError(
                "lifecycle repository did not preserve the exact event bundle"
            )
        return persisted.event

    def _load_decision_bundle(
        self,
        decision_ref: R1PromotionVersionRef,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundle:
        bundle = self._repository.get_decision_bundle(
            decision_ref,
            as_of=as_of,
        )
        if bundle is None or (
            bundle.decision.decision_id,
            bundle.decision.decision_version,
        ) != (decision_ref.stable_id, decision_ref.version):
            raise R1PromotionEvidenceError("exact promotion decision bundle is unavailable")
        if bundle.decision.recorded_at > as_of:
            raise R1PromotionEvidenceError("promotion decision is future-unrecorded")
        return bundle


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


__all__ = [
    "AppendR1PromotionLifecycleCommand",
    "AppendR1PromotionLifecycleEventUseCase",
    "EvaluateR1ForecastPromotionCommand",
    "EvaluateR1ForecastPromotionUseCase",
    "ExactEquityTrialResultEvidence",
    "ExactEquityTrialResultProvider",
    "ExactR1LifecycleAuthorizationEvidence",
    "ExactR1LifecycleAuthorizationProvider",
    "ExactR1PromotionPolicyProvider",
    "R1ForecastPromotionRepository",
    "R1ActiveForecastPromotionProvider",
    "R1ForecastPromotionDecisionBundle",
    "R1PromotionDecisionReceipt",
    "R1PromotionEvidenceError",
    "R1PromotionLifecycleAction",
    "R1PromotionLifecycleEventBundle",
    "R1PromotionScopeRef",
    "R1PromotionVersionRef",
    "ResearchOwnerReceiptProvider",
    "exact_equity_trial_result_record_hash",
    "exact_r1_lifecycle_authorization_evidence_hash",
    "r1_promotion_decision_receipt_hash",
    "r1_promotion_lifecycle_event_bundle_hash",
    "r1_forecast_promotion_decision_bundle_hash",
]
