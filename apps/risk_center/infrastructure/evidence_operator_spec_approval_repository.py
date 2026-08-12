"""Strict append-only persistence for Evidence operator specification approvals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.risk_center.application.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalConflict,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalUnavailable,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
    evidence_operator_spec_approval_identity_hash,
    evidence_operator_spec_subject_identity_hash,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_codec import (
    EvidenceOperatorSpecApprovalCodecError,
    decode_evidence_operator_spec_approval_record,
    decode_evidence_operator_spec_approval_subject,
    encode_evidence_operator_spec_approval_record,
    encode_evidence_operator_spec_approval_subject,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_models import (
    _ACTIVE_APPROVAL_UOW,
    EvidenceOperatorSpecApprovalRecordModel,
    EvidenceOperatorSpecApprovalSubjectModel,
    _activate_evidence_operator_spec_approval_uow,
    _claim_evidence_operator_spec_approval_insert,
)


class EvidenceOperatorSpecApprovalClock(Protocol):
    """Authoritative Risk Center persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoEvidenceOperatorSpecApprovalClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoEvidenceOperatorSpecApprovalRepository:
    """Private append store and public strict exact/PIT approval reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceOperatorSpecApprovalClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoEvidenceOperatorSpecApprovalClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open the private all-or-nothing first-winner append boundary."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_evidence_operator_spec_approval_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Risk Center clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise EvidenceOperatorSpecApprovalCorruption(
                "Risk Center Evidence operator spec approval clock is naive"
            )
        return value

    def get_subject_winner(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        """Restore a subject identity through redundant identity-first anchors."""

        self._require_cutoff(as_of)
        identity_hash = evidence_operator_spec_subject_identity_hash(
            subject_id=subject_id,
            subject_version=subject_version,
        )
        models = list(
            EvidenceOperatorSpecApprovalSubjectModel._default_manager.using(self._using).filter(
                Q(subject_id=subject_id, subject_version=subject_version)
                | Q(subject_identity_hash=identity_hash)
            )
        )
        if not models:
            return None
        subjects = tuple(self._restore_subject(model) for model in models)
        matches = tuple(
            subject
            for subject in subjects
            if subject.subject_id == subject_id and subject.subject_version == subject_version
        )
        if len(matches) != 1:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval subject identity is ambiguous or does not match its headers"
            )
        model = models[subjects.index(matches[0])]
        return matches[0] if model.recorded_at <= as_of else None

    def get_approval_winner(
        self,
        *,
        approval_id: str,
        approval_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Restore an approval identity without trusting a caller content hash."""

        self._require_cutoff(as_of)
        identity_hash = evidence_operator_spec_approval_identity_hash(
            approval_id=approval_id,
            approval_version=approval_version,
        )
        models = list(
            EvidenceOperatorSpecApprovalRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(
                Q(approval_id=approval_id, approval_version=approval_version)
                | Q(approval_identity_hash=identity_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore_approval(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.approval_id == approval_id and record.approval_version == approval_version
        )
        if len(matches) != 1:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval identity is ambiguous or does not match its headers"
            )
        model = models[records.index(matches[0])]
        return matches[0] if model.recorded_at <= as_of else None

    def append(
        self,
        approval: EvidenceOperatorSpecApprovalRecord,
        *,
        recorded_at: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord:
        """Append subject plus approval or recover the concurrent first winner."""

        if recorded_at != approval.issued_at:
            raise EvidenceOperatorSpecApprovalConflict(
                "approval record must use the authoritative transaction clock"
            )
        subject_values = _subject_values(approval.subject, recorded_at=recorded_at)
        approval_values = _approval_values(approval, recorded_at=recorded_at)
        try:
            with transaction.atomic(using=self._using):
                subject_model = EvidenceOperatorSpecApprovalSubjectModel(**subject_values)
                with _claim_evidence_operator_spec_approval_insert(
                    token=_active_token(),
                    model_type=EvidenceOperatorSpecApprovalSubjectModel,
                    expected_values=subject_values,
                ):
                    subject_model.save(force_insert=True, using=self._using)
                approval_values_with_fk: dict[str, object] = {
                    **approval_values,
                    "subject_id": subject_model.pk,
                }
                approval_model = EvidenceOperatorSpecApprovalRecordModel(**approval_values_with_fk)
                with _claim_evidence_operator_spec_approval_insert(
                    token=_active_token(),
                    model_type=EvidenceOperatorSpecApprovalRecordModel,
                    expected_values=approval_values_with_fk,
                ):
                    approval_model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self.get_approval_winner(
                approval_id=approval.approval_id,
                approval_version=approval.approval_version,
                as_of=self.now(),
            )
            if winner is None:
                raise EvidenceOperatorSpecApprovalConflict(
                    "approval append conflicted without a visible first winner"
                ) from None
            return winner
        return self._restore_approval(approval_model)

    def get_exact_by_hash(
        self,
        *,
        approval_id: str,
        approval_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Restore by identity and hash while retaining identity-first tamper anchors."""

        self._require_cutoff(as_of)
        identity_hash = evidence_operator_spec_approval_identity_hash(
            approval_id=approval_id,
            approval_version=approval_version,
        )
        models = list(
            EvidenceOperatorSpecApprovalRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(
                Q(approval_id=approval_id, approval_version=approval_version)
                | Q(approval_identity_hash=identity_hash)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore_approval(model) for model in models)
        matches = tuple(
            (record, model)
            for record, model in zip(records, models, strict=True)
            if record.approval_id == approval_id
            and record.approval_version == approval_version
            and record.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            raise EvidenceOperatorSpecApprovalCorruption(
                "exact approval does not match its identity/hash headers"
            )
        record, model = matches[0]
        return record if model.recorded_at <= as_of else None

    def get_for_definition(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return one valid exact approval matching the Research activation selector."""

        self._require_cutoff(as_of)
        identity_hash = evidence_operator_spec_approval_identity_hash(
            approval_id=approval_id,
            approval_version=approval_version,
        )
        models = list(
            EvidenceOperatorSpecApprovalRecordModel._default_manager.using(self._using)
            .select_related("subject")
            .filter(
                Q(approval_id=approval_id, approval_version=approval_version)
                | Q(approval_identity_hash=identity_hash)
                | Q(operator_id=operator_id, operator_version=operator_version)
                | Q(definition_hash=definition_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore_approval(model) for model in models)
        matches = tuple(
            (record, model)
            for record, model in zip(records, models, strict=True)
            if record.approval_id == approval_id
            and record.approval_version == approval_version
            and record.subject.operator_id == operator_id
            and record.subject.operator_version == operator_version
            and record.subject.definition_hash == definition_hash
            and record.subject.supersedes_activation_hash == supersedes_activation_hash
        )
        if len(matches) > 1:
            raise EvidenceOperatorSpecApprovalCorruption(
                "multiple approvals match one exact Research selector"
            )
        if not matches:
            return None
        record, model = matches[0]
        if model.recorded_at > as_of or not record.is_valid_at(as_of):
            return None
        return record

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise EvidenceOperatorSpecApprovalUnavailable("approval as_of is naive")
        if as_of > self.now():
            raise EvidenceOperatorSpecApprovalUnavailable("future approval as_of is not permitted")

    def _restore_subject(
        self,
        model: EvidenceOperatorSpecApprovalSubjectModel,
    ) -> EvidenceOperatorSpecApprovalSubject:
        try:
            subject = decode_evidence_operator_spec_approval_subject(model.canonical_payload)
        except EvidenceOperatorSpecApprovalCodecError as error:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval subject payload cannot be restored"
            ) from error
        if _subject_headers(subject) != _subject_model_headers(model):
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval subject headers do not match payload"
            )
        if model.subject_identity_hash != evidence_operator_spec_subject_identity_hash(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
        ):
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval subject identity seal is invalid"
            )
        if model.ledger_header_hash != _subject_ledger_header_hash(
            subject,
            recorded_at=model.recorded_at,
        ):
            raise EvidenceOperatorSpecApprovalCorruption("approval subject ledger seal is invalid")
        if not subject.requested_at <= model.recorded_at < subject.valid_until:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval subject persisted outside its validity window"
            )
        return subject

    def _restore_approval(
        self,
        model: EvidenceOperatorSpecApprovalRecordModel,
    ) -> EvidenceOperatorSpecApprovalRecord:
        subject = self._restore_subject(model.subject)
        try:
            approval = decode_evidence_operator_spec_approval_record(model.canonical_payload)
        except EvidenceOperatorSpecApprovalCodecError as error:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval record payload cannot be restored"
            ) from error
        if approval.subject != subject:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval record/subject payload substitution"
            )
        if _approval_headers(approval) != _approval_model_headers(model):
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval record headers do not match payload"
            )
        if model.approval_identity_hash != evidence_operator_spec_approval_identity_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
        ):
            raise EvidenceOperatorSpecApprovalCorruption("approval record identity seal is invalid")
        if model.ledger_header_hash != _approval_ledger_header_hash(
            approval,
            recorded_at=model.recorded_at,
        ):
            raise EvidenceOperatorSpecApprovalCorruption("approval record ledger seal is invalid")
        if model.subject_id != model.subject.pk:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval record subject foreign key is invalid"
            )
        if model.recorded_at != model.subject.recorded_at:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval record/subject knowledge clock mismatch"
            )
        if approval.issued_at != model.recorded_at:
            raise EvidenceOperatorSpecApprovalCorruption(
                "approval issue time is not the Risk Center server clock"
            )
        return approval


def _active_token() -> object:
    token = _ACTIVE_APPROVAL_UOW.get()
    if token is None:
        raise EvidenceOperatorSpecApprovalConflict(
            "approval append requires an active private unit of work"
        )
    return token


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject_ledger_header_hash(
    subject: EvidenceOperatorSpecApprovalSubject,
    *,
    recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "subject_identity_hash": evidence_operator_spec_subject_identity_hash(
                subject_id=subject.subject_id,
                subject_version=subject.subject_version,
            ),
            "subject_content_hash": subject.content_hash,
            "recorded_at": _datetime_text(recorded_at),
        }
    )


def _approval_ledger_header_hash(
    approval: EvidenceOperatorSpecApprovalRecord,
    *,
    recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "approval_identity_hash": evidence_operator_spec_approval_identity_hash(
                approval_id=approval.approval_id,
                approval_version=approval.approval_version,
            ),
            "approval_content_hash": approval.content_hash,
            "subject_content_hash": approval.subject.content_hash,
            "recorded_at": _datetime_text(recorded_at),
        }
    )


def _subject_values(
    subject: EvidenceOperatorSpecApprovalSubject,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    actor = subject.requested_by
    return {
        "subject_id": subject.subject_id,
        "subject_version": subject.subject_version,
        "subject_identity_hash": evidence_operator_spec_subject_identity_hash(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
        ),
        "operator_id": subject.operator_id,
        "operator_version": subject.operator_version,
        "definition_hash": subject.definition_hash,
        "supersedes_activation_hash": subject.supersedes_activation_hash,
        "requested_actor_id": actor.actor_id,
        "requested_actor_kind": actor.kind.value,
        "requested_actor_is_staff": actor.is_staff,
        "requested_actor_user_id": actor.user_id,
        "requested_at": subject.requested_at,
        "valid_until": subject.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_evidence_operator_spec_approval_subject(subject),
        "content_hash": subject.content_hash,
        "ledger_header_hash": _subject_ledger_header_hash(
            subject,
            recorded_at=recorded_at,
        ),
    }


def _approval_values(
    approval: EvidenceOperatorSpecApprovalRecord,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    subject = approval.subject
    actor = approval.approved_by
    return {
        "owner": approval.owner,
        "capability": approval.capability,
        "approval_id": approval.approval_id,
        "approval_version": approval.approval_version,
        "approval_identity_hash": evidence_operator_spec_approval_identity_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
        ),
        "subject_hash": subject.content_hash,
        "operator_id": subject.operator_id,
        "operator_version": subject.operator_version,
        "definition_hash": subject.definition_hash,
        "supersedes_activation_hash": subject.supersedes_activation_hash,
        "approved_actor_id": actor.actor_id,
        "approved_actor_kind": actor.kind.value,
        "approved_actor_is_staff": actor.is_staff,
        "approved_actor_user_id": actor.user_id,
        "issued_at": approval.issued_at,
        "valid_until": approval.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_evidence_operator_spec_approval_record(approval),
        "content_hash": approval.content_hash,
        "ledger_header_hash": _approval_ledger_header_hash(
            approval,
            recorded_at=recorded_at,
        ),
    }


def _subject_headers(subject: EvidenceOperatorSpecApprovalSubject) -> tuple[object, ...]:
    actor = subject.requested_by
    return (
        subject.subject_id,
        subject.subject_version,
        subject.operator_id,
        subject.operator_version,
        subject.definition_hash,
        subject.supersedes_activation_hash,
        actor.actor_id,
        actor.kind.value,
        actor.is_staff,
        actor.user_id,
        subject.requested_at,
        subject.valid_until,
        subject.content_hash,
    )


def _subject_model_headers(
    model: EvidenceOperatorSpecApprovalSubjectModel,
) -> tuple[object, ...]:
    return (
        model.subject_id,
        model.subject_version,
        model.operator_id,
        model.operator_version,
        model.definition_hash,
        model.supersedes_activation_hash,
        model.requested_actor_id,
        model.requested_actor_kind,
        model.requested_actor_is_staff,
        model.requested_actor_user_id,
        model.requested_at,
        model.valid_until,
        model.content_hash,
    )


def _approval_headers(approval: EvidenceOperatorSpecApprovalRecord) -> tuple[object, ...]:
    subject = approval.subject
    actor = approval.approved_by
    return (
        approval.owner,
        approval.capability,
        approval.approval_id,
        approval.approval_version,
        subject.content_hash,
        subject.operator_id,
        subject.operator_version,
        subject.definition_hash,
        subject.supersedes_activation_hash,
        actor.actor_id,
        actor.kind.value,
        actor.is_staff,
        actor.user_id,
        approval.issued_at,
        approval.valid_until,
        approval.content_hash,
    )


def _approval_model_headers(
    model: EvidenceOperatorSpecApprovalRecordModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.capability,
        model.approval_id,
        model.approval_version,
        model.subject_hash,
        model.operator_id,
        model.operator_version,
        model.definition_hash,
        model.supersedes_activation_hash,
        model.approved_actor_id,
        model.approved_actor_kind,
        model.approved_actor_is_staff,
        model.approved_actor_user_id,
        model.issued_at,
        model.valid_until,
        model.content_hash,
    )


__all__ = [
    "DjangoEvidenceOperatorSpecApprovalClock",
    "DjangoEvidenceOperatorSpecApprovalRepository",
    "EvidenceOperatorSpecApprovalClock",
]
