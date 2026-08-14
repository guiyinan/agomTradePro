"""Closed-world Django repository for Account owner-assignment evidence v2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2Conflict,
    AccountOwnerAssignmentEvidenceV2Corruption,
    AccountOwnerAssignmentEvidenceV2Unavailable,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
    validate_account_owner_assignment_evidence_v2_root,
    validate_account_owner_assignment_evidence_v2_successor,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v2_codec import (
    AccountOwnerAssignmentEvidenceV2CodecError,
    decode_account_owner_assignment_evidence_v2,
    decode_account_owner_assignment_subject_v2,
    encode_account_owner_assignment_evidence_v2,
    encode_account_owner_assignment_subject_v2,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v2_models import (
    AccountOwnerAssignmentEvidenceV2Model,
    AccountOwnerAssignmentSubjectV2Model,
    _activate_account_owner_assignment_evidence_v2_uow,
    _claim_account_owner_assignment_evidence_v2_insert,
)


class AccountOwnerAssignmentEvidenceV2Clock(Protocol):
    """Authoritative persistence clock."""

    def now(self) -> datetime: ...


class DjangoAccountOwnerAssignmentEvidenceV2Clock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return one aware server timestamp."""

        return timezone.now()


class DjangoAccountOwnerAssignmentEvidenceV2Repository:
    """Append immutable subjects/evidence after closed-world validation."""

    def __init__(
        self,
        *,
        clock: AccountOwnerAssignmentEvidenceV2Clock | None = None,
        using: str = "default",
    ) -> None:
        self._clock = clock or DjangoAccountOwnerAssignmentEvidenceV2Clock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nestable private append unit of work."""

        if self._uow is not None:
            raise AccountOwnerAssignmentEvidenceV2Conflict("nested owner-assignment v2 UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_owner_assignment_evidence_v2_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated authoritative repository clock."""

        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise AccountOwnerAssignmentEvidenceV2Corruption("repository clock is naive")
        return value

    def get_subject_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV2 | None:
        """Return one subject identity winner knowable at the cutoff."""

        self._cutoff(as_of)
        subjects, _ = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in subjects
            if value.subject_id == evidence_id
            and value.subject_version == evidence_version
            and value.requested_at <= as_of
        )
        if len(matches) > 1:
            raise AccountOwnerAssignmentEvidenceV2Corruption("subject winner is ambiguous")
        return matches[0] if matches else None

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV2, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV2:
        """Append or replay the exact subject identity first winner."""

        checked = _subject(subject)
        self._require_uow()
        _aware(recorded_at, "subject recorded_at")
        if recorded_at != checked.requested_at:
            raise AccountOwnerAssignmentEvidenceV2Conflict(
                "subject persisted_at must equal requested_at"
            )
        subjects, _ = self._closed_world(lock=True)
        anchors = tuple(
            value
            for _, value in subjects
            if (
                value.subject_id == checked.subject_id
                and value.subject_version == checked.subject_version
            )
            or value.identity_hash == checked.identity_hash
            or value.content_hash == checked.content_hash
        )
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise AccountOwnerAssignmentEvidenceV2Conflict("subject first winner differs")
        values = _subject_values(checked)
        try:
            self._insert(AccountOwnerAssignmentSubjectV2Model, values)
        except IntegrityError as error:
            subjects, _ = self._closed_world(lock=True)
            exact = tuple(value for _, value in subjects if value == checked)
            if len(exact) == 1:
                return exact[0]
            raise AccountOwnerAssignmentEvidenceV2Conflict(
                "concurrent subject first winner"
            ) from error
        restored = self.get_subject_winner(
            evidence_id=checked.subject_id,
            evidence_version=checked.subject_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentEvidenceV2Corruption("subject restore mismatch")
        return restored

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return one evidence identity winner knowable at the cutoff."""

        self._cutoff(as_of)
        _, evidence = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in evidence
            if value.evidence_id == evidence_id
            and value.evidence_version == evidence_version
            and value.recorded_at <= as_of
        )
        if len(matches) > 1:
            raise AccountOwnerAssignmentEvidenceV2Corruption("evidence winner is ambiguous")
        return matches[0] if matches else None

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return the visible logical account-key head without expiry fallback."""

        self._cutoff(as_of)
        _, evidence = self._closed_world(lock=False)
        records = tuple(
            value
            for _, value in evidence
            if value.recorded_at <= as_of
            and value.subject.physical.account_namespace == account_namespace
            and value.subject.physical.account_id == account_id
        )
        return _chain_head(records) if records else None

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return the visible logical underlying-key head without fallback."""

        self._cutoff(as_of)
        _, evidence = self._closed_world(lock=False)
        records = tuple(
            value
            for _, value in evidence
            if value.recorded_at <= as_of
            and value.subject.physical.underlying_unified_account_namespace
            == underlying_unified_account_namespace
            and value.subject.physical.underlying_unified_account_id
            == underlying_unified_account_id
        )
        return _chain_head(records) if records else None

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidenceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2:
        """CAS append against both mapping heads or replay one exact candidate."""

        checked = _evidence(evidence)
        self._require_uow()
        _aware(recorded_at, "evidence recorded_at")
        if recorded_at != checked.recorded_at:
            raise AccountOwnerAssignmentEvidenceV2Conflict(
                "evidence persisted_at must equal recorded_at"
            )
        if checked.supersedes_content_hash != expected_predecessor_hash:
            raise AccountOwnerAssignmentEvidenceV2Conflict("evidence predecessor mismatch")
        subjects, records = self._closed_world(lock=True)
        subject_rows = tuple((row, value) for row, value in subjects if value == checked.subject)
        if len(subject_rows) != 1:
            raise AccountOwnerAssignmentEvidenceV2Conflict("evidence requires exact subject")
        anchors = tuple(
            value
            for row, value in records
            if (
                value.evidence_id == checked.evidence_id
                and value.evidence_version == checked.evidence_version
            )
            or value.identity_hash == checked.identity_hash
            or value.content_hash == checked.content_hash
            or value.subject.content_hash == checked.subject.content_hash
            or (
                checked.supersedes_content_hash is None
                and (
                    row.account_root_claim_hash == checked.account_claim_hash
                    or row.underlying_root_claim_hash == checked.underlying_claim_hash
                )
            )
            or (
                checked.supersedes_content_hash is not None
                and value.supersedes_content_hash == checked.supersedes_content_hash
            )
        )
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise AccountOwnerAssignmentEvidenceV2Conflict("evidence first winner differs")
        account_records = tuple(
            value
            for _, value in records
            if value.recorded_at <= recorded_at and _account_key(value) == _account_key(checked)
        )
        underlying_records = tuple(
            value
            for _, value in records
            if value.recorded_at <= recorded_at
            and _underlying_key(value) == _underlying_key(checked)
        )
        account_head = _chain_head(account_records) if account_records else None
        underlying_head = _chain_head(underlying_records) if underlying_records else None
        if account_head != underlying_head:
            raise AccountOwnerAssignmentEvidenceV2Corruption("mapping heads disagree")
        actual = account_head.content_hash if account_head is not None else None
        if actual != expected_predecessor_hash:
            raise AccountOwnerAssignmentEvidenceV2Conflict("dual-head CAS failed")
        try:
            if account_head is None:
                validate_account_owner_assignment_evidence_v2_root(checked)
            else:
                validate_account_owner_assignment_evidence_v2_successor(account_head, checked)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentEvidenceV2Conflict("invalid evidence append") from error
        values = _evidence_values(checked, subject_pk=subject_rows[0][0].pk)
        try:
            self._insert(AccountOwnerAssignmentEvidenceV2Model, values)
        except IntegrityError as error:
            _, records = self._closed_world(lock=True)
            exact = tuple(value for _, value in records if value == checked)
            if len(exact) == 1:
                return exact[0]
            raise AccountOwnerAssignmentEvidenceV2Conflict(
                "concurrent evidence first winner or successor"
            ) from error
        restored = self.get_winner(
            evidence_id=checked.evidence_id,
            evidence_version=checked.evidence_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentEvidenceV2Corruption("evidence restore mismatch")
        return restored

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return immutable historical evidence by all exact anchors."""

        self._cutoff(as_of)
        _, records = self._closed_world(lock=False)
        anchors = tuple(
            value
            for _, value in records
            if (value.evidence_id == evidence_id and value.evidence_version == evidence_version)
            or value.content_hash == expected_content_hash
        )
        if not anchors:
            return None
        matches = tuple(
            value
            for value in anchors
            if value.evidence_id == evidence_id
            and value.evidence_version == evidence_version
            and value.content_hash == expected_content_hash
            and value.recorded_at <= as_of
        )
        if len(anchors) != 1 or len(matches) > 1:
            raise AccountOwnerAssignmentEvidenceV2Corruption("exact anchors are ambiguous")
        return matches[0] if matches else None

    def _closed_world(self, *, lock: bool) -> tuple[
        tuple[tuple[AccountOwnerAssignmentSubjectV2Model, AccountOwnerAssignmentSubjectV2], ...],
        tuple[tuple[AccountOwnerAssignmentEvidenceV2Model, AccountOwnerAssignmentEvidenceV2], ...],
    ]:
        subject_query = AccountOwnerAssignmentSubjectV2Model._base_manager.using(self._using).all()
        if lock:
            subject_query = subject_query.select_for_update()
        subjects = tuple((row, _restore_subject(row)) for row in subject_query.order_by("pk"))
        by_pk = {row.pk: value for row, value in subjects if row.pk is not None}
        evidence_query = AccountOwnerAssignmentEvidenceV2Model._base_manager.using(
            self._using
        ).all()
        if lock:
            evidence_query = evidence_query.select_for_update()
        evidence: list[
            tuple[AccountOwnerAssignmentEvidenceV2Model, AccountOwnerAssignmentEvidenceV2]
        ] = []
        used_subjects: set[int] = set()
        for row in evidence_query.order_by("pk"):
            subject = by_pk.get(row.subject_id)
            if subject is None or row.subject_id in used_subjects:
                raise AccountOwnerAssignmentEvidenceV2Corruption(
                    "evidence subject OneToOne is orphaned or duplicated"
                )
            value = _restore_evidence(row, subject)
            used_subjects.add(row.subject_id)
            evidence.append((row, value))
        return subjects, tuple(evidence)

    def _insert(
        self,
        model_type: (
            type[AccountOwnerAssignmentSubjectV2Model] | type[AccountOwnerAssignmentEvidenceV2Model]
        ),
        values: dict[str, object],
    ) -> None:
        token = self._require_uow()
        with _claim_account_owner_assignment_evidence_v2_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise AccountOwnerAssignmentEvidenceV2Conflict("append requires private UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        _aware(as_of, "as_of")
        if as_of > self.now():
            raise AccountOwnerAssignmentEvidenceV2Unavailable("future as_of is forbidden")


def _subject(value: object) -> AccountOwnerAssignmentSubjectV2:
    if type(value) is not AccountOwnerAssignmentSubjectV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("subject type substitution")
    AccountOwnerAssignmentSubjectV2.__post_init__(value)
    return value


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV2:
    if type(value) is not AccountOwnerAssignmentEvidenceV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("evidence type substitution")
    AccountOwnerAssignmentEvidenceV2.__post_init__(value)
    return value


def _aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentEvidenceV2Unavailable(f"{name} must be timezone-aware")


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fixed(value: AccountOwnerAssignmentSubjectV2 | AccountOwnerAssignmentEvidenceV2) -> str:
    payload: dict[str, object] = {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "status": value.status,
    }
    if type(value) is AccountOwnerAssignmentEvidenceV2:
        payload["blocker_codes"] = list(value.blocker_codes)
    return _hash(payload)


def _subject_values(value: AccountOwnerAssignmentSubjectV2) -> dict[str, object]:
    physical, receipt = value.physical, value.receipt
    payload = encode_account_owner_assignment_subject_v2(value)
    upstream = _hash({"physical": payload["physical"], "receipt": payload["receipt"]})
    values: dict[str, object] = {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "physical_observation_id": physical.observation_id,
        "physical_observation_version": physical.observation_version,
        "physical_identity_hash": physical.identity_hash,
        "physical_content_hash": physical.content_hash,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "receipt_identity_hash": receipt.identity_hash,
        "receipt_content_hash": receipt.content_hash,
        "account_namespace": physical.account_namespace,
        "account_id": physical.account_id,
        "underlying_unified_account_namespace": physical.underlying_unified_account_namespace,
        "underlying_unified_account_id": physical.underlying_unified_account_id,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "permission": value.permission,
        "status": value.status,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "upstream_binding_seal": upstream,
        "fixed_authority_seal": _fixed(value),
        "record_seal": _hash({"subject": payload}),
        "persisted_at": value.requested_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "upstream_binding_seal": upstream,
            "fixed_authority_seal": values["fixed_authority_seal"],
            "persisted_at": _time(value.requested_at),
        }
    )
    return values


def _evidence_values(
    value: AccountOwnerAssignmentEvidenceV2, *, subject_pk: int | None
) -> dict[str, object]:
    if subject_pk is None:
        raise AccountOwnerAssignmentEvidenceV2Corruption("subject has no database identity")
    physical, actor = value.subject.physical, value.approved_by
    payload = encode_account_owner_assignment_evidence_v2(value)
    values: dict[str, object] = {
        "subject_id": subject_pk,
        "subject_content_hash": value.subject.content_hash,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "evidence_id": value.evidence_id,
        "evidence_version": value.evidence_version,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "account_namespace": physical.account_namespace,
        "account_id": physical.account_id,
        "underlying_unified_account_namespace": physical.underlying_unified_account_namespace,
        "underlying_unified_account_id": physical.underlying_unified_account_id,
        "assignment_state": value.assignment_state,
        "assigned_owner_user_id": value.assigned_owner_user_id,
        "approved_actor_id": actor.actor_id,
        "approved_user_id": actor.user_id,
        "approved_role": actor.role,
        "approved_kind": actor.kind,
        "approved_is_staff": actor.is_staff,
        "approved_at": value.approved_at,
        "recorded_at": value.recorded_at,
        "approval_valid_until": value.approval_valid_until,
        "valid_until": value.valid_until,
        "supersedes_content_hash": value.supersedes_content_hash,
        "account_root_claim_hash": (
            value.account_claim_hash if value.supersedes_content_hash is None else None
        ),
        "underlying_root_claim_hash": (
            value.underlying_claim_hash if value.supersedes_content_hash is None else None
        ),
        "permission": value.permission,
        "status": value.status,
        "blocker_codes": list(value.blocker_codes),
        "canonical_payload": payload,
        "subject_binding_seal": _hash(payload["subject"]),
        "approver_binding_seal": _hash(payload["approved_by"]),
        "mapping_binding_seal": _hash(
            {
                "account_claim_hash": value.account_claim_hash,
                "underlying_claim_hash": value.underlying_claim_hash,
            }
        ),
        "fixed_authority_seal": _fixed(value),
        "record_seal": _hash({"evidence": payload}),
        "persisted_at": value.recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "subject_binding_seal": values["subject_binding_seal"],
            "approver_binding_seal": values["approver_binding_seal"],
            "mapping_binding_seal": values["mapping_binding_seal"],
            "fixed_authority_seal": values["fixed_authority_seal"],
            "account_root_claim_hash": values["account_root_claim_hash"],
            "underlying_root_claim_hash": values["underlying_root_claim_hash"],
            "persisted_at": _time(value.recorded_at),
        }
    )
    return values


def _restore_subject(row: AccountOwnerAssignmentSubjectV2Model) -> AccountOwnerAssignmentSubjectV2:
    try:
        value = decode_account_owner_assignment_subject_v2(row.canonical_payload)
    except AccountOwnerAssignmentEvidenceV2CodecError as error:
        raise AccountOwnerAssignmentEvidenceV2Corruption("subject payload corrupt") from error
    expected = _subject_values(value)
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                f"subject ledger seal mismatch: {name}"
            )
    return value


def _restore_evidence(
    row: AccountOwnerAssignmentEvidenceV2Model, subject: AccountOwnerAssignmentSubjectV2
) -> AccountOwnerAssignmentEvidenceV2:
    try:
        value = decode_account_owner_assignment_evidence_v2(row.canonical_payload)
    except AccountOwnerAssignmentEvidenceV2CodecError as error:
        raise AccountOwnerAssignmentEvidenceV2Corruption("evidence payload corrupt") from error
    if value.subject != subject:
        raise AccountOwnerAssignmentEvidenceV2Corruption("evidence subject binding mismatch")
    expected = _evidence_values(value, subject_pk=row.subject_id)
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                f"evidence ledger seal mismatch: {name}"
            )
    return value


def _account_key(value: AccountOwnerAssignmentEvidenceV2) -> tuple[str, str]:
    physical = value.subject.physical
    return physical.account_namespace, physical.account_id


def _underlying_key(value: AccountOwnerAssignmentEvidenceV2) -> tuple[str, int]:
    physical = value.subject.physical
    return (
        physical.underlying_unified_account_namespace,
        physical.underlying_unified_account_id,
    )


def _chain_head(
    records: tuple[AccountOwnerAssignmentEvidenceV2, ...],
) -> AccountOwnerAssignmentEvidenceV2:
    by_hash = {value.content_hash: value for value in records}
    if len(by_hash) != len(records):
        raise AccountOwnerAssignmentEvidenceV2Corruption("duplicate evidence content")
    roots = tuple(value for value in records if value.supersedes_content_hash is None)
    if len(roots) != 1:
        raise AccountOwnerAssignmentEvidenceV2Corruption("mapping chain root count")
    successor: dict[str, AccountOwnerAssignmentEvidenceV2] = {}
    for value in records:
        predecessor_hash = value.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None or predecessor_hash in successor:
            raise AccountOwnerAssignmentEvidenceV2Corruption("mapping chain missing or forked")
        try:
            validate_account_owner_assignment_evidence_v2_successor(predecessor, value)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentEvidenceV2Corruption("mapping successor invalid") from error
        successor[predecessor_hash] = value
    visited: set[str] = set()
    current = roots[0]
    while current.content_hash not in visited:
        visited.add(current.content_hash)
        following = successor.get(current.content_hash)
        if following is None:
            break
        current = following
    if len(visited) != len(records):
        raise AccountOwnerAssignmentEvidenceV2Corruption("mapping chain disconnected or cyclic")
    return current


__all__ = [
    "AccountOwnerAssignmentEvidenceV2Clock",
    "DjangoAccountOwnerAssignmentEvidenceV2Clock",
    "DjangoAccountOwnerAssignmentEvidenceV2Repository",
]
