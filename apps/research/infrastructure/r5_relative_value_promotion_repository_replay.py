"""Replay and collision helpers for the Research R5 promotion repository."""

from __future__ import annotations

from django.db import models

from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionRef,
    r5_relative_value_decision_authorization_hash,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
    R5RelativeValueLifecycleScopeRef,
    r5_relative_value_lifecycle_evidence_hash,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionArtifact,
    R5PromotionArtifactKind,
    r5_promotion_artifact_registration_command_hash,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    derive_r5_relative_value_lifecycle_state,
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
)
from apps.research.infrastructure.r5_relative_value_promotion_repository_support import (
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


class R5PromotionRepositoryReplayMixin:
    """Strictly replay persisted R5 promotion evidence."""

    _using: str

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
