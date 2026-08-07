"""Strict canonical JSON codec for R2 promotion ledgers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureEvidenceSeal,
    R2MarketStructureLifecycleAction,
    R2MarketStructureLifecycleAuthorization,
    R2MarketStructureLifecycleEvent,
    R2MarketStructureLifecycleEventType,
    R2MarketStructurePromotionDecision,
    R2MarketStructurePromotionDecisionOutcome,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionRef,
    R2MarketStructurePromotionScope,
    create_r2_market_structure_promotion_decision,
)


class R2MarketStructurePromotionCodecError(ValueError):
    """Raised when canonical ledger bytes cannot be restored exactly."""


def _object(payload: object, label: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise R2MarketStructurePromotionCodecError(f"{label} must be an object")
    return cast(dict[str, object], payload)


def _require_exact_keys(
    payload: dict[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(payload) != expected:
        raise R2MarketStructurePromotionCodecError(
            f"{label} contains missing or unsupported fields"
        )


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise R2MarketStructurePromotionCodecError(f"{key} must be text")
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise R2MarketStructurePromotionCodecError(f"{key} must be an integer")
    return value


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise R2MarketStructurePromotionCodecError(f"{key} must be a boolean")
    return value


def _datetime(payload: dict[str, object], key: str) -> datetime:
    try:
        return datetime.fromisoformat(_text(payload, key))
    except ValueError as error:
        raise R2MarketStructurePromotionCodecError(f"{key} must be an ISO datetime") from error


def _texts(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise R2MarketStructurePromotionCodecError(f"{key} must be a text list")
    return tuple(cast(list[str], value))


def _ref(payload: object, label: str) -> R2MarketStructurePromotionRef:
    value = _object(payload, label)
    reference = R2MarketStructurePromotionRef(
        stable_id=_text(value, "stable_id"),
        version=_text(value, "version"),
    )
    _require_exact_keys(value, set(reference.to_payload()), label)
    return reference


def _optional_ref(payload: object, label: str) -> R2MarketStructurePromotionRef | None:
    return None if payload is None else _ref(payload, label)


def _scope(payload: object) -> R2MarketStructurePromotionScope:
    value = _object(payload, "scope")
    scope = R2MarketStructurePromotionScope(
        group_code=_text(value, "group_code"),
        group_revision=_integer(value, "group_revision"),
        method_version=_text(value, "method_version"),
        policy_code=_text(value, "policy_code"),
        policy_version=_integer(value, "policy_version"),
        scope_id=_text(value, "scope_id"),
        content_hash=_text(value, "content_hash"),
    )
    _require_exact_keys(value, set(scope.to_payload()), "scope")
    return scope


def _evidence(payload: object) -> R2MarketStructureEvidenceSeal:
    value = _object(payload, "evidence")
    evidence = R2MarketStructureEvidenceSeal(
        evidence_key=_text(value, "evidence_key"),
        evidence_version=_integer(value, "evidence_version"),
        evidence_hash=_text(value, "evidence_hash"),
        input_hash=_text(value, "input_hash"),
        output_hash=_text(value, "output_hash"),
        scope=_scope(value.get("scope")),
        as_of_time=_datetime(value, "as_of_time"),
        publication_ids=_texts(value, "publication_ids"),
        publication_hashes=_texts(value, "publication_hashes"),
        publication_datasets=_texts(value, "publication_datasets"),
        content_hash=_text(value, "content_hash"),
    )
    _require_exact_keys(value, set(evidence.to_payload()), "evidence")
    expected = canonical_hash(
        {
            "as_of_time": evidence.as_of_time.astimezone(UTC).isoformat(),
            "evidence_hash": evidence.evidence_hash,
            "evidence_key": evidence.evidence_key,
            "evidence_version": evidence.evidence_version,
            "input_hash": evidence.input_hash,
            "output_hash": evidence.output_hash,
            "publication_datasets": evidence.publication_datasets,
            "publication_hashes": evidence.publication_hashes,
            "publication_ids": evidence.publication_ids,
            "schema": "research-r2-market-structure-evidence-seal.v1",
            "scope": evidence.scope.to_payload(),
        }
    )
    if expected != evidence.content_hash:
        raise R2MarketStructurePromotionCodecError("evidence content hash mismatch")
    return evidence


def _policy(payload: object) -> R2MarketStructurePromotionPolicy:
    value = _object(payload, "policy")
    policy = R2MarketStructurePromotionPolicy(
        policy_id=_text(value, "policy_id"),
        policy_version=_text(value, "policy_version"),
        scope=_scope(value.get("scope")),
        required_publication_datasets=_texts(value, "required_publication_datasets"),
        owner_approval_ref=_text(value, "owner_approval_ref"),
        owner_approval_hash=_text(value, "owner_approval_hash"),
        registered_at=_datetime(value, "registered_at"),
        active_from=_datetime(value, "active_from"),
        valid_until=_datetime(value, "valid_until"),
        content_hash=_text(value, "content_hash"),
        research_only=_boolean(value, "research_only"),
        structure_description_only=_boolean(value, "structure_description_only"),
        must_not_use_for_decision=_boolean(value, "must_not_use_for_decision"),
        must_not_execute=_boolean(value, "must_not_execute"),
    )
    _require_exact_keys(value, set(policy.to_payload()), "policy")
    return policy


def _decision_authorization(
    payload: object,
    *,
    policy: R2MarketStructurePromotionPolicy,
    evidence: R2MarketStructureEvidenceSeal,
) -> R2MarketStructureDecisionAuthorization:
    value = _object(payload, "decision authorization")
    authorization = R2MarketStructureDecisionAuthorization(
        authorization_id=_text(value, "authorization_id"),
        authorization_version=_text(value, "authorization_version"),
        policy_ref=_ref(value.get("policy_ref"), "policy_ref"),
        policy_content_hash=_text(value, "policy_content_hash"),
        evidence_ref=_ref(value.get("evidence_ref"), "evidence_ref"),
        evidence_content_hash=_text(value, "evidence_content_hash"),
        scope_id=_text(value, "scope_id"),
        scope_content_hash=_text(value, "scope_content_hash"),
        issued_at=_datetime(value, "issued_at"),
        decided_at=_datetime(value, "decided_at"),
        decision_recorded_at=_datetime(value, "decision_recorded_at"),
        valid_until=_datetime(value, "valid_until"),
        owner_receipt_hash=_text(value, "owner_receipt_hash"),
        content_hash=_text(value, "content_hash"),
    )
    _require_exact_keys(
        value,
        set(authorization.to_payload()),
        "decision authorization",
    )
    rebuilt = R2MarketStructureDecisionAuthorization.create(
        authorization_version=authorization.authorization_version,
        policy=policy,
        evidence=evidence,
        issued_at=authorization.issued_at,
        decided_at=authorization.decided_at,
        decision_recorded_at=authorization.decision_recorded_at,
        valid_until=authorization.valid_until,
        owner_receipt_hash=authorization.owner_receipt_hash,
    )
    if rebuilt != authorization:
        raise R2MarketStructurePromotionCodecError("decision authorization hash mismatch")
    return authorization


def encode_r2_market_structure_policy(
    policy: R2MarketStructurePromotionPolicy,
) -> str:
    """Encode one exact policy."""

    return json.dumps(
        policy.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def decode_r2_market_structure_policy(payload: str) -> R2MarketStructurePromotionPolicy:
    """Restore one exact policy."""

    try:
        return _policy(json.loads(payload))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, R2MarketStructurePromotionCodecError):
            raise
        raise R2MarketStructurePromotionCodecError("invalid R2 policy payload") from error


def encode_r2_market_structure_decision(
    decision: R2MarketStructurePromotionDecision,
) -> str:
    """Encode one exact decision graph."""

    return json.dumps(
        decision.to_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_r2_market_structure_decision(
    payload: str,
) -> R2MarketStructurePromotionDecision:
    """Restore and factory-replay one exact decision graph."""

    try:
        value = _object(json.loads(payload), "decision")
        policy = _policy(value.get("policy"))
        evidence = _evidence(value.get("evidence"))
        authorization = _decision_authorization(
            value.get("authorization"),
            policy=policy,
            evidence=evidence,
        )
        decision = R2MarketStructurePromotionDecision(
            decision_id=_text(value, "decision_id"),
            decision_version=_text(value, "decision_version"),
            outcome=R2MarketStructurePromotionDecisionOutcome(_text(value, "outcome")),
            policy=policy,
            evidence=evidence,
            authorization=authorization,
            decided_at=_datetime(value, "decided_at"),
            recorded_at=_datetime(value, "recorded_at"),
            valid_until=_datetime(value, "valid_until"),
            reason_codes=_texts(value, "reason_codes"),
            content_hash=_text(value, "content_hash"),
            research_only=_boolean(value, "research_only"),
            structure_description_only=_boolean(value, "structure_description_only"),
            must_not_use_for_decision=_boolean(value, "must_not_use_for_decision"),
            must_not_execute=_boolean(value, "must_not_execute"),
        )
        _require_exact_keys(value, set(decision.to_payload()), "decision")
        if (
            create_r2_market_structure_promotion_decision(
                policy=policy,
                evidence=evidence,
                authorization=authorization,
            )
            != decision
        ):
            raise R2MarketStructurePromotionCodecError("decision factory replay mismatch")
        return decision
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, R2MarketStructurePromotionCodecError):
            raise
        raise R2MarketStructurePromotionCodecError("invalid R2 decision payload") from error


def _lifecycle_authorization(payload: object) -> R2MarketStructureLifecycleAuthorization:
    value = _object(payload, "lifecycle authorization")
    authorization = R2MarketStructureLifecycleAuthorization(
        authorization_id=_text(value, "authorization_id"),
        authorization_version=_text(value, "authorization_version"),
        scope_id=_text(value, "scope_id"),
        scope_content_hash=_text(value, "scope_content_hash"),
        action=R2MarketStructureLifecycleAction(_text(value, "action")),
        decision_ref=_ref(value.get("decision_ref"), "decision_ref"),
        decision_content_hash=_text(value, "decision_content_hash"),
        rollback_target_ref=_optional_ref(
            value.get("rollback_target_ref"),
            "rollback_target_ref",
        ),
        rollback_target_content_hash=_text(value, "rollback_target_content_hash"),
        issued_at=_datetime(value, "issued_at"),
        occurred_at=_datetime(value, "occurred_at"),
        event_recorded_at=_datetime(value, "event_recorded_at"),
        valid_until=_datetime(value, "valid_until"),
        reason_codes=_texts(value, "reason_codes"),
        owner_receipt_hash=_text(value, "owner_receipt_hash"),
        content_hash=_text(value, "content_hash"),
    )
    _require_exact_keys(
        value,
        set(authorization.to_payload()),
        "lifecycle authorization",
    )
    expected = canonical_hash(
        {
            **{
                key: item
                for key, item in authorization.to_payload().items()
                if key not in {"authorization_id", "content_hash"}
            },
            "schema": "research-r2-market-structure-lifecycle-authorization.v1",
        }
    )
    if (
        expected != authorization.content_hash
        or authorization.authorization_id != f"r2-ms-lifecycle-auth-{expected}"
    ):
        raise R2MarketStructurePromotionCodecError("lifecycle authorization hash mismatch")
    return authorization


def encode_r2_market_structure_lifecycle_event(
    event: R2MarketStructureLifecycleEvent,
) -> str:
    """Encode one exact lifecycle event graph."""

    return json.dumps(event.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def decode_r2_market_structure_lifecycle_event(
    payload: str,
) -> R2MarketStructureLifecycleEvent:
    """Restore and hash-replay one exact lifecycle event graph."""

    try:
        value = _object(json.loads(payload), "lifecycle event")
        authorization = _lifecycle_authorization(value.get("authorization"))
        event = R2MarketStructureLifecycleEvent(
            event_id=_text(value, "event_id"),
            event_version=_text(value, "event_version"),
            scope_id=_text(value, "scope_id"),
            scope_content_hash=_text(value, "scope_content_hash"),
            stream_id=_text(value, "stream_id"),
            sequence=_integer(value, "sequence"),
            event_type=R2MarketStructureLifecycleEventType(_text(value, "event_type")),
            decision_ref=_ref(value.get("decision_ref"), "decision_ref"),
            decision_content_hash=_text(value, "decision_content_hash"),
            rollback_target_ref=_optional_ref(
                value.get("rollback_target_ref"),
                "rollback_target_ref",
            ),
            rollback_target_content_hash=_text(value, "rollback_target_content_hash"),
            authorization=authorization,
            previous_event_hash=_text(value, "previous_event_hash"),
            occurred_at=_datetime(value, "occurred_at"),
            recorded_at=_datetime(value, "recorded_at"),
            content_hash=_text(value, "content_hash"),
        )
        _require_exact_keys(value, set(event.to_payload()), "lifecycle event")
        expected = canonical_hash(
            {
                **{
                    key: item
                    for key, item in event.to_payload().items()
                    if key not in {"event_id", "content_hash"}
                },
                "schema": "research-r2-market-structure-lifecycle-event.v1",
            }
        )
        if expected != event.content_hash or event.event_id != f"r2-ms-lifecycle-{expected}":
            raise R2MarketStructurePromotionCodecError("lifecycle event hash mismatch")
        return event
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, R2MarketStructurePromotionCodecError):
            raise
        raise R2MarketStructurePromotionCodecError("invalid R2 lifecycle payload") from error


__all__ = [
    "R2MarketStructurePromotionCodecError",
    "decode_r2_market_structure_decision",
    "decode_r2_market_structure_lifecycle_event",
    "decode_r2_market_structure_policy",
    "encode_r2_market_structure_decision",
    "encode_r2_market_structure_lifecycle_event",
    "encode_r2_market_structure_policy",
]
