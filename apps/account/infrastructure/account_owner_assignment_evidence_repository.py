"""Strict append-only persistence for Account owner-assignment evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentRepository,
    AccountOwnerAssignmentSubject,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
    validate_account_owner_assignment_successor,
)
from apps.account.infrastructure.account_owner_assignment_evidence_codec import (
    AccountOwnerAssignmentEvidenceCodecError,
    decode_account_owner_assignment_evidence,
    decode_account_owner_assignment_subject,
    encode_account_owner_assignment_evidence,
    encode_account_owner_assignment_subject,
)
from apps.account.infrastructure.account_owner_assignment_evidence_models import (
    _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW,
    AccountOwnerAssignmentEvidenceModel,
    AccountOwnerAssignmentSubjectModel,
    _activate_account_owner_assignment_uow,
    _claim_account_owner_assignment_insert,
)


class DjangoAccountOwnerAssignmentUnavailable(AccountOwnerAssignmentUnavailable):
    """The requested exact Account owner-assignment record is unavailable."""


class DjangoAccountOwnerAssignmentConflict(AccountOwnerAssignmentConflict):
    """An immutable identity or logical-chain claim has another first winner."""


class DjangoAccountOwnerAssignmentCorruption(AccountOwnerAssignmentCorruption):
    """Persisted owner-assignment data or chain structure is corrupt."""


class AccountOwnerAssignmentClock(Protocol):
    """Authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoAccountOwnerAssignmentClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoAccountOwnerAssignmentRepository(AccountOwnerAssignmentRepository):
    """Two-stage private ledger with closed-world exact/PIT/CAS reads."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountOwnerAssignmentClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoAccountOwnerAssignmentClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_account_owner_assignment_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise DjangoAccountOwnerAssignmentCorruption(
                "Account owner-assignment clock is naive or substituted"
            )
        return value

    def get_subject_winner(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentSubject | None:
        """Return the immutable subject identity winner recorded by a PIT cutoff."""

        self._require_cutoff(as_of)
        subjects = self._all_subjects(lock=False)
        matches = tuple(
            (value, row)
            for row, value in subjects
            if value.evidence_id == evidence_id and value.evidence_version == evidence_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject identity is ambiguous"
            )
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def append_subject(
        self,
        subject: AccountOwnerAssignmentSubject,
        *,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentSubject:
        """Append or replay one exact subject identity first winner."""

        token = _active_token()
        checked = _require_subject(subject)
        _require_aware(recorded_at, "subject recorded_at")
        if recorded_at != checked.requested_at:
            raise DjangoAccountOwnerAssignmentConflict(
                "subject persisted_at/recorded_at must equal requested_at"
            )
        if not checked.is_current_at(recorded_at):
            raise DjangoAccountOwnerAssignmentConflict(
                "subject must be persisted inside its validity window"
            )
        existing = self._exact_subject_model(checked, lock=True)
        if existing is not None:
            return self._restore_subject(existing)
        values = _subject_model_values(checked, recorded_at=recorded_at)
        model = AccountOwnerAssignmentSubjectModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_account_owner_assignment_insert(
                    token=token,
                    model_type=AccountOwnerAssignmentSubjectModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_subject_model(checked, lock=True)
            if winner is None:
                raise DjangoAccountOwnerAssignmentConflict(
                    "subject append conflicted without an exact visible first winner"
                ) from None
            return self._restore_subject(winner)
        return self._restore_subject(model)

    def get_winner(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return the approved evidence identity winner recorded by a PIT cutoff."""

        self._require_cutoff(as_of)
        records = self._all_evidence(lock=False)
        matches = tuple(
            (value, row)
            for row, value in records
            if value.evidence_id == evidence_id and value.evidence_version == evidence_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence identity is ambiguous"
            )
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        row_observation_id: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return the final visible logical head without expiry fallback."""

        self._require_cutoff(as_of)
        return self._current_head(
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=underlying_unified_account_namespace,
            underlying_unified_account_id=underlying_unified_account_id,
            row_observation_id=row_observation_id,
            as_of=as_of,
            lock=False,
        )

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidence:
        """CAS-append or replay one exact identity/content/logical first winner."""

        token = _active_token()
        checked = _require_evidence(evidence)
        _require_aware(recorded_at, "evidence recorded_at")
        if recorded_at != checked.recorded_at:
            raise DjangoAccountOwnerAssignmentConflict(
                "evidence persisted_at must equal its authoritative recorded_at"
            )
        if checked.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoAccountOwnerAssignmentConflict(
                "owner-assignment evidence predecessor mismatch"
            )
        if not checked.is_knowable_at(recorded_at):
            raise DjangoAccountOwnerAssignmentConflict(
                "evidence must be persisted inside its validity window"
            )
        subject_model = self._subject_for_evidence(checked, lock=True)
        existing = self._exact_evidence_model(checked, lock=True)
        if existing is not None:
            return self._restore_evidence(existing)
        current = self._current_head(
            account_namespace=checked.account_namespace,
            account_id=checked.account_id,
            underlying_unified_account_namespace=(checked.underlying_unified_account_namespace),
            underlying_unified_account_id=checked.underlying_unified_account_id,
            row_observation_id=checked.row_observation_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoAccountOwnerAssignmentConflict(
                "owner-assignment evidence current head changed"
            )
        if current is not None:
            try:
                validate_account_owner_assignment_successor(current, checked)
            except (TypeError, ValueError) as error:
                raise DjangoAccountOwnerAssignmentConflict(
                    "owner-assignment evidence successor is invalid"
                ) from error
        values = _evidence_model_values(
            checked,
            subject_id=subject_model.pk,
            recorded_at=recorded_at,
        )
        model = AccountOwnerAssignmentEvidenceModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_account_owner_assignment_insert(
                    token=token,
                    model_type=AccountOwnerAssignmentEvidenceModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_evidence_model(checked, lock=True)
            if winner is None:
                raise DjangoAccountOwnerAssignmentConflict(
                    "evidence append conflicted without an exact visible first winner"
                ) from None
            return self._restore_evidence(winner)
        model.subject = subject_model
        return self._restore_evidence(model)

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return one exact identity/hash record knowable at the PIT cutoff."""

        self._require_cutoff(as_of)
        records = self._all_evidence(lock=False)
        anchors = tuple(
            (value, row)
            for row, value in records
            if (
                (value.evidence_id == evidence_id and value.evidence_version == evidence_version)
                or value.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            (value, row)
            for value, row in anchors
            if value.evidence_id == evidence_id
            and value.evidence_version == evidence_version
            and value.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment exact identity/hash anchors are ambiguous"
            )
        value, row = matches[0]
        if row.recorded_at > as_of or not value.is_knowable_at(as_of):
            return None
        return value

    def _current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        row_observation_id: str,
        as_of: datetime,
        lock: bool,
    ) -> AccountOwnerAssignmentEvidence | None:
        records = self._all_evidence(lock=lock)
        visible = tuple(value for row, value in records if row.recorded_at <= as_of)
        chain = tuple(
            value
            for value in visible
            if value.account_namespace == account_namespace
            and value.account_id == account_id
            and value.underlying_unified_account_namespace == underlying_unified_account_namespace
            and value.underlying_unified_account_id == underlying_unified_account_id
            and value.row_observation_id == row_observation_id
        )
        return _restore_full_chain(chain) if chain else None

    def _all_subjects(
        self,
        *,
        lock: bool,
    ) -> tuple[tuple[AccountOwnerAssignmentSubjectModel, AccountOwnerAssignmentSubject], ...]:
        """Restore the full subject table before trusting mutable headers."""

        queryset = AccountOwnerAssignmentSubjectModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("pk"))
        return tuple((row, self._restore_subject(row)) for row in rows)

    def _all_evidence(
        self,
        *,
        lock: bool,
    ) -> tuple[tuple[AccountOwnerAssignmentEvidenceModel, AccountOwnerAssignmentEvidence], ...]:
        """Restore both complete tables before selector, PIT, or chain filtering."""

        subjects = self._all_subjects(lock=lock)
        subjects_by_pk = {row.pk: value for row, value in subjects if row.pk is not None}
        queryset = (
            AccountOwnerAssignmentEvidenceModel._default_manager.using(self._using)
            .select_related("subject")
            .all()
        )
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("pk"))
        restored: list[
            tuple[AccountOwnerAssignmentEvidenceModel, AccountOwnerAssignmentEvidence]
        ] = []
        for row in rows:
            subject = subjects_by_pk.get(row.subject_id)
            if subject is None:
                raise DjangoAccountOwnerAssignmentCorruption(
                    "owner-assignment evidence subject FK is orphaned"
                )
            restored.append((row, self._restore_evidence(row, subject=subject)))
        return tuple(restored)

    def _exact_subject_model(
        self,
        subject: AccountOwnerAssignmentSubject,
        *,
        lock: bool,
    ) -> AccountOwnerAssignmentSubjectModel | None:
        identity = _subject_identity_hash(subject.evidence_id, subject.evidence_version)
        row_binding = _row_binding_hash(subject)
        provenance_binding = _provenance_binding_hash(subject)
        restored = self._all_subjects(lock=lock)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.evidence_id == subject.evidence_id
                    and value.evidence_version == subject.evidence_version
                )
                or row.subject_identity_hash == identity
                or value.content_hash == subject.content_hash
                or row.row_binding_hash == row_binding
                or row.provenance_binding_hash == provenance_binding
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == subject)
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountOwnerAssignmentConflict(
                "subject identity or definition has another first winner"
            )
        return matches[0]

    def _exact_evidence_model(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        *,
        lock: bool,
    ) -> AccountOwnerAssignmentEvidenceModel | None:
        root_claim = _root_claim_hash(evidence)
        restored = self._all_evidence(lock=lock)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.evidence_id == evidence.evidence_id
                    and value.evidence_version == evidence.evidence_version
                )
                or value.identity_hash == evidence.identity_hash
                or value.content_hash == evidence.content_hash
                or value.subject_content_hash == evidence.subject_content_hash
                or (evidence.supersedes_content_hash is None and row.root_claim_hash == root_claim)
                or (
                    evidence.supersedes_content_hash is not None
                    and value.supersedes_content_hash == evidence.supersedes_content_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == evidence)
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountOwnerAssignmentConflict(
                "evidence identity, content, subject, or chain claim has another first winner"
            )
        return matches[0]

    def _subject_for_evidence(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        *,
        lock: bool,
    ) -> AccountOwnerAssignmentSubjectModel:
        subjects = self._all_subjects(lock=lock)
        matches = tuple(
            (row, subject)
            for row, subject in subjects
            if subject.evidence_id == evidence.evidence_id
            and subject.evidence_version == evidence.evidence_version
        )
        if len(matches) != 1:
            raise DjangoAccountOwnerAssignmentConflict(
                "evidence requires one exact registered subject first winner"
            )
        row, subject = matches[0]
        try:
            _validate_subject_evidence_binding(subject, evidence)
        except (TypeError, ValueError) as error:
            raise DjangoAccountOwnerAssignmentConflict(
                "evidence does not bind its exact registered subject"
            ) from error
        return row

    def _restore_subject(
        self,
        model: AccountOwnerAssignmentSubjectModel,
    ) -> AccountOwnerAssignmentSubject:
        try:
            subject = decode_account_owner_assignment_subject(model.canonical_payload)
        except AccountOwnerAssignmentEvidenceCodecError as error:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject canonical payload cannot be restored"
            ) from error
        if _subject_headers(subject) != _subject_model_headers(model, subject):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject headers do not match canonical payload"
            )
        if model.subject_identity_hash != _subject_identity_hash(
            subject.evidence_id, subject.evidence_version
        ):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject identity seal is invalid"
            )
        if model.row_binding_hash != _row_binding_hash(subject):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject row binding seal is invalid"
            )
        if model.provenance_binding_hash != _provenance_binding_hash(subject):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject provenance binding seal is invalid"
            )
        if model.ledger_header_hash != _subject_ledger_hash(subject, recorded_at=model.recorded_at):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject ledger header seal is invalid"
            )
        if (
            type(model.persisted_at) is not datetime
            or model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != subject.requested_at
        ):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment subject persistence clock is invalid"
            )
        return subject

    def _restore_evidence(
        self,
        model: AccountOwnerAssignmentEvidenceModel,
        *,
        subject: AccountOwnerAssignmentSubject | None = None,
    ) -> AccountOwnerAssignmentEvidence:
        registered = subject or self._restore_subject(model.subject)
        try:
            evidence = decode_account_owner_assignment_evidence(model.canonical_payload)
        except AccountOwnerAssignmentEvidenceCodecError as error:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence canonical payload cannot be restored"
            ) from error
        if _evidence_headers(evidence) != _evidence_model_headers(model, evidence):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence headers do not match canonical payload"
            )
        try:
            _validate_subject_evidence_binding(registered, evidence)
        except (TypeError, ValueError) as error:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence subject binding is invalid"
            ) from error
        expected_root = (
            _root_claim_hash(evidence) if evidence.supersedes_content_hash is None else None
        )
        if model.root_claim_hash != expected_root:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence root claim is invalid"
            )
        if model.ledger_header_hash != _evidence_ledger_hash(
            evidence, recorded_at=model.recorded_at
        ):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence ledger header seal is invalid"
            )
        if (
            type(model.persisted_at) is not datetime
            or model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != evidence.recorded_at
            or registered.requested_at > evidence.recorded_at
        ):
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment evidence persistence clock is invalid"
            )
        return evidence

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "owner-assignment as_of")
        if as_of > self.now():
            raise DjangoAccountOwnerAssignmentUnavailable(
                "future owner-assignment as_of is forbidden"
            )


def _active_token() -> object:
    token = _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW.get()
    if token is None:
        raise DjangoAccountOwnerAssignmentConflict(
            "owner-assignment append requires an active private unit of work"
        )
    return token


def _require_subject(value: object) -> AccountOwnerAssignmentSubject:
    if type(value) is not AccountOwnerAssignmentSubject:
        raise DjangoAccountOwnerAssignmentCorruption("owner-assignment subject type substitution")
    AccountOwnerAssignmentSubject.__post_init__(value)
    return value


def _require_evidence(value: object) -> AccountOwnerAssignmentEvidence:
    if type(value) is not AccountOwnerAssignmentEvidence:
        raise DjangoAccountOwnerAssignmentCorruption("owner-assignment evidence type substitution")
    AccountOwnerAssignmentEvidence.__post_init__(value)
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoAccountOwnerAssignmentUnavailable(f"{field_name} must be timezone-aware")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject_identity_hash(evidence_id: str, evidence_version: str) -> str:
    return _hash_payload(
        {
            "capability": "account_owner_assignment_subject",
            "evidence_id": evidence_id,
            "evidence_version": evidence_version,
        }
    )


def _row_binding_hash(subject: AccountOwnerAssignmentSubject) -> str:
    return _hash_payload(subject.row.to_payload())


def _provenance_binding_hash(subject: AccountOwnerAssignmentSubject) -> str:
    return _hash_payload(subject.receipt.to_payload())


def _root_claim_hash(evidence: AccountOwnerAssignmentEvidence) -> str:
    return _hash_payload(
        {
            "account_namespace": evidence.account_namespace,
            "account_id": evidence.account_id,
            "underlying_unified_account_namespace": (evidence.underlying_unified_account_namespace),
            "underlying_unified_account_id": evidence.underlying_unified_account_id,
            "row_observation_id": evidence.row_observation_id,
        }
    )


def _subject_ledger_hash(
    subject: AccountOwnerAssignmentSubject,
    *,
    recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "subject": encode_account_owner_assignment_subject(subject),
            "subject_identity_hash": _subject_identity_hash(
                subject.evidence_id, subject.evidence_version
            ),
            "row_binding_hash": _row_binding_hash(subject),
            "provenance_binding_hash": _provenance_binding_hash(subject),
            "persisted_at": _time(recorded_at),
        }
    )


def _evidence_ledger_hash(
    evidence: AccountOwnerAssignmentEvidence,
    *,
    recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "evidence": encode_account_owner_assignment_evidence(evidence),
            "subject_content_hash": evidence.subject_content_hash,
            "root_claim_hash": (
                _root_claim_hash(evidence) if evidence.supersedes_content_hash is None else None
            ),
            "persisted_at": _time(recorded_at),
        }
    )


def _actor_payload(actor: AccountOwnerAssignmentActor) -> dict[str, object]:
    return actor.to_payload()


def _subject_model_values(
    subject: AccountOwnerAssignmentSubject,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    row = subject.row
    receipt = subject.receipt
    claimant = subject.claimant
    receipt_claimant = receipt.claimant
    return {
        "evidence_id": subject.evidence_id,
        "evidence_version": subject.evidence_version,
        "subject_identity_hash": _subject_identity_hash(
            subject.evidence_id, subject.evidence_version
        ),
        "row_owner": row.owner,
        "row_artifact_type": row.artifact_type,
        "row_observation_id": row.observation_id,
        "row_observation_version": row.observation_version,
        "row_content_hash": row.content_hash,
        "account_namespace": row.account_namespace,
        "account_id": row.account_id,
        "underlying_unified_account_namespace": row.underlying_unified_account_namespace,
        "underlying_unified_account_id": row.underlying_unified_account_id,
        "row_observed_at": row.observed_at,
        "row_recorded_at": row.recorded_at,
        "row_valid_until": row.valid_until,
        "row_binding_hash": _row_binding_hash(subject),
        "receipt_owner": receipt.owner,
        "receipt_artifact_type": receipt.artifact_type,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "receipt_content_hash": receipt.content_hash,
        "provenance_kind": receipt.provenance_kind,
        "assignment_state": receipt.assignment_state,
        "assigned_owner_user_id": receipt.assigned_owner_user_id,
        "receipt_account_namespace": receipt.account_namespace,
        "receipt_account_id": receipt.account_id,
        "receipt_underlying_namespace": receipt.underlying_unified_account_namespace,
        "receipt_underlying_id": receipt.underlying_unified_account_id,
        "receipt_row_id": receipt.row_observation_id,
        "receipt_row_version": receipt.row_observation_version,
        "receipt_row_content_hash": receipt.row_observation_content_hash,
        "receipt_claimant_actor_id": receipt_claimant.actor_id,
        "receipt_claimant_user_id": receipt_claimant.user_id,
        "receipt_claimant_role": receipt_claimant.role,
        "receipt_claimant_kind": receipt_claimant.kind,
        "receipt_claimant_is_staff": receipt_claimant.is_staff,
        "receipt_issued_at": receipt.issued_at,
        "receipt_recorded_at": receipt.recorded_at,
        "receipt_valid_until": receipt.valid_until,
        "provenance_binding_hash": _provenance_binding_hash(subject),
        "claimant_actor_id": claimant.actor_id,
        "claimant_user_id": claimant.user_id,
        "claimant_role": claimant.role,
        "claimant_kind": claimant.kind,
        "claimant_is_staff": claimant.is_staff,
        "requested_at": subject.requested_at,
        "valid_until": subject.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_account_owner_assignment_subject(subject),
        "content_hash": subject.content_hash,
        "ledger_header_hash": _subject_ledger_hash(subject, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _evidence_model_values(
    evidence: AccountOwnerAssignmentEvidence,
    *,
    subject_id: int,
    recorded_at: datetime,
) -> dict[str, object]:
    claimant = evidence.claimant
    approved = evidence.approved_by
    return {
        "subject_id": subject_id,
        "subject_content_hash": evidence.subject_content_hash,
        "owner": evidence.owner,
        "artifact_type": evidence.artifact_type,
        "schema": evidence.schema,
        "evidence_id": evidence.evidence_id,
        "evidence_version": evidence.evidence_version,
        "identity_hash": evidence.identity_hash,
        "account_namespace": evidence.account_namespace,
        "account_id": evidence.account_id,
        "underlying_unified_account_namespace": (evidence.underlying_unified_account_namespace),
        "underlying_unified_account_id": evidence.underlying_unified_account_id,
        "assignment_state": evidence.assignment_state,
        "assigned_owner_user_id": evidence.assigned_owner_user_id,
        "row_observation_owner": evidence.row_observation_owner,
        "row_observation_artifact_type": evidence.row_observation_artifact_type,
        "row_observation_id": evidence.row_observation_id,
        "row_observation_version": evidence.row_observation_version,
        "row_observation_content_hash": evidence.row_observation_content_hash,
        "provenance_kind": evidence.provenance_kind,
        "provenance_ref_owner": evidence.provenance_ref_owner,
        "provenance_ref_artifact_type": evidence.provenance_ref_artifact_type,
        "provenance_ref_id": evidence.provenance_ref_id,
        "provenance_ref_version": evidence.provenance_ref_version,
        "provenance_ref_content_hash": evidence.provenance_ref_content_hash,
        "claimant_actor_id": claimant.actor_id,
        "claimant_user_id": claimant.user_id,
        "claimant_role": claimant.role,
        "claimant_kind": claimant.kind,
        "claimant_is_staff": claimant.is_staff,
        "approved_actor_id": approved.actor_id,
        "approved_user_id": approved.user_id,
        "approved_role": approved.role,
        "approved_kind": approved.kind,
        "approved_is_staff": approved.is_staff,
        "issued_at": evidence.issued_at,
        "approved_at": evidence.approved_at,
        "recorded_at": recorded_at,
        "valid_until": evidence.valid_until,
        "supersedes_content_hash": evidence.supersedes_content_hash,
        "root_claim_hash": (
            _root_claim_hash(evidence) if evidence.supersedes_content_hash is None else None
        ),
        "permission": evidence.permission,
        "status": evidence.status,
        "blocker_codes": list(evidence.blocker_codes),
        "canonical_payload": encode_account_owner_assignment_evidence(evidence),
        "content_hash": evidence.content_hash,
        "ledger_header_hash": _evidence_ledger_hash(evidence, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _subject_headers(subject: AccountOwnerAssignmentSubject) -> dict[str, object]:
    values = _subject_model_values(subject, recorded_at=subject.requested_at)
    for key in (
        "subject_identity_hash",
        "row_binding_hash",
        "provenance_binding_hash",
        "canonical_payload",
        "ledger_header_hash",
        "persisted_at",
    ):
        values.pop(key)
    return values


def _subject_model_headers(
    model: AccountOwnerAssignmentSubjectModel,
    subject: AccountOwnerAssignmentSubject,
) -> dict[str, object]:
    keys = _subject_headers(subject).keys()
    return {
        key: tuple(getattr(model, key)) if key == "blocker_codes" else getattr(model, key)
        for key in keys
    }


def _evidence_headers(evidence: AccountOwnerAssignmentEvidence) -> dict[str, object]:
    values = _evidence_model_values(
        evidence,
        subject_id=0,
        recorded_at=evidence.recorded_at,
    )
    for key in (
        "subject_id",
        "root_claim_hash",
        "canonical_payload",
        "ledger_header_hash",
        "persisted_at",
    ):
        values.pop(key)
    values["blocker_codes"] = tuple(evidence.blocker_codes)
    return values


def _evidence_model_headers(
    model: AccountOwnerAssignmentEvidenceModel,
    evidence: AccountOwnerAssignmentEvidence,
) -> dict[str, object]:
    keys = _evidence_headers(evidence).keys()
    return {
        key: tuple(getattr(model, key)) if key == "blocker_codes" else getattr(model, key)
        for key in keys
    }


def _validate_subject_evidence_binding(
    subject: AccountOwnerAssignmentSubject,
    evidence: AccountOwnerAssignmentEvidence,
) -> None:
    row = subject.row
    receipt = subject.receipt
    if not (
        evidence.evidence_id == subject.evidence_id
        and evidence.evidence_version == subject.evidence_version
        and evidence.subject_content_hash == subject.content_hash
        and evidence.account_namespace == row.account_namespace
        and evidence.account_id == row.account_id
        and evidence.underlying_unified_account_namespace
        == row.underlying_unified_account_namespace
        and evidence.underlying_unified_account_id == row.underlying_unified_account_id
        and evidence.row_observation_owner == row.owner
        and evidence.row_observation_artifact_type == row.artifact_type
        and evidence.row_observation_id == row.observation_id
        and evidence.row_observation_version == row.observation_version
        and evidence.row_observation_content_hash == row.content_hash
        and evidence.assignment_state == receipt.assignment_state
        and evidence.assigned_owner_user_id == receipt.assigned_owner_user_id
        and evidence.provenance_kind == receipt.provenance_kind
        and evidence.provenance_ref_owner == receipt.owner
        and evidence.provenance_ref_artifact_type == receipt.artifact_type
        and evidence.provenance_ref_id == receipt.receipt_id
        and evidence.provenance_ref_version == receipt.receipt_version
        and evidence.provenance_ref_content_hash == receipt.content_hash
        and evidence.claimant.to_payload() == subject.claimant.to_payload()
        and evidence.issued_at == subject.requested_at
        and evidence.recorded_at <= subject.valid_until
        and evidence.valid_until <= subject.valid_until
    ):
        raise ValueError("evidence is not the exact approved subject projection")


def _restore_full_chain(
    records: tuple[AccountOwnerAssignmentEvidence, ...],
) -> AccountOwnerAssignmentEvidence:
    by_hash = {record.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoAccountOwnerAssignmentCorruption("owner-assignment chain has duplicate content")
    roots = tuple(record for record in records if record.supersedes_content_hash is None)
    if len(roots) != 1:
        raise DjangoAccountOwnerAssignmentCorruption(
            "owner-assignment chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, AccountOwnerAssignmentEvidence] = {}
    for record in records:
        predecessor_hash = record.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment predecessor has multiple successors"
            )
        try:
            validate_account_owner_assignment_successor(predecessor, record)
        except (TypeError, ValueError) as error:
            raise DjangoAccountOwnerAssignmentCorruption(
                "owner-assignment successor link is invalid"
            ) from error
        successor_by_predecessor[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.content_hash not in visited:
        visited.add(current.content_hash)
        successor = successor_by_predecessor.get(current.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise DjangoAccountOwnerAssignmentCorruption(
            "owner-assignment chain is disconnected or cyclic"
        )
    return current


__all__ = [
    "AccountOwnerAssignmentClock",
    "DjangoAccountOwnerAssignmentClock",
    "DjangoAccountOwnerAssignmentConflict",
    "DjangoAccountOwnerAssignmentCorruption",
    "DjangoAccountOwnerAssignmentRepository",
    "DjangoAccountOwnerAssignmentUnavailable",
]
