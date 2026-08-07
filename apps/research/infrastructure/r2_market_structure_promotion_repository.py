"""Transactional exact repository for R2 promotion ledgers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.fixed_income.domain.evidence import canonical_hash, require_aware
from apps.research.application.r2_market_structure_promotion import (
    R2MarketStructurePromotionClock,
    R2MarketStructurePromotionEvidenceError,
    require_r2_market_structure_pit_cutoff,
)
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureLifecycleEvent,
    R2MarketStructurePromotionDecision,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionRef,
    derive_r2_market_structure_active_stack,
)
from apps.research.infrastructure.r2_market_structure_promotion_codec import (
    R2MarketStructurePromotionCodecError,
    decode_r2_market_structure_decision,
    decode_r2_market_structure_lifecycle_event,
    decode_r2_market_structure_policy,
    encode_r2_market_structure_decision,
    encode_r2_market_structure_lifecycle_event,
    encode_r2_market_structure_policy,
)
from apps.research.infrastructure.r2_market_structure_promotion_models import (
    R2MarketStructurePromotionDecisionModel,
    R2MarketStructurePromotionLifecycleEventModel,
    R2MarketStructurePromotionPolicyModel,
    _activate_r2_promotion_unit_of_work,
    _claim_r2_promotion_insert,
    _r2_promotion_unit_of_work_is_active,
)


class R2MarketStructurePromotionRepositoryError(R2MarketStructurePromotionEvidenceError):
    """Base stable repository failure."""


class R2MarketStructurePromotionRepositoryConflict(R2MarketStructurePromotionRepositoryError):
    """Raised for immutable identity conflicts."""

    def __init__(self, detail: str) -> None:
        super().__init__("r2_market_structure.repository_conflict", detail)


class R2MarketStructurePromotionRepositoryCorruption(R2MarketStructurePromotionRepositoryError):
    """Raised when persisted headers or payloads diverge."""

    def __init__(self, detail: str) -> None:
        super().__init__("r2_market_structure.repository_corruption", detail)


class DjangoR2MarketStructurePromotionClock:
    """Django-aware authoritative clock."""

    def now(self) -> datetime:
        return timezone.now()


def _ledger_receipt_hash(
    *,
    ledger_kind: str,
    content_hash: str,
    ledger_recorded_at: datetime,
) -> str:
    return canonical_hash(
        {
            "content_hash": content_hash,
            "ledger_kind": ledger_kind,
            "ledger_recorded_at": ledger_recorded_at.isoformat(),
            "schema": "research-r2-market-structure-ledger-receipt.v1",
        }
    )


def _policy_values(
    policy: R2MarketStructurePromotionPolicy,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "scope_id": policy.scope.scope_id,
        "scope_content_hash": policy.scope.content_hash,
        "registered_at": policy.registered_at,
        "active_from": policy.active_from,
        "valid_until": policy.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": _ledger_receipt_hash(
            ledger_kind="policy",
            content_hash=policy.content_hash,
            ledger_recorded_at=ledger_recorded_at,
        ),
        "canonical_payload": encode_r2_market_structure_policy(policy),
        "content_hash": policy.content_hash,
        "research_only": policy.research_only,
        "structure_description_only": policy.structure_description_only,
        "must_not_use_for_decision": policy.must_not_use_for_decision,
        "must_not_execute": policy.must_not_execute,
    }


def _decision_values(
    decision: R2MarketStructurePromotionDecision,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    return {
        "decision_id": decision.decision_id,
        "decision_version": decision.decision_version,
        "scope_id": decision.policy.scope.scope_id,
        "scope_content_hash": decision.policy.scope.content_hash,
        "policy_id": decision.policy.policy_id,
        "policy_version": decision.policy.policy_version,
        "policy_content_hash": decision.policy.content_hash,
        "evidence_key": decision.evidence.evidence_key,
        "evidence_version": decision.evidence.evidence_version,
        "evidence_content_hash": decision.evidence.content_hash,
        "authorization_id": decision.authorization.authorization_id,
        "authorization_version": decision.authorization.authorization_version,
        "authorization_content_hash": decision.authorization.content_hash,
        "outcome": decision.outcome.value,
        "decided_at": decision.decided_at,
        "semantic_recorded_at": decision.recorded_at,
        "valid_until": decision.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": _ledger_receipt_hash(
            ledger_kind="decision",
            content_hash=decision.content_hash,
            ledger_recorded_at=ledger_recorded_at,
        ),
        "canonical_payload": encode_r2_market_structure_decision(decision),
        "content_hash": decision.content_hash,
        "research_only": decision.research_only,
        "structure_description_only": decision.structure_description_only,
        "must_not_use_for_decision": decision.must_not_use_for_decision,
        "must_not_execute": decision.must_not_execute,
    }


def _event_values(
    event: R2MarketStructureLifecycleEvent,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    target = event.rollback_target_ref
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "scope_id": event.scope_id,
        "scope_content_hash": event.scope_content_hash,
        "stream_id": event.stream_id,
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "decision_id": event.decision_ref.stable_id,
        "decision_version": event.decision_ref.version,
        "decision_content_hash": event.decision_content_hash,
        "rollback_target_id": "" if target is None else target.stable_id,
        "rollback_target_version": "" if target is None else target.version,
        "rollback_target_content_hash": event.rollback_target_content_hash,
        "authorization_id": event.authorization.authorization_id,
        "authorization_version": event.authorization.authorization_version,
        "authorization_content_hash": event.authorization.content_hash,
        "previous_event_hash": event.previous_event_hash,
        "occurred_at": event.occurred_at,
        "semantic_recorded_at": event.recorded_at,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": _ledger_receipt_hash(
            ledger_kind="lifecycle",
            content_hash=event.content_hash,
            ledger_recorded_at=ledger_recorded_at,
        ),
        "canonical_payload": encode_r2_market_structure_lifecycle_event(event),
        "content_hash": event.content_hash,
    }


def _matches(model: models.Model, values: dict[str, object]) -> bool:
    return all(getattr(model, field_name) == value for field_name, value in values.items())


class DjangoR2MarketStructurePromotionRepository:
    """Strict replay repository with a private append surface."""

    def __init__(
        self,
        *,
        clock: R2MarketStructurePromotionClock | None = None,
        using: str = "default",
    ) -> None:
        self._clock = clock or DjangoR2MarketStructurePromotionClock()
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            with _activate_r2_promotion_unit_of_work(self._token):
                yield

    def _require_uow(self) -> None:
        connection = transaction.get_connection(self._using)
        if not _r2_promotion_unit_of_work_is_active(self._token) or not connection.in_atomic_block:
            raise R2MarketStructurePromotionRepositoryConflict(
                "operation requires its closure-bound unit of work"
            )

    def server_now(self) -> datetime:
        value = self._clock.now()
        require_aware(value, "R2 promotion server clock")
        return value

    def _append_policy(
        self,
        policy: R2MarketStructurePromotionPolicy,
    ) -> R2MarketStructurePromotionPolicy:
        self._require_uow()
        now = self.server_now()
        if not policy.is_active_at(now):
            raise R2MarketStructurePromotionRepositoryConflict(
                "policy is inactive at server registration"
            )
        candidates = self._policy_candidates(policy.reference, policy.content_hash)
        if candidates:
            matches = tuple(self._policy_from_model(item) for item in candidates)
            if len(matches) == 1 and matches[0] == policy:
                return matches[0]
            raise R2MarketStructurePromotionRepositoryConflict("policy identity conflicts")
        values = _policy_values(policy, ledger_recorded_at=now)
        try:
            with _claim_r2_promotion_insert(
                token=self._token,
                model_type=R2MarketStructurePromotionPolicyModel,
                expected_values=values,
            ):
                model = R2MarketStructurePromotionPolicyModel(**values)
                model.full_clean()
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            raise R2MarketStructurePromotionRepositoryConflict("policy append failed") from error
        return self._policy_from_model(model)

    def get_policy(
        self,
        policy_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionPolicy | None:
        self._require_uow()
        require_r2_market_structure_pit_cutoff(as_of, server_now=self.server_now())
        candidates = self._policy_candidates(policy_ref, None)
        restored = tuple((model, self._policy_from_model(model)) for model in candidates)
        matches = tuple(
            (model, policy) for model, policy in restored if policy.reference == policy_ref
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "policy selector has multiple exact matches"
            )
        model, policy = matches[0]
        if model.ledger_recorded_at > as_of or not policy.is_active_at(as_of):
            return None
        return policy

    def _append_decision(
        self,
        decision: R2MarketStructurePromotionDecision,
    ) -> R2MarketStructurePromotionDecision:
        self._require_uow()
        policy = self.get_policy(decision.policy.reference, as_of=decision.decided_at)
        if policy != decision.policy:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "decision policy graph was substituted"
            )
        candidates = self._decision_candidates(
            decision.reference,
            decision.content_hash,
            decision.authorization.reference,
        )
        if candidates:
            matches = tuple(self._decision_from_model(item) for item in candidates)
            if len(matches) == 1 and matches[0] == decision:
                return matches[0]
            raise R2MarketStructurePromotionRepositoryConflict("decision identity conflicts")
        now = self.server_now()
        if now > decision.recorded_at:
            raise R2MarketStructurePromotionRepositoryConflict(
                "decision server receipt postdates semantic recorded_at"
            )
        values = _decision_values(decision, ledger_recorded_at=now)
        try:
            with _claim_r2_promotion_insert(
                token=self._token,
                model_type=R2MarketStructurePromotionDecisionModel,
                expected_values=values,
            ):
                model = R2MarketStructurePromotionDecisionModel(**values)
                model.full_clean()
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            raise R2MarketStructurePromotionRepositoryConflict("decision append failed") from error
        return self._decision_from_model(model)

    def get_decision(
        self,
        decision_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionDecision | None:
        self._require_uow()
        require_r2_market_structure_pit_cutoff(as_of, server_now=self.server_now())
        candidates = self._decision_candidates(decision_ref, None, None)
        restored = tuple((model, self._decision_from_model(model)) for model in candidates)
        matches = tuple(
            (model, decision) for model, decision in restored if decision.reference == decision_ref
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "decision selector has multiple exact matches"
            )
        model, decision = matches[0]
        if model.ledger_recorded_at > as_of or decision.recorded_at > as_of:
            return None
        return decision

    def _append_lifecycle_event(
        self,
        event: R2MarketStructureLifecycleEvent,
    ) -> R2MarketStructureLifecycleEvent:
        self._require_uow()
        history = self.load_lifecycle_stream(event.scope_id)
        derive_r2_market_structure_active_stack((*history, event))
        candidates = self._event_candidates(
            event.authorization.reference,
            event.content_hash,
            event.scope_id,
        )
        if candidates:
            restored = tuple(self._event_from_model(item) for item in candidates)
            if len(restored) == 1 and restored[0] == event:
                return restored[0]
            raise R2MarketStructurePromotionRepositoryConflict("lifecycle identity conflicts")
        now = self.server_now()
        if now > event.recorded_at:
            raise R2MarketStructurePromotionRepositoryConflict(
                "lifecycle server receipt postdates semantic recorded_at"
            )
        values = _event_values(event, ledger_recorded_at=now)
        try:
            with _claim_r2_promotion_insert(
                token=self._token,
                model_type=R2MarketStructurePromotionLifecycleEventModel,
                expected_values=values,
            ):
                model = R2MarketStructurePromotionLifecycleEventModel(**values)
                model.full_clean()
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            raise R2MarketStructurePromotionRepositoryConflict("lifecycle append failed") from error
        return self._event_from_model(model)

    def load_lifecycle_stream(
        self,
        scope_id: str,
    ) -> tuple[R2MarketStructureLifecycleEvent, ...]:
        self._require_uow()
        stream_id = f"research:r2:market-structure:{scope_id}"
        models_found = tuple(
            R2MarketStructurePromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(models.Q(scope_id=scope_id) | models.Q(stream_id=stream_id))
            .order_by("pk")
        )
        restored = tuple(self._event_from_model(item) for item in models_found)
        ordered = tuple(sorted(restored, key=lambda item: item.sequence))
        if any(item.scope_id != scope_id or item.stream_id != stream_id for item in ordered):
            raise R2MarketStructurePromotionRepositoryCorruption(
                "lifecycle scope or stream was tampered"
            )
        try:
            derive_r2_market_structure_active_stack(ordered)
        except ValueError as error:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "lifecycle stream is forked or discontinuous"
            ) from error
        return ordered

    def get_event_by_authorization(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
    ) -> R2MarketStructureLifecycleEvent | None:
        self._require_uow()
        candidates = self._event_candidates(authorization_ref, None, None)
        restored = tuple(self._event_from_model(item) for item in candidates)
        matches = tuple(
            item for item in restored if item.authorization.reference == authorization_ref
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "lifecycle authorization selector has multiple matches"
            )
        return matches[0]

    def _policy_candidates(
        self,
        reference: R2MarketStructurePromotionRef,
        content_hash: str | None,
    ) -> tuple[R2MarketStructurePromotionPolicyModel, ...]:
        anchors = models.Q(
            policy_id=reference.stable_id,
            policy_version=reference.version,
        )
        if content_hash is not None:
            anchors |= models.Q(content_hash=content_hash)
        return tuple(
            R2MarketStructurePromotionPolicyModel._default_manager.using(self._using)
            .filter(anchors)
            .order_by("pk")
        )

    def _decision_candidates(
        self,
        reference: R2MarketStructurePromotionRef,
        content_hash: str | None,
        authorization_ref: R2MarketStructurePromotionRef | None,
    ) -> tuple[R2MarketStructurePromotionDecisionModel, ...]:
        anchors = models.Q(
            decision_id=reference.stable_id,
            decision_version=reference.version,
        )
        if content_hash is not None:
            anchors |= models.Q(content_hash=content_hash)
        if authorization_ref is not None:
            anchors |= models.Q(
                authorization_id=authorization_ref.stable_id,
                authorization_version=authorization_ref.version,
            )
        return tuple(
            R2MarketStructurePromotionDecisionModel._default_manager.using(self._using)
            .filter(anchors)
            .order_by("pk")
        )

    def _event_candidates(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
        content_hash: str | None,
        scope_id: str | None,
    ) -> tuple[R2MarketStructurePromotionLifecycleEventModel, ...]:
        anchors = models.Q(
            authorization_id=authorization_ref.stable_id,
            authorization_version=authorization_ref.version,
        )
        if content_hash is not None:
            anchors |= models.Q(content_hash=content_hash)
        if scope_id is not None:
            anchors |= models.Q(scope_id=scope_id)
        return tuple(
            R2MarketStructurePromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(anchors)
            .order_by("pk")
        )

    def _policy_from_model(
        self,
        model: R2MarketStructurePromotionPolicyModel,
    ) -> R2MarketStructurePromotionPolicy:
        try:
            policy = decode_r2_market_structure_policy(model.canonical_payload)
            values = _policy_values(
                policy,
                ledger_recorded_at=model.ledger_recorded_at,
            )
        except (R2MarketStructurePromotionCodecError, TypeError, ValueError) as error:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "policy payload is invalid"
            ) from error
        if not _matches(model, values):
            raise R2MarketStructurePromotionRepositoryCorruption(
                "policy header or receipt was tampered"
            )
        return policy

    def _decision_from_model(
        self,
        model: R2MarketStructurePromotionDecisionModel,
    ) -> R2MarketStructurePromotionDecision:
        try:
            decision = decode_r2_market_structure_decision(model.canonical_payload)
            values = _decision_values(
                decision,
                ledger_recorded_at=model.ledger_recorded_at,
            )
        except (R2MarketStructurePromotionCodecError, TypeError, ValueError) as error:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "decision payload is invalid"
            ) from error
        if not _matches(model, values):
            raise R2MarketStructurePromotionRepositoryCorruption(
                "decision header or receipt was tampered"
            )
        return decision

    def _event_from_model(
        self,
        model: R2MarketStructurePromotionLifecycleEventModel,
    ) -> R2MarketStructureLifecycleEvent:
        try:
            event = decode_r2_market_structure_lifecycle_event(model.canonical_payload)
            values = _event_values(
                event,
                ledger_recorded_at=model.ledger_recorded_at,
            )
        except (R2MarketStructurePromotionCodecError, TypeError, ValueError) as error:
            raise R2MarketStructurePromotionRepositoryCorruption(
                "lifecycle payload is invalid"
            ) from error
        if not _matches(model, values):
            raise R2MarketStructurePromotionRepositoryCorruption(
                "lifecycle header or receipt was tampered"
            )
        return event


__all__ = [
    "DjangoR2MarketStructurePromotionClock",
    "DjangoR2MarketStructurePromotionRepository",
    "R2MarketStructurePromotionRepositoryConflict",
    "R2MarketStructurePromotionRepositoryCorruption",
]
