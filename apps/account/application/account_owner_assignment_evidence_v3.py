"""ID/hash-only registration and staff approval for Account evidence v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
    AccountOwnerAssignmentSubjectV3,
    validate_account_owner_assignment_evidence_v3_root,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class RegisterAccountOwnerAssignmentSubjectV3Command:
    """Select one subject and exact Receipt-v3/Binding-v2/Physical-v3 seals."""

    subject_id: str
    subject_version: str
    receipt_id: str
    receipt_version: str
    expected_receipt_content_hash: str
    binding_id: str
    binding_version: str
    expected_binding_content_hash: str
    physical_root_id: str
    physical_root_version: str
    expected_physical_root_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "subject_id",
            "subject_version",
            "receipt_id",
            "receipt_version",
            "binding_id",
            "binding_version",
            "physical_root_id",
            "physical_root_version",
        ):
            _token(getattr(self, name), name)
        for name in (
            "expected_receipt_content_hash",
            "expected_binding_content_hash",
            "expected_physical_root_content_hash",
        ):
            _digest(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ApproveAccountOwnerAssignmentEvidenceV3Command:
    """Select one evidence root and exact registered subject seal."""

    evidence_id: str
    evidence_version: str
    subject_id: str
    subject_version: str
    expected_subject_content_hash: str

    def __post_init__(self) -> None:
        for name in ("evidence_id", "evidence_version", "subject_id", "subject_version"):
            _token(getattr(self, name), name)
        _digest(self.expected_subject_content_hash, "expected_subject_content_hash")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentEvidenceV3Command:
    """Select immutable staff evidence at one historical PIT cutoff."""

    evidence_id: str
    evidence_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentEvidenceV3Command:
    """Carry the complete expected dual-mapping evidence root."""

    expected_evidence: AccountOwnerAssignmentEvidenceV3
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_evidence) is not AccountOwnerAssignmentEvidenceV3:
            raise TypeError("expected_evidence must be exact AccountOwnerAssignmentEvidenceV3")
        self.expected_evidence.__post_init__()
        _aware(self.as_of, "as_of")


class ExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider(Protocol):
    """Read one exact-current creation claimant Receipt-v3 head."""

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV3 | None: ...


class ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(Protocol):
    """Read one exact-current allocated Physical-v3 head."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None: ...


class CurrentAccountOwnerAssignmentApproverProvider(Protocol):
    """Resolve the currently authenticated human staff approver."""

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None: ...


class AccountOwnerAssignmentEvidenceV3Repository(Protocol):
    """Persist subject/evidence first winners and two root mapping CAS anchors."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV3 | None: ...

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV3, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV3: ...

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...

    def append_root(
        self,
        evidence: AccountOwnerAssignmentEvidenceV3,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3: ...

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...


def _receipt(
    value: object,
    *,
    receipt_id: str,
    receipt_version: str,
    content_hash: str,
    cutoff: datetime,
) -> AccountOwnerAssignmentProvenanceReceiptV3:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact-current Receipt-v3 is unavailable")
    if type(value) is not AccountOwnerAssignmentProvenanceReceiptV3:
        raise AccountOwnerAssignmentCorruption("Receipt-v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Receipt-v3 is corrupt") from error
    if (
        value.receipt_id != receipt_id
        or value.receipt_version != receipt_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Receipt-v3 selector substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("Receipt-v3 is not current")
    return value


def _root(
    value: object,
    *,
    observation_id: str,
    observation_version: str,
    content_hash: str,
    cutoff: datetime,
) -> AllocatedPhysicalAccountRowObservationV3:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact-current Physical-v3 is unavailable")
    if type(value) is not AllocatedPhysicalAccountRowObservationV3:
        raise AccountOwnerAssignmentCorruption("Physical-v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Physical-v3 is corrupt") from error
    if (
        value.observation_id != observation_id
        or value.observation_version != observation_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Physical-v3 selector substitution")
    if not value.is_knowable_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("Physical-v3 is not current")
    return value


def _subject(value: object) -> AccountOwnerAssignmentSubjectV3:
    if type(value) is not AccountOwnerAssignmentSubjectV3:
        raise AccountOwnerAssignmentCorruption("subject v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("subject v3 is corrupt") from error
    return value


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV3:
    if type(value) is not AccountOwnerAssignmentEvidenceV3:
        raise AccountOwnerAssignmentCorruption("evidence v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("evidence v3 is corrupt") from error
    return value


def _approver(value: object) -> AccountOwnerAssignmentServerActor:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("current human staff approver is unavailable")
    if type(value) is not AccountOwnerAssignmentServerActor:
        raise AccountOwnerAssignmentCorruption("approver type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("approver is corrupt") from error
    if not value.is_staff or value.role != "account_owner_assignment_approver":
        raise AccountOwnerAssignmentUnavailable("current human staff approver is ineligible")
    return value


class RegisterAccountOwnerAssignmentSubjectV3:
    """Winner-first registration after same-cutoff Receipt-v3/Physical-v3 double reads."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        repository: AccountOwnerAssignmentEvidenceV3Repository,
    ) -> None:
        self._receipts = receipt_provider
        self._roots = root_provider
        self._repository = repository

    def execute(
        self, command: RegisterAccountOwnerAssignmentSubjectV3Command
    ) -> AccountOwnerAssignmentSubjectV3:
        """Register or historically replay one immutable subject first winner."""

        if type(command) is not RegisterAccountOwnerAssignmentSubjectV3Command:
            raise TypeError("command must be exact RegisterAccountOwnerAssignmentSubjectV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=cutoff,
            )
            if winner is not None:
                checked = _subject(winner)
                if checked.requested_at > cutoff or not _subject_matches(checked, command):
                    raise AccountOwnerAssignmentConflict("subject v3 identity has another winner")
                return checked
            first = self._read(command, cutoff)
            try:
                final = self._read(command, cutoff)
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict("subject v3 upstream changed") from error
            if final != first:
                raise AccountOwnerAssignmentConflict("subject v3 upstream changed")
            receipt, root = final
            binding = receipt.binding
            physical = root.physical_observation
            candidate = AccountOwnerAssignmentSubjectV3(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                receipt=receipt,
                binding=binding,
                physical_root=root,
                receipt_identity_hash=receipt.identity_hash,
                receipt_content_hash=receipt.content_hash,
                binding_identity_hash=binding.identity_hash,
                binding_content_hash=binding.content_hash,
                creation_root_identity_hash=root.identity_hash,
                creation_root_content_hash=root.content_hash,
                account_claim_hash=binding.account_claim_hash,
                underlying_claim_hash=binding.underlying_claim_hash,
                physical_observation_content_hash=physical.content_hash,
                physical_source_content_hash=physical.source_content_hash,
                physical_raw_observation_content_hash=physical.raw_observation_content_hash,
                requested_at=cutoff,
                valid_until=min(receipt.valid_until, root.valid_until),
            )
            persisted = _subject(self._repository.append_subject(candidate, recorded_at=cutoff))
            if persisted != candidate:
                raise AccountOwnerAssignmentConflict("subject v3 first winner differs")
            return persisted

    def _read(
        self, command: RegisterAccountOwnerAssignmentSubjectV3Command, cutoff: datetime
    ) -> tuple[
        AccountOwnerAssignmentProvenanceReceiptV3,
        AllocatedPhysicalAccountRowObservationV3,
    ]:
        receipt = _receipt(
            self._receipts.get_exact_current(
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
        binding = receipt.binding
        if (
            binding.binding_id != command.binding_id
            or binding.binding_version != command.binding_version
            or binding.content_hash != command.expected_binding_content_hash
        ):
            raise AccountOwnerAssignmentCorruption("Binding-v2 selector substitution")
        root = _root(
            self._roots.get_exact_current(
                observation_id=command.physical_root_id,
                observation_version=command.physical_root_version,
                expected_content_hash=command.expected_physical_root_content_hash,
                as_of=cutoff,
            ),
            observation_id=command.physical_root_id,
            observation_version=command.physical_root_version,
            content_hash=command.expected_physical_root_content_hash,
            cutoff=cutoff,
        )
        if binding.creation_root != root:
            raise AccountOwnerAssignmentCorruption("Receipt-v3 and Physical-v3 disagree")
        return receipt, root


class ApproveAccountOwnerAssignmentEvidenceV3:
    """Winner-first, two-person staff approval of one root-only mapping."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        approver_provider: CurrentAccountOwnerAssignmentApproverProvider,
        repository: AccountOwnerAssignmentEvidenceV3Repository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._receipts = receipt_provider
        self._roots = root_provider
        self._approvers = approver_provider
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self, command: ApproveAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3:
        """Approve or historically replay one immutable evidence root."""

        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV3Command:
            raise TypeError("command must be exact ApproveAccountOwnerAssignmentEvidenceV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            approver = _approver(self._approvers.get_current(as_of=cutoff))
            winner = self._repository.get_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            if winner is not None:
                checked = _evidence(winner)
                if checked.recorded_at > cutoff:
                    raise AccountOwnerAssignmentCorruption("repository returned future evidence v3")
                if checked.approved_by != approver.to_domain() or not _evidence_matches(
                    checked, command
                ):
                    raise AccountOwnerAssignmentConflict("evidence v3 identity has another winner")
                return checked
            first = self._read(command, cutoff)
            first_approver = approver
            account_head, underlying_head = self._heads(first, cutoff)
            try:
                final = self._read(command, cutoff)
                final_approver = _approver(self._approvers.get_current(as_of=cutoff))
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict(
                    "evidence v3 approval inputs changed"
                ) from error
            if first != final or first_approver != final_approver:
                raise AccountOwnerAssignmentConflict("evidence v3 approval inputs changed")
            if account_head is not None or underlying_head is not None:
                if account_head != underlying_head:
                    raise AccountOwnerAssignmentCorruption("evidence v3 mapping heads disagree")
                raise AccountOwnerAssignmentConflict("evidence v3 mapping already has a root")
            if (
                final.claimant.actor_id == final_approver.actor_id
                or final.claimant.user_id == final_approver.user_id
            ):
                raise AccountOwnerAssignmentUnavailable(
                    "claimant and staff approver must be independent"
                )
            recorded_at = _clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentCorruption("repository clock moved backwards")
            approval_valid_until = recorded_at + self._validity_period
            candidate = AccountOwnerAssignmentEvidenceV3(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                subject=final,
                assigned_owner_user_id=final.claimant.user_id,
                approved_by=final_approver.to_domain(),
                approved_at=cutoff,
                recorded_at=recorded_at,
                approval_valid_until=approval_valid_until,
                valid_until=min(final.valid_until, approval_valid_until),
            )
            try:
                validate_account_owner_assignment_evidence_v3_root(candidate)
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentCorruption("evidence v3 root is invalid") from error
            persisted = _evidence(
                self._repository.append_root(
                    candidate,
                    expected_account_head_hash=None,
                    expected_underlying_head_hash=None,
                    recorded_at=recorded_at,
                )
            )
            if persisted != candidate:
                raise AccountOwnerAssignmentConflict("evidence v3 first winner differs")
            return persisted

    def _read(
        self, command: ApproveAccountOwnerAssignmentEvidenceV3Command, cutoff: datetime
    ) -> AccountOwnerAssignmentSubjectV3:
        value = self._repository.get_subject_winner(
            subject_id=command.subject_id,
            subject_version=command.subject_version,
            as_of=cutoff,
        )
        if value is None:
            raise AccountOwnerAssignmentUnavailable("subject v3 is unavailable")
        subject = _subject(value)
        if not _approve_subject_matches(subject, command):
            raise AccountOwnerAssignmentCorruption("subject v3 selector substitution")
        if not subject.is_current_at(cutoff):
            raise AccountOwnerAssignmentUnavailable("subject v3 is not current")
        receipt = subject.receipt
        current_receipt = _receipt(
            self._receipts.get_exact_current(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                expected_content_hash=receipt.content_hash,
                as_of=cutoff,
            ),
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            content_hash=receipt.content_hash,
            cutoff=cutoff,
        )
        root = subject.physical_root
        current_root = _root(
            self._roots.get_exact_current(
                observation_id=root.observation_id,
                observation_version=root.observation_version,
                expected_content_hash=root.content_hash,
                as_of=cutoff,
            ),
            observation_id=root.observation_id,
            observation_version=root.observation_version,
            content_hash=root.content_hash,
            cutoff=cutoff,
        )
        if current_receipt != receipt or current_root != root:
            raise AccountOwnerAssignmentCorruption("subject v3 upstream substitution")
        return subject

    def _heads(
        self, subject: AccountOwnerAssignmentSubjectV3, cutoff: datetime
    ) -> tuple[AccountOwnerAssignmentEvidenceV3 | None, AccountOwnerAssignmentEvidenceV3 | None]:
        binding = subject.binding
        account = self._repository.get_account_head(
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            as_of=cutoff,
        )
        underlying = self._repository.get_underlying_head(
            underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            as_of=cutoff,
        )
        return (
            _evidence(account) if account is not None else None,
            _evidence(underlying) if underlying is not None else None,
        )


class GetExactAccountOwnerAssignmentEvidenceV3:
    """Read immutable evidence historically without current-upstream requirements."""

    def __init__(self, repository: AccountOwnerAssignmentEvidenceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        """Return exact evidence permanently once its record is knowable."""

        if type(command) is not GetExactAccountOwnerAssignmentEvidenceV3Command:
            raise TypeError("command must be exact GetExactAccountOwnerAssignmentEvidenceV3Command")
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
        ):
            raise AccountOwnerAssignmentCorruption("exact evidence v3 selector substitution")
        return checked if checked.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentEvidenceV3:
    """Return only the exact dual-head evidence with current Receipt-v3/Physical-v3."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        repository: AccountOwnerAssignmentEvidenceV3Repository,
    ) -> None:
        self._receipts = receipt_provider
        self._roots = root_provider
        self._repository = repository

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        """Return none for stale, split-head, substituted, or unavailable upstream state."""

        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV3Command:
            raise TypeError(
                "command must be exact GetCurrentAccountOwnerAssignmentEvidenceV3Command"
            )
        command.__post_init__()
        expected = command.expected_evidence
        exact = GetExactAccountOwnerAssignmentEvidenceV3(self._repository).execute(
            GetExactAccountOwnerAssignmentEvidenceV3Command(
                expected.evidence_id,
                expected.evidence_version,
                expected.content_hash,
                command.as_of,
            )
        )
        if exact != expected or not expected.is_current_at(command.as_of):
            return None
        binding = expected.subject.binding
        account = self._repository.get_account_head(
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            as_of=command.as_of,
        )
        underlying = self._repository.get_underlying_head(
            underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            as_of=command.as_of,
        )
        if (
            account is None
            or underlying is None
            or _evidence(account) != expected
            or _evidence(underlying) != expected
        ):
            return None
        receipt = expected.subject.receipt
        raw_receipt = self._receipts.get_exact_current(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=command.as_of,
        )
        root = expected.subject.physical_root
        raw_root = self._roots.get_exact_current(
            observation_id=root.observation_id,
            observation_version=root.observation_version,
            expected_content_hash=root.content_hash,
            as_of=command.as_of,
        )
        if raw_receipt is None or raw_root is None:
            return None
        return (
            expected
            if (
                _receipt(
                    raw_receipt,
                    receipt_id=receipt.receipt_id,
                    receipt_version=receipt.receipt_version,
                    content_hash=receipt.content_hash,
                    cutoff=command.as_of,
                )
                == receipt
                and _root(
                    raw_root,
                    observation_id=root.observation_id,
                    observation_version=root.observation_version,
                    content_hash=root.content_hash,
                    cutoff=command.as_of,
                )
                == root
            )
            else None
        )


def _clock(value: object) -> datetime:
    try:
        return _aware(value, "repository clock")
    except ValueError as error:
        raise AccountOwnerAssignmentCorruption(str(error)) from error


def _subject_matches(
    subject: AccountOwnerAssignmentSubjectV3,
    command: RegisterAccountOwnerAssignmentSubjectV3Command,
) -> bool:
    return (
        subject.subject_id,
        subject.subject_version,
        subject.receipt.receipt_id,
        subject.receipt.receipt_version,
        subject.receipt.content_hash,
        subject.binding.binding_id,
        subject.binding.binding_version,
        subject.binding.content_hash,
        subject.physical_root.observation_id,
        subject.physical_root.observation_version,
        subject.physical_root.content_hash,
    ) == (
        command.subject_id,
        command.subject_version,
        command.receipt_id,
        command.receipt_version,
        command.expected_receipt_content_hash,
        command.binding_id,
        command.binding_version,
        command.expected_binding_content_hash,
        command.physical_root_id,
        command.physical_root_version,
        command.expected_physical_root_content_hash,
    )


def _approve_subject_matches(
    subject: AccountOwnerAssignmentSubjectV3,
    command: ApproveAccountOwnerAssignmentEvidenceV3Command,
) -> bool:
    return (
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
    ) == (command.subject_id, command.subject_version, command.expected_subject_content_hash)


def _evidence_matches(
    evidence: AccountOwnerAssignmentEvidenceV3,
    command: ApproveAccountOwnerAssignmentEvidenceV3Command,
) -> bool:
    return (
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.subject.subject_id,
        evidence.subject.subject_version,
        evidence.subject.content_hash,
    ) == (
        command.evidence_id,
        command.evidence_version,
        command.subject_id,
        command.subject_version,
        command.expected_subject_content_hash,
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceV3Repository",
    "ApproveAccountOwnerAssignmentEvidenceV3",
    "ApproveAccountOwnerAssignmentEvidenceV3Command",
    "CurrentAccountOwnerAssignmentApproverProvider",
    "ExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider",
    "ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider",
    "GetCurrentAccountOwnerAssignmentEvidenceV3",
    "GetCurrentAccountOwnerAssignmentEvidenceV3Command",
    "GetExactAccountOwnerAssignmentEvidenceV3",
    "GetExactAccountOwnerAssignmentEvidenceV3Command",
    "RegisterAccountOwnerAssignmentSubjectV3",
    "RegisterAccountOwnerAssignmentSubjectV3Command",
]
