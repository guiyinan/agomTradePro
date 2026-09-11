"""Application orchestration for inactive Account owner-assignment evidence v4.

The use cases in this module coordinate versioned Domain values and public
source Protocols.  They do not authenticate a request, create an owner, or
grant execution authority.  In particular, approval only happens when an
authenticated composition explicitly calls :class:`ApproveAccountOwnerAssignmentEvidenceV4`;
the participant projection is evidence about the server-selected owner and is
not itself an approval event.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    CurrentSingleOwnerParticipantsReader,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
    validate_account_owner_assignment_evidence_v4_dual_mapping_root,
    validate_account_owner_assignment_evidence_v4_root,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
)


def _token(value: object, name: str) -> None:
    """Validate one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    """Validate one lowercase SHA-256 selector."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    """Validate one timezone-aware datetime without changing its value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentEvidenceV4:
    """Bind complete Evidence v4 to the authenticated approval source."""

    evidence: AccountOwnerAssignmentEvidenceV4
    authority: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Validate the immutable evidence and every non-secret authority fact."""

        if type(self.evidence) is not AccountOwnerAssignmentEvidenceV4:
            raise TypeError("evidence must be an exact AccountOwnerAssignmentEvidenceV4")
        self.evidence.__post_init__()
        if type(self.authority) is not CurrentAccountActorAuthorityV3:
            raise TypeError("authority must be an exact CurrentAccountActorAuthorityV3")
        self.authority.__post_init__()
        if (
            self.authority.actor_id != self.evidence.approved_by.actor_id
            or self.authority.user_id != self.evidence.approved_by.user_id
            or self.authority.is_staff is not self.evidence.approved_by.is_staff
        ):
            raise ValueError("evidence authority actor seal is invalid")
        if (
            not self.authority.is_authenticated
            or not self.authority.is_active
            or not self.authority.is_staff
            or self.authority.rbac_role != "admin"
        ):
            raise ValueError("evidence authority is not an authenticated current admin")
        if self.authority.recorded_at > self.evidence.approved_at:
            raise ValueError("authority recorded_at must precede evidence approval")
        if self.evidence.approval_valid_until > self.authority.valid_until:
            raise ValueError("approval validity exceeds approval authority validity")
        if self.evidence.valid_until > self.authority.valid_until:
            raise ValueError("evidence validity exceeds approval authority validity")


@dataclass(frozen=True, slots=True)
class RegisterAccountOwnerAssignmentSubjectV4Command:
    """Select one Subject v4 and its exact Receipt/Physical source seals."""

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
        """Validate the server-provided ID/hash-only registration selectors."""

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
class ApproveAccountOwnerAssignmentEvidenceV4Command:
    """Select one evidence first winner and one exact registered Subject hash."""

    evidence_id: str
    evidence_version: str
    subject_id: str
    subject_version: str
    expected_subject_content_hash: str

    def __post_init__(self) -> None:
        """Validate the approval command without accepting identity or role facts."""

        for name in ("evidence_id", "evidence_version", "subject_id", "subject_version"):
            _token(getattr(self, name), name)
        _digest(self.expected_subject_content_hash, "expected_subject_content_hash")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentEvidenceV4Command:
    """Select immutable historical Evidence v4 by exact ID, version, and hash."""

    evidence_id: str
    evidence_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate historical selectors and an aware point-in-time cutoff."""

        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentEvidenceV4Command:
    """Select one exact Evidence v4 that still has both current mapping heads."""

    evidence_id: str
    evidence_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate current selectors and an aware point-in-time cutoff."""

        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


class ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider(Protocol):
    """Read one exact-current Receipt v4 from its public Application boundary."""

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return the selected Receipt v4 only when its current source is valid."""
        ...


class AccountOwnerAssignmentEvidenceV4Repository(Protocol):
    """Persist Subject v4 and root Evidence v4 with first-winner/CAS semantics."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work for one write or replay."""
        ...

    def now(self) -> datetime:
        """Return the timezone-aware repository clock."""
        ...

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV4 | None:
        """Return the immutable Subject first winner knowable at ``as_of``."""
        ...

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV4, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV4:
        """Append or replay one Subject first winner under repository CAS."""
        ...

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the immutable Evidence first winner knowable at ``as_of``."""
        ...

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the account mapping head at ``as_of`` without fallback."""
        ...

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the underlying mapping head at ``as_of`` without fallback."""
        ...

    def append_root(
        self,
        record: PersistedAccountOwnerAssignmentEvidenceV4,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4:
        """Append one root only after both logical heads pass CAS checks."""
        ...

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return only the requested historical Evidence identity and hash."""
        ...


@dataclass(frozen=True, slots=True)
class _SubjectInputs:
    """Validated exact-current upstream values used to register a Subject."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV4
    root: AllocatedPhysicalAccountRowObservationV3


@dataclass(frozen=True, slots=True)
class _ApprovalInputs:
    """Validated Subject, upstream sources, and server-owned participants."""

    subject: AccountOwnerAssignmentSubjectV4
    receipt: AccountOwnerAssignmentProvenanceReceiptV4
    root: AllocatedPhysicalAccountRowObservationV3
    participants: CurrentSingleOwnerParticipants


def _receipt(
    value: object | None,
    *,
    receipt_id: str,
    receipt_version: str,
    content_hash: str,
    cutoff: datetime,
) -> AccountOwnerAssignmentProvenanceReceiptV4:
    """Validate one exact-current Receipt v4 returned by a public provider."""

    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact-current Receipt v4 is unavailable")
    if type(value) is not AccountOwnerAssignmentProvenanceReceiptV4:
        raise AccountOwnerAssignmentCorruption("Receipt v4 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Receipt v4 is corrupt") from error
    if (
        value.receipt_id != receipt_id
        or value.receipt_version != receipt_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Receipt v4 selector substitution")
    if not value.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("Receipt v4 is not current")
    return value


def _root(
    value: object | None,
    *,
    observation_id: str,
    observation_version: str,
    content_hash: str,
    cutoff: datetime,
) -> AllocatedPhysicalAccountRowObservationV3:
    """Validate one exact-current Physical v3 observation returned by a provider."""

    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact-current Physical v3 is unavailable")
    if type(value) is not AllocatedPhysicalAccountRowObservationV3:
        raise AccountOwnerAssignmentCorruption("Physical v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Physical v3 is corrupt") from error
    if (
        value.observation_id != observation_id
        or value.observation_version != observation_version
        or value.content_hash != content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Physical v3 selector substitution")
    if not value.is_knowable_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("Physical v3 is not current")
    return value


def _subject(value: object) -> AccountOwnerAssignmentSubjectV4:
    """Restore and validate one exact Subject v4 returned by a repository."""

    if type(value) is not AccountOwnerAssignmentSubjectV4:
        raise AccountOwnerAssignmentCorruption("Subject v4 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Subject v4 is corrupt") from error
    return value


def _record(value: object) -> PersistedAccountOwnerAssignmentEvidenceV4:
    """Restore and validate one exact persisted Evidence v4 envelope."""

    if type(value) is not PersistedAccountOwnerAssignmentEvidenceV4:
        raise AccountOwnerAssignmentCorruption("Evidence v4 record type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Evidence v4 record is corrupt") from error
    return value


def _participants(value: object | None, *, as_of: datetime) -> CurrentSingleOwnerParticipants:
    """Validate the complete server-owned policy, authority, and role projection."""

    if value is None:
        raise AccountOwnerAssignmentUnavailable("current single-owner participants are unavailable")
    if type(value) is not CurrentSingleOwnerParticipants:
        raise AccountOwnerAssignmentCorruption("participants type substitution")
    participants = value
    try:
        cutoff = _aware(as_of, "as_of")
        policy = participants.policy
        authority = participants.authority
        claimant = participants.claimant
        approver = participants.approver
        if type(policy) is not SingleOwnerAuthorityPolicyV1:
            raise TypeError("participants policy type substitution")
        policy.__post_init__()
        if type(authority) is not CurrentAccountActorAuthorityV3:
            raise TypeError("participants authority type substitution")
        authority.__post_init__()
        if type(claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("participants claimant type substitution")
        if type(approver) is not AccountOwnerAssignmentActor:
            raise TypeError("participants approver type substitution")
        claimant.__post_init__()
        approver.__post_init__()
        observed_at = _aware(participants.observed_at, "participants observed_at")
        valid_until = _aware(participants.valid_until, "participants valid_until")
    except (AttributeError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("participants projection is corrupt") from error
    if observed_at != cutoff:
        raise AccountOwnerAssignmentCorruption("participants observation clock substitution")
    if authority.recorded_at > cutoff:
        raise AccountOwnerAssignmentCorruption("participants authority clock substitution")
    if not policy.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("current single-owner policy is unavailable")
    if (
        not authority.is_authenticated
        or not authority.is_active
        or not authority.is_staff
        or authority.rbac_role != "admin"
        or cutoff >= authority.valid_until
    ):
        raise AccountOwnerAssignmentUnavailable("current actor authority is unavailable")
    if valid_until <= cutoff:
        raise AccountOwnerAssignmentUnavailable("current participant validity is unavailable")
    if valid_until > min(policy.valid_until, authority.valid_until):
        raise AccountOwnerAssignmentCorruption("participant validity exceeds its sources")
    try:
        validate_single_owner_participants(
            policy=policy,
            claimant=claimant,
            approver=approver,
            as_of=cutoff,
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption(
            "participants roles or policy are corrupt"
        ) from error
    if (
        authority.actor_id != claimant.actor_id
        or authority.actor_id != approver.actor_id
        or authority.user_id != claimant.user_id
        or authority.user_id != approver.user_id
        or authority.is_staff is not claimant.is_staff
        or authority.is_staff is not approver.is_staff
    ):
        raise AccountOwnerAssignmentCorruption("participants authority actor substitution")
    return participants


class RegisterAccountOwnerAssignmentSubjectV4:
    """Register one immutable Subject v4 after Receipt/Physical double reads."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        repository: AccountOwnerAssignmentEvidenceV4Repository,
    ) -> None:
        """Inject public exact-current source readers and a Subject repository."""

        self._receipts = receipt_provider
        self._roots = root_provider
        self._repository = repository

    def execute(
        self, command: RegisterAccountOwnerAssignmentSubjectV4Command
    ) -> AccountOwnerAssignmentSubjectV4:
        """Register or replay a Subject first winner with no source fallback."""

        if type(command) is not RegisterAccountOwnerAssignmentSubjectV4Command:
            raise TypeError(
                "command must be an exact RegisterAccountOwnerAssignmentSubjectV4Command"
            )
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner_value = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=cutoff,
            )
            if winner_value is not None:
                winner = _subject(winner_value)
                if winner.requested_at > cutoff:
                    raise AccountOwnerAssignmentCorruption("repository returned future Subject v4")
                if not _subject_matches(winner, command):
                    raise AccountOwnerAssignmentConflict("Subject v4 identity has another winner")
                try:
                    current = self._read(command, cutoff)
                except AccountOwnerAssignmentUnavailable as error:
                    raise AccountOwnerAssignmentConflict(
                        "Subject v4 winner no longer has current sources"
                    ) from error
                if current.receipt != winner.receipt or current.root != winner.physical_root:
                    raise AccountOwnerAssignmentConflict("Subject v4 winner source changed")
                if not winner.is_current_at(cutoff):
                    raise AccountOwnerAssignmentConflict("Subject v4 winner is no longer current")
                return winner

            first = self._read(command, cutoff)
            recorded_at = _clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentCorruption("repository clock moved backwards")
            try:
                final = self._read(command, recorded_at)
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict(
                    "Subject v4 sources changed during registration"
                ) from error
            if final != first:
                raise AccountOwnerAssignmentConflict(
                    "Subject v4 sources changed during registration"
                )
            receipt, root = final.receipt, final.root
            binding = receipt.binding
            physical = root.physical_observation
            valid_until = min(receipt.valid_until, root.valid_until)
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentUnavailable(
                    "Subject v4 sources expired before registration"
                )
            candidate = AccountOwnerAssignmentSubjectV4(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                receipt=receipt,
                binding=binding,
                physical_root=root,
                receipt_identity_hash=receipt.identity_hash,
                receipt_content_hash=receipt.content_hash,
                policy_identity_hash=receipt.policy.identity_hash,
                policy_content_hash=receipt.policy.content_hash,
                binding_identity_hash=binding.identity_hash,
                binding_content_hash=binding.content_hash,
                allocation_identity_hash=binding.allocation.identity_hash,
                allocation_content_hash=binding.allocation.content_hash,
                creation_root_identity_hash=root.identity_hash,
                creation_root_content_hash=root.content_hash,
                account_claim_hash=binding.account_claim_hash,
                underlying_claim_hash=binding.underlying_claim_hash,
                physical_observation_content_hash=physical.content_hash,
                physical_source_content_hash=physical.source_content_hash,
                physical_raw_observation_content_hash=physical.raw_observation_content_hash,
                requested_at=cutoff,
                valid_until=valid_until,
            )
            persisted = _subject(self._repository.append_subject(candidate, recorded_at=cutoff))
            if persisted != candidate:
                raise AccountOwnerAssignmentConflict("Subject v4 first winner differs")
            return persisted

    def _read(
        self, command: RegisterAccountOwnerAssignmentSubjectV4Command, cutoff: datetime
    ) -> _SubjectInputs:
        """Read and cross-check exact Receipt v4 and Physical v3 sources."""

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
            raise AccountOwnerAssignmentCorruption("Binding v2 selector substitution")
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
            raise AccountOwnerAssignmentCorruption("Receipt v4 and Physical v3 disagree")
        return _SubjectInputs(receipt, root)


def _read_approval_inputs(
    repository: AccountOwnerAssignmentEvidenceV4Repository,
    receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
    root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
    participants_reader: CurrentSingleOwnerParticipantsReader,
    command: ApproveAccountOwnerAssignmentEvidenceV4Command,
    cutoff: datetime,
) -> _ApprovalInputs:
    """Read a current Subject, its Receipt/Physical sources, and participants."""

    subject_value = repository.get_subject_winner(
        subject_id=command.subject_id,
        subject_version=command.subject_version,
        as_of=cutoff,
    )
    if subject_value is None:
        raise AccountOwnerAssignmentUnavailable("Subject v4 is unavailable")
    subject = _subject(subject_value)
    if (subject.subject_id, subject.subject_version) != (
        command.subject_id,
        command.subject_version,
    ):
        raise AccountOwnerAssignmentCorruption("Subject v4 selector substitution")
    if subject.content_hash != command.expected_subject_content_hash:
        raise AccountOwnerAssignmentConflict("Subject v4 identity has another winner")
    if not subject.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("Subject v4 is not current")
    receipt = subject.receipt
    current_receipt = _receipt(
        receipt_provider.get_exact_current(
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
        root_provider.get_exact_current(
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
        raise AccountOwnerAssignmentCorruption("Subject v4 upstream substitution")
    participants = _participants(participants_reader.get_current(as_of=cutoff), as_of=cutoff)
    if (
        participants.policy != receipt.policy
        or participants.claimant != receipt.claimant
        or participants.policy.identity_hash != receipt.policy_identity_hash
        or participants.policy.content_hash != receipt.policy_content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Subject v4 participant source substitution")
    return _ApprovalInputs(subject, current_receipt, current_root, participants)


def _read_heads(
    repository: AccountOwnerAssignmentEvidenceV4Repository,
    subject: AccountOwnerAssignmentSubjectV4,
    cutoff: datetime,
) -> tuple[
    PersistedAccountOwnerAssignmentEvidenceV4 | None,
    PersistedAccountOwnerAssignmentEvidenceV4 | None,
]:
    """Read and type-check both logical account mapping heads."""

    binding = subject.binding
    account_value = repository.get_account_head(
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        as_of=cutoff,
    )
    underlying_value = repository.get_underlying_head(
        underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        as_of=cutoff,
    )
    return (
        None if account_value is None else _record(account_value),
        None if underlying_value is None else _record(underlying_value),
    )


def _matches_record(
    inputs: _ApprovalInputs, record: PersistedAccountOwnerAssignmentEvidenceV4
) -> bool:
    """Compare current source facts with an already persisted Evidence record."""

    return (
        inputs.subject == record.evidence.subject
        and inputs.participants.policy == record.evidence.policy
        and inputs.participants.claimant == record.evidence.claimant
        and inputs.participants.approver == record.evidence.approved_by
        and inputs.participants.authority == record.authority
    )


class ApproveAccountOwnerAssignmentEvidenceV4:
    """Explicitly approve one Subject as inactive same-owner Evidence v4."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        participants_reader: CurrentSingleOwnerParticipantsReader,
        repository: AccountOwnerAssignmentEvidenceV4Repository,
        validity_period: timedelta,
    ) -> None:
        """Inject server-owned participant/source readers and the evidence repository."""

        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._receipts = receipt_provider
        self._roots = root_provider
        self._participants = participants_reader
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self, command: ApproveAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4:
        """Explicitly record or current-revalidate one inactive Evidence v4 root.

        Calling this method is the approval action.  A participant projection
        alone never appends evidence and this class is not a login hook.
        """

        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV4Command:
            raise TypeError(
                "command must be an exact ApproveAccountOwnerAssignmentEvidenceV4Command"
            )
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner_value = self._repository.get_winner(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                as_of=cutoff,
            )
            if winner_value is not None:
                winner = _record(winner_value)
                evidence = winner.evidence
                if evidence.recorded_at > cutoff:
                    raise AccountOwnerAssignmentCorruption("repository returned future Evidence v4")
                if not _evidence_matches(evidence, command):
                    raise AccountOwnerAssignmentConflict("Evidence v4 identity has another winner")
                if not evidence.is_current_at(cutoff):
                    raise AccountOwnerAssignmentConflict("Evidence v4 winner is no longer current")
                try:
                    current = self._read(command, cutoff)
                except AccountOwnerAssignmentUnavailable as error:
                    raise AccountOwnerAssignmentConflict(
                        "Evidence v4 winner no longer has current sources"
                    ) from error
                if not _matches_record(current, winner):
                    raise AccountOwnerAssignmentConflict("Evidence v4 winner source changed")
                account_head, underlying_head = _read_heads(
                    self._repository, current.subject, cutoff
                )
                if account_head != winner or underlying_head != winner:
                    raise AccountOwnerAssignmentConflict("Evidence v4 winner mapping heads changed")
                return evidence

            first = self._read(command, cutoff)
            first_heads = _read_heads(self._repository, first.subject, cutoff)
            _require_empty_heads(*first_heads)
            recorded_at = _clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentCorruption("repository clock moved backwards")
            try:
                final = self._read(command, recorded_at)
                final_heads = _read_heads(self._repository, final.subject, recorded_at)
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict(
                    "Evidence v4 sources changed during approval"
                ) from error
            if not _same_approval_inputs(first, final):
                raise AccountOwnerAssignmentConflict("Evidence v4 sources changed during approval")
            _require_empty_heads(*final_heads)
            approval_valid_until = min(
                cutoff + self._validity_period,
                final.participants.authority.valid_until,
                final.participants.valid_until,
            )
            valid_until = min(final.subject.valid_until, approval_valid_until)
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentUnavailable("Evidence v4 approval sources expired")
            evidence = AccountOwnerAssignmentEvidenceV4(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                subject=final.subject,
                policy_identity_hash=final.participants.policy.identity_hash,
                policy_content_hash=final.participants.policy.content_hash,
                assigned_owner_user_id=final.participants.claimant.user_id,
                approved_by=final.participants.approver,
                approved_at=cutoff,
                recorded_at=recorded_at,
                approval_valid_until=approval_valid_until,
                valid_until=valid_until,
                account_claim_hash=final.subject.account_claim_hash,
                underlying_claim_hash=final.subject.underlying_claim_hash,
            )
            try:
                validate_account_owner_assignment_evidence_v4_root(evidence)
                validate_account_owner_assignment_evidence_v4_dual_mapping_root(
                    evidence,
                    account_claim_hash=final.subject.account_claim_hash,
                    underlying_claim_hash=final.subject.underlying_claim_hash,
                )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentCorruption("Evidence v4 root is invalid") from error
            record = PersistedAccountOwnerAssignmentEvidenceV4(
                evidence=evidence,
                authority=final.participants.authority,
            )
            persisted = _record(
                self._repository.append_root(
                    record,
                    expected_account_head_hash=None,
                    expected_underlying_head_hash=None,
                    recorded_at=recorded_at,
                )
            )
            if persisted != record:
                raise AccountOwnerAssignmentConflict("Evidence v4 first winner differs")
            return persisted.evidence

    def _read(
        self, command: ApproveAccountOwnerAssignmentEvidenceV4Command, cutoff: datetime
    ) -> _ApprovalInputs:
        """Read this approval's source graph through the shared typed helper."""

        return _read_approval_inputs(
            self._repository,
            self._receipts,
            self._roots,
            self._participants,
            command,
            cutoff,
        )


class GetExactAccountOwnerAssignmentEvidenceV4:
    """Read immutable Evidence history without requiring current authority."""

    def __init__(self, repository: AccountOwnerAssignmentEvidenceV4Repository) -> None:
        """Inject the exact historical Evidence repository."""

        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Return exact Evidence once its recorded clock is knowable."""

        if type(command) is not GetExactAccountOwnerAssignmentEvidenceV4Command:
            raise TypeError(
                "command must be an exact GetExactAccountOwnerAssignmentEvidenceV4Command"
            )
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = _record(value)
        evidence = record.evidence
        if not _evidence_selector_matches(evidence, command):
            raise AccountOwnerAssignmentCorruption("exact Evidence v4 selector substitution")
        return evidence if evidence.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentEvidenceV4:
    """Read exact Evidence only while policy, authority, sources, and both heads agree."""

    def __init__(
        self,
        *,
        receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        participants_reader: CurrentSingleOwnerParticipantsReader,
        repository: AccountOwnerAssignmentEvidenceV4Repository,
    ) -> None:
        """Inject all current source readers required for a fail-closed read."""

        self._receipts = receipt_provider
        self._roots = root_provider
        self._participants = participants_reader
        self._repository = repository

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Return no value for stale, substituted, revoked, split, or expired state."""

        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV4Command:
            raise TypeError(
                "command must be an exact GetCurrentAccountOwnerAssignmentEvidenceV4Command"
            )
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            evidence_id=command.evidence_id,
            evidence_version=command.evidence_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = _record(value)
        evidence = record.evidence
        if not _evidence_selector_matches(evidence, command):
            raise AccountOwnerAssignmentCorruption("current Evidence v4 selector substitution")
        if not evidence.is_current_at(command.as_of):
            return None
        approval = ApproveAccountOwnerAssignmentEvidenceV4Command(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            subject_id=evidence.subject.subject_id,
            subject_version=evidence.subject.subject_version,
            expected_subject_content_hash=evidence.subject.content_hash,
        )
        try:
            inputs = _read_approval_inputs(
                self._repository,
                self._receipts,
                self._roots,
                self._participants,
                approval,
                command.as_of,
            )
        except AccountOwnerAssignmentUnavailable:
            return None
        if not _matches_record(inputs, record):
            return None
        account_value = self._repository.get_account_head(
            account_namespace=evidence.subject.binding.account_namespace_claim,
            account_id=evidence.subject.binding.account_id_claim,
            as_of=command.as_of,
        )
        underlying_value = self._repository.get_underlying_head(
            underlying_unified_account_namespace=(
                evidence.subject.binding.underlying_unified_account_namespace_claim
            ),
            underlying_unified_account_id=(
                evidence.subject.binding.underlying_unified_account_id_claim
            ),
            as_of=command.as_of,
        )
        if account_value is None or underlying_value is None:
            return None
        account_head = _record(account_value)
        underlying_head = _record(underlying_value)
        if account_head != record or underlying_head != record:
            return None
        return evidence


def _clock(value: object) -> datetime:
    """Convert a repository clock failure into a typed corruption error."""

    try:
        return _aware(value, "repository clock")
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption(str(error)) from error


def _subject_matches(
    subject: AccountOwnerAssignmentSubjectV4,
    command: RegisterAccountOwnerAssignmentSubjectV4Command,
) -> bool:
    """Compare every server-selected Subject registration selector."""

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


def _evidence_matches(
    evidence: AccountOwnerAssignmentEvidenceV4,
    command: ApproveAccountOwnerAssignmentEvidenceV4Command,
) -> bool:
    """Compare an existing root with the exact approval selectors."""

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


def _evidence_selector_matches(
    evidence: AccountOwnerAssignmentEvidenceV4,
    command: (
        GetExactAccountOwnerAssignmentEvidenceV4Command
        | GetCurrentAccountOwnerAssignmentEvidenceV4Command
    ),
) -> bool:
    """Compare a historical/current read result with its ID/version/hash."""

    return (
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
    ) == (command.evidence_id, command.evidence_version, command.expected_content_hash)


def _same_approval_inputs(first: _ApprovalInputs, final: _ApprovalInputs) -> bool:
    """Compare stable source facts while allowing observation clocks to advance."""

    return (
        first.subject == final.subject
        and first.receipt == final.receipt
        and first.root == final.root
        and first.participants.policy == final.participants.policy
        and first.participants.authority == final.participants.authority
        and first.participants.claimant == final.participants.claimant
        and first.participants.approver == final.participants.approver
        and first.participants.valid_until == final.participants.valid_until
    )


def _require_empty_heads(
    account: PersistedAccountOwnerAssignmentEvidenceV4 | None,
    underlying: PersistedAccountOwnerAssignmentEvidenceV4 | None,
) -> None:
    """Require both logical mapping heads to be empty before a root append."""

    if account is None and underlying is None:
        return
    if account is None or underlying is None or account != underlying:
        raise AccountOwnerAssignmentCorruption("Evidence v4 mapping heads disagree")
    raise AccountOwnerAssignmentConflict("Evidence v4 mapping already has a root")


__all__ = [
    "AccountOwnerAssignmentEvidenceV4Repository",
    "ApproveAccountOwnerAssignmentEvidenceV4",
    "ApproveAccountOwnerAssignmentEvidenceV4Command",
    "CurrentSingleOwnerParticipantsReader",
    "ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider",
    "ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider",
    "GetCurrentAccountOwnerAssignmentEvidenceV4",
    "GetCurrentAccountOwnerAssignmentEvidenceV4Command",
    "GetExactAccountOwnerAssignmentEvidenceV4",
    "GetExactAccountOwnerAssignmentEvidenceV4Command",
    "PersistedAccountOwnerAssignmentEvidenceV4",
    "RegisterAccountOwnerAssignmentSubjectV4",
    "RegisterAccountOwnerAssignmentSubjectV4Command",
]
