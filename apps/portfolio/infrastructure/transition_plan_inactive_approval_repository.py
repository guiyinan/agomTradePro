"""Append-only persistence for inactive transition-plan approvals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanInactiveApprovalConflict,
    TransitionPlanInactiveApprovalCorruption,
    TransitionPlanInactiveApprovalSubject,
    TransitionPlanInactiveApprovalUnavailable,
)
from apps.portfolio.domain.transition_plan_integrity import TransitionPlanApprovalReceipt
from apps.portfolio.infrastructure.transition_plan_inactive_approval_codec import (
    TransitionPlanInactiveApprovalCodecError,
    decode_transition_plan_inactive_approval_receipt,
    decode_transition_plan_inactive_approval_subject,
    encode_transition_plan_inactive_approval_receipt,
    encode_transition_plan_inactive_approval_subject,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_models import (
    _ACTIVE_TRANSITION_APPROVAL_UOW,
    TransitionPlanInactiveApprovalReceiptModel,
    TransitionPlanInactiveApprovalSubjectModel,
    _activate_transition_plan_inactive_approval_uow,
    _claim_transition_plan_inactive_approval_insert,
)


class TransitionPlanInactiveApprovalClock(Protocol):
    """Authoritative Portfolio persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware timestamp."""


class DjangoTransitionPlanInactiveApprovalClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoTransitionPlanInactiveApprovalRepository:
    """Private append store and strict identity/hash/PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: TransitionPlanInactiveApprovalClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoTransitionPlanInactiveApprovalClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private first-winner transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_transition_plan_inactive_approval_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TransitionPlanInactiveApprovalCorruption("Portfolio approval clock is naive")
        return value

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> TransitionPlanInactiveApprovalSubject | None:
        """Return one immutable subject winner knowable at the cutoff."""

        self._require_cutoff(as_of)
        identity = _identity_hash("subject", subject_id, subject_version)
        rows = list(
            TransitionPlanInactiveApprovalSubjectModel._default_manager.using(self._using).filter(
                Q(subject_id=subject_id, subject_version=subject_version)
                | Q(subject_identity_hash=identity)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_subject(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.subject_id == subject_id and value.subject_version == subject_version
        )
        if len(matches) != 1:
            raise TransitionPlanInactiveApprovalCorruption("approval subject identity ambiguous")
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        """Return one immutable receipt winner knowable at the cutoff."""

        self._require_cutoff(as_of)
        identity = _identity_hash("receipt", receipt_id, receipt_version)
        rows = list(
            TransitionPlanInactiveApprovalReceiptModel._default_manager.using(self._using)
            .select_related("subject_record")
            .filter(
                Q(receipt_id=receipt_id, receipt_version=receipt_version)
                | Q(receipt_identity_hash=identity)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_receipt(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.receipt_id == receipt_id and value.receipt_version == receipt_version
        )
        if len(matches) != 1:
            raise TransitionPlanInactiveApprovalCorruption("approval receipt identity ambiguous")
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def append_subject(
        self, subject: TransitionPlanInactiveApprovalSubject, *, recorded_at: datetime
    ) -> TransitionPlanInactiveApprovalSubject:
        """Append or return one exact subject first winner."""

        if recorded_at != subject.requested_at:
            raise TransitionPlanInactiveApprovalConflict(
                "approval subject must use the authoritative transaction clock"
            )
        _active_token()
        existing = self._exact_subject_model(subject)
        if existing is not None:
            return self._restore_subject(existing)
        values = _subject_values(subject, recorded_at)
        model = TransitionPlanInactiveApprovalSubjectModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_transition_plan_inactive_approval_insert(
                    token=_active_token(),
                    model_type=TransitionPlanInactiveApprovalSubjectModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_subject_model(subject)
            if winner is None:
                raise TransitionPlanInactiveApprovalConflict(
                    "approval subject append conflicted without exact first winner"
                ) from None
            return self._restore_subject(winner)
        return self._restore_subject(model)

    def append(
        self,
        receipt: TransitionPlanApprovalReceipt,
        *,
        subject: TransitionPlanInactiveApprovalSubject,
        recorded_at: datetime,
    ) -> TransitionPlanApprovalReceipt:
        """Append an inactive receipt against its persisted exact subject."""

        if recorded_at != receipt.issued_at:
            raise TransitionPlanInactiveApprovalConflict(
                "approval receipt must use the authoritative transaction clock"
            )
        _active_token()
        subject_model = self._exact_subject_model(subject)
        if subject_model is None:
            raise TransitionPlanInactiveApprovalConflict(
                "approval receipt requires its persisted exact subject"
            )
        if (
            receipt.subject_id != subject.subject_id
            or receipt.subject_version != subject.subject_version
            or receipt.subject_content_hash != subject.content_hash
            or receipt.requested_by != subject.requested_by
            or receipt.plan_id != subject.plan_id
            or receipt.plan_version != subject.plan_version
            or receipt.plan_content_hash != subject.plan_content_hash
            or receipt.account_id != subject.account_id
            or receipt.decision_snapshot_id != subject.decision_snapshot_id
        ):
            raise TransitionPlanInactiveApprovalConflict("receipt does not bind exact subject")
        existing = self._exact_receipt_model(receipt, subject)
        if existing is not None:
            return self._restore_receipt(existing)
        values = _receipt_values(receipt, subject, recorded_at)
        claimed = {**values, "subject_record_id": subject_model.pk}
        model = TransitionPlanInactiveApprovalReceiptModel(**claimed)
        try:
            with transaction.atomic(using=self._using):
                with _claim_transition_plan_inactive_approval_insert(
                    token=_active_token(),
                    model_type=TransitionPlanInactiveApprovalReceiptModel,
                    expected_values=claimed,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_receipt_model(receipt, subject)
            if winner is None:
                raise TransitionPlanInactiveApprovalConflict(
                    "approval receipt append conflicted without exact first winner"
                ) from None
            return self._restore_receipt(winner)
        return self._restore_receipt(model)

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TransitionPlanApprovalReceipt | None:
        """Return one exact valid receipt by identity, hash, and PIT cutoff."""

        self._require_cutoff(as_of)
        identity = _identity_hash("receipt", receipt_id, receipt_version)
        rows = list(
            TransitionPlanInactiveApprovalReceiptModel._default_manager.using(self._using)
            .select_related("subject_record")
            .filter(
                Q(receipt_id=receipt_id, receipt_version=receipt_version)
                | Q(receipt_identity_hash=identity)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_receipt(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.receipt_id == receipt_id
            and value.receipt_version == receipt_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            raise TransitionPlanInactiveApprovalCorruption(
                "exact approval receipt identity/hash mismatch"
            )
        value, row = matches[0]
        if row.recorded_at > as_of or not value.issued_at <= as_of < value.valid_until:
            return None
        return value

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise TransitionPlanInactiveApprovalUnavailable("approval as_of is naive")
        if as_of > self.now():
            raise TransitionPlanInactiveApprovalUnavailable("future approval as_of is forbidden")

    def _exact_subject_model(
        self, subject: TransitionPlanInactiveApprovalSubject
    ) -> TransitionPlanInactiveApprovalSubjectModel | None:
        identity = _identity_hash("subject", subject.subject_id, subject.subject_version)
        rows = list(
            TransitionPlanInactiveApprovalSubjectModel._default_manager.using(self._using).filter(
                Q(subject_id=subject.subject_id, subject_version=subject.subject_version)
                | Q(subject_identity_hash=identity)
                | Q(plan_id=subject.plan_id, plan_version=subject.plan_version)
                | Q(content_hash=subject.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore_subject(row) == subject)
        if len(rows) != 1 or len(matches) != 1:
            raise TransitionPlanInactiveApprovalConflict(
                "approval subject uniqueness anchor has another first winner"
            )
        return matches[0]

    def _restore_subject(
        self, model: TransitionPlanInactiveApprovalSubjectModel
    ) -> TransitionPlanInactiveApprovalSubject:
        try:
            value = decode_transition_plan_inactive_approval_subject(model.canonical_payload)
        except TransitionPlanInactiveApprovalCodecError as error:
            raise TransitionPlanInactiveApprovalCorruption(
                "approval subject payload cannot be restored"
            ) from error
        if _subject_headers(value) != _subject_model_headers(model):
            raise TransitionPlanInactiveApprovalCorruption(
                "approval subject headers do not match payload"
            )
        if model.subject_identity_hash != _identity_hash(
            "subject", value.subject_id, value.subject_version
        ) or model.ledger_header_hash != _subject_ledger_hash(value, model.recorded_at):
            raise TransitionPlanInactiveApprovalCorruption("approval subject seal is invalid")
        if model.persisted_at < model.recorded_at:
            raise TransitionPlanInactiveApprovalCorruption(
                "approval subject persistence clock is invalid"
            )
        return value

    def _exact_receipt_model(
        self,
        receipt: TransitionPlanApprovalReceipt,
        subject: TransitionPlanInactiveApprovalSubject,
    ) -> TransitionPlanInactiveApprovalReceiptModel | None:
        identity = _identity_hash("receipt", receipt.receipt_id, receipt.receipt_version)
        rows = list(
            TransitionPlanInactiveApprovalReceiptModel._default_manager.using(self._using)
            .select_related("subject_record")
            .filter(
                Q(receipt_id=receipt.receipt_id, receipt_version=receipt.receipt_version)
                | Q(receipt_identity_hash=identity)
                | Q(subject_hash=subject.content_hash)
                | Q(plan_id=receipt.plan_id, plan_version=receipt.plan_version)
                | Q(content_hash=receipt.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore_receipt(row) == receipt)
        if len(rows) != 1 or len(matches) != 1:
            raise TransitionPlanInactiveApprovalConflict(
                "approval receipt uniqueness anchor has another first winner"
            )
        return matches[0]

    def _restore_receipt(
        self, model: TransitionPlanInactiveApprovalReceiptModel
    ) -> TransitionPlanApprovalReceipt:
        subject = self._restore_subject(model.subject_record)
        try:
            value = decode_transition_plan_inactive_approval_receipt(model.canonical_payload)
        except TransitionPlanInactiveApprovalCodecError as error:
            raise TransitionPlanInactiveApprovalCorruption(
                "approval receipt payload cannot be restored"
            ) from error
        if _receipt_headers(value, subject) != _receipt_model_headers(model):
            raise TransitionPlanInactiveApprovalCorruption(
                "approval receipt headers do not match payload"
            )
        if model.receipt_identity_hash != _identity_hash(
            "receipt", value.receipt_id, value.receipt_version
        ) or model.ledger_header_hash != _receipt_ledger_hash(value, subject, model.recorded_at):
            raise TransitionPlanInactiveApprovalCorruption("approval receipt seal is invalid")
        if (
            model.subject_record.recorded_at > model.recorded_at
            or value.issued_at != model.recorded_at
            or model.persisted_at < model.recorded_at
        ):
            raise TransitionPlanInactiveApprovalCorruption("approval receipt clock is invalid")
        return value


def _active_token() -> object:
    token = _ACTIVE_TRANSITION_APPROVAL_UOW.get()
    if token is None:
        raise TransitionPlanInactiveApprovalConflict(
            "approval append requires an active private unit of work"
        )
    return token


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity_hash(kind: str, identifier: str, version: str) -> str:
    return _hash({"identity_kind": kind, "id": identifier, "version": version})


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject_ledger_hash(value: TransitionPlanInactiveApprovalSubject, at: datetime) -> str:
    return _hash(
        {
            "identity": _identity_hash("subject", value.subject_id, value.subject_version),
            "content": value.content_hash,
            "recorded_at": _time(at),
        }
    )


def _receipt_ledger_hash(
    value: TransitionPlanApprovalReceipt,
    subject: TransitionPlanInactiveApprovalSubject,
    at: datetime,
) -> str:
    return _hash(
        {
            "identity": _identity_hash("receipt", value.receipt_id, value.receipt_version),
            "content": value.content_hash,
            "subject": subject.content_hash,
            "recorded_at": _time(at),
        }
    )


def _subject_values(
    value: TransitionPlanInactiveApprovalSubject, at: datetime
) -> dict[str, object]:
    actor = value.requested_by
    return {
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "subject_identity_hash": _identity_hash("subject", value.subject_id, value.subject_version),
        "plan_id": value.plan_id,
        "plan_version": value.plan_version,
        "plan_content_hash": value.plan_content_hash,
        "account_id": value.account_id,
        "decision_snapshot_id": value.decision_snapshot_id,
        "requested_actor_id": actor.actor_id,
        "requested_actor_user_id": actor.user_id,
        "requested_actor_role": actor.role,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "recorded_at": at,
        "canonical_payload": encode_transition_plan_inactive_approval_subject(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _subject_ledger_hash(value, at),
    }


def _receipt_values(
    value: TransitionPlanApprovalReceipt,
    subject: TransitionPlanInactiveApprovalSubject,
    at: datetime,
) -> dict[str, object]:
    actor = value.approved_by
    requester = value.requested_by
    return {
        "owner": value.owner,
        "schema": value.schema,
        "receipt_id": value.receipt_id,
        "receipt_version": value.receipt_version,
        "receipt_identity_hash": _identity_hash("receipt", value.receipt_id, value.receipt_version),
        "subject_hash": subject.content_hash,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "subject_content_hash": value.subject_content_hash,
        "plan_id": value.plan_id,
        "plan_version": value.plan_version,
        "plan_content_hash": value.plan_content_hash,
        "account_id": value.account_id,
        "decision_snapshot_id": value.decision_snapshot_id,
        "requested_actor_id": requester.actor_id,
        "requested_actor_user_id": requester.user_id,
        "requested_actor_role": requester.role,
        "approved_actor_id": actor.actor_id,
        "approved_actor_user_id": actor.user_id,
        "approved_actor_role": actor.role,
        "plan_status_at_issue": value.plan_status_at_issue,
        "issued_at": value.issued_at,
        "valid_until": value.valid_until,
        "recorded_at": at,
        "canonical_payload": encode_transition_plan_inactive_approval_receipt(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _receipt_ledger_hash(value, subject, at),
    }


def _subject_headers(value: TransitionPlanInactiveApprovalSubject) -> tuple[object, ...]:
    actor = value.requested_by
    return (
        value.subject_id,
        value.subject_version,
        value.plan_id,
        value.plan_version,
        value.plan_content_hash,
        value.account_id,
        value.decision_snapshot_id,
        actor.actor_id,
        actor.user_id,
        actor.role,
        value.requested_at,
        value.valid_until,
        value.content_hash,
    )


def _subject_model_headers(model: TransitionPlanInactiveApprovalSubjectModel) -> tuple[object, ...]:
    return (
        model.subject_id,
        model.subject_version,
        model.plan_id,
        model.plan_version,
        model.plan_content_hash,
        model.account_id,
        model.decision_snapshot_id,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.requested_at,
        model.valid_until,
        model.content_hash,
    )


def _receipt_headers(
    value: TransitionPlanApprovalReceipt, subject: TransitionPlanInactiveApprovalSubject
) -> tuple[object, ...]:
    actor = value.approved_by
    requester = value.requested_by
    return (
        value.owner,
        value.schema,
        value.receipt_id,
        value.receipt_version,
        subject.content_hash,
        value.subject_id,
        value.subject_version,
        value.subject_content_hash,
        value.plan_id,
        value.plan_version,
        value.plan_content_hash,
        value.account_id,
        value.decision_snapshot_id,
        requester.actor_id,
        requester.user_id,
        requester.role,
        actor.actor_id,
        actor.user_id,
        actor.role,
        value.plan_status_at_issue,
        value.issued_at,
        value.valid_until,
        value.content_hash,
    )


def _receipt_model_headers(model: TransitionPlanInactiveApprovalReceiptModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.schema,
        model.receipt_id,
        model.receipt_version,
        model.subject_hash,
        model.subject_id,
        model.subject_version,
        model.subject_content_hash,
        model.plan_id,
        model.plan_version,
        model.plan_content_hash,
        model.account_id,
        model.decision_snapshot_id,
        model.requested_actor_id,
        model.requested_actor_user_id,
        model.requested_actor_role,
        model.approved_actor_id,
        model.approved_actor_user_id,
        model.approved_actor_role,
        model.plan_status_at_issue,
        model.issued_at,
        model.valid_until,
        model.content_hash,
    )


__all__ = [
    "DjangoTransitionPlanInactiveApprovalClock",
    "DjangoTransitionPlanInactiveApprovalRepository",
    "TransitionPlanInactiveApprovalClock",
]
