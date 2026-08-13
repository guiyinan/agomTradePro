"""Two-stage ID-only workflow for inactive Account owner assignment evidence."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from apps.account.domain.account_owner_assignment_evidence import (
    ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE,
    ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS,
    ACCOUNT_OWNER_ASSIGNMENT_OWNER,
    ACCOUNT_OWNER_ASSIGNMENT_PERMISSION,
    ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER,
    ACCOUNT_OWNER_ASSIGNMENT_SCHEMA,
    ACCOUNT_OWNER_ASSIGNMENT_STATUS,
    ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE,
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
    validate_account_owner_assignment_successor,
)


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class AccountOwnerAssignmentUnavailable(ValueError):
    """An exact current subject, row, receipt, or evidence is unavailable."""


class AccountOwnerAssignmentConflict(ValueError):
    """An immutable identity or logical chain has another first winner."""


class AccountOwnerAssignmentCorruption(ValueError):
    """A provider or repository returned substituted evidence."""


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentServerActor:
    """Server-authenticated human actor; approval additionally requires staff."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = False

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("actor user_id must be an exact positive integer")
        _require_token(self.role, "role")
        if self.kind != "human":
            raise ValueError("account owner assignment actor must be human")
        if type(self.is_staff) is not bool:
            raise TypeError("actor is_staff must be an exact boolean")

    def to_domain(self) -> AccountOwnerAssignmentActor:
        """Project the authenticated server actor into the pure Domain value."""

        return AccountOwnerAssignmentActor(
            actor_id=self.actor_id,
            user_id=self.user_id,
            role=self.role,
            kind=self.kind,
            is_staff=self.is_staff,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the exact authenticated actor boundary payload."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class ExactAccountRowObservation:
    """Consumer-owned exact immutable observation of one unified account row."""

    observation_id: str
    observation_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if (
            self.owner != ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER
            or self.artifact_type != ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE
        ):
            raise ValueError("row observation authority is invalid")
        if self.account_namespace != ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE:
            raise ValueError("row observation account_namespace is invalid")
        if (
            self.underlying_unified_account_namespace
            != ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE
        ):
            raise ValueError("row observation underlying namespace is invalid")
        for field_name in ("observed_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.observed_at <= self.recorded_at < self.valid_until:
            raise ValueError("row observation clock sequence is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact row is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the exact row observation boundary payload."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "observation_id": self.observation_id,
            "observation_version": self.observation_version,
            "content_hash": self.content_hash,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "observed_at": _utc_text(self.observed_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


_RECEIPT_TYPES = {
    "creation": "account_creation_receipt",
    "migration": "account_legacy_default_assignment_receipt",
    "manual_reclaim": "account_owner_reclaim_receipt",
}


@dataclass(frozen=True, slots=True)
class ExactAccountAssignmentProvenanceReceipt:
    """Consumer-owned Account receipt defining one owner-assignment claim."""

    receipt_id: str
    receipt_version: str
    content_hash: str
    provenance_kind: str
    assignment_state: str
    assigned_owner_user_id: int | None
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_observation_id: str
    row_observation_version: str
    row_observation_content_hash: str
    claimant_actor_id: str
    claimant_user_id: int
    claimant_role: str
    claimant_kind: str
    claimant_is_staff: bool
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_OWNER
    artifact_type: str = "account_creation_receipt"

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "receipt_version",
            "provenance_kind",
            "assignment_state",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "row_observation_id",
            "row_observation_version",
            "claimant_actor_id",
            "claimant_role",
            "claimant_kind",
            "owner",
            "artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        _require_hash(self.row_observation_content_hash, "row_observation_content_hash")
        claimant = self.claimant
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if self.owner != ACCOUNT_OWNER_ASSIGNMENT_OWNER:
            raise ValueError("provenance receipt owner is invalid")
        expected_type = _RECEIPT_TYPES.get(self.provenance_kind)
        if expected_type is None or self.artifact_type != expected_type:
            raise ValueError("provenance receipt kind or artifact type is invalid")
        if self.assignment_state == "authoritative":
            if self.provenance_kind not in ("creation", "manual_reclaim"):
                raise ValueError("authoritative assignment provenance is invalid")
            if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
                raise ValueError("authoritative receipt requires an exact owner")
        elif self.assignment_state == "legacy_default":
            if self.provenance_kind != "migration":
                raise ValueError("legacy_default receipt requires migration provenance")
            if self.assigned_owner_user_id is not None:
                raise ValueError("legacy_default receipt cannot claim an owner")
        else:
            raise ValueError("provenance receipt assignment_state is invalid")
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("provenance receipt clock sequence is invalid")
        if (
            self.assignment_state == "authoritative"
            and self.assigned_owner_user_id != claimant.user_id
        ):
            raise ValueError("authoritative receipt claimant must be the assigned owner")

    @property
    def claimant(self) -> AccountOwnerAssignmentServerActor:
        """Return the exact claimant sealed by the owner-side receipt."""

        return AccountOwnerAssignmentServerActor(
            actor_id=self.claimant_actor_id,
            user_id=self.claimant_user_id,
            role=self.claimant_role,
            kind=self.claimant_kind,
            is_staff=self.claimant_is_staff,
        )

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact receipt is knowable and current."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the exact provenance receipt boundary payload."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "receipt_id": self.receipt_id,
            "receipt_version": self.receipt_version,
            "content_hash": self.content_hash,
            "provenance_kind": self.provenance_kind,
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_observation_id": self.row_observation_id,
            "row_observation_version": self.row_observation_version,
            "row_observation_content_hash": self.row_observation_content_hash,
            "claimant": self.claimant.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentSubject:
    """First-winner registration of exact row and provenance definitions."""

    evidence_id: str
    evidence_version: str
    row: ExactAccountRowObservation
    receipt: ExactAccountAssignmentProvenanceReceipt
    claimant: AccountOwnerAssignmentServerActor
    requested_at: datetime
    valid_until: datetime
    content_hash: str = ""

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "evidence_id")
        _require_token(self.evidence_version, "evidence_version")
        if type(self.row) is not ExactAccountRowObservation:
            raise TypeError("row must be an exact ExactAccountRowObservation")
        if type(self.receipt) is not ExactAccountAssignmentProvenanceReceipt:
            raise TypeError("receipt must be an exact provenance receipt")
        if type(self.claimant) is not AccountOwnerAssignmentServerActor:
            raise TypeError("claimant must be an exact server actor")
        ExactAccountRowObservation.__post_init__(self.row)
        ExactAccountAssignmentProvenanceReceipt.__post_init__(self.receipt)
        AccountOwnerAssignmentServerActor.__post_init__(self.claimant)
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.valid_until, "valid_until")
        if not self.requested_at < self.valid_until:
            raise ValueError("assignment subject validity is invalid")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "subject content_hash")
            if self.content_hash != expected:
                raise ValueError("assignment subject content_hash is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this registered subject is current at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.requested_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_version": self.evidence_version,
            "row": self.row.to_payload(),
            "receipt": self.receipt.to_payload(),
            "claimant": self.claimant.to_payload(),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class RegisterAccountOwnerAssignmentCommand:
    """ID-only registration selector; no hashes, facts, actors, or clocks."""

    evidence_id: str
    evidence_version: str
    row_observation_id: str
    row_observation_version: str
    provenance_receipt_id: str
    provenance_receipt_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "evidence_version",
            "row_observation_id",
            "row_observation_version",
            "provenance_receipt_id",
            "provenance_receipt_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ApproveAccountOwnerAssignmentCommand:
    """ID-only approval selector using server-owned actor and clock."""

    evidence_id: str
    evidence_version: str

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "evidence_id")
        _require_token(self.evidence_version, "evidence_version")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentCommand:
    """Exact evidence identity/hash/PIT selector."""

    evidence_id: str
    evidence_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "evidence_id")
        _require_token(self.evidence_version, "evidence_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentCommand:
    """Full semantic selector for one exact inactive logical head."""

    evidence: AccountOwnerAssignmentEvidence
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.evidence) is not AccountOwnerAssignmentEvidence:
            raise TypeError("evidence must be exact AccountOwnerAssignmentEvidence")
        AccountOwnerAssignmentEvidence.__post_init__(self.evidence)
        _require_aware(self.as_of, "as_of")


class ExactAccountRowObservationProvider(Protocol):
    """Load one exact-current Account row observation."""

    def get_exact_current(
        self, *, observation_id: str, observation_version: str, as_of: datetime
    ) -> ExactAccountRowObservation | None:
        """Return one exact-current observation at the server cutoff."""


class ExactAccountAssignmentProvenanceReceiptProvider(Protocol):
    """Load one exact-current Account-owned provenance receipt."""

    def get_exact_current(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> ExactAccountAssignmentProvenanceReceipt | None:
        """Return one exact-current receipt at the server cutoff."""


class AccountOwnerAssignmentRepository(Protocol):
    """First-winner subject/evidence store with logical-head CAS reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one owner-assignment transaction."""

    def now(self) -> datetime:
        """Return the authoritative Account server clock."""

    def get_subject_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubject | None:
        """Return the immutable registered subject first winner."""

    def append_subject(
        self, subject: AccountOwnerAssignmentSubject, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubject:
        """Append or return a subject identity first winner."""

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return the immutable approved evidence first winner."""

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
        """Return the full logical head without expiry fallback."""

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidence:
        """Append under first-winner and predecessor CAS semantics."""

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return exact identity/hash evidence knowable at one PIT."""


class RegisterAccountOwnerAssignment:
    """Register exact owner definitions with the receipt-sealed claimant."""

    def __init__(
        self,
        *,
        row_provider: ExactAccountRowObservationProvider,
        receipt_provider: ExactAccountAssignmentProvenanceReceiptProvider,
        repository: AccountOwnerAssignmentRepository,
    ) -> None:
        self._row_provider = row_provider
        self._receipt_provider = receipt_provider
        self._repository = repository

    def execute(
        self, command: RegisterAccountOwnerAssignmentCommand
    ) -> AccountOwnerAssignmentSubject:
        """Register or replay one claimant-bound subject first winner."""

        if type(command) is not RegisterAccountOwnerAssignmentCommand:
            raise TypeError("command must be exact RegisterAccountOwnerAssignmentCommand")
        RegisterAccountOwnerAssignmentCommand.__post_init__(command)
        with self._repository.atomic():
            cutoff = self._repository.now()
            _require_aware(cutoff, "repository cutoff")
            first = self._read_definition(command, cutoff)
            winner = self._repository.get_subject_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            final = self._read_definition(command, cutoff)
            if final != first:
                raise AccountOwnerAssignmentConflict(
                    "row observation or provenance receipt changed during registration"
                )
            row, receipt = final
            if winner is not None:
                checked = _require_subject(winner)
                if not checked.is_current_at(cutoff):
                    raise AccountOwnerAssignmentUnavailable(
                        "registered owner-assignment subject is unavailable"
                    )
                stable = AccountOwnerAssignmentSubject(
                    evidence_id=command.evidence_id,
                    evidence_version=command.evidence_version,
                    row=row,
                    receipt=receipt,
                    claimant=receipt.claimant,
                    requested_at=checked.requested_at,
                    valid_until=min(row.valid_until, receipt.valid_until),
                )
                if stable != checked:
                    raise AccountOwnerAssignmentConflict(
                        "owner-assignment subject identity has another first winner"
                    )
                return checked
            subject = AccountOwnerAssignmentSubject(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                row=row,
                receipt=receipt,
                claimant=receipt.claimant,
                requested_at=cutoff,
                valid_until=min(row.valid_until, receipt.valid_until),
            )
            persisted = self._repository.append_subject(subject, recorded_at=cutoff)
            checked = _require_subject(persisted)
            if checked != subject:
                raise AccountOwnerAssignmentConflict(
                    "concurrent owner-assignment subject first winner differs"
                )
            return checked

    def _read_definition(
        self, command: RegisterAccountOwnerAssignmentCommand, cutoff: datetime
    ) -> tuple[ExactAccountRowObservation, ExactAccountAssignmentProvenanceReceipt]:
        row = _require_row(
            self._row_provider.get_exact_current(
                observation_id=command.row_observation_id,
                observation_version=command.row_observation_version,
                as_of=cutoff,
            ),
            observation_id=command.row_observation_id,
            observation_version=command.row_observation_version,
            cutoff=cutoff,
        )
        receipt = _require_receipt(
            self._receipt_provider.get_exact_current(
                receipt_id=command.provenance_receipt_id,
                receipt_version=command.provenance_receipt_version,
                as_of=cutoff,
            ),
            receipt_id=command.provenance_receipt_id,
            receipt_version=command.provenance_receipt_version,
            cutoff=cutoff,
        )
        _validate_receipt_row(receipt, row)
        return row, receipt


class ApproveAccountOwnerAssignment:
    """Approve one persisted subject after exact subject/definition double reads."""

    def __init__(
        self,
        *,
        row_provider: ExactAccountRowObservationProvider,
        receipt_provider: ExactAccountAssignmentProvenanceReceiptProvider,
        repository: AccountOwnerAssignmentRepository,
        actor: AccountOwnerAssignmentServerActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not AccountOwnerAssignmentServerActor:
            raise TypeError("actor must be an exact server actor")
        AccountOwnerAssignmentServerActor.__post_init__(actor)
        if actor.is_staff is not True:
            raise AccountOwnerAssignmentUnavailable("approval requires human staff")
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._row_provider = row_provider
        self._receipt_provider = receipt_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self, command: ApproveAccountOwnerAssignmentCommand
    ) -> AccountOwnerAssignmentEvidence:
        """Approve or replay one approver-bound inactive evidence first winner."""

        if type(command) is not ApproveAccountOwnerAssignmentCommand:
            raise TypeError("command must be exact ApproveAccountOwnerAssignmentCommand")
        ApproveAccountOwnerAssignmentCommand.__post_init__(command)
        with self._repository.atomic():
            cutoff = self._repository.now()
            _require_aware(cutoff, "repository cutoff")
            first_subject = self._read_subject(command, cutoff)
            first_definition = self._read_subject_definition(first_subject, cutoff)
            self._validate_approver(first_subject)
            winner = self._repository.get_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                account_namespace=first_subject.row.account_namespace,
                account_id=first_subject.row.account_id,
                underlying_unified_account_namespace=(
                    first_subject.row.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=(first_subject.row.underlying_unified_account_id),
                row_observation_id=first_subject.row.observation_id,
                as_of=cutoff,
            )
            final_subject = self._read_subject(command, cutoff)
            final_definition = self._read_subject_definition(final_subject, cutoff)
            if final_subject != first_subject or final_definition != first_definition:
                raise AccountOwnerAssignmentConflict(
                    "owner-assignment subject or definition changed during approval"
                )
            row, receipt = final_definition
            if winner is not None:
                checked = _require_evidence(winner)
                self._validate_winner(checked, final_subject, row, receipt, head, cutoff)
                return checked
            valid_until = min(
                row.valid_until,
                receipt.valid_until,
                cutoff + self._validity_period,
            )
            if cutoff >= valid_until:
                raise AccountOwnerAssignmentUnavailable(
                    "owner-assignment definition expired before approval was recorded"
                )
            predecessor = _require_evidence(head) if head is not None else None
            evidence = self._build_evidence(
                final_subject,
                row,
                receipt,
                approved_at=cutoff,
                recorded_at=cutoff,
                valid_until=valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            if predecessor is not None:
                validate_account_owner_assignment_successor(predecessor, evidence)
            persisted = self._repository.append(
                evidence,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=cutoff,
            )
            checked = _require_evidence(persisted)
            if checked != evidence:
                raise AccountOwnerAssignmentConflict(
                    "concurrent owner-assignment evidence first winner differs"
                )
            return checked

    def _read_subject(
        self, command: ApproveAccountOwnerAssignmentCommand, cutoff: datetime
    ) -> AccountOwnerAssignmentSubject:
        value = self._repository.get_subject_winner(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            as_of=cutoff,
        )
        if value is None:
            raise AccountOwnerAssignmentUnavailable(
                "persisted owner-assignment subject is unavailable"
            )
        subject = _require_subject(value)
        if (
            subject.evidence_id != command.evidence_id
            or subject.evidence_version != command.evidence_version
        ):
            raise AccountOwnerAssignmentCorruption("subject identity substitution")
        if not subject.is_current_at(cutoff):
            raise AccountOwnerAssignmentUnavailable(
                "persisted owner-assignment subject is unavailable"
            )
        return subject

    def _read_subject_definition(
        self, subject: AccountOwnerAssignmentSubject, cutoff: datetime
    ) -> tuple[ExactAccountRowObservation, ExactAccountAssignmentProvenanceReceipt]:
        row = _require_row(
            self._row_provider.get_exact_current(
                observation_id=subject.row.observation_id,
                observation_version=subject.row.observation_version,
                as_of=cutoff,
            ),
            observation_id=subject.row.observation_id,
            observation_version=subject.row.observation_version,
            cutoff=cutoff,
        )
        receipt = _require_receipt(
            self._receipt_provider.get_exact_current(
                receipt_id=subject.receipt.receipt_id,
                receipt_version=subject.receipt.receipt_version,
                as_of=cutoff,
            ),
            receipt_id=subject.receipt.receipt_id,
            receipt_version=subject.receipt.receipt_version,
            cutoff=cutoff,
        )
        _validate_receipt_row(receipt, row)
        if row != subject.row or receipt != subject.receipt:
            raise AccountOwnerAssignmentCorruption(
                "current owner-assignment definition no longer matches the subject"
            )
        return row, receipt

    def _validate_approver(self, subject: AccountOwnerAssignmentSubject) -> None:
        if (
            self._actor.actor_id == subject.claimant.actor_id
            or self._actor.user_id == subject.claimant.user_id
        ):
            raise AccountOwnerAssignmentUnavailable(
                "claimant and staff approver must be independent"
            )

    def _build_evidence(
        self,
        subject: AccountOwnerAssignmentSubject,
        row: ExactAccountRowObservation,
        receipt: ExactAccountAssignmentProvenanceReceipt,
        *,
        approved_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountOwnerAssignmentEvidence:
        return AccountOwnerAssignmentEvidence(
            evidence_id=subject.evidence_id,
            evidence_version=subject.evidence_version,
            account_namespace=row.account_namespace,
            account_id=row.account_id,
            underlying_unified_account_namespace=(row.underlying_unified_account_namespace),
            underlying_unified_account_id=row.underlying_unified_account_id,
            assignment_state=receipt.assignment_state,
            assigned_owner_user_id=receipt.assigned_owner_user_id,
            row_observation_owner=row.owner,
            row_observation_artifact_type=row.artifact_type,
            row_observation_id=row.observation_id,
            row_observation_version=row.observation_version,
            row_observation_content_hash=row.content_hash,
            provenance_kind=receipt.provenance_kind,
            provenance_ref_owner=receipt.owner,
            provenance_ref_artifact_type=receipt.artifact_type,
            provenance_ref_id=receipt.receipt_id,
            provenance_ref_version=receipt.receipt_version,
            provenance_ref_content_hash=receipt.content_hash,
            subject_content_hash=subject.content_hash,
            claimant=subject.claimant.to_domain(),
            approved_by=self._actor.to_domain(),
            issued_at=subject.requested_at,
            approved_at=approved_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        subject: AccountOwnerAssignmentSubject,
        row: ExactAccountRowObservation,
        receipt: ExactAccountAssignmentProvenanceReceipt,
        head: AccountOwnerAssignmentEvidence | None,
        cutoff: datetime,
    ) -> None:
        if not evidence.is_knowable_at(cutoff):
            raise AccountOwnerAssignmentUnavailable(
                "persisted owner-assignment evidence is unavailable"
            )
        if evidence.approved_by != self._actor.to_domain():
            raise AccountOwnerAssignmentConflict(
                "owner-assignment evidence belongs to another approver"
            )
        stable = self._build_evidence(
            subject,
            row,
            receipt,
            approved_at=evidence.approved_at,
            recorded_at=evidence.recorded_at,
            valid_until=evidence.valid_until,
            supersedes_content_hash=evidence.supersedes_content_hash,
        )
        if stable != evidence:
            raise AccountOwnerAssignmentConflict(
                "owner-assignment evidence identity has another first winner"
            )
        if head is None or _require_evidence(head) != evidence:
            raise AccountOwnerAssignmentConflict(
                "owner-assignment evidence is no longer the logical current head"
            )


class GetExactAccountOwnerAssignment:
    """Read exact inactive evidence by identity, content hash, and PIT."""

    def __init__(self, repository: AccountOwnerAssignmentRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentCommand
    ) -> AccountOwnerAssignmentEvidence | None:
        """Return only the exact knowable inactive evidence."""

        if type(command) is not GetExactAccountOwnerAssignmentCommand:
            raise TypeError("command must be exact GetExactAccountOwnerAssignmentCommand")
        GetExactAccountOwnerAssignmentCommand.__post_init__(command)

        value = self._repository.get_exact_by_hash(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        evidence = _require_evidence(value)
        if (
            evidence.evidence_id != command.evidence_id
            or evidence.evidence_version != command.evidence_version
            or evidence.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentCorruption("exact evidence identity substitution")
        if not evidence.is_knowable_at(command.as_of):
            return None
        if evidence.activation_available or not evidence.must_not_execute:
            raise AccountOwnerAssignmentCorruption("evidence execution state substitution")
        return evidence


class GetCurrentAccountOwnerAssignment:
    """Read one exact full-selector inactive logical head."""

    def __init__(self, repository: AccountOwnerAssignmentRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentCommand
    ) -> AccountOwnerAssignmentEvidence | None:
        """Reject superseded heads and every semantic selector substitution."""

        if type(command) is not GetCurrentAccountOwnerAssignmentCommand:
            raise TypeError("command must be exact GetCurrentAccountOwnerAssignmentCommand")
        GetCurrentAccountOwnerAssignmentCommand.__post_init__(command)

        expected = command.evidence
        value = GetExactAccountOwnerAssignment(self._repository).execute(
            GetExactAccountOwnerAssignmentCommand(
                evidence_id=expected.evidence_id,
                evidence_version=expected.evidence_version,
                expected_content_hash=expected.content_hash,
                as_of=command.as_of,
            )
        )
        if value is None or value != expected:
            return None
        head = self._repository.get_current_head(
            account_namespace=expected.account_namespace,
            account_id=expected.account_id,
            underlying_unified_account_namespace=(expected.underlying_unified_account_namespace),
            underlying_unified_account_id=expected.underlying_unified_account_id,
            row_observation_id=expected.row_observation_id,
            as_of=command.as_of,
        )
        if head is None or _require_evidence(head) != expected:
            return None
        return value


def _require_row(
    value: ExactAccountRowObservation | None,
    *,
    observation_id: str,
    observation_version: str,
    cutoff: datetime,
) -> ExactAccountRowObservation:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact row observation is unavailable")
    if type(value) is not ExactAccountRowObservation:
        raise AccountOwnerAssignmentCorruption("row observation type substitution")
    ExactAccountRowObservation.__post_init__(value)
    if value.observation_id != observation_id or value.observation_version != observation_version:
        raise AccountOwnerAssignmentCorruption("row observation identity substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("exact row observation is unavailable")
    return value


def _require_receipt(
    value: ExactAccountAssignmentProvenanceReceipt | None,
    *,
    receipt_id: str,
    receipt_version: str,
    cutoff: datetime,
) -> ExactAccountAssignmentProvenanceReceipt:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact provenance receipt is unavailable")
    if type(value) is not ExactAccountAssignmentProvenanceReceipt:
        raise AccountOwnerAssignmentCorruption("provenance receipt type substitution")
    ExactAccountAssignmentProvenanceReceipt.__post_init__(value)
    if value.receipt_id != receipt_id or value.receipt_version != receipt_version:
        raise AccountOwnerAssignmentCorruption("provenance receipt identity substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("exact provenance receipt is unavailable")
    return value


def _validate_receipt_row(
    receipt: ExactAccountAssignmentProvenanceReceipt,
    row: ExactAccountRowObservation,
) -> None:
    if not (
        receipt.account_namespace == row.account_namespace
        and receipt.account_id == row.account_id
        and receipt.underlying_unified_account_namespace == row.underlying_unified_account_namespace
        and receipt.underlying_unified_account_id == row.underlying_unified_account_id
        and receipt.row_observation_id == row.observation_id
        and receipt.row_observation_version == row.observation_version
        and receipt.row_observation_content_hash == row.content_hash
    ):
        raise AccountOwnerAssignmentCorruption(
            "provenance receipt does not bind the exact row observation"
        )


def _require_subject(value: object) -> AccountOwnerAssignmentSubject:
    if type(value) is not AccountOwnerAssignmentSubject:
        raise AccountOwnerAssignmentCorruption("subject type substitution")
    AccountOwnerAssignmentSubject.__post_init__(value)
    return value


def _require_evidence(value: object) -> AccountOwnerAssignmentEvidence:
    if type(value) is not AccountOwnerAssignmentEvidence:
        raise AccountOwnerAssignmentCorruption("evidence type substitution")
    AccountOwnerAssignmentEvidence.__post_init__(value)
    return value


__all__ = [
    "AccountOwnerAssignmentConflict",
    "AccountOwnerAssignmentCorruption",
    "AccountOwnerAssignmentRepository",
    "AccountOwnerAssignmentServerActor",
    "AccountOwnerAssignmentSubject",
    "AccountOwnerAssignmentUnavailable",
    "ApproveAccountOwnerAssignment",
    "ApproveAccountOwnerAssignmentCommand",
    "ExactAccountAssignmentProvenanceReceipt",
    "ExactAccountAssignmentProvenanceReceiptProvider",
    "ExactAccountRowObservation",
    "ExactAccountRowObservationProvider",
    "GetCurrentAccountOwnerAssignment",
    "GetCurrentAccountOwnerAssignmentCommand",
    "GetExactAccountOwnerAssignment",
    "GetExactAccountOwnerAssignmentCommand",
    "RegisterAccountOwnerAssignment",
    "RegisterAccountOwnerAssignmentCommand",
]
