"""Closed-world Django repository for Account owner-assignment evidence v3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
    AccountOwnerAssignmentSubjectV3,
    validate_account_owner_assignment_evidence_v3_dual_mapping_root,
    validate_account_owner_assignment_evidence_v3_root,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_codec import (
    AccountOwnerAssignmentEvidenceV3CodecError,
    decode_account_owner_assignment_evidence_v3,
    decode_account_owner_assignment_subject_v3,
    encode_account_owner_assignment_evidence_v3,
    encode_account_owner_assignment_subject_v3,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_models import (
    AccountOwnerAssignmentEvidenceV3Model,
    AccountOwnerAssignmentSubjectV3Model,
    _activate_account_owner_assignment_evidence_v3_uow,
    _claim_account_owner_assignment_evidence_v3_insert,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_models import (
    AccountOwnerAssignmentProvenanceReceiptV3Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)


class AccountOwnerAssignmentEvidenceV3Clock(Protocol):
    def now(self) -> datetime: ...


_ValueT = TypeVar("_ValueT")


class DjangoAccountOwnerAssignmentEvidenceV3Clock:
    def now(self) -> datetime:
        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    subjects: tuple[
        tuple[AccountOwnerAssignmentSubjectV3Model, AccountOwnerAssignmentSubjectV3], ...
    ]
    evidence: tuple[
        tuple[AccountOwnerAssignmentEvidenceV3Model, AccountOwnerAssignmentEvidenceV3], ...
    ]


class DjangoAccountOwnerAssignmentEvidenceV3Repository:
    """Append exact subject/evidence roots after complete upstream replay."""

    def __init__(
        self, *, clock: AccountOwnerAssignmentEvidenceV3Clock | None = None, using: str = "default"
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._clock = clock or DjangoAccountOwnerAssignmentEvidenceV3Clock()
        self._using = using
        self._receipts = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(using=using)
        self._consumption = DjangoCanonicalAccountCreationConsumptionRepository(using=using)
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        if self._uow is not None:
            raise AccountOwnerAssignmentConflict("nested owner-assignment v3 UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_owner_assignment_evidence_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        value = self._clock.now()
        if not _is_aware(value):
            raise AccountOwnerAssignmentCorruption("repository clock is naive")
        return value

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV3 | None:
        self._cutoff(as_of)
        matches = tuple(
            value
            for _, value in self._closed_world(lock=False).subjects
            if (value.subject_id, value.subject_version) == (subject_id, subject_version)
            and value.requested_at <= as_of
        )
        return _single(matches, "subject identity")

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV3, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV3:
        checked = _subject(subject)
        token = self._require_uow()
        if recorded_at != checked.requested_at:
            raise AccountOwnerAssignmentConflict("subject persisted_at differs")
        self._lock_binding(checked)
        world = self._closed_world(lock=True)
        anchors = tuple(
            value
            for row, value in world.subjects
            if (value.subject_id, value.subject_version)
            == (checked.subject_id, checked.subject_version)
            or value.identity_hash == checked.identity_hash
            or value.content_hash == checked.content_hash
            or row.receipt_id == self._receipt_pk(checked)
        )
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise AccountOwnerAssignmentConflict("subject v3 first winner differs")
        self._validate_subject_upstream(checked, None)
        values = _subject_values(
            checked,
            receipt_pk=self._receipt_pk(checked),
            binding_pk=self._binding_pk(checked),
            root_pk=self._root_pk(checked),
        )
        try:
            with transaction.atomic(using=self._using):
                self._insert(AccountOwnerAssignmentSubjectV3Model, values, token)
        except IntegrityError as error:
            exact = tuple(
                value for _, value in self._closed_world(lock=True).subjects if value == checked
            )
            if len(exact) == 1:
                return exact[0]
            raise AccountOwnerAssignmentConflict("concurrent subject v3 winner") from error
        restored = self.get_subject_winner(
            subject_id=checked.subject_id,
            subject_version=checked.subject_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentCorruption("subject v3 restore mismatch")
        return restored

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self._cutoff(as_of)
        matches = tuple(
            value
            for _, value in self._closed_world(lock=False).evidence
            if (value.evidence_id, value.evidence_version) == (evidence_id, evidence_version)
            and value.recorded_at <= as_of
        )
        return _single(matches, "evidence identity")

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self._cutoff(as_of)
        matches = tuple(
            value
            for _, value in self._closed_world(lock=False).evidence
            if value.recorded_at <= as_of
            and (
                value.subject.binding.account_namespace_claim,
                value.subject.binding.account_id_claim,
            )
            == (account_namespace, account_id)
        )
        return _single(matches, "account mapping root")

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self._cutoff(as_of)
        matches = tuple(
            value
            for _, value in self._closed_world(lock=False).evidence
            if value.recorded_at <= as_of
            and (
                value.subject.binding.underlying_unified_account_namespace_claim,
                value.subject.binding.underlying_unified_account_id_claim,
            )
            == (underlying_unified_account_namespace, underlying_unified_account_id)
        )
        return _single(matches, "underlying mapping root")

    def append_root(
        self,
        evidence: AccountOwnerAssignmentEvidenceV3,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3:
        checked = _evidence(evidence)
        token = self._require_uow()
        if expected_account_head_hash is not None or expected_underlying_head_hash is not None:
            raise AccountOwnerAssignmentConflict("evidence v3 is root-only")
        if recorded_at != checked.recorded_at:
            raise AccountOwnerAssignmentConflict("evidence persisted_at differs")
        self._lock_binding(checked.subject)
        world = self._closed_world(lock=True)
        subject_rows = tuple(
            (row, value) for row, value in world.subjects if value == checked.subject
        )
        if len(subject_rows) != 1:
            raise AccountOwnerAssignmentConflict("evidence requires exact subject v3")
        anchors = tuple(
            value
            for row, value in world.evidence
            if (value.evidence_id, value.evidence_version)
            == (checked.evidence_id, checked.evidence_version)
            or value.identity_hash == checked.identity_hash
            or value.content_hash == checked.content_hash
            or row.subject_id == subject_rows[0][0].pk
            or row.account_root_claim_hash == checked.account_claim_hash
            or row.underlying_root_claim_hash == checked.underlying_claim_hash
        )
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise AccountOwnerAssignmentConflict("evidence v3 root already occupied")
        self._validate_subject_upstream(checked.subject, checked.recorded_at)
        values = _evidence_values(checked, subject_pk=subject_rows[0][0].pk)
        try:
            validate_account_owner_assignment_evidence_v3_root(checked)
            validate_account_owner_assignment_evidence_v3_dual_mapping_root(
                checked,
                account_claim_hash=checked.account_claim_hash,
                underlying_claim_hash=checked.underlying_claim_hash,
            )
            with transaction.atomic(using=self._using):
                self._insert(AccountOwnerAssignmentEvidenceV3Model, values, token)
        except IntegrityError as error:
            exact = tuple(
                value for _, value in self._closed_world(lock=True).evidence if value == checked
            )
            if len(exact) == 1:
                return exact[0]
            raise AccountOwnerAssignmentConflict("concurrent evidence v3 root") from error
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("invalid evidence v3 root") from error
        restored = self.get_winner(
            evidence_id=checked.evidence_id,
            evidence_version=checked.evidence_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentCorruption("evidence v3 restore mismatch")
        return restored

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self._cutoff(as_of)
        anchors = tuple(
            value
            for _, value in self._closed_world(lock=False).evidence
            if (value.evidence_id, value.evidence_version) == (evidence_id, evidence_version)
            or value.content_hash == expected_content_hash
        )
        matches = tuple(
            value
            for value in anchors
            if (value.evidence_id, value.evidence_version, value.content_hash)
            == (evidence_id, evidence_version, expected_content_hash)
            and value.recorded_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise AccountOwnerAssignmentCorruption("evidence v3 exact anchors disagree")
        return matches[0] if matches else None

    def _closed_world(self, *, lock: bool) -> _World:
        subject_query = AccountOwnerAssignmentSubjectV3Model._base_manager.using(
            self._using
        ).select_related(
            "receipt", "binding", "creation_root", "receipt__binding", "binding__creation_root"
        )
        evidence_query = AccountOwnerAssignmentEvidenceV3Model._base_manager.using(
            self._using
        ).all()
        if lock:
            subject_query = subject_query.select_for_update()
            evidence_query = evidence_query.select_for_update()
        subjects: list[
            tuple[AccountOwnerAssignmentSubjectV3Model, AccountOwnerAssignmentSubjectV3]
        ] = []
        for row in subject_query.order_by("pk"):
            value = _restore_subject(row)
            self._validate_subject_upstream(value, None, row=row)
            subjects.append((row, value))
        by_pk = {row.pk: value for row, value in subjects}
        evidence: list[
            tuple[AccountOwnerAssignmentEvidenceV3Model, AccountOwnerAssignmentEvidenceV3]
        ] = []
        used_subjects: set[int] = set()
        for evidence_row in evidence_query.order_by("pk"):
            subject = by_pk.get(evidence_row.subject_id)
            if subject is None or evidence_row.subject_id in used_subjects:
                raise AccountOwnerAssignmentCorruption("evidence v3 subject orphan or duplicate")
            evidence_value = _restore_evidence(evidence_row, subject)
            self._validate_subject_upstream(subject, evidence_value.recorded_at)
            used_subjects.add(evidence_row.subject_id)
            evidence.append((evidence_row, evidence_value))
        return _World(tuple(subjects), tuple(evidence))

    def _validate_subject_upstream(
        self,
        subject: AccountOwnerAssignmentSubjectV3,
        evidence_at: datetime | None,
        *,
        row: AccountOwnerAssignmentSubjectV3Model | None = None,
    ) -> None:
        receipt = subject.receipt
        try:
            exact = self._receipts.get_exact_by_hash(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                expected_content_hash=receipt.content_hash,
                as_of=subject.requested_at,
            )
            head_at_request = self._receipts.get_current_head(
                receipt_id=receipt.receipt_id, as_of=subject.requested_at
            )
            binding = self._consumption.get_winner(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                as_of=receipt.recorded_at,
            )
        except (
            CanonicalAccountCreationBindingV2Conflict,
            CanonicalAccountCreationBindingV2Corruption,
            CanonicalAccountCreationBindingV2Unavailable,
        ) as error:
            raise AccountOwnerAssignmentCorruption(
                "subject v3 upstream ledger is corrupt"
            ) from error
        if (
            exact is None
            or exact.receipt != receipt
            or head_at_request is None
            or head_at_request.receipt != receipt
            or not receipt.is_current_at(subject.requested_at)
            or binding is None
            or binding.binding != subject.binding
        ):
            raise AccountOwnerAssignmentCorruption(
                "subject v3 upstream is unavailable or substituted"
            )
        if evidence_at is not None:
            head_at_evidence = self._receipts.get_current_head(
                receipt_id=receipt.receipt_id, as_of=evidence_at
            )
            if head_at_evidence is None or head_at_evidence.receipt != receipt:
                raise AccountOwnerAssignmentCorruption("subject receipt was not head at approval")
        if row is not None and (
            row.receipt.binding_id != row.binding_id
            or row.binding.creation_root_id != row.creation_root_id
            or row.receipt_id != self._receipt_pk(subject)
            or row.binding_id != self._binding_pk(subject)
            or row.creation_root_id != self._root_pk(subject)
        ):
            raise AccountOwnerAssignmentCorruption("subject v3 FK chain differs")

    def _receipt_pk(self, subject: AccountOwnerAssignmentSubjectV3) -> int:
        row = self._receipts_model(subject)
        if row.pk is None:
            raise AccountOwnerAssignmentCorruption("Receipt-v3 has no database identity")
        return int(row.pk)

    def _receipts_model(
        self, subject: AccountOwnerAssignmentSubjectV3
    ) -> AccountOwnerAssignmentProvenanceReceiptV3Model:
        row = (
            AccountOwnerAssignmentProvenanceReceiptV3Model._base_manager.using(self._using)
            .filter(
                receipt_id=subject.receipt.receipt_id,
                receipt_version=subject.receipt.receipt_version,
                content_hash=subject.receipt.content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentCorruption("Receipt-v3 row unavailable")
        return row

    def _binding_pk(self, subject: AccountOwnerAssignmentSubjectV3) -> int:
        row = (
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .filter(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                content_hash=subject.binding.content_hash,
            )
            .first()
        )
        if row is None or row.pk is None:
            raise AccountOwnerAssignmentCorruption("Binding-v2 row unavailable")
        return int(row.pk)

    def _root_pk(self, subject: AccountOwnerAssignmentSubjectV3) -> int:
        row = (
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .filter(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                content_hash=subject.binding.content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentCorruption("Physical-v3 row unavailable")
        return int(row.creation_root_id)

    def _lock_binding(self, subject: AccountOwnerAssignmentSubjectV3) -> None:
        row = (
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                content_hash=subject.binding.content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentCorruption("Binding-v2 lock unavailable")

    def _insert(
        self,
        model_type: (
            type[AccountOwnerAssignmentSubjectV3Model] | type[AccountOwnerAssignmentEvidenceV3Model]
        ),
        values: dict[str, object],
        token: object,
    ) -> None:
        with _claim_account_owner_assignment_evidence_v3_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise AccountOwnerAssignmentConflict("append requires private UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        if not _is_aware(as_of):
            raise AccountOwnerAssignmentUnavailable("as_of must be timezone-aware")
        if as_of > self.now():
            raise AccountOwnerAssignmentUnavailable("future as_of is forbidden")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fixed(value: AccountOwnerAssignmentSubjectV3 | AccountOwnerAssignmentEvidenceV3) -> str:
    return _hash(
        {
            "owner": value.owner,
            "artifact_type": value.artifact_type,
            "schema": value.schema,
            "permission": value.permission,
            "status": value.status,
            "blocker_codes": list(value.blocker_codes),
        }
    )


def _subject_values(
    value: AccountOwnerAssignmentSubjectV3, *, receipt_pk: int, binding_pk: int, root_pk: int
) -> dict[str, object]:
    receipt, binding, root = value.receipt, value.binding, value.physical_root
    physical, claimant = root.physical_observation, value.claimant
    payload = encode_account_owner_assignment_subject_v3(value)
    values: dict[str, object] = {
        "receipt_id": receipt_pk,
        "binding_id": binding_pk,
        "creation_root_id": root_pk,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "receipt_ref_id": receipt.receipt_id,
        "receipt_ref_version": receipt.receipt_version,
        "binding_ref_id": binding.binding_id,
        "binding_ref_version": binding.binding_version,
        "creation_root_ref_id": root.observation_id,
        "creation_root_ref_version": root.observation_version,
        "receipt_identity_hash": value.receipt_identity_hash,
        "receipt_content_hash": value.receipt_content_hash,
        "binding_identity_hash": value.binding_identity_hash,
        "binding_content_hash": value.binding_content_hash,
        "creation_root_identity_hash": value.creation_root_identity_hash,
        "creation_root_content_hash": value.creation_root_content_hash,
        "binding_account_claim_hash": value.account_claim_hash,
        "binding_underlying_claim_hash": value.underlying_claim_hash,
        "physical_observation_content_hash": value.physical_observation_content_hash,
        "physical_source_content_hash": value.physical_source_content_hash,
        "physical_raw_observation_content_hash": value.physical_raw_observation_content_hash,
        "account_namespace": binding.account_namespace_claim,
        "account_id": binding.account_id_claim,
        "underlying_unified_account_namespace": binding.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id": binding.underlying_unified_account_id_claim,
        "assigned_owner_user_id": receipt.assigned_owner_user_id,
        "physical_row_user_id": physical.row_user_id,
        "claimant_actor_id": claimant.actor_id,
        "claimant_user_id": claimant.user_id,
        "claimant_role": claimant.role,
        "claimant_kind": claimant.kind,
        "claimant_is_staff": claimant.is_staff,
        "receipt_recorded_at": receipt.recorded_at,
        "receipt_valid_until": receipt.valid_until,
        "creation_root_recorded_at": root.recorded_at,
        "creation_root_valid_until": root.valid_until,
        "requested_at": value.requested_at,
        "valid_until": value.valid_until,
        "permission": value.permission,
        "status": value.status,
        "blocker_codes": list(value.blocker_codes),
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "upstream_binding_seal": _hash(
            {
                "receipt": payload["receipt"],
                "binding": payload["binding"],
                "physical_root": payload["physical_root"],
            }
        ),
        "claimant_binding_seal": _hash(receipt.claimant.to_payload()),
        "fixed_authority_seal": _fixed(value),
        "header_seal": _hash(
            {"subject_id": value.subject_id, "subject_version": value.subject_version}
        ),
        "record_seal": _hash({"subject": payload}),
        "persisted_at": value.requested_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "receipt_pk": receipt_pk,
            "binding_pk": binding_pk,
            "root_pk": root_pk,
            "persisted_at": _time(value.requested_at),
        }
    )
    return values


def _evidence_values(
    value: AccountOwnerAssignmentEvidenceV3, *, subject_pk: int | None
) -> dict[str, object]:
    if subject_pk is None:
        raise AccountOwnerAssignmentCorruption("subject v3 has no database identity")
    subject, binding, actor = value.subject, value.subject.binding, value.approved_by
    payload = encode_account_owner_assignment_evidence_v3(value)
    values: dict[str, object] = {
        "subject_id": subject_pk,
        "subject_content_hash": subject.content_hash,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "evidence_id": value.evidence_id,
        "evidence_version": value.evidence_version,
        "assignment_state": value.assignment_state,
        "assigned_owner_user_id": value.assigned_owner_user_id,
        "account_namespace": binding.account_namespace_claim,
        "account_id": binding.account_id_claim,
        "underlying_unified_account_namespace": binding.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id": binding.underlying_unified_account_id_claim,
        "claimant_actor_id": subject.claimant.actor_id,
        "claimant_user_id": subject.claimant.user_id,
        "approved_actor_id": actor.actor_id,
        "approved_user_id": actor.user_id,
        "approved_role": actor.role,
        "approved_kind": actor.kind,
        "approved_is_staff": actor.is_staff,
        "subject_requested_at": subject.requested_at,
        "subject_valid_until": subject.valid_until,
        "approved_at": value.approved_at,
        "recorded_at": value.recorded_at,
        "approval_valid_until": value.approval_valid_until,
        "valid_until": value.valid_until,
        "account_root_claim_hash": value.account_claim_hash,
        "underlying_root_claim_hash": value.underlying_claim_hash,
        "permission": value.permission,
        "status": value.status,
        "blocker_codes": list(value.blocker_codes),
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "subject_binding_seal": _hash(payload["subject"]),
        "approver_binding_seal": _hash(payload["approved_by"]),
        "mapping_binding_seal": _hash(
            {
                "account_root_claim_hash": value.account_claim_hash,
                "underlying_root_claim_hash": value.underlying_claim_hash,
            }
        ),
        "fixed_authority_seal": _fixed(value),
        "header_seal": _hash(
            {"evidence_id": value.evidence_id, "evidence_version": value.evidence_version}
        ),
        "record_seal": _hash({"evidence": payload}),
        "persisted_at": value.recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "subject_pk": subject_pk,
            "persisted_at": _time(value.recorded_at),
        }
    )
    return values


def _restore_subject(row: AccountOwnerAssignmentSubjectV3Model) -> AccountOwnerAssignmentSubjectV3:
    try:
        value = decode_account_owner_assignment_subject_v3(row.canonical_payload)
    except AccountOwnerAssignmentEvidenceV3CodecError as error:
        raise AccountOwnerAssignmentCorruption("subject v3 payload corrupt") from error
    expected = _subject_values(
        value, receipt_pk=row.receipt_id, binding_pk=row.binding_id, root_pk=row.creation_root_id
    )
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise AccountOwnerAssignmentCorruption(f"subject v3 ledger seal mismatch: {name}")
    return value


def _restore_evidence(
    row: AccountOwnerAssignmentEvidenceV3Model, subject: AccountOwnerAssignmentSubjectV3
) -> AccountOwnerAssignmentEvidenceV3:
    try:
        value = decode_account_owner_assignment_evidence_v3(row.canonical_payload)
    except AccountOwnerAssignmentEvidenceV3CodecError as error:
        raise AccountOwnerAssignmentCorruption("evidence v3 payload corrupt") from error
    if value.subject != subject:
        raise AccountOwnerAssignmentCorruption("evidence v3 subject binding differs")
    expected = _evidence_values(value, subject_pk=row.subject_id)
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise AccountOwnerAssignmentCorruption(f"evidence v3 ledger seal mismatch: {name}")
    return value


def _subject(value: object) -> AccountOwnerAssignmentSubjectV3:
    if type(value) is not AccountOwnerAssignmentSubjectV3:
        raise AccountOwnerAssignmentCorruption("subject v3 type substitution")
    value.__post_init__()
    return value


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV3:
    if type(value) is not AccountOwnerAssignmentEvidenceV3:
        raise AccountOwnerAssignmentCorruption("evidence v3 type substitution")
    value.__post_init__()
    return value


def _single(values: tuple[_ValueT, ...], label: str) -> _ValueT | None:
    if len(values) > 1:
        raise AccountOwnerAssignmentCorruption(f"{label} is ambiguous")
    return values[0] if values else None


def _is_aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountOwnerAssignmentEvidenceV3Clock",
    "DjangoAccountOwnerAssignmentEvidenceV3Clock",
    "DjangoAccountOwnerAssignmentEvidenceV3Repository",
]
