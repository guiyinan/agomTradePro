"""Transactional exact repository and providers for R5 promotion ledgers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from apps.fixed_income.domain.evidence import require_aware
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionRef,
    r5_relative_value_decision_authorization_hash,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAction,
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
    R5RelativeValueLifecycleScopeRef,
    r5_relative_value_lifecycle_evidence_hash,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionArtifact,
    R5PromotionArtifactKind,
    R5PromotionServerClock,
    r5_promotion_artifact_registration_command_hash,
    require_r5_promotion_pit_cutoff,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    create_r5_relative_value_promotion_decision,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleEventType,
    create_r5_relative_value_lifecycle_event,
    create_r5_relative_value_lifecycle_root,
    derive_r5_relative_value_lifecycle_state,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_relative_value_promotion_codec import (
    R5PromotionCodecError,
    decode_r5_decision_authorization,
    decode_r5_decision_bundle,
    decode_r5_lifecycle_authorization_evidence,
    decode_r5_lifecycle_event_bundle,
    decode_r5_promotion_artifact,
)
from apps.research.infrastructure.r5_relative_value_promotion_models import (
    R5PromotionArtifactModel,
    R5PromotionDecisionAuthorizationModel,
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleAuthorizationModel,
    R5PromotionLifecycleEventModel,
    _activate_r5_promotion_unit_of_work,
    _claim_r5_promotion_insert,
    _r5_promotion_unit_of_work_is_active,
)
from apps.research.infrastructure.r5_relative_value_promotion_repository_support import (
    DjangoR5PromotionServerClock,
    R5PromotionRepositoryConflict,
    R5PromotionRepositoryCorruption,
    _artifact_kind,
    _artifact_model_values,
    _artifact_ref,
    _content_hash_anchor,
    _decision_authorization_model_values,
    _decision_bundle_model_values,
    _lifecycle_authorization_model_values,
    _lifecycle_event_model_values,
    _model_matches,
)


class DjangoR5PromotionRepository:
    """Store and strictly replay the complete R5 promotion graph."""

    def __init__(
        self,
        *,
        clock: R5PromotionServerClock | None = None,
        using: str = "default",
    ) -> None:
        self._clock = clock or DjangoR5PromotionServerClock()
        self._using = using
        self._unit_of_work_token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction boundary key."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Activate the repository token inside one database transaction."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            with _activate_r5_promotion_unit_of_work(self._unit_of_work_token):
                yield

    def require_active_unit_of_work(self) -> None:
        """Reject reads and appends outside this exact transaction token."""

        connection = transaction.get_connection(self._using)
        if (
            not _r5_promotion_unit_of_work_is_active(self._unit_of_work_token)
            or not connection.in_atomic_block
        ):
            raise R5PromotionRepositoryConflict(
                "operation requires its closure-bound repository unit of work"
            )

    def server_now(self) -> datetime:
        """Claim and validate one authoritative server timestamp."""

        value = self._clock.now()
        require_aware(value, "R5 promotion server clock")
        return value

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        """Apply the shared future-cutoff gate before every PIT query."""

        require_r5_promotion_pit_cutoff(
            as_of,
            server_now=self.server_now(),
        )

    def _append_artifact(
        self,
        artifact: R5PromotionArtifact,
    ) -> R5PromotionArtifact:
        """Append one verified artifact through the private composition surface."""

        self.require_active_unit_of_work()
        ledger_recorded_at = self.server_now()
        kind = _artifact_kind(artifact)
        ref = _artifact_ref(artifact)
        if not artifact.is_active_at(ledger_recorded_at):
            raise R5PromotionRepositoryConflict("artifact is inactive at server registration")
        existing = self._artifact_collision(kind, ref, artifact.content_hash)
        if existing is not None:
            restored = self._artifact_from_model(existing)
            if restored != artifact:
                raise R5PromotionRepositoryConflict("artifact identity conflicts")
            return restored
        values = _artifact_model_values(
            artifact,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with transaction.atomic(using=self._using):
                with _claim_r5_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R5PromotionArtifactModel,
                    expected_values=values,
                ):
                    model = R5PromotionArtifactModel(**values)
                    model.full_clean()
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = self._artifact_collision(kind, ref, artifact.content_hash)
            if winner is None:
                raise R5PromotionRepositoryConflict("artifact append conflict") from error
            restored = self._artifact_from_model(winner)
            if restored != artifact:
                raise R5PromotionRepositoryConflict("artifact race fork") from error
            return restored
        restored = self._artifact_from_model(model)
        if restored != artifact:
            raise R5PromotionRepositoryCorruption("artifact append did not round-trip")
        return restored

    def get_exact_policy(
        self,
        policy_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionPolicy | None:
        """Return one exact active policy known at the PIT."""

        artifact = self._get_exact_artifact(
            R5PromotionArtifactKind.POLICY,
            policy_ref,
            as_of=as_of,
        )
        return artifact if type(artifact) is R5RelativeValuePromotionPolicy else None

    def get_exact_trial(
        self,
        trial_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionTrial | None:
        """Return one exact active trial known at the PIT."""

        artifact = self._get_exact_artifact(
            R5PromotionArtifactKind.TRIAL,
            trial_ref,
            as_of=as_of,
        )
        return artifact if type(artifact) is R5RelativeValuePromotionTrial else None

    def _get_exact_artifact(
        self,
        kind: R5PromotionArtifactKind,
        ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5PromotionArtifact | None:
        self.require_active_unit_of_work()
        self._require_pit_cutoff(as_of)
        command_hash = r5_promotion_artifact_registration_command_hash(
            artifact_kind=kind,
            artifact_ref=ref,
        )
        content_hash = _content_hash_anchor(
            ref.stable_id,
            prefix=("r5-rv-policy" if kind is R5PromotionArtifactKind.POLICY else "r5-rv-trial"),
        )
        anchors = models.Q(
            artifact_kind=kind.value,
            stable_id=ref.stable_id,
            version=ref.version,
        ) | models.Q(command_hash=command_hash)
        if content_hash is not None:
            anchors |= models.Q(content_hash=content_hash)
        candidates = tuple(
            R5PromotionArtifactModel._default_manager.using(self._using)
            .filter(anchors)
            .order_by("pk")
        )
        restored = tuple((model, self._artifact_from_model(model)) for model in candidates)
        matches = tuple(
            (model, artifact)
            for model, artifact in restored
            if _artifact_kind(artifact) is kind and _artifact_ref(artifact) == ref
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption("artifact selector has multiple exact matches")
        model, artifact = matches[0]
        if model.ledger_recorded_at > as_of:
            return None
        return artifact if artifact.is_active_at(as_of) else None

    def append_decision_bundle(
        self,
        bundle: R5RelativeValuePromotionDecisionBundle,
    ) -> R5RelativeValuePromotionDecisionBundle:
        """Atomically append the exact authorization receipt and decision child."""

        self.require_active_unit_of_work()
        existing = self._decision_collision(bundle)
        if existing is not None:
            restored = self._decision_bundle_from_model(existing)
            if restored != bundle:
                raise R5PromotionRepositoryConflict("decision identity conflicts")
            return restored
        decision = bundle.decision
        authorization = bundle.authorization
        policy_model = self._required_artifact_model(
            R5PromotionArtifactKind.POLICY,
            R5RelativeValuePromotionRef(decision.policy.policy_id, decision.policy.policy_version),
            decision.policy.content_hash,
        )
        trial_model = self._required_artifact_model(
            R5PromotionArtifactKind.TRIAL,
            R5RelativeValuePromotionRef(decision.trial.trial_id, decision.trial.trial_version),
            decision.trial.content_hash,
        )
        if (
            self._artifact_from_model(policy_model) != decision.policy
            or self._artifact_from_model(trial_model) != decision.trial
        ):
            raise R5PromotionRepositoryCorruption("decision artifact graph was substituted")
        rebuilt = R5RelativeValuePromotionDecisionBundle.create(
            decision=create_r5_relative_value_promotion_decision(
                policy=decision.policy,
                trial=decision.trial,
                decided_at=decision.decided_at,
                recorded_at=decision.recorded_at,
            ),
            authorization=authorization,
        )
        if rebuilt != bundle:
            raise R5PromotionRepositoryCorruption("decision factory rebuild mismatch")
        ledger_recorded_at = self.server_now()
        if ledger_recorded_at > decision.recorded_at:
            raise R5PromotionRepositoryConflict(
                "decision server receipt would postdate its immutable recorded_at"
            )
        auth_values = _decision_authorization_model_values(
            authorization,
            ledger_recorded_at=ledger_recorded_at,
        )
        decision_values = _decision_bundle_model_values(
            bundle,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with transaction.atomic(using=self._using):
                auth_claim = {
                    **auth_values,
                    "policy_id": policy_model.pk,
                    "trial_id": trial_model.pk,
                }
                with _claim_r5_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R5PromotionDecisionAuthorizationModel,
                    expected_values=auth_claim,
                ):
                    auth_model = R5PromotionDecisionAuthorizationModel(
                        policy=policy_model,
                        trial=trial_model,
                        **auth_values,
                    )
                    auth_model.full_clean()
                    auth_model.save(force_insert=True, using=self._using)
                child_claim = {
                    **decision_values,
                    "authorization_id": auth_model.pk,
                    "policy_id": policy_model.pk,
                    "trial_id": trial_model.pk,
                }
                with _claim_r5_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R5PromotionDecisionBundleModel,
                    expected_values=child_claim,
                ):
                    model = R5PromotionDecisionBundleModel(
                        authorization=auth_model,
                        policy=policy_model,
                        trial=trial_model,
                        **decision_values,
                    )
                    model.full_clean()
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = self._decision_collision(bundle)
            if winner is None:
                raise R5PromotionRepositoryConflict("decision append conflict") from error
            restored = self._decision_bundle_from_model(winner)
            if restored != bundle:
                raise R5PromotionRepositoryConflict("decision race fork") from error
            return restored
        restored = self._decision_bundle_from_model(model)
        if restored != bundle:
            raise R5PromotionRepositoryCorruption("decision append did not round-trip")
        return restored

    def get_decision_bundle(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        """Return one exact decision bundle known at the requested PIT."""

        self.require_active_unit_of_work()
        self._require_pit_cutoff(as_of)
        content_hash = _content_hash_anchor(
            decision_ref.stable_id,
            prefix="r5-rv-decision",
        )
        anchors = models.Q(
            decision_id=decision_ref.stable_id,
            decision_version=decision_ref.version,
        )
        if content_hash is not None:
            anchors |= models.Q(decision_content_hash=content_hash)
        candidates = tuple(
            R5PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(anchors)
            .select_related("authorization", "policy", "trial")
            .order_by("pk")
        )
        restored = tuple((model, self._decision_bundle_from_model(model)) for model in candidates)
        matches = tuple(
            (model, bundle)
            for model, bundle in restored
            if (bundle.decision.decision_id, bundle.decision.decision_version)
            == (decision_ref.stable_id, decision_ref.version)
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption("decision selector has multiple exact matches")
        model, bundle = matches[0]
        if model.ledger_recorded_at > as_of or bundle.decision.recorded_at > as_of:
            return None
        return bundle

    def get_exact_decision_authorization(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        """Return one persisted exact authorization known and active at PIT."""

        self.require_active_unit_of_work()
        self._require_pit_cutoff(as_of)
        content_hash = _content_hash_anchor(
            authorization_ref.stable_id,
            prefix="r5-rv-decision-auth",
        )
        anchors = models.Q(
            authorization_id=authorization_ref.stable_id,
            authorization_version=authorization_ref.version,
        ) | models.Q(
            policy__stable_id=policy_ref.stable_id,
            policy__version=policy_ref.version,
            trial__stable_id=trial_ref.stable_id,
            trial__version=trial_ref.version,
        )
        if content_hash is not None:
            anchors |= models.Q(content_hash=content_hash)
        candidates = tuple(
            R5PromotionDecisionAuthorizationModel._default_manager.using(self._using)
            .filter(anchors)
            .select_related("policy", "trial")
            .order_by("pk")
        )
        restored = tuple(
            (model, self._decision_authorization_from_model(model)) for model in candidates
        )
        matches = tuple(
            (model, authorization)
            for model, authorization in restored
            if (
                authorization.authorization_id,
                authorization.authorization_version,
                authorization.policy_ref,
                authorization.trial_ref,
            )
            == (
                authorization_ref.stable_id,
                authorization_ref.version,
                policy_ref,
                trial_ref,
            )
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption(
                "decision authorization selector has multiple exact matches"
            )
        model, authorization = matches[0]
        if model.ledger_recorded_at > as_of:
            return None
        return authorization if authorization.is_active_at(as_of) else None

    def append_lifecycle_event_bundle(
        self,
        bundle: R5RelativeValueLifecycleEventBundle,
    ) -> R5RelativeValueLifecycleEventBundle:
        """Atomically append lifecycle evidence and its self-linked event child."""

        self.require_active_unit_of_work()
        existing = self._lifecycle_collision(bundle)
        if existing is not None:
            restored = self._lifecycle_event_bundle_from_model(existing)
            if restored != bundle:
                raise R5PromotionRepositoryConflict("lifecycle identity conflicts")
            return restored
        event = bundle.event
        evidence = bundle.authorization_evidence
        decision_model = self._required_decision_model(event.decision)
        target_model = (
            None
            if event.rollback_target is None
            else self._required_decision_model(event.rollback_target)
        )
        restored_history = self._restore_lifecycle_scope(event.scope.scope_id)
        history_models = tuple(item[0] for item in restored_history)
        history = tuple(item[1] for item in restored_history)
        previous_model = history_models[-1] if history_models else None
        try:
            rebuilt_event = (
                create_r5_relative_value_lifecycle_root(
                    event_version=event.event_version,
                    decision=self._decision_bundle_from_model(decision_model).decision,
                    authorization=evidence.authorization,
                    reason_codes=evidence.reason_codes,
                    occurred_at=evidence.occurred_at,
                    recorded_at=evidence.event_recorded_at,
                )
                if not history
                else create_r5_relative_value_lifecycle_event(
                    event_version=event.event_version,
                    previous_events=tuple(item.event for item in history),
                    event_type=event.event_type,
                    decision=self._decision_bundle_from_model(decision_model).decision,
                    rollback_target=(
                        None
                        if target_model is None
                        else self._decision_bundle_from_model(target_model).decision
                    ),
                    authorization=evidence.authorization,
                    reason_codes=evidence.reason_codes,
                    occurred_at=evidence.occurred_at,
                    recorded_at=evidence.event_recorded_at,
                )
            )
            rebuilt = R5RelativeValueLifecycleEventBundle.create(
                event=rebuilt_event,
                authorization_evidence=evidence,
            )
        except ValueError as error:
            raise R5PromotionRepositoryCorruption(
                "lifecycle event cannot be rebuilt from the exact stream"
            ) from error
        if rebuilt != bundle:
            raise R5PromotionRepositoryCorruption("lifecycle factory rebuild mismatch")
        ledger_recorded_at = self.server_now()
        if ledger_recorded_at > event.recorded_at:
            raise R5PromotionRepositoryConflict(
                "lifecycle server receipt would postdate event recorded_at"
            )
        auth_values = _lifecycle_authorization_model_values(
            evidence,
            ledger_recorded_at=ledger_recorded_at,
        )
        event_values = _lifecycle_event_model_values(
            bundle,
            ledger_recorded_at=ledger_recorded_at,
        )
        try:
            with transaction.atomic(using=self._using):
                auth_claim = {
                    **auth_values,
                    "decision_id": decision_model.pk,
                    "rollback_target_id": None if target_model is None else target_model.pk,
                }
                with _claim_r5_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R5PromotionLifecycleAuthorizationModel,
                    expected_values=auth_claim,
                ):
                    auth_model = R5PromotionLifecycleAuthorizationModel(
                        decision=decision_model,
                        rollback_target=target_model,
                        **auth_values,
                    )
                    auth_model.full_clean()
                    auth_model.save(force_insert=True, using=self._using)
                child_claim = {
                    **event_values,
                    "authorization_id": auth_model.pk,
                    "decision_id": decision_model.pk,
                    "rollback_target_id": None if target_model is None else target_model.pk,
                    "previous_event_id": None if previous_model is None else previous_model.pk,
                }
                with _claim_r5_promotion_insert(
                    token=self._unit_of_work_token,
                    model_type=R5PromotionLifecycleEventModel,
                    expected_values=child_claim,
                ):
                    model = R5PromotionLifecycleEventModel(
                        authorization=auth_model,
                        decision=decision_model,
                        rollback_target=target_model,
                        previous_event=previous_model,
                        **event_values,
                    )
                    model.full_clean()
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = self._lifecycle_collision(bundle)
            if winner is None:
                raise R5PromotionRepositoryConflict("lifecycle append conflict") from error
            restored = self._lifecycle_event_bundle_from_model(winner)
            if restored != bundle:
                raise R5PromotionRepositoryConflict("lifecycle race fork") from error
            return restored
        restored = self._lifecycle_event_bundle_from_model(model)
        if restored != bundle:
            raise R5PromotionRepositoryCorruption("lifecycle append did not round-trip")
        return restored

    def load_lifecycle_stream(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
    ) -> tuple[R5RelativeValueLifecycleEventBundle, ...]:
        """Restore the complete ordered stream and verify its exact chain."""

        self.require_active_unit_of_work()
        return tuple(item[1] for item in self._restore_lifecycle_scope(scope_ref.scope_id))

    def get_event_bundle_by_authorization(
        self,
        authorization_ref: R5RelativeValuePromotionRef,
    ) -> R5RelativeValueLifecycleEventBundle | None:
        """Return the exact event winner for one evidence receipt identity."""

        self.require_active_unit_of_work()
        authorization_candidates = self._lifecycle_authorization_candidates(
            authorization_ref=authorization_ref,
        )
        restored_authorizations = tuple(
            (model, self._lifecycle_authorization_from_model(model))
            for model in authorization_candidates
        )
        authorization_matches = tuple(
            (model, evidence)
            for model, evidence in restored_authorizations
            if (evidence.evidence_id, evidence.evidence_version)
            == (authorization_ref.stable_id, authorization_ref.version)
        )
        if not authorization_matches:
            return None
        if len(authorization_matches) != 1:
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization selector has multiple exact matches"
            )
        authorization_model, evidence = authorization_matches[0]
        event_candidates = tuple(
            R5PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(
                models.Q(authorization_id=authorization_model.pk)
                | models.Q(
                    event_id=evidence.event_ref.stable_id,
                    event_version=evidence.event_ref.version,
                )
                | models.Q(event_content_hash=evidence.event_content_hash)
            )
            .select_related(
                "authorization",
                "decision__authorization",
                "decision__policy",
                "decision__trial",
                "rollback_target__authorization",
                "rollback_target__policy",
                "rollback_target__trial",
                "previous_event",
            )
            .order_by("pk")
        )
        restored_events = tuple(
            self._lifecycle_event_bundle_from_model(model) for model in event_candidates
        )
        matches = tuple(
            bundle for bundle in restored_events if bundle.authorization_evidence == evidence
        )
        if not matches:
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization receipt has no exact event child"
            )
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization has multiple event children"
            )
        return matches[0]

    def get_exact_lifecycle_authorization(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        """Return one persisted authorization matching every ID-only selector."""

        self.require_active_unit_of_work()
        event_type = {
            R5RelativeValueLifecycleAction.PROMOTE: R5RelativeValueLifecycleEventType.PROMOTED,
            R5RelativeValueLifecycleAction.RETIRE: R5RelativeValueLifecycleEventType.RETIRED,
            R5RelativeValueLifecycleAction.ROLLBACK: R5RelativeValueLifecycleEventType.ROLLED_BACK,
        }[action]
        candidates = self._lifecycle_authorization_candidates(
            authorization_ref=authorization_ref,
            scope_ref=scope_ref,
            decision_ref=decision_ref,
        )
        restored = tuple(
            (model, self._lifecycle_authorization_from_model(model)) for model in candidates
        )
        matches: list[
            tuple[
                R5PromotionLifecycleAuthorizationModel,
                R5RelativeValueLifecycleAuthorizationEvidence,
            ]
        ] = []
        for model, evidence in restored:
            actual_target = (
                None
                if evidence.authorization.rollback_target is None
                else R5RelativeValuePromotionRef(
                    evidence.authorization.rollback_target.decision_id,
                    evidence.authorization.rollback_target.decision_version,
                )
            )
            actual_decision = R5RelativeValuePromotionRef(
                evidence.authorization.decision.decision_id,
                evidence.authorization.decision.decision_version,
            )
            if (
                (evidence.evidence_id, evidence.evidence_version)
                == (authorization_ref.stable_id, authorization_ref.version)
                and evidence.authorization.scope.scope_id == scope_ref.scope_id
                and evidence.authorization.event_type is event_type
                and actual_decision == decision_ref
                and actual_target == rollback_target_ref
            ):
                matches.append((model, evidence))
        if not matches:
            return None
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization selector has multiple exact matches"
            )
        return matches[0][1]

    def _lifecycle_authorization_candidates(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef | None = None,
        decision_ref: R5RelativeValuePromotionRef | None = None,
    ) -> tuple[R5PromotionLifecycleAuthorizationModel, ...]:
        content_hash = _content_hash_anchor(
            authorization_ref.stable_id,
            prefix="r5-rv-lifecycle-evidence",
        )
        anchors = models.Q(
            evidence_id=authorization_ref.stable_id,
            evidence_version=authorization_ref.version,
        )
        if content_hash is not None:
            anchors |= models.Q(evidence_content_hash=content_hash)
        if scope_ref is not None:
            anchors |= models.Q(scope_id=scope_ref.scope_id)
        if decision_ref is not None:
            anchors |= models.Q(
                decision__decision_id=decision_ref.stable_id,
                decision__decision_version=decision_ref.version,
            )
        return tuple(
            R5PromotionLifecycleAuthorizationModel._default_manager.using(self._using)
            .filter(anchors)
            .select_related(
                "decision__authorization",
                "decision__policy",
                "decision__trial",
                "rollback_target__authorization",
                "rollback_target__policy",
                "rollback_target__trial",
            )
            .order_by("pk")
        )

    def _artifact_collision(
        self,
        kind: R5PromotionArtifactKind,
        ref: R5RelativeValuePromotionRef,
        content_hash: str,
    ) -> R5PromotionArtifactModel | None:
        return (
            R5PromotionArtifactModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    artifact_kind=kind.value,
                    stable_id=ref.stable_id,
                    version=ref.version,
                )
                | models.Q(content_hash=content_hash)
            )
            .first()
        )

    def _artifact_from_model(
        self,
        model: R5PromotionArtifactModel,
    ) -> R5PromotionArtifact:
        try:
            artifact = decode_r5_promotion_artifact(model.canonical_payload)
            values = _artifact_model_values(
                artifact,
                ledger_recorded_at=model.ledger_recorded_at,
            )
        except (R5PromotionCodecError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryCorruption("artifact payload is invalid") from error
        if not _model_matches(model, values):
            raise R5PromotionRepositoryCorruption("artifact header or receipt was tampered")
        return artifact

    def _required_artifact_model(
        self,
        kind: R5PromotionArtifactKind,
        ref: R5RelativeValuePromotionRef,
        expected_hash: str,
    ) -> R5PromotionArtifactModel:
        command_hash = r5_promotion_artifact_registration_command_hash(
            artifact_kind=kind,
            artifact_ref=ref,
        )
        candidates = tuple(
            R5PromotionArtifactModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    artifact_kind=kind.value,
                    stable_id=ref.stable_id,
                    version=ref.version,
                )
                | models.Q(content_hash=expected_hash)
                | models.Q(command_hash=command_hash)
            )
            .order_by("pk")
        )
        restored = tuple((model, self._artifact_from_model(model)) for model in candidates)
        matches = tuple(
            model
            for model, artifact in restored
            if _artifact_kind(artifact) is kind
            and _artifact_ref(artifact) == ref
            and artifact.content_hash == expected_hash
        )
        if not matches:
            raise R5PromotionRepositoryCorruption("required artifact is unavailable")
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption("required artifact has multiple exact matches")
        return matches[0]

    def _decision_collision(
        self,
        bundle: R5RelativeValuePromotionDecisionBundle,
    ) -> R5PromotionDecisionBundleModel | None:
        decision = bundle.decision
        return (
            R5PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    decision_id=decision.decision_id,
                    decision_version=decision.decision_version,
                )
                | models.Q(decision_content_hash=decision.content_hash)
                | models.Q(bundle_content_hash=bundle.content_hash)
                | models.Q(
                    authorization__authorization_id=bundle.authorization.authorization_id,
                    authorization__authorization_version=(
                        bundle.authorization.authorization_version
                    ),
                )
            )
            .select_related("authorization", "policy", "trial")
            .first()
        )

    def _decision_authorization_from_model(
        self,
        model: R5PromotionDecisionAuthorizationModel,
    ) -> R5RelativeValueDecisionAuthorization:
        try:
            authorization = decode_r5_decision_authorization(model.canonical_payload)
            values = _decision_authorization_model_values(
                authorization,
                ledger_recorded_at=model.ledger_recorded_at,
            )
        except (R5PromotionCodecError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryCorruption(
                "decision authorization payload is invalid"
            ) from error
        if (
            not _model_matches(model, values)
            or model.policy.artifact_kind != R5PromotionArtifactKind.POLICY.value
            or model.trial.artifact_kind != R5PromotionArtifactKind.TRIAL.value
            or (model.policy.stable_id, model.policy.version)
            != (authorization.policy_ref.stable_id, authorization.policy_ref.version)
            or (model.trial.stable_id, model.trial.version)
            != (authorization.trial_ref.stable_id, authorization.trial_ref.version)
            or authorization.content_hash
            != r5_relative_value_decision_authorization_hash(authorization)
        ):
            raise R5PromotionRepositoryCorruption(
                "decision authorization header or references were tampered"
            )
        self._artifact_from_model(model.policy)
        self._artifact_from_model(model.trial)
        return authorization

    def _decision_bundle_from_model(
        self,
        model: R5PromotionDecisionBundleModel,
    ) -> R5RelativeValuePromotionDecisionBundle:
        try:
            bundle = decode_r5_decision_bundle(model.canonical_payload)
            values = _decision_bundle_model_values(
                bundle,
                ledger_recorded_at=model.ledger_recorded_at,
            )
            authorization = self._decision_authorization_from_model(model.authorization)
            policy = self._artifact_from_model(model.policy)
            trial = self._artifact_from_model(model.trial)
        except (R5PromotionCodecError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryCorruption("decision bundle payload is invalid") from error
        if (
            not _model_matches(model, values)
            or authorization != bundle.authorization
            or policy != bundle.decision.policy
            or trial != bundle.decision.trial
            or model.authorization.policy != model.policy
            or model.authorization.trial != model.trial
        ):
            raise R5PromotionRepositoryCorruption(
                "decision bundle header, receipt or artifacts were tampered"
            )
        return bundle

    def _required_decision_model(
        self,
        identity: R5RelativeValueDecisionIdentity,
    ) -> R5PromotionDecisionBundleModel:
        candidates = tuple(
            R5PromotionDecisionBundleModel._default_manager.using(self._using)
            .filter(
                models.Q(
                    decision_id=identity.decision_id,
                    decision_version=identity.decision_version,
                )
                | models.Q(decision_content_hash=identity.content_hash)
            )
            .select_related("authorization", "policy", "trial")
            .order_by("pk")
        )
        restored = tuple((model, self._decision_bundle_from_model(model)) for model in candidates)
        matches = tuple(
            model
            for model, bundle in restored
            if R5RelativeValueDecisionIdentity.from_decision(bundle.decision) == identity
        )
        if not matches:
            raise R5PromotionRepositoryCorruption("required decision is unavailable")
        if len(matches) != 1:
            raise R5PromotionRepositoryCorruption("required decision has multiple exact matches")
        return matches[0]

    def _lifecycle_collision(
        self,
        bundle: R5RelativeValueLifecycleEventBundle,
    ) -> R5PromotionLifecycleEventModel | None:
        event = bundle.event
        evidence = bundle.authorization_evidence
        return (
            R5PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(
                models.Q(event_id=event.event_id, event_version=event.event_version)
                | models.Q(event_content_hash=event.content_hash)
                | models.Q(bundle_content_hash=bundle.content_hash)
                | models.Q(
                    authorization__evidence_id=evidence.evidence_id,
                    authorization__evidence_version=evidence.evidence_version,
                )
                | models.Q(stream_id=event.stream_id, sequence=event.sequence)
            )
            .select_related(
                "authorization",
                "decision__authorization",
                "decision__policy",
                "decision__trial",
                "rollback_target__authorization",
                "rollback_target__policy",
                "rollback_target__trial",
                "previous_event",
            )
            .first()
        )

    def _lifecycle_authorization_from_model(
        self,
        model: R5PromotionLifecycleAuthorizationModel,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence:
        try:
            evidence = decode_r5_lifecycle_authorization_evidence(model.canonical_payload)
            values = _lifecycle_authorization_model_values(
                evidence,
                ledger_recorded_at=model.ledger_recorded_at,
            )
            decision = self._decision_bundle_from_model(model.decision).decision
            target = (
                None
                if model.rollback_target is None
                else self._decision_bundle_from_model(model.rollback_target).decision
            )
        except (R5PromotionCodecError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization payload is invalid"
            ) from error
        if (
            not _model_matches(model, values)
            or evidence.authorization.decision
            != R5RelativeValueDecisionIdentity.from_decision(decision)
            or evidence.authorization.rollback_target
            != (None if target is None else R5RelativeValueDecisionIdentity.from_decision(target))
            or evidence.content_hash != r5_relative_value_lifecycle_evidence_hash(evidence)
        ):
            raise R5PromotionRepositoryCorruption(
                "lifecycle authorization header or decision references were tampered"
            )
        return evidence

    def _lifecycle_event_bundle_from_model(
        self,
        model: R5PromotionLifecycleEventModel,
    ) -> R5RelativeValueLifecycleEventBundle:
        try:
            bundle = decode_r5_lifecycle_event_bundle(model.canonical_payload)
            values = _lifecycle_event_model_values(
                bundle,
                ledger_recorded_at=model.ledger_recorded_at,
            )
            evidence = self._lifecycle_authorization_from_model(model.authorization)
            decision = self._decision_bundle_from_model(model.decision).decision
            target = (
                None
                if model.rollback_target is None
                else self._decision_bundle_from_model(model.rollback_target).decision
            )
        except (R5PromotionCodecError, TypeError, ValueError) as error:
            raise R5PromotionRepositoryCorruption("lifecycle event payload is invalid") from error
        event = bundle.event
        previous_hash = None if model.previous_event_hash == "" else model.previous_event_hash
        if (
            not _model_matches(model, values)
            or evidence != bundle.authorization_evidence
            or event.decision != R5RelativeValueDecisionIdentity.from_decision(decision)
            or event.rollback_target
            != (None if target is None else R5RelativeValueDecisionIdentity.from_decision(target))
            or event.previous_event_hash != previous_hash
            or (model.previous_event is None) != (event.previous_event_hash is None)
            or (
                model.previous_event is not None
                and model.previous_event.event_content_hash != event.previous_event_hash
            )
        ):
            raise R5PromotionRepositoryCorruption(
                "lifecycle event header, receipt or links were tampered"
            )
        return bundle

    def _lifecycle_models_for_scope(
        self,
        scope_id: str,
    ) -> tuple[R5PromotionLifecycleEventModel, ...]:
        stream_id = f"research:r5:relative-value:{scope_id}"
        return tuple(
            R5PromotionLifecycleEventModel._default_manager.using(self._using)
            .filter(
                models.Q(scope_id=scope_id)
                | models.Q(stream_id=stream_id)
                | models.Q(authorization__scope_id=scope_id)
                | models.Q(decision__scope_id=scope_id)
            )
            .select_related(
                "authorization",
                "decision__authorization",
                "decision__policy",
                "decision__trial",
                "rollback_target__authorization",
                "rollback_target__policy",
                "rollback_target__trial",
                "previous_event",
            )
            .order_by("pk")
        )

    def _restore_lifecycle_scope(
        self,
        scope_id: str,
    ) -> tuple[
        tuple[R5PromotionLifecycleEventModel, R5RelativeValueLifecycleEventBundle],
        ...,
    ]:
        expected_stream_id = f"research:r5:relative-value:{scope_id}"
        restored = tuple(
            (model, self._lifecycle_event_bundle_from_model(model))
            for model in self._lifecycle_models_for_scope(scope_id)
        )
        if any(
            bundle.event.scope.scope_id != scope_id or bundle.event.stream_id != expected_stream_id
            for _, bundle in restored
        ):
            raise R5PromotionRepositoryCorruption(
                "lifecycle scope anchors include a cross-scope or cross-stream event"
            )
        ordered = tuple(sorted(restored, key=lambda item: item[1].event.sequence))
        if tuple(item[1].event.sequence for item in ordered) != tuple(range(1, len(ordered) + 1)):
            raise R5PromotionRepositoryCorruption(
                "lifecycle sequence selectors are duplicated or discontinuous"
            )
        if ordered:
            try:
                derive_r5_relative_value_lifecycle_state(
                    tuple(item[1].event for item in ordered),
                    evaluated_at=max(item[1].event.recorded_at for item in ordered),
                )
            except ValueError as error:
                raise R5PromotionRepositoryCorruption(
                    "persisted lifecycle stream is forked or discontinuous"
                ) from error
        return ordered


class DjangoR5PromotionPolicyProvider:
    """Concrete exact PIT provider for persisted Research policies."""

    def __init__(self, repository: DjangoR5PromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared repository boundary."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        policy_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionPolicy | None:
        """Return one exact active policy."""

        return self._repository.get_exact_policy(policy_ref, as_of=as_of)


class DjangoR5PromotionTrialProvider:
    """Concrete exact PIT provider for persisted Research trials."""

    def __init__(self, repository: DjangoR5PromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared repository boundary."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        trial_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionTrial | None:
        """Return one exact active trial."""

        return self._repository.get_exact_trial(trial_ref, as_of=as_of)


class DjangoR5DecisionAuthorizationProvider:
    """Concrete exact PIT provider for persisted decision authorization."""

    def __init__(self, repository: DjangoR5PromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared repository boundary."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        """Return one persisted exact authorization."""

        return self._repository.get_exact_decision_authorization(
            authorization_ref=authorization_ref,
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            as_of=as_of,
        )


class DjangoR5LifecycleAuthorizationProvider:
    """Concrete exact provider for persisted lifecycle authorization evidence."""

    def __init__(self, repository: DjangoR5PromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared repository boundary."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        """Return one persisted exact lifecycle authorization."""

        return self._repository.get_exact_lifecycle_authorization(
            authorization_ref=authorization_ref,
            scope_ref=scope_ref,
            action=action,
            decision_ref=decision_ref,
            rollback_target_ref=rollback_target_ref,
        )


__all__ = [
    "DjangoR5DecisionAuthorizationProvider",
    "DjangoR5LifecycleAuthorizationProvider",
    "DjangoR5PromotionPolicyProvider",
    "DjangoR5PromotionRepository",
    "DjangoR5PromotionServerClock",
    "DjangoR5PromotionTrialProvider",
    "R5PromotionRepositoryConflict",
    "R5PromotionRepositoryCorruption",
    "R5PromotionServerClock",
]
