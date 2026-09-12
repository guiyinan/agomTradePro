"""Application orchestration for inactive Account owner-assignment Evidence V5.

Evidence V5 is an approval record over the re-observation-backed Subject V5.
The use cases below only coordinate public Application ports and immutable
Domain values.  They do not authenticate a request, activate an owner, or
grant execution authority.
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
from apps.account.application.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5Corruption,
    AccountOwnerAssignmentSubjectV5Unavailable,
    GetCurrentAccountOwnerAssignmentSubjectV5Command,
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
    validate_account_owner_assignment_evidence_v5_dual_mapping_root,
    validate_account_owner_assignment_evidence_v5_root,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
)
from core.exceptions import DataValidationError, DuplicateResourceError, ResourceNotFoundError


class AccountOwnerAssignmentEvidenceV5Unavailable(
    AccountOwnerAssignmentUnavailable, ResourceNotFoundError
):
    """An exact current Subject V5 or other Evidence V5 source is unavailable."""


class AccountOwnerAssignmentEvidenceV5Conflict(
    AccountOwnerAssignmentConflict, DuplicateResourceError
):
    """An immutable Evidence V5 winner or mapping head differs."""


class AccountOwnerAssignmentEvidenceV5Corruption(
    AccountOwnerAssignmentCorruption, DataValidationError
):
    """A repository or current reader substituted invalid Evidence V5 data."""


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
class PersistedAccountOwnerAssignmentEvidenceV5:
    """Bind complete Evidence V5 to the authenticated approval authority."""

    evidence: AccountOwnerAssignmentEvidenceV5
    authority: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Validate the immutable evidence and every non-secret authority fact."""

        if type(self.evidence) is not AccountOwnerAssignmentEvidenceV5:
            raise TypeError("evidence must be an exact AccountOwnerAssignmentEvidenceV5")
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
class ApproveAccountOwnerAssignmentEvidenceV5Command:
    """Select one Evidence V5 first winner and one exact Subject V5 hash."""

    evidence_id: str
    evidence_version: str
    subject_id: str
    subject_version: str
    expected_subject_content_hash: str

    def __post_init__(self) -> None:
        """Validate the ID/hash-only approval selectors."""

        for name in ("evidence_id", "evidence_version", "subject_id", "subject_version"):
            _token(getattr(self, name), name)
        _digest(self.expected_subject_content_hash, "expected_subject_content_hash")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentEvidenceV5Command:
    """Select immutable historical Evidence V5 by exact ID, version, and hash."""

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
class GetCurrentAccountOwnerAssignmentEvidenceV5Command:
    """Select one Evidence V5 only while its complete Subject V5 graph is current."""

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


class CurrentAccountOwnerAssignmentSubjectV5Reader(Protocol):
    """Read one exact current Subject V5 through its public Application port."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentSubjectV5Command
    ) -> AccountOwnerAssignmentSubjectV5 | None:
        """Return the selected current Subject V5 or no value."""
        ...


class CurrentSingleOwnerParticipantsReader(Protocol):
    """Re-read current policy, authority, and same-owner roles per cutoff."""

    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants | None:
        """Return exact current participant facts at ``as_of``."""
        ...


class AccountOwnerAssignmentEvidenceV5Repository(Protocol):
    """Persist Subject V5 and root Evidence V5 with first-winner/CAS semantics."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work for one approval or replay."""
        ...

    def now(self) -> datetime:
        """Return the timezone-aware repository clock."""
        ...

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV5 | PersistedAccountOwnerAssignmentSubjectV5 | None:
        """Return the immutable Subject V5 first winner knowable at ``as_of``."""
        ...

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the immutable Evidence V5 first winner knowable at ``as_of``."""
        ...

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the account mapping head at ``as_of`` without fallback."""
        ...

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the underlying mapping head at ``as_of`` without fallback."""
        ...

    def append_root(
        self,
        record: PersistedAccountOwnerAssignmentEvidenceV5,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5:
        """Append one root only after both logical mapping heads pass CAS checks."""
        ...

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return only the requested historical Evidence V5 identity and hash."""
        ...


@dataclass(frozen=True, slots=True)
class _ApprovalInputs:
    """Validated current Subject V5 and server-owned participant projection."""

    subject: AccountOwnerAssignmentSubjectV5
    participants: CurrentSingleOwnerParticipants


def _subject(
    value: object | None,
) -> AccountOwnerAssignmentSubjectV5 | None:
    """Restore and validate one exact Subject V5 or its durable envelope."""

    if value is None:
        return None
    if type(value) is PersistedAccountOwnerAssignmentSubjectV5:
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "Subject V5 record is corrupt"
            ) from error
        value = value.subject
    if type(value) is not AccountOwnerAssignmentSubjectV5:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Subject V5 type substitution")
    subject = value
    try:
        subject.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Subject V5 is corrupt") from error
    return subject


def _record(
    value: object | None,
) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
    """Restore and validate one exact persisted Evidence V5 envelope."""

    if value is None:
        return None
    if type(value) is not PersistedAccountOwnerAssignmentEvidenceV5:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Evidence V5 record type substitution")
    record = value
    try:
        record.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Evidence V5 record is corrupt") from error
    return record


def _participants(
    value: object | None,
    *,
    as_of: datetime,
) -> CurrentSingleOwnerParticipants:
    """Validate the complete server-owned policy, authority, and role projection."""

    if value is None:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "current single-owner participants are unavailable"
        )
    if type(value) is not CurrentSingleOwnerParticipants:
        raise AccountOwnerAssignmentEvidenceV5Corruption("participants type substitution")
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
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "participants projection is corrupt"
        ) from error
    if observed_at != cutoff:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "participants observation clock substitution"
        )
    if authority.recorded_at > cutoff:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "participants authority clock substitution"
        )
    if not policy.is_current_at(cutoff):
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "current single-owner policy is unavailable"
        )
    if (
        not authority.is_authenticated
        or not authority.is_active
        or not authority.is_staff
        or authority.rbac_role != "admin"
        or cutoff >= authority.valid_until
    ):
        raise AccountOwnerAssignmentEvidenceV5Unavailable("current actor authority is unavailable")
    if valid_until <= cutoff:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "current participant validity is unavailable"
        )
    if valid_until > min(policy.valid_until, authority.valid_until):
        raise AccountOwnerAssignmentEvidenceV5Corruption("participant validity exceeds its sources")
    try:
        validate_single_owner_participants(
            policy=policy,
            claimant=claimant,
            approver=approver,
            as_of=cutoff,
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
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
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "participants authority actor substitution"
        )
    return participants


def _current_subject(
    reader: CurrentAccountOwnerAssignmentSubjectV5Reader,
    *,
    subject_id: str,
    subject_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> AccountOwnerAssignmentSubjectV5:
    """Read and validate one exact current Subject V5 through its Application port."""

    try:
        value = reader.execute(
            GetCurrentAccountOwnerAssignmentSubjectV5Command(
                subject_id=subject_id,
                subject_version=subject_version,
                expected_content_hash=expected_content_hash,
                as_of=as_of,
            )
        )
    except AccountOwnerAssignmentEvidenceV5Unavailable:
        raise
    except AccountOwnerAssignmentSubjectV5Unavailable as error:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "current Subject V5 is unavailable"
        ) from error
    except AccountOwnerAssignmentSubjectV5Corruption as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "current Subject V5 reader returned corrupt evidence"
        ) from error
    except AccountOwnerAssignmentUnavailable as error:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "current Subject V5 is unavailable"
        ) from error
    except AccountOwnerAssignmentCorruption as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "current Subject V5 reader returned corrupt evidence"
        ) from error
    subject = _subject(value)
    if subject is None:
        raise AccountOwnerAssignmentEvidenceV5Unavailable("current Subject V5 is unavailable")
    if (
        subject.subject_id != subject_id
        or subject.subject_version != subject_version
        or subject.content_hash != expected_content_hash
    ):
        raise AccountOwnerAssignmentEvidenceV5Corruption("current Subject V5 selector substitution")
    try:
        current = subject.is_current_at(as_of)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "current Subject V5 cutoff is invalid"
        ) from error
    if not current:
        raise AccountOwnerAssignmentEvidenceV5Unavailable("Subject V5 is not current")
    return subject


def _read_approval_inputs(
    repository: AccountOwnerAssignmentEvidenceV5Repository,
    subject_reader: CurrentAccountOwnerAssignmentSubjectV5Reader,
    participants_reader: CurrentSingleOwnerParticipantsReader,
    command: ApproveAccountOwnerAssignmentEvidenceV5Command,
    cutoff: datetime,
) -> _ApprovalInputs:
    """Read a registered current Subject V5 and the current participant projection."""

    subject_value = repository.get_subject_winner(
        subject_id=command.subject_id,
        subject_version=command.subject_version,
        as_of=cutoff,
    )
    subject = _subject(subject_value)
    if subject is None:
        raise AccountOwnerAssignmentEvidenceV5Unavailable("Subject V5 is unavailable")
    if (subject.subject_id, subject.subject_version) != (
        command.subject_id,
        command.subject_version,
    ):
        raise AccountOwnerAssignmentEvidenceV5Corruption("Subject V5 selector substitution")
    if subject.content_hash != command.expected_subject_content_hash:
        raise AccountOwnerAssignmentEvidenceV5Conflict("Subject V5 identity has another winner")
    current_subject = _current_subject(
        subject_reader,
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        expected_content_hash=subject.content_hash,
        as_of=cutoff,
    )
    if current_subject != subject:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Subject V5 current source substitution")
    participants = _participants(participants_reader.get_current(as_of=cutoff), as_of=cutoff)
    if (
        participants.policy != subject.policy
        or participants.claimant != subject.claimant
        or participants.policy.identity_hash != subject.policy_identity_hash
        or participants.policy.content_hash != subject.policy_content_hash
    ):
        raise AccountOwnerAssignmentEvidenceV5Corruption(
            "Subject V5 participant source substitution"
        )
    return _ApprovalInputs(subject, participants)


def _read_heads(
    repository: AccountOwnerAssignmentEvidenceV5Repository,
    subject: AccountOwnerAssignmentSubjectV5,
    cutoff: datetime,
) -> tuple[
    PersistedAccountOwnerAssignmentEvidenceV5 | None,
    PersistedAccountOwnerAssignmentEvidenceV5 | None,
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
    return _record(account_value), _record(underlying_value)


class ApproveAccountOwnerAssignmentEvidenceV5:
    """Explicitly approve one current Subject V5 as inactive Evidence V5."""

    def __init__(
        self,
        *,
        subject_reader: CurrentAccountOwnerAssignmentSubjectV5Reader,
        participants_reader: CurrentSingleOwnerParticipantsReader,
        repository: AccountOwnerAssignmentEvidenceV5Repository,
        validity_period: timedelta,
    ) -> None:
        """Inject public current readers and the immutable Evidence V5 repository."""

        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._subjects = subject_reader
        self._participants = participants_reader
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self, command: ApproveAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5:
        """Record or replay one inactive Evidence V5 root after double reads."""

        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError(
                "command must be an exact ApproveAccountOwnerAssignmentEvidenceV5Command"
            )
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner = _record(
                self._repository.get_winner(
                    evidence_id=command.evidence_id,
                    evidence_version=command.evidence_version,
                    as_of=cutoff,
                )
            )
            if winner is not None:
                evidence = winner.evidence
                if evidence.recorded_at > cutoff:
                    raise AccountOwnerAssignmentEvidenceV5Corruption(
                        "repository returned future Evidence V5"
                    )
                if not _evidence_matches(evidence, command):
                    raise AccountOwnerAssignmentEvidenceV5Conflict(
                        "Evidence V5 identity has another winner"
                    )
                if not evidence.is_current_at(cutoff):
                    raise AccountOwnerAssignmentEvidenceV5Conflict(
                        "Evidence V5 winner is no longer current"
                    )
                try:
                    current = _read_approval_inputs(
                        self._repository,
                        self._subjects,
                        self._participants,
                        ApproveAccountOwnerAssignmentEvidenceV5Command(
                            evidence_id=evidence.evidence_id,
                            evidence_version=evidence.evidence_version,
                            subject_id=evidence.subject.subject_id,
                            subject_version=evidence.subject.subject_version,
                            expected_subject_content_hash=evidence.subject.content_hash,
                        ),
                        cutoff,
                    )
                except AccountOwnerAssignmentEvidenceV5Unavailable as error:
                    raise AccountOwnerAssignmentEvidenceV5Conflict(
                        "Evidence V5 winner no longer has current sources"
                    ) from error
                if not _matches_record(current, winner):
                    raise AccountOwnerAssignmentEvidenceV5Conflict(
                        "Evidence V5 winner source changed"
                    )
                account_head, underlying_head = _read_heads(
                    self._repository, current.subject, cutoff
                )
                if account_head != winner or underlying_head != winner:
                    raise AccountOwnerAssignmentEvidenceV5Conflict(
                        "Evidence V5 winner mapping heads changed"
                    )
                return evidence

            first = _read_approval_inputs(
                self._repository,
                self._subjects,
                self._participants,
                command,
                cutoff,
            )
            _require_empty_heads(*_read_heads(self._repository, first.subject, cutoff))
            recorded_at = _clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentEvidenceV5Corruption("repository clock moved backwards")
            try:
                final = _read_approval_inputs(
                    self._repository,
                    self._subjects,
                    self._participants,
                    command,
                    recorded_at,
                )
            except AccountOwnerAssignmentEvidenceV5Unavailable as error:
                raise AccountOwnerAssignmentEvidenceV5Conflict(
                    "Evidence V5 sources changed during approval"
                ) from error
            if not _same_approval_inputs(first, final):
                raise AccountOwnerAssignmentEvidenceV5Conflict(
                    "Evidence V5 sources changed during approval"
                )
            _require_empty_heads(*_read_heads(self._repository, final.subject, recorded_at))
            approval_valid_until = min(
                cutoff + self._validity_period,
                final.participants.authority.valid_until,
                final.participants.valid_until,
            )
            valid_until = min(final.subject.valid_until, approval_valid_until)
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentEvidenceV5Unavailable(
                    "Evidence V5 approval sources expired"
                )
            evidence = AccountOwnerAssignmentEvidenceV5(
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
                validate_account_owner_assignment_evidence_v5_root(evidence)
                validate_account_owner_assignment_evidence_v5_dual_mapping_root(
                    evidence,
                    account_claim_hash=final.subject.account_claim_hash,
                    underlying_claim_hash=final.subject.underlying_claim_hash,
                )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentEvidenceV5Corruption(
                    "Evidence V5 root is invalid"
                ) from error
            record = PersistedAccountOwnerAssignmentEvidenceV5(
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
                raise AccountOwnerAssignmentEvidenceV5Conflict("Evidence V5 first winner differs")
            if persisted is None:
                raise AccountOwnerAssignmentEvidenceV5Corruption(
                    "Evidence V5 repository returned no persisted winner"
                )
            return persisted.evidence


class GetExactAccountOwnerAssignmentEvidenceV5:
    """Read immutable historical Evidence V5 without current authority checks."""

    def __init__(self, repository: AccountOwnerAssignmentEvidenceV5Repository) -> None:
        """Inject the exact historical Evidence V5 repository."""

        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Return exact Evidence V5 once its recorded clock is knowable."""

        if type(command) is not GetExactAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError(
                "command must be an exact GetExactAccountOwnerAssignmentEvidenceV5Command"
            )
        command.__post_init__()
        record = _record(
            self._repository.get_exact_by_hash(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if record is None:
            return None
        evidence = record.evidence
        if not _evidence_selector_matches(evidence, command):
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "exact Evidence V5 selector substitution"
            )
        return evidence if evidence.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentEvidenceV5:
    """Read Evidence V5 only while Subject, authority, and both heads agree."""

    def __init__(
        self,
        *,
        subject_reader: CurrentAccountOwnerAssignmentSubjectV5Reader,
        participants_reader: CurrentSingleOwnerParticipantsReader,
        repository: AccountOwnerAssignmentEvidenceV5Repository,
    ) -> None:
        """Inject every current reader required for a fail-closed read."""

        self._subjects = subject_reader
        self._participants = participants_reader
        self._repository = repository

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Return no value for stale, substituted, split, or expired state."""

        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError(
                "command must be an exact GetCurrentAccountOwnerAssignmentEvidenceV5Command"
            )
        command.__post_init__()
        record = _record(
            self._repository.get_exact_by_hash(
                evidence_id=command.evidence_id,
                evidence_version=command.evidence_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if record is None:
            return None
        evidence = record.evidence
        if not _evidence_selector_matches(evidence, command):
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "current Evidence V5 selector substitution"
            )
        if not evidence.is_current_at(command.as_of):
            return None
        approval = ApproveAccountOwnerAssignmentEvidenceV5Command(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            subject_id=evidence.subject.subject_id,
            subject_version=evidence.subject.subject_version,
            expected_subject_content_hash=evidence.subject.content_hash,
        )
        try:
            inputs = _read_approval_inputs(
                self._repository,
                self._subjects,
                self._participants,
                approval,
                command.as_of,
            )
        except AccountOwnerAssignmentEvidenceV5Unavailable:
            return None
        if not _matches_record(inputs, record):
            return None
        account_head, underlying_head = _read_heads(
            self._repository, evidence.subject, command.as_of
        )
        if account_head is None or underlying_head is None:
            return None
        if account_head != record or underlying_head != record:
            return None
        return evidence


def _clock(value: object) -> datetime:
    """Validate and classify one repository clock value."""

    try:
        return _aware(value, "repository clock")
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption(str(error)) from error


def _evidence_matches(
    evidence: AccountOwnerAssignmentEvidenceV5,
    command: ApproveAccountOwnerAssignmentEvidenceV5Command,
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
    evidence: AccountOwnerAssignmentEvidenceV5,
    command: (
        GetExactAccountOwnerAssignmentEvidenceV5Command
        | GetCurrentAccountOwnerAssignmentEvidenceV5Command
    ),
) -> bool:
    """Compare a historical/current result with its ID, version, and hash."""

    return (
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
    ) == (command.evidence_id, command.evidence_version, command.expected_content_hash)


def _matches_record(
    inputs: _ApprovalInputs,
    record: PersistedAccountOwnerAssignmentEvidenceV5,
) -> bool:
    """Compare current Subject, participants, and authority with a persisted root."""

    return (
        inputs.subject == record.evidence.subject
        and inputs.participants.policy == record.evidence.policy
        and inputs.participants.claimant == record.evidence.claimant
        and inputs.participants.approver == record.evidence.approved_by
        and inputs.participants.authority == record.authority
    )


def _same_approval_inputs(first: _ApprovalInputs, final: _ApprovalInputs) -> bool:
    """Compare stable source facts while allowing only the observation clock to advance."""

    return (
        first.subject == final.subject
        and first.participants.policy == final.participants.policy
        and first.participants.authority == final.participants.authority
        and first.participants.claimant == final.participants.claimant
        and first.participants.approver == final.participants.approver
        and first.participants.valid_until == final.participants.valid_until
    )


def _require_empty_heads(
    account: PersistedAccountOwnerAssignmentEvidenceV5 | None,
    underlying: PersistedAccountOwnerAssignmentEvidenceV5 | None,
) -> None:
    """Require both logical mapping heads to be empty before a root append."""

    if account is None and underlying is None:
        return
    if account is None or underlying is None or account != underlying:
        raise AccountOwnerAssignmentEvidenceV5Corruption("Evidence V5 mapping heads disagree")
    raise AccountOwnerAssignmentEvidenceV5Conflict("Evidence V5 mapping already has a root")


__all__ = [
    "AccountOwnerAssignmentEvidenceV5Conflict",
    "AccountOwnerAssignmentEvidenceV5Corruption",
    "AccountOwnerAssignmentEvidenceV5Repository",
    "AccountOwnerAssignmentEvidenceV5Unavailable",
    "ApproveAccountOwnerAssignmentEvidenceV5",
    "ApproveAccountOwnerAssignmentEvidenceV5Command",
    "CurrentAccountOwnerAssignmentSubjectV5Reader",
    "CurrentSingleOwnerParticipantsReader",
    "GetCurrentAccountOwnerAssignmentEvidenceV5",
    "GetCurrentAccountOwnerAssignmentEvidenceV5Command",
    "GetExactAccountOwnerAssignmentEvidenceV5",
    "GetExactAccountOwnerAssignmentEvidenceV5Command",
    "PersistedAccountOwnerAssignmentEvidenceV5",
]
