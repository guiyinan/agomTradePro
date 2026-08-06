"""Transactional exact repository for Research R4 promotion ledgers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
    R4RollingResearchOwnerRecord,
)
from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleAction,
    R4PromotionLifecycleEventBundle,
    R4PromotionScopeRef,
)
from apps.research.application.r4_promotion_projection import (
    project_r4_portfolio_owner_record,
    project_r4_promotion_r3_attestation,
)
from apps.research.application.r4_promotion_registration import (
    R4PromotionClock,
    R4PromotionPolicyRegistrationDraft,
)
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    create_r4_promotion_decision,
)
from apps.research.domain.r4_promotion_evidence import R4PromotionR3AttestationEvidence
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    create_r4_promotion_lifecycle_event,
    create_r4_promotion_lifecycle_root,
    derive_r4_promotion_lifecycle_state,
)
from apps.research.domain.r4_promotion_record_seal import R4PromotionPortfolioRecordSeal
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy
from apps.research.domain.r4_promotion_trial import R4PromotionTrialSeal
from apps.research.infrastructure.r4_promotion_codec import (
    decode_r4_lifecycle_authorization_evidence,
    decode_r4_lifecycle_event_bundle,
    decode_r4_promotion_decision_bundle,
    decode_r4_promotion_decision_receipt,
    decode_r4_promotion_policy,
)
from apps.research.infrastructure.r4_promotion_model_values import (
    _decision_bundle_model_values,
    _decision_receipt_model_values,
    _lifecycle_event_model_values,
    _lifecycle_receipt_model_values,
    _model_value_subset,
    _policy_model_values,
)
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionLifecycleAuthorizationReceiptModel,
    R4PromotionLifecycleEventModel,
    R4PromotionPolicyModel,
    _activate_r4_promotion_unit_of_work,
    _claim_r4_promotion_insert,
    _r4_promotion_unit_of_work_is_active,
)
from apps.research.infrastructure.r4_promotion_providers import (
    R4PromotionRepositoryConflict,
    R4PromotionRepositoryCorruption,
    r4_lifecycle_authorization_claim_id,
    stable_r4_decision_receipt_id,
)


class DjangoR4PromotionClock:
    """Production authoritative clock for Research-owned receipts."""

    def now(self) -> datetime:
        """Return the Django timezone-aware server time."""

        return timezone.now()


class DjangoR4PromotionRepository:
    """Persist exact policy, decision and lifecycle evidence in one UoW."""

    def __init__(
        self,
        *,
        portfolio_query: R4RollingResearchExactQuery,
        current_r3_provider: ExactR3PromotionProvider,
        clock: R4PromotionClock | None = None,
        using: str = "default",
    ) -> None:
        self._portfolio_query = portfolio_query
        self._current_r3_provider = current_r3_provider
        self._clock = clock or DjangoR4PromotionClock()
        self._using = using
        self._unit_of_work_token = object()
        if portfolio_query.unit_of_work_key != self.unit_of_work_key:
            raise ValueError("Portfolio and Research R4 repositories must share one database")

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django database transaction boundary."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Wrap every owner read, receipt claim and child append atomically."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            with _activate_r4_promotion_unit_of_work(self._unit_of_work_token):
                yield

    def require_active_unit_of_work(self) -> None:
        """Fail closed unless this repository owns the active transaction."""

        connection = transaction.get_connection(self._using)
        if (
            not _r4_promotion_unit_of_work_is_active(self._unit_of_work_token)
            or not connection.in_atomic_block
        ):
            raise R4PromotionRepositoryConflict(
                "R4 promotion operation requires its repository unit of work"
            )

    def append_policy(
        self,
        draft: R4PromotionPolicyRegistrationDraft,
    ) -> R4PromotionPolicy:
        """Claim the server receipt and append or replay one policy draft."""

        with self.atomic():
            existing = self._get_policy_by_identity(draft.policy_id, draft.policy_version)
            if existing is not None:
                restored = self._policy_from_model(existing)
                if R4PromotionPolicyRegistrationDraft.from_policy(restored) != draft:
                    raise R4PromotionRepositoryConflict("R4 policy identity conflict")
                return restored
            policy = draft.materialize(recorded_at=self._clock.now())
            values = _policy_model_values(policy)
            try:
                with transaction.atomic(using=self._using):
                    with _claim_r4_promotion_insert(
                        token=self._unit_of_work_token,
                        model_type=R4PromotionPolicyModel,
                        expected_values=values,
                    ):
                        model = R4PromotionPolicyModel._default_manager.using(self._using).create(
                            **values
                        )
            except IntegrityError as error:
                winner = self._get_policy_collision(policy)
                if winner is None:
                    raise R4PromotionRepositoryConflict("R4 policy append conflict") from error
                restored = self._policy_from_model(winner)
                if R4PromotionPolicyRegistrationDraft.from_policy(restored) != draft:
                    raise R4PromotionRepositoryConflict("R4 policy identity conflict") from error
                return restored
            restored = self._policy_from_model(model)
            if restored != policy:
                raise R4PromotionRepositoryCorruption("R4 policy append was not exact")
            return restored

    def get_exact_policy(
        self,
        policy_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionPolicy | None:
        """Return one exact policy only inside the repository UoW."""

        self.require_active_unit_of_work()
        model = (
            R4PromotionPolicyModel._default_manager.using(self._using)
            .filter(
                policy_id=policy_ref.stable_id,
                policy_version=policy_ref.version,
                recorded_at__lte=as_of,
            )
            .first()
        )
        if model is None:
            return None
        policy = self._policy_from_model(model)
        return policy if policy.is_active_at(as_of) else None

    def claim_decision_receipt(
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
        """Claim or replay one server-clocked exact Research decision receipt."""

        self.require_active_unit_of_work()
        policy_model = self._get_policy_model(policy_ref, policy_content_hash)
        policy = self._policy_from_model(policy_model)
        if not policy.is_active_at(decided_at):
            return None
        owner_record, record, current_r3 = self._read_portfolio_evidence(
            record_id=portfolio_record_id,
            record_hash=portfolio_record_hash,
            as_of=decided_at,
            require_active=True,
        )
        if (
            owner_record.owner_record_key != portfolio_owner_record_key
            or record.recorded_at != portfolio_recorded_at
            or current_r3.content_hash != current_r3_content_hash
        ):
            raise R4PromotionRepositoryCorruption("Portfolio or current R3 receipt was substituted")
        receipt_id = stable_r4_decision_receipt_id(
            decision_ref=decision_ref,
            trial_ref=trial_ref,
            policy_ref=policy_ref,
            portfolio_record_id=portfolio_record_id,
            scope_id=policy.scope.scope_id,
        )
        requested = (
            trial_ref,
            policy_ref,
            policy_content_hash,
            portfolio_record_id,
            portfolio_record_hash,
            portfolio_owner_record_key,
            portfolio_recorded_at,
            current_r3_content_hash,
            decided_at,
            decision_valid_until,
        )
        existing = self._get_receipt_by_decision(decision_ref)
        if existing is not None:
            return self._match_decision_receipt(existing, requested)
        receipt = R4PromotionDecisionReceipt.create(
            receipt_id=receipt_id,
            receipt_version="receipt.v1",
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
            recorded_at=self._clock.now(),
            decision_valid_until=decision_valid_until,
        )
        values = _decision_receipt_model_values(receipt)
        claim_values = {**values, "policy_id": policy_model.pk}
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R4PromotionDecisionReceiptModel,
                    expected_values=claim_values,
                ):
                    model = R4PromotionDecisionReceiptModel._default_manager.using(
                        self._using
                    ).create(policy=policy_model, **values)
        except IntegrityError as error:
            winner = self._get_decision_receipt_collision(receipt)
            if winner is None:
                raise R4PromotionRepositoryConflict("R4 decision receipt conflict") from error
            return self._match_decision_receipt(winner, requested)
        restored = self._decision_receipt_from_model(model)
        if restored != receipt:
            raise R4PromotionRepositoryCorruption("R4 decision receipt append was not exact")
        return restored

    def append_decision_bundle(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundle:
        """Append one factory-rebuilt decision and its preclaimed receipt."""

        self.require_active_unit_of_work()
        collision = self._get_decision_bundle_collision(bundle)
        if collision is not None:
            restored = self._decision_bundle_from_model(collision)
            if restored != bundle:
                raise R4PromotionRepositoryConflict("R4 decision identity conflict")
            return restored
        decision = bundle.decision
        receipt_model = self._get_receipt_by_decision(
            R4PromotionVersionRef(decision.decision_id, decision.decision_version)
        )
        if (
            receipt_model is None
            or self._decision_receipt_from_model(receipt_model) != bundle.receipt
        ):
            raise R4PromotionRepositoryCorruption("exact R4 decision receipt is unavailable")
        policy_model = receipt_model.policy
        rebuilt = self._rebuild_decision_bundle(bundle)
        if rebuilt != bundle:
            raise R4PromotionRepositoryCorruption("R4 decision factory rebuild mismatch")
        values = _decision_bundle_model_values(bundle)
        claim_values = {
            **values,
            "receipt_id": receipt_model.pk,
            "policy_id": policy_model.pk,
        }
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R4PromotionDecisionBundleModel,
                    expected_values=claim_values,
                ):
                    model = R4PromotionDecisionBundleModel._default_manager.using(
                        self._using
                    ).create(
                        receipt=receipt_model,
                        policy=policy_model,
                        **values,
                    )
        except IntegrityError as error:
            winner = self._get_decision_bundle_collision(bundle)
            if winner is None:
                raise R4PromotionRepositoryConflict("R4 decision append conflict") from error
            restored = self._decision_bundle_from_model(winner)
            if restored != bundle:
                raise R4PromotionRepositoryConflict("R4 decision identity conflict") from error
            return restored
        return self._decision_bundle_from_model(model)

    def get_decision_bundle(
        self,
        decision_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        """Return one exact decision bundle known at the requested PIT."""

        self.require_active_unit_of_work()
        model = (
            R4PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                decision_id=decision_ref.stable_id,
                decision_version=decision_ref.version,
                recorded_at__lte=as_of,
            )
            .select_related("receipt", "policy")
            .first()
        )
        return self._decision_bundle_from_model(model) if model is not None else None

    def claim_lifecycle_authorization(
        self,
        *,
        event_ref: R4PromotionVersionRef,
        authorization: R4PromotionLifecycleAuthorization,
        reason_codes: tuple[str, ...],
    ) -> ExactR4LifecycleAuthorizationEvidence:
        """Claim stable server clocks for one exact owner authorization."""

        self.require_active_unit_of_work()
        expected_id = r4_lifecycle_authorization_claim_id(
            event_ref=event_ref,
            authorization=authorization,
        )
        if (
            authorization.authorization_id != expected_id
            or authorization.authorization_version != "authorization.v1"
        ):
            raise R4PromotionRepositoryConflict(
                "R4 lifecycle authorization identity is not canonical"
            )
        existing = self._get_lifecycle_receipt_by_event(event_ref)
        if existing is not None:
            evidence = self._lifecycle_evidence_from_model(existing)
            if (
                evidence.authorization != authorization
                or evidence.reason_codes != reason_codes
                or evidence.event_ref != event_ref
            ):
                raise R4PromotionRepositoryConflict("R4 lifecycle receipt identity conflict")
            return evidence
        now = self._clock.now()
        decision_model = self._get_decision_model_for_identity(
            authorization.decision,
            as_of=now,
        )
        target_model = (
            self._get_decision_model_for_identity(authorization.rollback_target, as_of=now)
            if authorization.rollback_target is not None
            else None
        )
        evidence = ExactR4LifecycleAuthorizationEvidence.create(
            event_ref=event_ref,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=now,
            event_recorded_at=now,
        )
        values = _lifecycle_receipt_model_values(evidence)
        claim_values = {
            **values,
            "decision_id": decision_model.pk,
            "rollback_target_id": None if target_model is None else target_model.pk,
        }
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R4PromotionLifecycleAuthorizationReceiptModel,
                    expected_values=claim_values,
                ):
                    model = R4PromotionLifecycleAuthorizationReceiptModel._default_manager.using(
                        self._using
                    ).create(
                        decision=decision_model,
                        rollback_target=target_model,
                        **values,
                    )
        except IntegrityError as error:
            winner = self._get_lifecycle_receipt_collision(evidence)
            if winner is None:
                raise R4PromotionRepositoryConflict("R4 lifecycle receipt conflict") from error
            restored = self._lifecycle_evidence_from_model(winner)
            if (
                restored.event_ref != event_ref
                or restored.authorization != authorization
                or restored.reason_codes != reason_codes
            ):
                raise R4PromotionRepositoryConflict(
                    "R4 lifecycle receipt identity conflict"
                ) from error
            return restored
        return self._lifecycle_evidence_from_model(model)

    def get_exact_lifecycle_authorization(
        self,
        *,
        authorization_ref: R4PromotionVersionRef,
        event_ref: R4PromotionVersionRef,
        scope_ref: R4PromotionScopeRef,
        action: R4PromotionLifecycleAction,
        decision_ref: R4PromotionVersionRef,
        rollback_target_ref: R4PromotionVersionRef | None,
    ) -> ExactR4LifecycleAuthorizationEvidence | None:
        """Return a claimed winner only when every exact identity matches."""

        self.require_active_unit_of_work()
        model = self._get_lifecycle_receipt_by_event(event_ref)
        if model is None:
            return None
        evidence = self._lifecycle_evidence_from_model(model)
        authorization = evidence.authorization
        target = authorization.rollback_target
        expected_target = (
            None
            if target is None
            else R4PromotionVersionRef(target.decision_id, target.decision_version)
        )
        if (
            (authorization.authorization_id, authorization.authorization_version)
            != (authorization_ref.stable_id, authorization_ref.version)
            or authorization.scope.scope_id != scope_ref.scope_id
            or authorization.event_type is not action.event_type
            or (authorization.decision.decision_id, authorization.decision.decision_version)
            != (decision_ref.stable_id, decision_ref.version)
            or expected_target != rollback_target_ref
        ):
            return None
        return evidence

    def append_lifecycle_event_bundle(
        self,
        bundle: R4PromotionLifecycleEventBundle,
    ) -> R4PromotionLifecycleEventBundle:
        """Append one exact stream tail or replay its immutable winner."""

        self.require_active_unit_of_work()
        collision = self._get_lifecycle_event_collision(bundle)
        if collision is not None:
            restored = self.get_lifecycle_event_bundle(
                R4PromotionVersionRef(collision.event_id, collision.event_version)
            )
            if restored != bundle:
                raise R4PromotionRepositoryConflict("R4 lifecycle event conflict")
            return restored
        event = bundle.event
        receipt_model = self._get_lifecycle_receipt_by_event(
            R4PromotionVersionRef(event.event_id, event.event_version)
        )
        if (
            receipt_model is None
            or self._lifecycle_evidence_from_model(receipt_model) != bundle.evidence
        ):
            raise R4PromotionRepositoryCorruption("exact R4 lifecycle receipt is unavailable")
        prefix_rows = tuple(
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
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
                raise R4PromotionRepositoryConflict("R4 lifecycle event conflict")
            return raced_winner
        rebuilt = self._rebuild_lifecycle_bundle(
            bundle,
            tuple(item.event for item in prefix),
        )
        if rebuilt != bundle:
            raise R4PromotionRepositoryCorruption("R4 lifecycle factory rebuild mismatch")
        previous_model = prefix_rows[-1] if prefix_rows else None
        values = _lifecycle_event_model_values(bundle)
        claim_values = {
            **values,
            "receipt_id": receipt_model.pk,
            "decision_id": receipt_model.decision_id,
            "rollback_target_id": receipt_model.rollback_target_id,
            "previous_event_id": None if previous_model is None else previous_model.pk,
        }
        try:
            with transaction.atomic(using=self._using):
                with _claim_r4_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R4PromotionLifecycleEventModel,
                    expected_values=claim_values,
                ):
                    model = R4PromotionLifecycleEventModel._default_manager.using(
                        self._using
                    ).create(
                        receipt=receipt_model,
                        decision=receipt_model.decision,
                        rollback_target=receipt_model.rollback_target,
                        previous_event=previous_model,
                        **values,
                    )
        except IntegrityError as error:
            winner = self._get_lifecycle_event_collision(bundle)
            if winner is None:
                raise R4PromotionRepositoryConflict("R4 lifecycle event conflict") from error
            restored = self.get_lifecycle_event_bundle(
                R4PromotionVersionRef(winner.event_id, winner.event_version)
            )
            if restored != bundle:
                raise R4PromotionRepositoryConflict("R4 lifecycle event conflict") from error
            return restored
        restored = self.get_lifecycle_event_bundle(
            R4PromotionVersionRef(model.event_id, model.event_version)
        )
        if restored is None:
            raise R4PromotionRepositoryCorruption("R4 lifecycle event disappeared")
        return restored

    def get_lifecycle_event_bundle(
        self,
        event_ref: R4PromotionVersionRef,
    ) -> R4PromotionLifecycleEventBundle | None:
        """Restore an event only through its complete canonical stream."""

        self.require_active_unit_of_work()
        row = (
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(event_id=event_ref.stable_id, event_version=event_ref.version)
            .first()
        )
        if row is None:
            return None
        rows = tuple(
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
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
        scope_ref: R4PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        """Restore the scope-local recorded prefix visible at ``as_of``."""

        self.require_active_unit_of_work()
        rows = tuple(
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(scope_id=scope_ref.scope_id, recorded_at__lte=as_of)
            .order_by("sequence")
        )
        bundles = self._restore_lifecycle_rows(rows, evaluated_at=as_of)
        return tuple(item.event for item in bundles)

    def load_lifecycle_stream(
        self,
        scope_ref: R4PromotionScopeRef,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        """Restore the complete append-only scope stream."""

        self.require_active_unit_of_work()
        rows = tuple(
            R4PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(scope_id=scope_ref.scope_id)
            .order_by("sequence")
        )
        bundles = self._restore_lifecycle_rows(rows)
        return tuple(item.event for item in bundles)

    def _read_portfolio_evidence(
        self,
        *,
        record_id: str,
        record_hash: str,
        as_of: datetime,
        require_active: bool,
    ) -> tuple[
        R4RollingResearchOwnerRecord,
        R4PromotionPortfolioRecordSeal,
        R4PromotionR3AttestationEvidence,
    ]:
        self.require_active_unit_of_work()
        owner_record = self._portfolio_query.get_exact(
            record_id=record_id,
            expected_record_hash=record_hash,
            as_of=as_of,
        )
        if owner_record is None:
            raise R4PromotionRepositoryCorruption("exact Portfolio R4 record is unavailable")
        record = project_r4_portfolio_owner_record(owner_record)
        source = owner_record.record.promotion_attestation
        current = self._current_r3_provider.get_exact(
            capability_key="macro_factor_r3",
            artifact_id=source.artifact_id,
            artifact_version=source.artifact_version,
            artifact_content_hash=source.artifact_content_hash,
            decision_id=source.decision_id,
            decision_version=source.decision_version,
            decision_content_hash=source.decision_content_hash,
            as_of=as_of,
        )
        if current is None:
            raise R4PromotionRepositoryCorruption("exact current R3 evidence is unavailable")
        current_evidence = project_r4_promotion_r3_attestation(current)
        if (
            record.record_id != record_id
            or record.record_hash != record_hash
            or record.record_r3_attestation != current_evidence
            or (
                require_active
                and (
                    not record.recorded_at <= as_of < record.valid_until
                    or not current_evidence.is_active_at(as_of)
                )
            )
        ):
            raise R4PromotionRepositoryCorruption(
                "Portfolio R4 record or current R3 evidence was substituted"
            )
        return owner_record, record, current_evidence

    def _policy_from_model(self, model: R4PromotionPolicyModel) -> R4PromotionPolicy:
        policy = decode_r4_promotion_policy(model.canonical_payload)
        values = _policy_model_values(policy)
        if values != _model_value_subset(model, values):
            raise R4PromotionRepositoryCorruption("R4 policy header/payload mismatch")
        return policy

    def _decision_receipt_from_model(
        self,
        model: R4PromotionDecisionReceiptModel,
    ) -> R4PromotionDecisionReceipt:
        receipt = decode_r4_promotion_decision_receipt(model.canonical_payload)
        values = _decision_receipt_model_values(receipt)
        if values != _model_value_subset(model, values):
            raise R4PromotionRepositoryCorruption("R4 decision receipt header mismatch")
        policy = self._policy_from_model(model.policy)
        if (
            receipt.policy_ref != R4PromotionVersionRef(policy.policy_id, policy.policy_version)
            or receipt.policy_content_hash != policy.content_hash
        ):
            raise R4PromotionRepositoryCorruption("R4 decision receipt policy FK mismatch")
        expected_id = stable_r4_decision_receipt_id(
            decision_ref=receipt.decision_ref,
            trial_ref=receipt.trial_ref,
            policy_ref=receipt.policy_ref,
            portfolio_record_id=receipt.portfolio_record_id,
            scope_id=policy.scope.scope_id,
        )
        if receipt.receipt_id != expected_id or receipt.receipt_version != "receipt.v1":
            raise R4PromotionRepositoryCorruption("R4 decision receipt identity is invalid")
        return receipt

    def _decision_bundle_from_model(
        self,
        model: R4PromotionDecisionBundleModel,
    ) -> R4PromotionDecisionBundle:
        bundle = decode_r4_promotion_decision_bundle(model.canonical_payload)
        receipt = self._decision_receipt_from_model(model.receipt)
        values = _decision_bundle_model_values(bundle)
        if values != _model_value_subset(model, values):
            raise R4PromotionRepositoryCorruption("R4 decision bundle header mismatch")
        if (
            bundle.receipt != receipt
            or model.policy_id != model.receipt.policy_id
            or bundle.decision.policy.content_hash != model.policy_content_hash
            or bundle.decision.trial.content_hash != model.trial_content_hash
            or bundle.decision.trial.current_r3_attestation.content_hash
            != model.current_r3_content_hash
        ):
            raise R4PromotionRepositoryCorruption("R4 decision bundle FK was substituted")
        return self._rebuild_decision_bundle(bundle)

    def _rebuild_decision_bundle(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundle:
        decision = bundle.decision
        policy = self.get_exact_policy(
            R4PromotionVersionRef(decision.policy.policy_id, decision.policy.policy_version),
            as_of=decision.decided_at,
        )
        if policy is None or policy != decision.policy:
            raise R4PromotionRepositoryCorruption("exact R4 policy is unavailable")
        owner_record, record, current_r3 = self._read_portfolio_evidence(
            record_id=decision.trial.portfolio_record.record_id,
            record_hash=decision.trial.portfolio_record.record_hash,
            as_of=decision.decided_at,
            require_active=True,
        )
        if (
            owner_record.owner_record_key != bundle.receipt.portfolio_owner_record_key
            or record.recorded_at != bundle.receipt.portfolio_recorded_at
            or current_r3.content_hash != bundle.receipt.current_r3_content_hash
        ):
            raise R4PromotionRepositoryCorruption("R4 owner receipt evidence was substituted")
        trial = R4PromotionTrialSeal.create(
            trial_id=decision.trial.trial_id,
            trial_version=decision.trial.trial_version,
            policy=policy,
            portfolio_record=record,
            current_r3_attestation=current_r3,
            evaluated_at=decision.trial.evaluated_at,
        )
        rebuilt_decision = create_r4_promotion_decision(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            policy=policy,
            trial=trial,
            as_of=decision.decided_at,
            recorded_at=decision.recorded_at,
        )
        rebuilt = R4PromotionDecisionBundle.create(
            decision=rebuilt_decision,
            receipt=bundle.receipt,
        )
        if rebuilt != bundle:
            raise R4PromotionRepositoryCorruption("R4 decision factory rebuild mismatch")
        return rebuilt

    def _lifecycle_evidence_from_model(
        self,
        model: R4PromotionLifecycleAuthorizationReceiptModel,
    ) -> ExactR4LifecycleAuthorizationEvidence:
        evidence = decode_r4_lifecycle_authorization_evidence(model.canonical_payload)
        values = _lifecycle_receipt_model_values(evidence)
        if values != _model_value_subset(model, values):
            raise R4PromotionRepositoryCorruption("R4 lifecycle receipt header mismatch")
        decision = self._decision_bundle_from_model(model.decision)
        if (
            R4PromotionDecisionIdentity.from_decision(decision.decision)
            != evidence.authorization.decision
            or model.decision_content_hash != decision.decision.content_hash
        ):
            raise R4PromotionRepositoryCorruption("R4 lifecycle decision FK mismatch")
        if model.rollback_target is None:
            target_identity = None
            target_hash = ""
        else:
            target = self._decision_bundle_from_model(model.rollback_target)
            target_identity = R4PromotionDecisionIdentity.from_decision(target.decision)
            target_hash = target.decision.content_hash
        if (
            target_identity != evidence.authorization.rollback_target
            or model.rollback_target_content_hash != target_hash
        ):
            raise R4PromotionRepositoryCorruption("R4 lifecycle target FK mismatch")
        expected_id = r4_lifecycle_authorization_claim_id(
            event_ref=evidence.event_ref,
            authorization=evidence.authorization,
        )
        if (
            evidence.authorization.authorization_id != expected_id
            or evidence.authorization.authorization_version != "authorization.v1"
        ):
            raise R4PromotionRepositoryCorruption("R4 lifecycle authorization ID is invalid")
        return evidence

    def _restore_lifecycle_rows(
        self,
        rows: tuple[R4PromotionLifecycleEventModel, ...],
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[R4PromotionLifecycleEventBundle, ...]:
        restored: list[R4PromotionLifecycleEventBundle] = []
        events: list[R4PromotionLifecycleEvent] = []
        for index, item in enumerate(rows):
            row = (
                R4PromotionLifecycleEventModel._default_manager.using(self._using)
                .select_related(
                    "receipt",
                    "receipt__decision",
                    "receipt__decision__receipt",
                    "receipt__decision__policy",
                    "receipt__rollback_target",
                    "decision",
                    "rollback_target",
                    "previous_event",
                )
                .get(pk=item.pk)
            )
            decoded = decode_r4_lifecycle_event_bundle(row.canonical_payload)
            evidence = self._lifecycle_evidence_from_model(row.receipt)
            values = _lifecycle_event_model_values(decoded)
            if values != _model_value_subset(row, values):
                raise R4PromotionRepositoryCorruption("R4 lifecycle event header mismatch")
            if (
                decoded.evidence != evidence
                or row.decision_id != row.receipt.decision_id
                or row.rollback_target_id != row.receipt.rollback_target_id
                or row.decision_content_hash != evidence.authorization.decision.content_hash
                or row.rollback_target_content_hash
                != (
                    ""
                    if evidence.authorization.rollback_target is None
                    else evidence.authorization.rollback_target.content_hash
                )
            ):
                raise R4PromotionRepositoryCorruption("R4 lifecycle event FK mismatch")
            expected_previous_id = rows[index - 1].pk if index else None
            if row.previous_event_id != expected_previous_id:
                raise R4PromotionRepositoryCorruption("R4 lifecycle previous FK mismatch")
            rebuilt = self._rebuild_lifecycle_bundle(decoded, tuple(events))
            restored.append(rebuilt)
            events.append(rebuilt.event)
        if events:
            derive_r4_promotion_lifecycle_state(
                tuple(events),
                evaluated_at=evaluated_at or max(item.recorded_at for item in events),
            )
        return tuple(restored)

    def _rebuild_lifecycle_bundle(
        self,
        bundle: R4PromotionLifecycleEventBundle,
        prefix: tuple[R4PromotionLifecycleEvent, ...],
    ) -> R4PromotionLifecycleEventBundle:
        event = bundle.event
        decision_model = self._get_decision_model_for_identity(
            event.decision,
            as_of=event.occurred_at,
        )
        decision = self._decision_bundle_from_model(decision_model).decision
        rollback_target: R4PromotionDecision | None = None
        if event.rollback_target is not None:
            target_model = self._get_decision_model_for_identity(
                event.rollback_target,
                as_of=event.occurred_at,
            )
            rollback_target = self._decision_bundle_from_model(target_model).decision
        if not prefix:
            rebuilt_event = create_r4_promotion_lifecycle_root(
                event_id=event.event_id,
                event_version=event.event_version,
                decision=decision,
                authorization=bundle.evidence.authorization,
                reason_codes=bundle.evidence.reason_codes,
                occurred_at=bundle.evidence.occurred_at,
                recorded_at=bundle.evidence.event_recorded_at,
            )
        else:
            rebuilt_event = create_r4_promotion_lifecycle_event(
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
        rebuilt = R4PromotionLifecycleEventBundle.create(
            event=rebuilt_event,
            evidence=bundle.evidence,
        )
        if rebuilt != bundle:
            raise R4PromotionRepositoryCorruption("R4 lifecycle factory rebuild mismatch")
        return rebuilt

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


__all__ = ["DjangoR4PromotionClock", "DjangoR4PromotionRepository"]
