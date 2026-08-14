"""Two-stage issuance of inactive authoritative account-mapping evidence v2."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
    validate_account_owner_assignment_evidence_v2_successor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
    validate_account_owner_assignment_provenance_receipt_v2_row,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)


class AccountOwnerAssignmentEvidenceV2Unavailable(RuntimeError):
    """Required current owner evidence is unavailable."""


class AccountOwnerAssignmentEvidenceV2Conflict(RuntimeError):
    """A first winner or logical head conflicts with the request."""


class AccountOwnerAssignmentEvidenceV2Corruption(RuntimeError):
    """A trusted provider or repository returned corrupt evidence."""


def _token(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or value.strip() != value or len(value) > 192 or any(c.isspace() for c in value):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _hash(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class RegisterAccountOwnerAssignmentSubjectV2Command:
    """ID/hash-only selector for one pending two-person approval subject."""

    evidence_id: str
    evidence_version: str
    physical_observation_id: str
    physical_observation_version: str
    expected_physical_content_hash: str
    receipt_id: str
    receipt_version: str
    expected_receipt_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "evidence_version",
            "physical_observation_id",
            "physical_observation_version",
            "receipt_id",
            "receipt_version",
        ):
            _token(getattr(self, name), name)
        _hash(self.expected_physical_content_hash, "expected_physical_content_hash")
        _hash(self.expected_receipt_content_hash, "expected_receipt_content_hash")


@dataclass(frozen=True, slots=True)
class ApproveAccountOwnerAssignmentEvidenceV2Command:
    """ID/hash-only selector; the authenticated approver is constructor-owned."""

    evidence_id: str
    evidence_version: str
    expected_subject_content_hash: str

    def __post_init__(self) -> None:
        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        _hash(self.expected_subject_content_hash, "expected_subject_content_hash")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentEvidenceV2Command:
    """Historical exact identity/hash/PIT selector."""

    evidence_id: str
    evidence_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        _hash(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentEvidenceV2Command:
    """Closed semantic selector for an exact current dual-mapping head."""

    expected_evidence: AccountOwnerAssignmentEvidenceV2
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_evidence) is not AccountOwnerAssignmentEvidenceV2:
            raise TypeError("expected_evidence must be exact AccountOwnerAssignmentEvidenceV2")
        AccountOwnerAssignmentEvidenceV2.__post_init__(self.expected_evidence)
        _aware(self.as_of, "as_of")


class ExactCurrentPhysicalAccountRowObservationV2Provider(Protocol):
    """Load one exact live physical-row v2 head."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None: ...


class ExactCurrentAccountOwnerAssignmentProvenanceReceiptV2Provider(Protocol):
    """Load one exact current claimant receipt v2 head."""

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV2 | None: ...


class AccountOwnerAssignmentEvidenceV2Repository(Protocol):
    """Append-only subject/evidence store with dual logical-head CAS."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_subject_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV2 | None: ...

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV2, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV2: ...

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidenceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2: ...

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...


def _physical(
    value: object,
    *,
    observation_id: str,
    observation_version: str,
    content_hash: str,
    cutoff: datetime,
) -> PhysicalAccountRowObservationV2:
    if value is None:
        raise AccountOwnerAssignmentEvidenceV2Unavailable("physical v2 head is unavailable")
    if type(value) is not PhysicalAccountRowObservationV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("physical v2 type substitution")
    try:
        PhysicalAccountRowObservationV2.__post_init__(value)
    except (TypeError, ValueError) as exc:
        raise AccountOwnerAssignmentEvidenceV2Corruption("physical v2 is corrupt") from exc
    if (
        value.observation_id != observation_id
        or value.observation_version != observation_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentEvidenceV2Corruption("physical v2 selector substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentEvidenceV2Unavailable("physical v2 head is not live")
    return value


def _receipt(
    value: object,
    *,
    receipt_id: str,
    receipt_version: str,
    content_hash: str,
    cutoff: datetime,
) -> AccountOwnerAssignmentProvenanceReceiptV2:
    if value is None:
        raise AccountOwnerAssignmentEvidenceV2Unavailable("claimant receipt v2 is unavailable")
    if type(value) is not AccountOwnerAssignmentProvenanceReceiptV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("claimant receipt v2 type substitution")
    try:
        AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(value)
    except (TypeError, ValueError) as exc:
        raise AccountOwnerAssignmentEvidenceV2Corruption("claimant receipt v2 is corrupt") from exc
    if (
        value.receipt_id != receipt_id
        or value.receipt_version != receipt_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentEvidenceV2Corruption("claimant receipt selector substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentEvidenceV2Unavailable("claimant receipt is not current")
    return value


def _subject(value: object) -> AccountOwnerAssignmentSubjectV2:
    if type(value) is not AccountOwnerAssignmentSubjectV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("subject type substitution")
    try:
        AccountOwnerAssignmentSubjectV2.__post_init__(value)
    except (TypeError, ValueError) as exc:
        raise AccountOwnerAssignmentEvidenceV2Corruption("subject is corrupt") from exc
    return value


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV2:
    if type(value) is not AccountOwnerAssignmentEvidenceV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("evidence type substitution")
    try:
        AccountOwnerAssignmentEvidenceV2.__post_init__(value)
    except (TypeError, ValueError) as exc:
        raise AccountOwnerAssignmentEvidenceV2Corruption("evidence is corrupt") from exc
    return value


class RegisterAccountOwnerAssignmentSubjectV2:
    """Register a claimant-bound subject after same-cutoff double reads."""

    def __init__(
        self,
        *,
        physical_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV2Provider,
        repository: AccountOwnerAssignmentEvidenceV2Repository,
    ) -> None:
        self._physical_provider = physical_provider
        self._receipt_provider = receipt_provider
        self._repository = repository

    def execute(
        self, command: RegisterAccountOwnerAssignmentSubjectV2Command
    ) -> AccountOwnerAssignmentSubjectV2:
        """Register or replay one exact subject first winner."""
        if type(command) is not RegisterAccountOwnerAssignmentSubjectV2Command:
            raise TypeError("command must be exact RegisterAccountOwnerAssignmentSubjectV2Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _aware(self._repository.now(), "repository cutoff")
            first = self._read(command, cutoff)
            winner = self._repository.get_subject_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            final = self._read(command, cutoff)
            if first != final:
                raise AccountOwnerAssignmentEvidenceV2Conflict(
                    "upstream changed during registration"
                )
            physical, receipt = final
            if winner is not None:
                checked = _subject(winner)
                stable = AccountOwnerAssignmentSubjectV2(
                    subject_id=command.evidence_id,
                    subject_version=command.evidence_version,
                    physical=physical,
                    receipt=receipt,
                    requested_at=checked.requested_at,
                    valid_until=min(physical.valid_until, receipt.valid_until),
                )
                if stable != checked or not checked.is_current_at(cutoff):
                    raise AccountOwnerAssignmentEvidenceV2Conflict(
                        "subject identity has another winner"
                    )
                return checked
            candidate = AccountOwnerAssignmentSubjectV2(
                subject_id=command.evidence_id,
                subject_version=command.evidence_version,
                physical=physical,
                receipt=receipt,
                requested_at=cutoff,
                valid_until=min(physical.valid_until, receipt.valid_until),
            )
            persisted = _subject(self._repository.append_subject(candidate, recorded_at=cutoff))
            if persisted != candidate:
                raise AccountOwnerAssignmentEvidenceV2Conflict("subject first winner differs")
            return persisted

    def _read(
        self, command: RegisterAccountOwnerAssignmentSubjectV2Command, cutoff: datetime
    ) -> tuple[PhysicalAccountRowObservationV2, AccountOwnerAssignmentProvenanceReceiptV2]:
        physical = _physical(
            self._physical_provider.get_exact_current(
                observation_id=command.physical_observation_id,
                observation_version=command.physical_observation_version,
                expected_content_hash=command.expected_physical_content_hash,
                as_of=cutoff,
            ),
            observation_id=command.physical_observation_id,
            observation_version=command.physical_observation_version,
            content_hash=command.expected_physical_content_hash,
            cutoff=cutoff,
        )
        receipt = _receipt(
            self._receipt_provider.get_exact_current(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                expected_content_hash=command.expected_receipt_content_hash,
                as_of=cutoff,
            ),
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            content_hash=command.expected_receipt_content_hash,
            cutoff=cutoff,
        )
        try:
            validate_account_owner_assignment_provenance_receipt_v2_row(receipt, physical)
        except (TypeError, ValueError) as exc:
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                "receipt does not bind physical v2"
            ) from exc
        return physical, receipt


class ApproveAccountOwnerAssignmentEvidenceV2:
    """Issue staff-approved mapping evidence after dual-head and upstream checks."""

    def __init__(
        self,
        *,
        physical_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV2Provider,
        repository: AccountOwnerAssignmentEvidenceV2Repository,
        approver: AccountOwnerAssignmentActor,
        validity_period: timedelta,
    ) -> None:
        if type(approver) is not AccountOwnerAssignmentActor:
            raise TypeError("approver must be exact AccountOwnerAssignmentActor")
        approver.__post_init__()
        if not approver.is_staff or approver.role != "account_owner_assignment_approver":
            raise AccountOwnerAssignmentEvidenceV2Unavailable("approval requires assignment staff")
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be exact positive timedelta")
        self._physical_provider = physical_provider
        self._receipt_provider = receipt_provider
        self._repository = repository
        self._approver = approver
        self._validity_period = validity_period

    def execute(
        self, command: ApproveAccountOwnerAssignmentEvidenceV2Command
    ) -> AccountOwnerAssignmentEvidenceV2:
        """Approve or replay an approver-bound evidence first winner."""
        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV2Command:
            raise TypeError("command must be exact ApproveAccountOwnerAssignmentEvidenceV2Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _aware(self._repository.now(), "repository cutoff")
            first_subject = self._read_subject(command, cutoff)
            first_upstream = self._read_upstream(first_subject, cutoff)
            winner = self._repository.get_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            account_head, underlying_head = self._heads(first_subject.physical, cutoff)
            final_subject = self._read_subject(command, cutoff)
            final_upstream = self._read_upstream(final_subject, cutoff)
            if first_subject != final_subject or first_upstream != final_upstream:
                raise AccountOwnerAssignmentEvidenceV2Conflict("approval inputs changed")
            if (
                final_subject.claimant.actor_id == self._approver.actor_id
                or final_subject.claimant.user_id == self._approver.user_id
            ):
                raise AccountOwnerAssignmentEvidenceV2Unavailable(
                    "claimant and staff approver must be independent"
                )
            if winner is not None:
                checked = _evidence(winner)
                if checked.approved_by != self._approver:
                    raise AccountOwnerAssignmentEvidenceV2Conflict(
                        "evidence belongs to another approver"
                    )
                if (
                    checked.subject != final_subject
                    or account_head != checked
                    or underlying_head != checked
                ):
                    raise AccountOwnerAssignmentEvidenceV2Conflict(
                        "evidence winner is not the dual head"
                    )
                if not checked.is_current_at(cutoff):
                    raise AccountOwnerAssignmentEvidenceV2Unavailable(
                        "evidence winner is unavailable"
                    )
                return checked
            predecessor = account_head
            approval_valid_until = cutoff + self._validity_period
            candidate = AccountOwnerAssignmentEvidenceV2(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                subject=final_subject,
                assignment_state=(
                    "authoritative"
                    if final_subject.receipt.assignment_state == "claimed_owner"
                    else "legacy_default"
                ),
                assigned_owner_user_id=(
                    final_subject.claimant.user_id
                    if final_subject.receipt.assignment_state == "claimed_owner"
                    else None
                ),
                approved_by=self._approver,
                approved_at=cutoff,
                recorded_at=cutoff,
                approval_valid_until=approval_valid_until,
                valid_until=min(final_subject.valid_until, approval_valid_until),
                supersedes_content_hash=(predecessor.content_hash if predecessor else None),
            )
            if predecessor is not None:
                try:
                    validate_account_owner_assignment_evidence_v2_successor(predecessor, candidate)
                except (TypeError, ValueError) as exc:
                    raise AccountOwnerAssignmentEvidenceV2Conflict(
                        "evidence successor is invalid"
                    ) from exc
            persisted = _evidence(
                self._repository.append(
                    candidate,
                    expected_predecessor_hash=(predecessor.content_hash if predecessor else None),
                    recorded_at=cutoff,
                )
            )
            if persisted != candidate:
                raise AccountOwnerAssignmentEvidenceV2Conflict("evidence first winner differs")
            return persisted

    def _read_subject(
        self, command: ApproveAccountOwnerAssignmentEvidenceV2Command, cutoff: datetime
    ) -> AccountOwnerAssignmentSubjectV2:
        value = self._repository.get_subject_winner(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            as_of=cutoff,
        )
        if value is None:
            raise AccountOwnerAssignmentEvidenceV2Unavailable("subject is unavailable")
        subject = _subject(value)
        if (
            subject.subject_id != command.evidence_id
            or subject.subject_version != command.evidence_version
            or subject.content_hash != command.expected_subject_content_hash
        ):
            raise AccountOwnerAssignmentEvidenceV2Corruption("subject selector substitution")
        if not subject.is_current_at(cutoff):
            raise AccountOwnerAssignmentEvidenceV2Unavailable("subject is not current")
        return subject

    def _read_upstream(
        self, subject: AccountOwnerAssignmentSubjectV2, cutoff: datetime
    ) -> tuple[PhysicalAccountRowObservationV2, AccountOwnerAssignmentProvenanceReceiptV2]:
        physical = _physical(
            self._physical_provider.get_exact_current(
                observation_id=subject.physical.observation_id,
                observation_version=subject.physical.observation_version,
                expected_content_hash=subject.physical.content_hash,
                as_of=cutoff,
            ),
            observation_id=subject.physical.observation_id,
            observation_version=subject.physical.observation_version,
            content_hash=subject.physical.content_hash,
            cutoff=cutoff,
        )
        receipt = _receipt(
            self._receipt_provider.get_exact_current(
                receipt_id=subject.receipt.receipt_id,
                receipt_version=subject.receipt.receipt_version,
                expected_content_hash=subject.receipt.content_hash,
                as_of=cutoff,
            ),
            receipt_id=subject.receipt.receipt_id,
            receipt_version=subject.receipt.receipt_version,
            content_hash=subject.receipt.content_hash,
            cutoff=cutoff,
        )
        if physical != subject.physical or receipt != subject.receipt:
            raise AccountOwnerAssignmentEvidenceV2Corruption("subject upstream substitution")
        return physical, receipt

    def _heads(
        self, physical: PhysicalAccountRowObservationV2, cutoff: datetime
    ) -> tuple[AccountOwnerAssignmentEvidenceV2 | None, AccountOwnerAssignmentEvidenceV2 | None]:
        account = self._repository.get_account_head(
            account_namespace=physical.account_namespace,
            account_id=physical.account_id,
            as_of=cutoff,
        )
        underlying = self._repository.get_underlying_head(
            underlying_unified_account_namespace=physical.underlying_unified_account_namespace,
            underlying_unified_account_id=physical.underlying_unified_account_id,
            as_of=cutoff,
        )
        checked_account = _evidence(account) if account is not None else None
        checked_underlying = _evidence(underlying) if underlying is not None else None
        if checked_account != checked_underlying:
            raise AccountOwnerAssignmentEvidenceV2Corruption("mapping heads disagree")
        return checked_account, checked_underlying


class GetExactAccountOwnerAssignmentEvidenceV2:
    """Read immutable evidence historically without granting current authority."""

    def __init__(self, repository: AccountOwnerAssignmentEvidenceV2Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentEvidenceV2Command
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return an exact evidence value knowable at the PIT cutoff."""
        if type(command) is not GetExactAccountOwnerAssignmentEvidenceV2Command:
            raise TypeError("command must be exact GetExactAccountOwnerAssignmentEvidenceV2Command")
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = _evidence(value)
        if (
            checked.evidence_id != command.evidence_id
            or checked.evidence_version != command.evidence_version
            or checked.content_hash != command.expected_content_hash
            or checked.recorded_at > command.as_of
        ):
            raise AccountOwnerAssignmentEvidenceV2Corruption("exact evidence substitution")
        return checked


class GetCurrentAccountOwnerAssignmentEvidenceV2:
    """Return current evidence only after both upstream and mapping heads revalidate."""

    def __init__(
        self,
        *,
        physical_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV2Provider,
        repository: AccountOwnerAssignmentEvidenceV2Repository,
    ) -> None:
        self._physical_provider = physical_provider
        self._receipt_provider = receipt_provider
        self._repository = repository

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV2Command
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        """Return no value for superseded, terminal, expired, or split-head mappings."""
        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV2Command:
            raise TypeError(
                "command must be exact GetCurrentAccountOwnerAssignmentEvidenceV2Command"
            )
        command.__post_init__()
        expected = command.expected_evidence
        exact = self._repository.get_exact_by_hash(
            evidence_id=expected.evidence_id,
            evidence_version=expected.evidence_version,
            expected_content_hash=expected.content_hash,
            as_of=command.as_of,
        )
        if exact is None:
            return None
        checked = _evidence(exact)
        account = self._repository.get_account_head(
            account_namespace=expected.subject.physical.account_namespace,
            account_id=expected.subject.physical.account_id,
            as_of=command.as_of,
        )
        underlying = self._repository.get_underlying_head(
            underlying_unified_account_namespace=(
                expected.subject.physical.underlying_unified_account_namespace
            ),
            underlying_unified_account_id=(expected.subject.physical.underlying_unified_account_id),
            as_of=command.as_of,
        )
        checked_account = _evidence(account) if account is not None else None
        checked_underlying = _evidence(underlying) if underlying is not None else None
        if checked != expected or checked_account != expected or checked_underlying != expected:
            return None
        raw_physical = self._physical_provider.get_exact_current(
            observation_id=expected.subject.physical.observation_id,
            observation_version=expected.subject.physical.observation_version,
            expected_content_hash=expected.subject.physical.content_hash,
            as_of=command.as_of,
        )
        if raw_physical is None:
            return None
        physical = _physical(
            raw_physical,
            observation_id=expected.subject.physical.observation_id,
            observation_version=expected.subject.physical.observation_version,
            content_hash=expected.subject.physical.content_hash,
            cutoff=command.as_of,
        )
        raw_receipt = self._receipt_provider.get_exact_current(
            receipt_id=expected.subject.receipt.receipt_id,
            receipt_version=expected.subject.receipt.receipt_version,
            expected_content_hash=expected.subject.receipt.content_hash,
            as_of=command.as_of,
        )
        if raw_receipt is None:
            return None
        receipt = _receipt(
            raw_receipt,
            receipt_id=expected.subject.receipt.receipt_id,
            receipt_version=expected.subject.receipt.receipt_version,
            content_hash=expected.subject.receipt.content_hash,
            cutoff=command.as_of,
        )
        if physical != expected.subject.physical or receipt != expected.subject.receipt:
            return None
        return expected if expected.is_current_at(command.as_of) else None


__all__ = [
    "AccountOwnerAssignmentEvidenceV2Conflict",
    "AccountOwnerAssignmentEvidenceV2Corruption",
    "AccountOwnerAssignmentEvidenceV2Repository",
    "AccountOwnerAssignmentEvidenceV2Unavailable",
    "ApproveAccountOwnerAssignmentEvidenceV2",
    "ApproveAccountOwnerAssignmentEvidenceV2Command",
    "ExactCurrentAccountOwnerAssignmentProvenanceReceiptV2Provider",
    "ExactCurrentPhysicalAccountRowObservationV2Provider",
    "GetCurrentAccountOwnerAssignmentEvidenceV2",
    "GetCurrentAccountOwnerAssignmentEvidenceV2Command",
    "GetExactAccountOwnerAssignmentEvidenceV2",
    "GetExactAccountOwnerAssignmentEvidenceV2Command",
    "RegisterAccountOwnerAssignmentSubjectV2",
    "RegisterAccountOwnerAssignmentSubjectV2Command",
]
