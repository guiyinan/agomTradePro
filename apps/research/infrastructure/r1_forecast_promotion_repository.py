"""Transactional exact repository for Research R1 promotion ledgers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.research.application.r1_forecast_promotion import (
    ExactR1LifecycleAuthorizationEvidence,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionReceipt,
    R1PromotionLifecycleAction,
    R1PromotionLifecycleEventBundle,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1PromotionDecisionIdentity,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEvent,
    create_r1_forecast_promotion_decision,
    create_r1_promotion_lifecycle_event,
    create_r1_promotion_lifecycle_root,
    derive_r1_promotion_lifecycle_state,
)
from apps.research.infrastructure.r1_forecast_promotion_codec import (
    decode_r1_lifecycle_authorization_evidence,
    decode_r1_lifecycle_event_bundle,
    decode_r1_promotion_decision_bundle,
    decode_r1_promotion_policy,
    encode_r1_lifecycle_authorization_evidence,
    encode_r1_lifecycle_event_bundle,
    encode_r1_promotion_decision_bundle,
    encode_r1_promotion_policy,
)
from apps.research.infrastructure.r1_forecast_promotion_models import (
    R1ForecastPromotionDecisionBundleModel,
    R1ForecastPromotionPolicyModel,
    R1PromotionDecisionReceiptModel,
    R1PromotionLifecycleEventBundleModel,
    R1PromotionLifecycleReceiptModel,
)
from apps.research.infrastructure.r1_forecast_promotion_providers import (
    DjangoExactEquityTrialResultProvider,
    DjangoR1DecisionReceiptProvider,
    DjangoR1LifecycleAuthorizationProvider,
    DjangoR1PromotionPolicyProvider,
    ExactEquityTrialOwnerRecordProvider,
    R1LifecycleAuthorizationClaim,
    R1LifecycleAuthorizationSource,
    R1PromotionRepositoryConflict,
    R1PromotionRepositoryCorruption,
    _stable_decision_receipt_id,
    r1_lifecycle_authorization_claim_id,
)

_ACTIVE_R1_PROMOTION_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_r1_promotion_unit_of_work",
    default=None,
)


class DjangoR1ForecastPromotionRepository:
    """Persist exact owner receipts, decisions and lifecycle hash chains."""

    def __init__(
        self,
        *,
        equity_trial_provider: ExactEquityTrialOwnerRecordProvider,
        using: str = "default",
    ) -> None:
        self._equity_trial_provider = equity_trial_provider
        self._using = using
        self._unit_of_work_token = object()
        if equity_trial_provider.unit_of_work_key != self.unit_of_work_key:
            raise ValueError("Equity and Research repositories must share one database")

    @property
    def unit_of_work_key(self) -> str:
        """Identify the Django database transaction used by this repository."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap stable receipt claim and child bundle append in one transaction."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            reset_token = _ACTIVE_R1_PROMOTION_UNIT_OF_WORK.set(self._unit_of_work_token)
            try:
                yield
            finally:
                _ACTIVE_R1_PROMOTION_UNIT_OF_WORK.reset(reset_token)

    def require_active_unit_of_work(self) -> None:
        """Fail closed unless this repository owns the active DB transaction."""

        connection = transaction.get_connection(self._using)
        if (
            _ACTIVE_R1_PROMOTION_UNIT_OF_WORK.get() is not self._unit_of_work_token
            or not connection.in_atomic_block
        ):
            raise R1PromotionRepositoryConflict(
                "R1 promotion write requires its repository unit of work"
            )

    def append_policy(self, policy: R1ForecastPromotionPolicy) -> R1ForecastPromotionPolicy:
        """Append one exact policy or return its immutable replay."""

        existing = (
            R1ForecastPromotionPolicyModel._default_manager.using(self._using)
            .filter(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
            )
            .first()
        )
        if existing is not None:
            restored = self._policy_from_model(existing)
            if restored != policy:
                raise R1PromotionRepositoryConflict("promotion policy identity conflict")
            return restored
        try:
            with transaction.atomic(using=self._using):
                model = R1ForecastPromotionPolicyModel._default_manager.using(self._using).create(
                    **_policy_model_values(policy)
                )
        except IntegrityError as error:
            winner = (
                R1ForecastPromotionPolicyModel._default_manager.using(self._using)
                .filter(
                    policy_id=policy.policy_id,
                    policy_version=policy.policy_version,
                )
                .first()
            )
            if winner is None:
                raise R1PromotionRepositoryConflict("promotion policy append conflict") from error
            restored = self._policy_from_model(winner)
            if restored != policy:
                raise R1PromotionRepositoryConflict("promotion policy identity conflict") from error
            return restored
        restored = self._policy_from_model(model)
        if restored != policy:
            raise R1PromotionRepositoryCorruption("promotion policy append was not exact")
        return restored

    def get_exact_policy(
        self,
        policy_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionPolicy | None:
        """Return the exact policy only after its owner receipt time."""

        model = (
            R1ForecastPromotionPolicyModel._default_manager.using(self._using)
            .filter(
                policy_id=policy_ref.stable_id,
                policy_version=policy_ref.version,
                recorded_at__lte=as_of,
            )
            .first()
        )
        return self._policy_from_model(model) if model is not None else None

    def claim_decision_receipt(
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
        """Atomically claim or replay one stable Research decision receipt."""

        self.require_active_unit_of_work()

        existing = (
            R1PromotionDecisionReceiptModel._default_manager.using(self._using)
            .filter(
                decision_id=decision_ref.stable_id,
                decision_version=decision_ref.version,
            )
            .select_related("policy", "equity_result")
            .first()
        )
        requested = (
            policy_ref,
            policy_content_hash,
            result_ref,
            result_content_hash,
            equity_result_recorded_at,
            equity_result_record_hash,
            decided_at,
            decision_valid_until,
        )
        if existing is not None:
            return self._match_decision_receipt(existing, requested)
        policy_model = self._get_policy_model(policy_ref, policy_content_hash)
        result_record_key = self._get_equity_result_record_key(
            result_ref,
            result_content_hash,
            equity_result_recorded_at,
        )
        recorded_at = timezone.now()
        receipt = R1PromotionDecisionReceipt.create(
            receipt_id=_stable_decision_receipt_id(
                decision_ref=decision_ref,
                policy_ref=policy_ref,
                result_ref=result_ref,
                scope_id=policy_model.scope_id,
            ),
            receipt_version="receipt.v1",
            decision_ref=decision_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            result_ref=result_ref,
            result_content_hash=result_content_hash,
            equity_result_recorded_at=equity_result_recorded_at,
            equity_result_record_hash=equity_result_record_hash,
            decided_at=decided_at,
            recorded_at=recorded_at,
            decision_valid_until=decision_valid_until,
        )
        try:
            with transaction.atomic(using=self._using):
                model = R1PromotionDecisionReceiptModel._default_manager.using(self._using).create(
                    policy=policy_model,
                    equity_result_id=result_record_key,
                    **_decision_receipt_model_values(receipt),
                )
        except IntegrityError as error:
            winner = (
                R1PromotionDecisionReceiptModel._default_manager.using(self._using)
                .filter(
                    decision_id=decision_ref.stable_id,
                    decision_version=decision_ref.version,
                )
                .select_related("policy", "equity_result")
                .first()
            )
            if winner is None:
                raise R1PromotionRepositoryConflict("decision receipt claim conflict") from error
            return self._match_decision_receipt(winner, requested)
        return self._decision_receipt_from_model(model)

    def append_decision_bundle(
        self,
        bundle: R1ForecastPromotionDecisionBundle,
    ) -> R1ForecastPromotionDecisionBundle:
        """Append one factory-rebuilt decision and its preclaimed receipt."""

        self.require_active_unit_of_work()

        decision = bundle.decision
        existing = (
            R1ForecastPromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                decision_id=decision.decision_id,
                decision_version=decision.decision_version,
            )
            .select_related("receipt", "policy", "equity_result")
            .first()
        )
        if existing is not None:
            restored = self._decision_bundle_from_model(existing)
            if restored != bundle:
                raise R1PromotionRepositoryConflict("promotion decision identity conflict")
            return restored
        receipt_model = (
            R1PromotionDecisionReceiptModel._default_manager.using(self._using)
            .select_related("policy", "equity_result")
            .filter(
                decision_id=decision.decision_id,
                decision_version=decision.decision_version,
            )
            .first()
        )
        if (
            receipt_model is None
            or self._decision_receipt_from_model(receipt_model) != bundle.receipt
        ):
            raise R1PromotionRepositoryCorruption("exact decision receipt claim is unavailable")
        self._rebuild_decision_bundle(bundle)
        try:
            with transaction.atomic(using=self._using):
                model = R1ForecastPromotionDecisionBundleModel._default_manager.using(
                    self._using
                ).create(
                    receipt=receipt_model,
                    policy=receipt_model.policy,
                    equity_result=receipt_model.equity_result,
                    **_decision_bundle_model_values(bundle),
                )
        except IntegrityError as error:
            winner = (
                R1ForecastPromotionDecisionBundleModel._default_manager.using(self._using)
                .filter(
                    decision_id=decision.decision_id,
                    decision_version=decision.decision_version,
                )
                .select_related("receipt", "policy", "equity_result")
                .first()
            )
            if winner is None:
                raise R1PromotionRepositoryConflict("promotion decision append conflict") from error
            restored = self._decision_bundle_from_model(winner)
            if restored != bundle:
                raise R1PromotionRepositoryConflict(
                    "promotion decision identity conflict"
                ) from error
            return restored
        return self._decision_bundle_from_model(model)

    def get_decision_bundle(
        self,
        decision_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundle | None:
        """Return an exact decision bundle only after its Research receipt."""

        model = (
            R1ForecastPromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                decision_id=decision_ref.stable_id,
                decision_version=decision_ref.version,
                recorded_at__lte=as_of,
            )
            .select_related("receipt", "policy", "equity_result")
            .first()
        )
        return self._decision_bundle_from_model(model) if model is not None else None

    def claim_lifecycle_authorization(
        self,
        *,
        event_ref: R1PromotionVersionRef,
        authorization: R1PromotionLifecycleAuthorization,
        reason_codes: tuple[str, ...],
    ) -> ExactR1LifecycleAuthorizationEvidence:
        """Atomically claim stable server clocks for owner authorization."""

        self.require_active_unit_of_work()

        existing = (
            R1PromotionLifecycleReceiptModel._default_manager.using(self._using)
            .filter(
                event_id=event_ref.stable_id,
                event_version=event_ref.version,
            )
            .select_related("decision", "rollback_target")
            .first()
        )
        if existing is not None:
            evidence = self._lifecycle_evidence_from_model(existing)
            if (
                evidence.authorization != authorization
                or evidence.reason_codes != reason_codes
                or evidence.event_ref != event_ref
            ):
                raise R1PromotionRepositoryConflict("lifecycle receipt identity conflict")
            return evidence
        expected_authorization_id = r1_lifecycle_authorization_claim_id(
            event_ref=event_ref,
            authorization=authorization,
        )
        if (
            authorization.authorization_id != expected_authorization_id
            or authorization.authorization_version != "authorization.v1"
        ):
            raise R1PromotionRepositoryConflict(
                "lifecycle authorization claim identity is not canonical"
            )
        now = timezone.now()
        decision_model = self._get_decision_model_for_identity(
            authorization.decision,
            as_of=now,
        )
        target_model = (
            self._get_decision_model_for_identity(authorization.rollback_target, as_of=now)
            if authorization.rollback_target is not None
            else None
        )
        evidence = ExactR1LifecycleAuthorizationEvidence.create(
            event_ref=event_ref,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=now,
            event_recorded_at=now,
        )
        try:
            with transaction.atomic(using=self._using):
                model = R1PromotionLifecycleReceiptModel._default_manager.using(self._using).create(
                    decision=decision_model,
                    rollback_target=target_model,
                    **_lifecycle_receipt_model_values(evidence),
                )
        except IntegrityError as error:
            winner = (
                R1PromotionLifecycleReceiptModel._default_manager.using(self._using)
                .filter(
                    event_id=event_ref.stable_id,
                    event_version=event_ref.version,
                )
                .select_related("decision", "rollback_target")
                .first()
            )
            if winner is None:
                raise R1PromotionRepositoryConflict("lifecycle receipt claim conflict") from error
            restored = self._lifecycle_evidence_from_model(winner)
            if restored.authorization != authorization or restored.reason_codes != reason_codes:
                raise R1PromotionRepositoryConflict(
                    "lifecycle receipt identity conflict"
                ) from error
            return restored
        return self._lifecycle_evidence_from_model(model)

    def get_exact_lifecycle_authorization(
        self,
        *,
        authorization_ref: R1PromotionVersionRef,
        event_ref: R1PromotionVersionRef,
        scope_ref: R1PromotionScopeRef,
        action: R1PromotionLifecycleAction,
        decision_ref: R1PromotionVersionRef,
        rollback_target_ref: R1PromotionVersionRef | None,
    ) -> ExactR1LifecycleAuthorizationEvidence | None:
        """Return a claimed winner only when every requested identity matches."""

        model = (
            R1PromotionLifecycleReceiptModel._default_manager.using(self._using)
            .filter(
                event_id=event_ref.stable_id,
                event_version=event_ref.version,
            )
            .select_related("decision", "rollback_target")
            .first()
        )
        if model is None:
            return None
        evidence = self._lifecycle_evidence_from_model(model)
        authorization = evidence.authorization
        target = authorization.rollback_target
        expected_target = (
            R1PromotionVersionRef(target.decision_id, target.decision_version)
            if target is not None
            else None
        )
        if (
            (authorization.authorization_id, authorization.authorization_version)
            != (authorization_ref.stable_id, authorization_ref.version)
            or authorization.promotion_scope.scope_id != scope_ref.scope_id
            or authorization.event_type is not action.event_type
            or (authorization.decision.decision_id, authorization.decision.decision_version)
            != (decision_ref.stable_id, decision_ref.version)
            or expected_target != rollback_target_ref
        ):
            return None
        return evidence

    def append_lifecycle_event_bundle(
        self,
        bundle: R1PromotionLifecycleEventBundle,
    ) -> R1PromotionLifecycleEventBundle:
        """Append one exact tail event or replay its immutable identity."""

        self.require_active_unit_of_work()

        event = bundle.event
        existing = (
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(
                event_id=event.event_id,
                event_version=event.event_version,
            )
            .first()
        )
        if existing is not None:
            restored = self.get_lifecycle_event_bundle(
                R1PromotionVersionRef(event.event_id, event.event_version)
            )
            if restored != bundle:
                raise R1PromotionRepositoryConflict("lifecycle event identity conflict")
            return restored
        receipt_model = (
            R1PromotionLifecycleReceiptModel._default_manager.using(self._using)
            .filter(
                event_id=event.event_id,
                event_version=event.event_version,
            )
            .select_related("decision", "rollback_target")
            .first()
        )
        if (
            receipt_model is None
            or self._lifecycle_evidence_from_model(receipt_model) != bundle.evidence
        ):
            raise R1PromotionRepositoryCorruption("exact lifecycle receipt is unavailable")
        prefix_rows = tuple(
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(stream_id=event.stream_id)
            .order_by("sequence")
        )
        prefix = self._restore_lifecycle_rows(prefix_rows)
        raced_winner = next(
            (
                item
                for item in prefix
                if (item.event.event_id, item.event.event_version)
                == (event.event_id, event.event_version)
            ),
            None,
        )
        if raced_winner is not None:
            if raced_winner != bundle:
                raise R1PromotionRepositoryConflict("lifecycle event identity conflict")
            return raced_winner
        rebuilt = self._rebuild_lifecycle_bundle(
            bundle,
            tuple(item.event for item in prefix),
        )
        if rebuilt != bundle:
            raise R1PromotionRepositoryCorruption("lifecycle event factory rebuild mismatch")
        previous_model = prefix_rows[-1] if prefix_rows else None
        try:
            with transaction.atomic(using=self._using):
                model = R1PromotionLifecycleEventBundleModel._default_manager.using(
                    self._using
                ).create(
                    receipt=receipt_model,
                    decision=receipt_model.decision,
                    rollback_target=receipt_model.rollback_target,
                    previous_event=previous_model,
                    **_lifecycle_event_model_values(bundle),
                )
        except IntegrityError as error:
            winner = (
                R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
                .filter(
                    event_id=event.event_id,
                    event_version=event.event_version,
                )
                .first()
            )
            if winner is None:
                raise R1PromotionRepositoryConflict("lifecycle event append conflict") from error
            restored = self.get_lifecycle_event_bundle(
                R1PromotionVersionRef(event.event_id, event.event_version)
            )
            if restored != bundle:
                raise R1PromotionRepositoryConflict("lifecycle event identity conflict") from error
            return restored
        restored = self.get_lifecycle_event_bundle(
            R1PromotionVersionRef(model.event_id, model.event_version)
        )
        if restored is None:
            raise R1PromotionRepositoryCorruption("appended lifecycle event disappeared")
        return restored

    def get_lifecycle_event_bundle(
        self,
        event_ref: R1PromotionVersionRef,
    ) -> R1PromotionLifecycleEventBundle | None:
        """Restore an event only through its complete canonical stream."""

        row = (
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(
                event_id=event_ref.stable_id,
                event_version=event_ref.version,
            )
            .first()
        )
        if row is None:
            return None
        rows = tuple(
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(stream_id=row.stream_id)
            .order_by("sequence")
        )
        bundles = self._restore_lifecycle_rows(rows)
        return next(
            (
                item
                for item in bundles
                if (item.event.event_id, item.event.event_version)
                == (event_ref.stable_id, event_ref.version)
            ),
            None,
        )

    def load_lifecycle_history(
        self,
        scope_ref: R1PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R1PromotionLifecycleEvent, ...]:
        """Restore the exact recorded prefix visible at one knowledge time."""

        rows = tuple(
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(
                scope_id=scope_ref.scope_id,
                recorded_at__lte=as_of,
            )
            .order_by("sequence")
        )
        bundles = self._restore_lifecycle_rows(rows, evaluated_at=as_of)
        return tuple(item.event for item in bundles)

    def load_lifecycle_stream(
        self,
        scope_ref: R1PromotionScopeRef,
    ) -> tuple[R1PromotionLifecycleEvent, ...]:
        """Restore the complete stream, including evidence recorded later."""

        rows = tuple(
            R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
            .filter(scope_id=scope_ref.scope_id)
            .order_by("sequence")
        )
        bundles = self._restore_lifecycle_rows(rows)
        return tuple(item.event for item in bundles)

    def _policy_from_model(
        self,
        model: R1ForecastPromotionPolicyModel,
    ) -> R1ForecastPromotionPolicy:
        policy = decode_r1_promotion_policy(model.canonical_payload)
        if _policy_model_values(policy) != _model_value_subset(model, _policy_model_values(policy)):
            raise R1PromotionRepositoryCorruption("promotion policy header/payload mismatch")
        return policy

    def _decision_receipt_from_model(
        self,
        model: R1PromotionDecisionReceiptModel,
    ) -> R1PromotionDecisionReceipt:
        policy = self._policy_from_model(model.policy)
        result_model = model.equity_result
        receipt = R1PromotionDecisionReceipt(
            receipt_id=model.receipt_id,
            receipt_version=model.receipt_version,
            decision_ref=R1PromotionVersionRef(model.decision_id, model.decision_version),
            policy_ref=R1PromotionVersionRef(policy.policy_id, policy.policy_version),
            policy_content_hash=model.policy_content_hash,
            result_ref=R1PromotionVersionRef(result_model.result_id, result_model.result_version),
            result_content_hash=model.result_content_hash,
            equity_result_recorded_at=model.equity_result_recorded_at,
            equity_result_record_hash=model.equity_result_record_hash,
            owner=model.owner,
            capability=model.capability,
            purpose=model.purpose,
            decided_at=model.decided_at,
            recorded_at=model.recorded_at,
            decision_valid_until=model.decision_valid_until,
            content_hash=model.content_hash,
        )
        if (
            receipt.policy_content_hash != policy.content_hash
            or receipt.result_content_hash != result_model.content_hash
            or receipt.equity_result_recorded_at != result_model.recorded_at
        ):
            raise R1PromotionRepositoryCorruption("decision receipt foreign-key header mismatch")
        expected_receipt_id = _stable_decision_receipt_id(
            decision_ref=receipt.decision_ref,
            policy_ref=receipt.policy_ref,
            result_ref=receipt.result_ref,
            scope_id=policy.promotion_scope.scope_id,
        )
        if receipt.receipt_id != expected_receipt_id or receipt.receipt_version != "receipt.v1":
            raise R1PromotionRepositoryCorruption("decision receipt claim identity is invalid")
        return receipt

    def _decision_bundle_from_model(
        self,
        model: R1ForecastPromotionDecisionBundleModel,
    ) -> R1ForecastPromotionDecisionBundle:
        bundle = decode_r1_promotion_decision_bundle(model.canonical_payload)
        receipt = self._decision_receipt_from_model(model.receipt)
        if bundle.receipt != receipt:
            raise R1PromotionRepositoryCorruption("decision bundle receipt payload mismatch")
        values = _decision_bundle_model_values(bundle)
        if values != _model_value_subset(model, values):
            raise R1PromotionRepositoryCorruption("decision bundle header/payload mismatch")
        if (
            model.policy_id != model.receipt.policy_id
            or model.equity_result_id != model.receipt.equity_result_id
        ):
            raise R1PromotionRepositoryCorruption("decision bundle foreign keys were substituted")
        return self._rebuild_decision_bundle(bundle)

    def _rebuild_decision_bundle(
        self,
        bundle: R1ForecastPromotionDecisionBundle,
    ) -> R1ForecastPromotionDecisionBundle:
        decision = bundle.decision
        policy = self.get_exact_policy(
            R1PromotionVersionRef(decision.policy.policy_id, decision.policy.policy_version),
            as_of=decision.decided_at,
        )
        result_evidence = self._equity_trial_provider.get_exact(
            R1PromotionVersionRef(decision.trial.result_id, decision.trial.result_version),
            as_of=decision.decided_at,
        )
        if policy is None or result_evidence is None:
            raise R1PromotionRepositoryCorruption("exact decision upstream evidence is unavailable")
        if (
            result_evidence.recorded_at != bundle.receipt.equity_result_recorded_at
            or result_evidence.record_hash != bundle.receipt.equity_result_record_hash
        ):
            raise R1PromotionRepositoryCorruption("Equity owner receipt was substituted")
        rebuilt_decision = create_r1_forecast_promotion_decision(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            policy=policy,
            result=result_evidence.result,
            as_of=decision.decided_at,
            recorded_at=decision.recorded_at,
        )
        rebuilt = R1ForecastPromotionDecisionBundle.create(
            decision=rebuilt_decision,
            receipt=bundle.receipt,
        )
        if rebuilt != bundle:
            raise R1PromotionRepositoryCorruption("decision factory rebuild mismatch")
        return rebuilt

    def _lifecycle_evidence_from_model(
        self,
        model: R1PromotionLifecycleReceiptModel,
    ) -> ExactR1LifecycleAuthorizationEvidence:
        evidence = decode_r1_lifecycle_authorization_evidence(model.canonical_payload)
        values = _lifecycle_receipt_model_values(evidence)
        if values != _model_value_subset(model, values):
            raise R1PromotionRepositoryCorruption("lifecycle receipt header/payload mismatch")
        decision = self._decision_bundle_from_model(model.decision)
        if (
            R1PromotionDecisionIdentity.from_decision(decision.decision)
            != evidence.authorization.decision
        ):
            raise R1PromotionRepositoryCorruption("lifecycle receipt decision FK mismatch")
        if model.rollback_target is None:
            target_identity = None
        else:
            target = self._decision_bundle_from_model(model.rollback_target)
            target_identity = R1PromotionDecisionIdentity.from_decision(target.decision)
        if target_identity != evidence.authorization.rollback_target:
            raise R1PromotionRepositoryCorruption("lifecycle receipt rollback FK mismatch")
        expected_authorization_id = r1_lifecycle_authorization_claim_id(
            event_ref=evidence.event_ref,
            authorization=evidence.authorization,
        )
        if (
            evidence.authorization.authorization_id != expected_authorization_id
            or evidence.authorization.authorization_version != "authorization.v1"
        ):
            raise R1PromotionRepositoryCorruption(
                "lifecycle authorization claim identity is invalid"
            )
        return evidence

    def _restore_lifecycle_rows(
        self,
        rows: tuple[R1PromotionLifecycleEventBundleModel, ...],
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[R1PromotionLifecycleEventBundle, ...]:
        restored: list[R1PromotionLifecycleEventBundle] = []
        events: list[R1PromotionLifecycleEvent] = []
        for index, row in enumerate(rows):
            row = (
                R1PromotionLifecycleEventBundleModel._default_manager.using(self._using)
                .select_related("receipt", "decision", "rollback_target", "previous_event")
                .get(pk=row.pk)
            )
            decoded = decode_r1_lifecycle_event_bundle(row.canonical_payload)
            evidence = self._lifecycle_evidence_from_model(row.receipt)
            if decoded.evidence != evidence:
                raise R1PromotionRepositoryCorruption("lifecycle bundle receipt mismatch")
            if (
                row.decision_id != row.receipt.decision_id
                or row.rollback_target_id != row.receipt.rollback_target_id
            ):
                raise R1PromotionRepositoryCorruption(
                    "lifecycle event decision foreign keys were substituted"
                )
            if (
                decoded.event.decision != evidence.authorization.decision
                or decoded.event.rollback_target != evidence.authorization.rollback_target
            ):
                raise R1PromotionRepositoryCorruption(
                    "lifecycle event identities do not match its receipt"
                )
            values = _lifecycle_event_model_values(decoded)
            if values != _model_value_subset(row, values):
                raise R1PromotionRepositoryCorruption("lifecycle event header/payload mismatch")
            expected_previous_id = rows[index - 1].pk if index else None
            if row.previous_event_id != expected_previous_id:
                raise R1PromotionRepositoryCorruption("lifecycle previous-event FK mismatch")
            rebuilt = self._rebuild_lifecycle_bundle(decoded, tuple(events))
            restored.append(rebuilt)
            events.append(rebuilt.event)
        if events:
            derive_r1_promotion_lifecycle_state(
                tuple(events),
                evaluated_at=evaluated_at or max(item.recorded_at for item in events),
            )
        return tuple(restored)

    def _rebuild_lifecycle_bundle(
        self,
        bundle: R1PromotionLifecycleEventBundle,
        prefix: tuple[R1PromotionLifecycleEvent, ...],
    ) -> R1PromotionLifecycleEventBundle:
        event = bundle.event
        decision_model = self._get_decision_model_for_identity(
            event.decision,
            as_of=event.occurred_at,
        )
        decision = self._decision_bundle_from_model(decision_model).decision
        rollback_target: R1ForecastPromotionDecision | None = None
        if event.rollback_target is not None:
            target_model = self._get_decision_model_for_identity(
                event.rollback_target,
                as_of=event.occurred_at,
            )
            rollback_target = self._decision_bundle_from_model(target_model).decision
        if not prefix:
            rebuilt_event = create_r1_promotion_lifecycle_root(
                event_id=event.event_id,
                event_version=event.event_version,
                decision=decision,
                authorization=bundle.evidence.authorization,
                reason_codes=bundle.evidence.reason_codes,
                occurred_at=bundle.evidence.occurred_at,
                recorded_at=bundle.evidence.event_recorded_at,
            )
        else:
            rebuilt_event = create_r1_promotion_lifecycle_event(
                event_id=event.event_id,
                event_version=event.event_version,
                previous_events=prefix,
                event_type=event.event_type,
                decision=decision,
                rollback_target=rollback_target,
                authorization=bundle.evidence.authorization,
                reason_codes=bundle.evidence.reason_codes,
                occurred_at=bundle.evidence.occurred_at,
                recorded_at=bundle.evidence.event_recorded_at,
            )
        rebuilt = R1PromotionLifecycleEventBundle.create(
            event=rebuilt_event,
            evidence=bundle.evidence,
        )
        if rebuilt != bundle:
            raise R1PromotionRepositoryCorruption("lifecycle factory rebuild mismatch")
        return rebuilt

    def _get_policy_model(
        self,
        policy_ref: R1PromotionVersionRef,
        content_hash: str,
    ) -> R1ForecastPromotionPolicyModel:
        model = (
            R1ForecastPromotionPolicyModel._default_manager.using(self._using)
            .filter(
                policy_id=policy_ref.stable_id,
                policy_version=policy_ref.version,
                content_hash=content_hash,
            )
            .first()
        )
        if model is None:
            raise R1PromotionRepositoryCorruption("exact policy row is unavailable")
        self._policy_from_model(model)
        return model

    def _get_equity_result_record_key(
        self,
        result_ref: R1PromotionVersionRef,
        content_hash: str,
        recorded_at: datetime,
    ) -> int:
        record_key = self._equity_trial_provider.get_owner_record_key(
            result_ref,
            content_hash=content_hash,
            recorded_at=recorded_at,
        )
        if record_key is None:
            raise R1PromotionRepositoryCorruption("exact Equity result owner row is unavailable")
        return record_key

    def _get_decision_model_for_identity(
        self,
        identity: R1PromotionDecisionIdentity,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundleModel:
        model = (
            R1ForecastPromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                decision_id=identity.decision_id,
                decision_version=identity.decision_version,
                decision_content_hash=identity.content_hash,
                recorded_at__lte=as_of,
            )
            .first()
        )
        if model is None:
            raise R1PromotionRepositoryCorruption("exact lifecycle decision is unavailable")
        restored = self._decision_bundle_from_model(model)
        if R1PromotionDecisionIdentity.from_decision(restored.decision) != identity:
            raise R1PromotionRepositoryCorruption("lifecycle decision identity mismatch")
        return model

    def _match_decision_receipt(
        self,
        model: R1PromotionDecisionReceiptModel,
        requested: tuple[
            R1PromotionVersionRef,
            str,
            R1PromotionVersionRef,
            str,
            datetime,
            str,
            datetime,
            datetime,
        ],
    ) -> R1PromotionDecisionReceipt:
        receipt = self._decision_receipt_from_model(model)
        actual = (
            receipt.policy_ref,
            receipt.policy_content_hash,
            receipt.result_ref,
            receipt.result_content_hash,
            receipt.equity_result_recorded_at,
            receipt.equity_result_record_hash,
            receipt.decided_at,
            receipt.decision_valid_until,
        )
        if actual != requested:
            raise R1PromotionRepositoryConflict("decision receipt identity conflict")
        return receipt


def _policy_model_values(policy: R1ForecastPromotionPolicy) -> dict[str, object]:
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


def _decision_receipt_model_values(
    receipt: R1PromotionDecisionReceipt,
) -> dict[str, object]:
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


def _decision_bundle_model_values(
    bundle: R1ForecastPromotionDecisionBundle,
) -> dict[str, object]:
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


def _lifecycle_receipt_model_values(
    evidence: ExactR1LifecycleAuthorizationEvidence,
) -> dict[str, object]:
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


def _lifecycle_event_model_values(
    bundle: R1PromotionLifecycleEventBundle,
) -> dict[str, object]:
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


def _model_value_subset(model: object, values: dict[str, object]) -> dict[str, object]:
    return {name: getattr(model, name) for name in values}


__all__ = [
    "DjangoExactEquityTrialResultProvider",
    "DjangoR1DecisionReceiptProvider",
    "DjangoR1ForecastPromotionRepository",
    "DjangoR1LifecycleAuthorizationProvider",
    "DjangoR1PromotionPolicyProvider",
    "R1PromotionRepositoryConflict",
    "R1PromotionRepositoryCorruption",
    "R1LifecycleAuthorizationClaim",
    "R1LifecycleAuthorizationSource",
    "ExactEquityTrialOwnerRecordProvider",
    "r1_lifecycle_authorization_claim_id",
]
