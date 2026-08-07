"""Shared value mapping and errors for the R5 promotion repository."""

from __future__ import annotations

from datetime import datetime

from django.db import models
from django.utils import timezone

from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionArtifact,
    R5PromotionArtifactKind,
    r5_promotion_artifact_registration_command_hash,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_relative_value_promotion_codec import (
    encode_r5_decision_authorization,
    encode_r5_decision_bundle,
    encode_r5_lifecycle_authorization_evidence,
    encode_r5_lifecycle_event_bundle,
    encode_r5_promotion_artifact,
)


class R5PromotionRepositoryConflict(R5RelativeValuePromotionEvidenceError):
    """Raised when one immutable identity collides with different evidence."""

    def __init__(self, detail: str) -> None:
        super().__init__("r5_promotion.repository_conflict", detail)


class R5PromotionRepositoryCorruption(R5RelativeValuePromotionEvidenceError):
    """Raised when stored payload, headers, references or seals disagree."""

    def __init__(self, detail: str) -> None:
        super().__init__("r5_promotion.repository_corruption", detail)


class DjangoR5PromotionServerClock:
    """Production clock backed by Django's timezone-aware clock."""

    def now(self) -> datetime:
        """Return the current server timestamp."""

        return timezone.now()


def _ledger_receipt_hash(
    *,
    receipt_kind: str,
    identity: tuple[str, ...],
    content_hash: str,
    ledger_recorded_at: datetime,
) -> str:
    require_aware(ledger_recorded_at, "R5 promotion ledger_recorded_at")
    require_sha256(content_hash, "R5 promotion ledger content_hash")
    return canonical_hash(
        {
            "schema": "research-r5-promotion-ledger-receipt.v1",
            "receipt_kind": receipt_kind,
            "identity": identity,
            "content_hash": content_hash,
            "ledger_recorded_at": ledger_recorded_at,
        }
    )


def _content_hash_anchor(stable_id: str, *, prefix: str) -> str | None:
    """Return the content-address suffix only for one canonical namespace."""

    expected_prefix = f"{prefix}:"
    if not stable_id.startswith(expected_prefix):
        return None
    digest = stable_id.removeprefix(expected_prefix)
    try:
        require_sha256(digest, "R5 promotion content-address anchor")
    except ValueError:
        return None
    return digest


def _artifact_kind(artifact: R5PromotionArtifact) -> R5PromotionArtifactKind:
    if type(artifact) is R5RelativeValuePromotionPolicy:
        return R5PromotionArtifactKind.POLICY
    if type(artifact) is R5RelativeValuePromotionTrial:
        return R5PromotionArtifactKind.TRIAL
    raise R5PromotionRepositoryCorruption("unsupported R5 promotion artifact type")


def _artifact_ref(artifact: R5PromotionArtifact) -> R5RelativeValuePromotionRef:
    if isinstance(artifact, R5RelativeValuePromotionPolicy):
        return R5RelativeValuePromotionRef(artifact.policy_id, artifact.policy_version)
    return R5RelativeValuePromotionRef(artifact.trial_id, artifact.trial_version)


def _artifact_recorded_at(artifact: R5PromotionArtifact) -> datetime:
    return artifact.recorded_at


def _artifact_active_from(artifact: R5PromotionArtifact) -> datetime:
    if isinstance(artifact, R5RelativeValuePromotionPolicy):
        return artifact.active_from
    return artifact.recorded_at


def _artifact_valid_until(artifact: R5PromotionArtifact) -> datetime:
    if isinstance(artifact, R5RelativeValuePromotionPolicy):
        return artifact.active_until
    return artifact.valid_until


def _artifact_model_values(
    artifact: R5PromotionArtifact,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    kind = _artifact_kind(artifact)
    ref = _artifact_ref(artifact)
    command_hash = r5_promotion_artifact_registration_command_hash(
        artifact_kind=kind,
        artifact_ref=ref,
    )
    receipt_hash = _ledger_receipt_hash(
        receipt_kind=f"artifact:{kind.value}",
        identity=(ref.stable_id, ref.version),
        content_hash=artifact.content_hash,
        ledger_recorded_at=ledger_recorded_at,
    )
    return {
        "artifact_kind": kind.value,
        "stable_id": ref.stable_id,
        "version": ref.version,
        "owner": artifact.owner,
        "capability": artifact.capability,
        "purpose": artifact.purpose,
        "scope_id": artifact.scope.scope_id,
        "scope_content_hash": artifact.scope.content_hash,
        "semantic_recorded_at": _artifact_recorded_at(artifact),
        "active_from": _artifact_active_from(artifact),
        "valid_until": _artifact_valid_until(artifact),
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": receipt_hash,
        "command_hash": command_hash,
        "canonical_payload": encode_r5_promotion_artifact(artifact),
        "content_hash": artifact.content_hash,
        "research_only": artifact.research_only,
        "must_not_use_for_decision": artifact.must_not_use_for_decision,
        "must_not_execute": artifact.must_not_execute,
    }


def _decision_authorization_model_values(
    authorization: R5RelativeValueDecisionAuthorization,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    receipt_hash = _ledger_receipt_hash(
        receipt_kind="decision_authorization",
        identity=(authorization.authorization_id, authorization.authorization_version),
        content_hash=authorization.content_hash,
        ledger_recorded_at=ledger_recorded_at,
    )
    return {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "owner": authorization.owner,
        "capability": authorization.capability,
        "purpose": authorization.purpose,
        "scope_id": authorization.scope_id,
        "scope_content_hash": authorization.scope_content_hash,
        "issued_at": authorization.issued_at,
        "recorded_at": authorization.recorded_at,
        "decided_at": authorization.decided_at,
        "decision_recorded_at": authorization.decision_recorded_at,
        "decision_valid_until": authorization.decision_valid_until,
        "valid_until": authorization.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": receipt_hash,
        "canonical_payload": encode_r5_decision_authorization(authorization),
        "content_hash": authorization.content_hash,
    }


def _decision_bundle_model_values(
    bundle: R5RelativeValuePromotionDecisionBundle,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    decision = bundle.decision
    receipt_hash = _ledger_receipt_hash(
        receipt_kind="decision_bundle",
        identity=(decision.decision_id, decision.decision_version),
        content_hash=bundle.content_hash,
        ledger_recorded_at=ledger_recorded_at,
    )
    return {
        "decision_id": decision.decision_id,
        "decision_version": decision.decision_version,
        "owner": decision.owner,
        "capability": decision.capability,
        "purpose": decision.purpose,
        "scope_id": decision.scope.scope_id,
        "scope_content_hash": decision.scope.content_hash,
        "outcome": decision.outcome.value,
        "decided_at": decision.decided_at,
        "recorded_at": decision.recorded_at,
        "valid_until": decision.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": receipt_hash,
        "canonical_payload": encode_r5_decision_bundle(bundle),
        "decision_content_hash": decision.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "research_only": decision.research_only,
        "must_not_use_for_decision": decision.must_not_use_for_decision,
        "must_not_execute": decision.must_not_execute,
    }


def _lifecycle_authorization_model_values(
    evidence: R5RelativeValueLifecycleAuthorizationEvidence,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    authorization = evidence.authorization
    receipt_hash = _ledger_receipt_hash(
        receipt_kind="lifecycle_authorization",
        identity=(evidence.evidence_id, evidence.evidence_version),
        content_hash=evidence.content_hash,
        ledger_recorded_at=ledger_recorded_at,
    )
    return {
        "evidence_id": evidence.evidence_id,
        "evidence_version": evidence.evidence_version,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "scope_id": authorization.scope.scope_id,
        "scope_content_hash": authorization.scope.content_hash,
        "event_id": evidence.event_ref.stable_id,
        "event_version": evidence.event_ref.version,
        "event_type": authorization.event_type.value,
        "reason_codes": list(evidence.reason_codes),
        "reason_hash": authorization.reason_hash,
        "authorization_issued_at": authorization.issued_at,
        "authorization_recorded_at": authorization.recorded_at,
        "authorization_valid_until": authorization.valid_until,
        "receipt_recorded_at": evidence.receipt_recorded_at,
        "occurred_at": evidence.occurred_at,
        "event_recorded_at": evidence.event_recorded_at,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": receipt_hash,
        "authorization_content_hash": authorization.content_hash,
        "evidence_content_hash": evidence.content_hash,
        "event_content_hash": evidence.event_content_hash,
        "canonical_payload": encode_r5_lifecycle_authorization_evidence(evidence),
    }


def _lifecycle_event_model_values(
    bundle: R5RelativeValueLifecycleEventBundle,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    event = bundle.event
    receipt_hash = _ledger_receipt_hash(
        receipt_kind="lifecycle_event",
        identity=(event.event_id, event.event_version),
        content_hash=bundle.content_hash,
        ledger_recorded_at=ledger_recorded_at,
    )
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "scope_id": event.scope.scope_id,
        "scope_content_hash": event.scope.content_hash,
        "stream_id": event.stream_id,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "reason_codes": list(event.reason_codes),
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "ledger_recorded_at": ledger_recorded_at,
        "ledger_receipt_hash": receipt_hash,
        "previous_event_hash": event.previous_event_hash or "",
        "canonical_payload": encode_r5_lifecycle_event_bundle(bundle),
        "event_content_hash": event.content_hash,
        "bundle_content_hash": bundle.content_hash,
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_execute": event.must_not_execute,
    }


def _model_matches(model: models.Model, values: dict[str, object]) -> bool:
    return all(getattr(model, field_name) == value for field_name, value in values.items())
