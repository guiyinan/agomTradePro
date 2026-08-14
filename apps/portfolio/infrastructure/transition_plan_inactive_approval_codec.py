"""Canonical codecs for inactive transition-plan approval ledgers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanInactiveApprovalSubject,
)
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
)


class TransitionPlanInactiveApprovalCodecError(ValueError):
    """A stored subject or receipt is malformed or non-canonical."""


def encode_transition_plan_inactive_approval_subject(
    value: TransitionPlanInactiveApprovalSubject,
) -> dict[str, object]:
    """Encode one complete immutable subject."""

    return {**value._content_payload(), "content_hash": value.content_hash}


def decode_transition_plan_inactive_approval_subject(
    payload: object,
) -> TransitionPlanInactiveApprovalSubject:
    """Restore and revalidate one complete immutable subject."""

    data = _mapping(
        payload,
        {
            "owner",
            "schema",
            "subject_id",
            "subject_version",
            "plan_id",
            "plan_version",
            "plan_content_hash",
            "account_id",
            "decision_snapshot_id",
            "requested_by",
            "requested_at",
            "valid_until",
            "execution_permission",
            "blocker_codes",
            "content_hash",
        },
    )
    try:
        value = TransitionPlanInactiveApprovalSubject(
            owner=_string(data["owner"]),
            schema=_string(data["schema"]),
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            plan_id=_string(data["plan_id"]),
            plan_version=_positive_integer(data["plan_version"]),
            plan_content_hash=_string(data["plan_content_hash"]),
            account_id=_string(data["account_id"]),
            decision_snapshot_id=_string(data["decision_snapshot_id"]),
            requested_by=_actor(data["requested_by"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            execution_permission=_string(data["execution_permission"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TransitionPlanInactiveApprovalCodecError, TypeError, ValueError) as error:
        raise TransitionPlanInactiveApprovalCodecError("approval subject is invalid") from error
    _canonical(payload, encode_transition_plan_inactive_approval_subject(value))
    return value


def encode_transition_plan_inactive_approval_receipt(
    value: TransitionPlanApprovalReceipt,
) -> dict[str, object]:
    """Encode one complete immutable receipt without its derived flag."""

    payload = value.to_payload()
    return {key: item for key, item in payload.items() if key != "must_not_execute"}


def decode_transition_plan_inactive_approval_receipt(
    payload: object,
) -> TransitionPlanApprovalReceipt:
    """Restore and revalidate one complete immutable receipt."""

    data = _mapping(
        payload,
        {
            "owner",
            "schema",
            "receipt_id",
            "receipt_version",
            "subject_id",
            "subject_version",
            "subject_content_hash",
            "plan_id",
            "plan_version",
            "plan_content_hash",
            "account_id",
            "decision_snapshot_id",
            "requested_by",
            "approved_by",
            "issued_at",
            "valid_until",
            "plan_status_at_issue",
            "approval_state",
            "execution_permission",
            "blocker_codes",
            "content_hash",
        },
    )
    try:
        value = TransitionPlanApprovalReceipt(
            owner=_string(data["owner"]),
            schema=_string(data["schema"]),
            receipt_id=_string(data["receipt_id"]),
            receipt_version=_string(data["receipt_version"]),
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            subject_content_hash=_string(data["subject_content_hash"]),
            plan_id=_string(data["plan_id"]),
            plan_version=_positive_integer(data["plan_version"]),
            plan_content_hash=_string(data["plan_content_hash"]),
            account_id=_string(data["account_id"]),
            decision_snapshot_id=_string(data["decision_snapshot_id"]),
            requested_by=_actor(data["requested_by"]),
            approved_by=_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            plan_status_at_issue=_string(data["plan_status_at_issue"]),
            approval_state=_string(data["approval_state"]),
            execution_permission=_string(data["execution_permission"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TransitionPlanInactiveApprovalCodecError, TypeError, ValueError) as error:
        raise TransitionPlanInactiveApprovalCodecError("approval receipt is invalid") from error
    _canonical(payload, encode_transition_plan_inactive_approval_receipt(value))
    return value


def _actor(payload: object) -> TransitionPlanApprovalActor:
    data = _mapping(payload, {"actor_id", "user_id", "role", "kind", "is_staff"})
    return TransitionPlanApprovalActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise TransitionPlanInactiveApprovalCodecError("approval payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected bool")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError("expected string array")
    return tuple(cast(list[str], value))


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


def _canonical(original: object, canonical: dict[str, object]) -> None:
    if original != canonical:
        raise TransitionPlanInactiveApprovalCodecError("approval payload is not canonical")


__all__ = [
    "TransitionPlanInactiveApprovalCodecError",
    "decode_transition_plan_inactive_approval_receipt",
    "decode_transition_plan_inactive_approval_subject",
    "encode_transition_plan_inactive_approval_receipt",
    "encode_transition_plan_inactive_approval_subject",
]
