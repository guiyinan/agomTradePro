"""Application use cases for inactive Evidence V5-backed Authority V3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Conflict,
    AccountOwnerAssignmentEvidenceV5Corruption,
    AccountOwnerAssignmentEvidenceV5Unavailable,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerAssignmentEvidenceV5Reader,
    CurrentOwnerTenantAuthorityParticipantsReader,
    CurrentOwnerTenantAuthorityV3,
    HistoricalOwnerAssignmentEvidenceV5Reader,
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Repository,
    OwnerTenantAuthorityV3Unavailable,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
    validate_owner_v3_authentication,
    validate_owner_v3_time,
)
from apps.account.application.single_owner_actor_authority import CurrentSingleOwnerParticipants
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    APPROVER_ROLE,
    REVOKER_ROLE,
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
    validate_owner_tenant_authority_v3_revocation,
    validate_owner_tenant_authority_v3_root,
    validate_owner_tenant_authority_v3_successor,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
)


def _token(value: object, name: str) -> None:
    """Require one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    """Require one complete lowercase SHA-256 selector."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    """Require one timezone-aware timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class IssueOwnerTenantAuthorityV3Command:
    """Select one current Evidence V5 for a first Authority V3 root."""

    authority_id: str
    authority_version: str
    assignment_evidence_id: str
    assignment_evidence_version: str
    expected_assignment_evidence_content_hash: str

    def __post_init__(self) -> None:
        """Validate the closed ID/hash-only root selectors."""

        for name in (
            "authority_id",
            "authority_version",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _token(getattr(self, name), name)
        _digest(
            self.expected_assignment_evidence_content_hash,
            "expected_assignment_evidence_content_hash",
        )


@dataclass(frozen=True, slots=True)
class GetCurrentOwnerTenantAuthorityV3Command:
    """Select one Authority V3 by its exact durable identity for a live read."""

    authority_id: str
    authority_version: str
    expected_content_hash: str

    def __post_init__(self) -> None:
        """Validate the exact current selector."""

        _token(self.authority_id, "authority_id")
        _token(self.authority_version, "authority_version")
        _digest(self.expected_content_hash, "expected_content_hash")


@dataclass(frozen=True, slots=True)
class GetExactOwnerTenantAuthorityV3Command(GetCurrentOwnerTenantAuthorityV3Command):
    """Select one immutable Authority V3 at an explicit historical cutoff."""

    as_of: datetime

    def __post_init__(self) -> None:
        """Validate the exact historical selector and point-in-time cutoff."""

        GetCurrentOwnerTenantAuthorityV3Command.__post_init__(self)
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class SupersedeOwnerTenantAuthorityV3Command:
    """Select one opaque-version active successor and its exact predecessor."""

    authority_id: str
    authority_version: str
    predecessor_version: str
    expected_predecessor_content_hash: str
    assignment_evidence_id: str
    assignment_evidence_version: str
    expected_assignment_evidence_content_hash: str

    def __post_init__(self) -> None:
        """Validate successor identity, predecessor CAS, and Evidence V5 selectors."""

        for name in (
            "authority_id",
            "authority_version",
            "predecessor_version",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _token(getattr(self, name), name)
        _digest(self.expected_predecessor_content_hash, "expected_predecessor_content_hash")
        _digest(
            self.expected_assignment_evidence_content_hash,
            "expected_assignment_evidence_content_hash",
        )


SuccessorOwnerTenantAuthorityV3Command = SupersedeOwnerTenantAuthorityV3Command
IssueOwnerTenantAuthorityV3SuccessorCommand = SupersedeOwnerTenantAuthorityV3Command


@dataclass(frozen=True, slots=True)
class RevokeOwnerTenantAuthorityV3Command(GetCurrentOwnerTenantAuthorityV3Command):
    """Select one exact Authority V3 and a stable reason for its revocation."""

    reason: str

    def __post_init__(self) -> None:
        """Validate the immutable target and replay-stable reason."""

        GetCurrentOwnerTenantAuthorityV3Command.__post_init__(self)
        _token(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Keep one current Evidence V5 and participant observation comparable."""

    assignment: AccountOwnerAssignmentEvidenceV5
    participants: CurrentSingleOwnerParticipants


class OwnerTenantAuthorityV3Service:
    """Orchestrate Authority V3 roots, successors, current reads, and revocations."""

    def __init__(
        self,
        *,
        repository: OwnerTenantAuthorityV3Repository,
        current_assignments: CurrentOwnerAssignmentEvidenceV5Reader,
        historical_assignments: HistoricalOwnerAssignmentEvidenceV5Reader,
        participants: CurrentOwnerTenantAuthorityParticipantsReader,
        validity_period: timedelta,
    ) -> None:
        """Bind public Evidence V5 readers and one server-owned repository boundary."""

        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        if not callable(getattr(current_assignments, "execute", None)):
            raise TypeError("current_assignments must expose execute")
        if not callable(getattr(historical_assignments, "execute", None)):
            raise TypeError("historical_assignments must expose execute")
        if not callable(getattr(participants, "get_current", None)):
            raise TypeError("participants must expose get_current")
        self._repository = repository
        self._current_assignments = current_assignments
        self._historical_assignments = historical_assignments
        self._participants = participants
        self._validity_period = validity_period

    def issue(self, command: IssueOwnerTenantAuthorityV3Command) -> OwnerTenantAuthorityV3:
        """Issue or replay one first-winner active Authority V3 root."""

        if type(command) is not IssueOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact IssueOwnerTenantAuthorityV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = self._now()
            winner = self._winner(command.authority_id, command.authority_version, cutoff)
            if winner is not None:
                checked = winner.authority
                if not self._root_matches(checked, command):
                    raise OwnerTenantAuthorityV3Conflict(
                        "authority root identity has another winner"
                    )
                if self._current(winner, cutoff) is None:
                    raise OwnerTenantAuthorityV3Conflict(
                        "authority root winner no longer has current sources"
                    )
                return checked
            self._empty_slots(
                command.authority_id, command.expected_assignment_evidence_content_hash, cutoff
            )
            first = self._inputs(command, cutoff)
            recorded_at = self._now()
            if recorded_at < cutoff:
                raise OwnerTenantAuthorityV3Corruption("authority repository clock moved backwards")
            second = self._inputs(command, recorded_at)
            if not self._same_inputs(first, second):
                raise OwnerTenantAuthorityV3Conflict("authority approval inputs changed")
            candidate = self._candidate(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                assignment=second.assignment,
                participants=second.participants,
                approved_at=cutoff,
                recorded_at=recorded_at,
                predecessor_hash=None,
            )
            try:
                validate_owner_tenant_authority_v3_root(candidate)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Corruption(
                    "authority root candidate is invalid"
                ) from error
            record = PersistedOwnerTenantAuthorityV3(candidate, second.participants.authority)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=recorded_at,
            )
            checked = self._record(persisted).authority
            if checked != candidate:
                raise OwnerTenantAuthorityV3Conflict("authority root first winner differs")
            return checked

    def successor(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Append or replay one exact active successor with predecessor CAS."""

        if type(command) is not SupersedeOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact SupersedeOwnerTenantAuthorityV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = self._now()
            if command.authority_version == command.predecessor_version:
                raise OwnerTenantAuthorityV3Conflict("authority successor version must advance")
            winner = self._winner(command.authority_id, command.authority_version, cutoff)
            if winner is not None:
                checked = winner.authority
                if not self._successor_matches(checked, command):
                    raise OwnerTenantAuthorityV3Conflict(
                        "authority successor identity has another winner"
                    )
                if self._current(winner, cutoff) is None:
                    raise OwnerTenantAuthorityV3Conflict(
                        "authority successor winner no longer has current sources"
                    )
                return checked
            predecessor_record = self._repository.get_head(
                authority_id=command.authority_id,
                as_of=cutoff,
            )
            if predecessor_record is None:
                raise OwnerTenantAuthorityV3Unavailable("authority predecessor is unavailable")
            predecessor = self._record(predecessor_record).authority
            if (
                predecessor.authority_version != command.predecessor_version
                or predecessor.content_hash != command.expected_predecessor_content_hash
            ):
                raise OwnerTenantAuthorityV3Conflict("authority predecessor changed")
            first = self._inputs(
                IssueOwnerTenantAuthorityV3Command(
                    command.authority_id,
                    command.authority_version,
                    command.assignment_evidence_id,
                    command.assignment_evidence_version,
                    command.expected_assignment_evidence_content_hash,
                ),
                cutoff,
            )
            if (
                first.assignment != predecessor.assignment
                or first.participants.policy != predecessor.policy
            ):
                raise OwnerTenantAuthorityV3Conflict("authority successor source scope changed")
            recorded_at = self._now()
            if recorded_at < cutoff:
                raise OwnerTenantAuthorityV3Corruption("authority repository clock moved backwards")
            if recorded_at <= predecessor.recorded_at:
                raise OwnerTenantAuthorityV3Conflict(
                    "authority successor recording clock must advance"
                )
            second = self._inputs(
                IssueOwnerTenantAuthorityV3Command(
                    command.authority_id,
                    command.authority_version,
                    command.assignment_evidence_id,
                    command.assignment_evidence_version,
                    command.expected_assignment_evidence_content_hash,
                ),
                recorded_at,
            )
            if not self._same_inputs(first, second):
                raise OwnerTenantAuthorityV3Conflict("authority successor inputs changed")
            if (
                second.assignment != predecessor.assignment
                or second.participants.policy != predecessor.policy
            ):
                raise OwnerTenantAuthorityV3Conflict("authority successor source scope changed")
            latest_record = self._repository.get_head(
                authority_id=command.authority_id,
                as_of=recorded_at,
            )
            if latest_record is None or self._record(latest_record).authority != predecessor:
                raise OwnerTenantAuthorityV3Conflict("authority predecessor changed")
            candidate = self._candidate(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                assignment=second.assignment,
                participants=second.participants,
                approved_at=cutoff,
                recorded_at=recorded_at,
                predecessor_hash=predecessor.content_hash,
            )
            try:
                validate_owner_tenant_authority_v3_successor(predecessor, candidate)
            except ValueError as error:
                raise OwnerTenantAuthorityV3Conflict(
                    "authority successor does not satisfy predecessor chain"
                ) from error
            record = PersistedOwnerTenantAuthorityV3(candidate, second.participants.authority)
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=predecessor.content_hash,
                recorded_at=recorded_at,
            )
            checked = self._record(persisted).authority
            if checked != candidate:
                raise OwnerTenantAuthorityV3Conflict("authority successor winner differs")
            return checked

    def supersede(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Alias `successor` for callers using the V1 lifecycle vocabulary."""

        return self.successor(command)

    def get_exact(
        self,
        command: GetExactOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3 | None:
        """Read one exact historical Authority V3 and its original Evidence V5."""

        if type(command) is not GetExactOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetExactOwnerTenantAuthorityV3Command")
        command.__post_init__()
        with self._repository.atomic():
            record = self._winner(command.authority_id, command.authority_version, command.as_of)
            if record is None:
                return None
            authority = record.authority
            if authority.content_hash != command.expected_content_hash:
                raise OwnerTenantAuthorityV3Conflict("authority content hash differs")
            self._history(authority)
            return authority if authority.is_knowable_at(command.as_of) else None

    def get_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Revalidate the final head, policy, fresh actor, and revocation state."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = self._now()
            record = self._selected(command, cutoff)
            if record is None:
                return None
            return self._current(record, cutoff)

    def revoke(
        self,
        command: RevokeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3Revocation:
        """Append or replay one immutable revocation with fresh current authority."""

        if type(command) is not RevokeOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact RevokeOwnerTenantAuthorityV3Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = self._now()
            record = self._selected(command, cutoff)
            if record is None:
                raise OwnerTenantAuthorityV3Unavailable("exact authority is unavailable")
            authority = record.authority
            self._history(authority)
            first = self._authority_participants(authority, cutoff)
            second_cutoff = self._now()
            second = self._authority_participants(authority, second_cutoff)
            if not self._same_participants(first, second):
                raise OwnerTenantAuthorityV3Conflict("authentication changed during revocation")
            recorded_at = self._now()
            if recorded_at < cutoff:
                raise OwnerTenantAuthorityV3Corruption("authority repository clock moved backwards")
            self._heads(record, recorded_at)
            existing = self._revocation(authority, recorded_at)
            if existing is not None:
                if existing.revocation.reason != command.reason:
                    raise OwnerTenantAuthorityV3Conflict("revocation replay changed reason")
                return existing.revocation
            revocation = OwnerTenantAuthorityV3Revocation(
                authority_content_hash=authority.content_hash,
                policy_content_hash=authority.policy.content_hash,
                revoked_by=self._actor(second.authority, REVOKER_ROLE),
                revoked_at=cutoff,
                recorded_at=recorded_at,
                reason=command.reason,
            )
            try:
                validate_owner_tenant_authority_v3_revocation(authority, revocation)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Corruption(
                    "authority revocation candidate is invalid"
                ) from error
            candidate = PersistedOwnerTenantAuthorityV3Revocation(revocation, second.authority)
            persisted = self._repository.append_revocation(
                candidate,
                expected_authority_content_hash=authority.content_hash,
                recorded_at=recorded_at,
            )
            checked = self._revocation_record(persisted)
            if checked != candidate:
                raise OwnerTenantAuthorityV3Conflict("authority revocation first winner differs")
            return checked.revocation

    def _now(self) -> datetime:
        """Read and validate the repository's authoritative clock."""

        try:
            return validate_owner_v3_time(self._repository.now())
        except ValueError as error:
            raise OwnerTenantAuthorityV3Corruption("repository clock is invalid") from error

    def _winner(
        self,
        authority_id: str,
        authority_version: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Restore one exact first winner without historical fallback."""

        result = self._repository.get_winner(
            authority_id=authority_id,
            authority_version=authority_version,
            as_of=as_of,
        )
        if result is None:
            return None
        checked = self._record(result)
        authority = checked.authority
        if (
            authority.authority_id,
            authority.authority_version,
            authority.recorded_at <= as_of,
        ) != (authority_id, authority_version, True):
            raise OwnerTenantAuthorityV3Corruption(
                "authority winner selector or clock was substituted"
            )
        return checked

    def _selected(
        self,
        command: (
            GetCurrentOwnerTenantAuthorityV3Command
            | GetExactOwnerTenantAuthorityV3Command
            | RevokeOwnerTenantAuthorityV3Command
        ),
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Select a winner and enforce its exact content hash."""

        record = self._winner(command.authority_id, command.authority_version, as_of)
        if record is not None and record.authority.content_hash != command.expected_content_hash:
            raise OwnerTenantAuthorityV3Conflict("authority content hash differs")
        return record

    def _record(self, value: object) -> PersistedOwnerTenantAuthorityV3:
        """Restore and validate one exact persisted authority envelope."""

        if type(value) is not PersistedOwnerTenantAuthorityV3:
            raise OwnerTenantAuthorityV3Corruption("authority record type substitution")
        record = value
        try:
            record.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption("authority record is corrupt") from error
        return record

    def _revocation_record(
        self,
        value: object,
    ) -> PersistedOwnerTenantAuthorityV3Revocation:
        """Restore and validate one exact persisted revocation envelope."""

        if type(value) is not PersistedOwnerTenantAuthorityV3Revocation:
            raise OwnerTenantAuthorityV3Corruption("revocation record type substitution")
        record = value
        try:
            record.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption("revocation record is corrupt") from error
        return record

    def _history(self, authority: OwnerTenantAuthorityV3) -> None:
        """Recheck the complete exact Evidence V5 graph at the authority record clock."""

        try:
            result = self._historical_assignments.execute(
                GetExactAccountOwnerAssignmentEvidenceV5Command(
                    authority.assignment_evidence_id,
                    authority.assignment_evidence_version,
                    authority.assignment_evidence_content_hash,
                    authority.recorded_at,
                )
            )
        except AccountOwnerAssignmentEvidenceV5Unavailable as error:
            raise OwnerTenantAuthorityV3Corruption(
                "historical Evidence V5 is unavailable"
            ) from error
        except AccountOwnerAssignmentEvidenceV5Conflict as error:
            raise OwnerTenantAuthorityV3Corruption("historical Evidence V5 conflicts") from error
        except AccountOwnerAssignmentEvidenceV5Corruption as error:
            raise OwnerTenantAuthorityV3Corruption("historical Evidence V5 is corrupt") from error
        if type(result) is not AccountOwnerAssignmentEvidenceV5 or result != authority.assignment:
            raise OwnerTenantAuthorityV3Corruption(
                "historical Evidence V5 is missing or substituted"
            )
        try:
            result.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption("historical Evidence V5 is corrupt") from error
        if not result.is_knowable_at(authority.recorded_at):
            raise OwnerTenantAuthorityV3Corruption("historical Evidence V5 is not knowable")

    def _current_assignment(
        self,
        command: IssueOwnerTenantAuthorityV3Command,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV5:
        """Read one exact current Evidence V5 through the public Application port."""

        try:
            result = self._current_assignments.execute(
                GetCurrentAccountOwnerAssignmentEvidenceV5Command(
                    command.assignment_evidence_id,
                    command.assignment_evidence_version,
                    command.expected_assignment_evidence_content_hash,
                    as_of,
                )
            )
        except AccountOwnerAssignmentEvidenceV5Unavailable as error:
            raise OwnerTenantAuthorityV3Unavailable("current Evidence V5 is unavailable") from error
        except AccountOwnerAssignmentEvidenceV5Conflict as error:
            raise OwnerTenantAuthorityV3Conflict("current Evidence V5 conflicts") from error
        except AccountOwnerAssignmentEvidenceV5Corruption as error:
            raise OwnerTenantAuthorityV3Corruption("current Evidence V5 is corrupt") from error
        if result is None:
            raise OwnerTenantAuthorityV3Unavailable("current Evidence V5 is unavailable")
        if type(result) is not AccountOwnerAssignmentEvidenceV5:
            raise OwnerTenantAuthorityV3Corruption("Evidence V5 type substitution")
        try:
            result.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption("Evidence V5 is corrupt") from error
        if (
            result.evidence_id,
            result.evidence_version,
            result.content_hash,
        ) != (
            command.assignment_evidence_id,
            command.assignment_evidence_version,
            command.expected_assignment_evidence_content_hash,
        ):
            raise OwnerTenantAuthorityV3Corruption("Evidence V5 selector substitution")
        if not result.is_current_at(as_of):
            raise OwnerTenantAuthorityV3Unavailable("Evidence V5 is not current")
        return result

    def _authority_assignment(
        self,
        authority: OwnerTenantAuthorityV3,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV5:
        """Re-read the exact current Evidence V5 sealed by one authority."""

        assignment = self._current_assignment(
            IssueOwnerTenantAuthorityV3Command(
                authority.authority_id,
                authority.authority_version,
                authority.assignment_evidence_id,
                authority.assignment_evidence_version,
                authority.assignment_evidence_content_hash,
            ),
            as_of,
        )
        if assignment != authority.assignment:
            raise OwnerTenantAuthorityV3Corruption(
                "current Evidence V5 differs from the sealed authority assignment"
            )
        return assignment

    def _inputs(
        self,
        command: IssueOwnerTenantAuthorityV3Command,
        as_of: datetime,
    ) -> _Inputs:
        """Read current Evidence V5 and current policy/authentication at one cutoff."""

        assignment = self._current_assignment(command, as_of)
        participants = self._participants_at(as_of)
        if participants.policy != assignment.policy or participants.claimant != assignment.claimant:
            raise OwnerTenantAuthorityV3Corruption(
                "Evidence V5 and current participant scope differ"
            )
        return _Inputs(assignment, participants)

    def _participants_at(self, as_of: datetime) -> CurrentSingleOwnerParticipants:
        """Validate current policy, actor authority, roles, and finite validity."""

        cutoff = _aware(as_of, "as_of")
        try:
            value = self._participants.get_current(as_of=cutoff)
        except OwnerTenantAuthorityV3Unavailable:
            raise
        except OwnerTenantAuthorityV3Corruption:
            raise
        except (AttributeError, TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption(
                "current participant projection is corrupt"
            ) from error
        if value is None:
            raise OwnerTenantAuthorityV3Unavailable(
                "current owner/tenant policy and actor are unavailable"
            )
        if type(value) is not CurrentSingleOwnerParticipants:
            raise OwnerTenantAuthorityV3Corruption("participant type substitution")
        participants = value
        try:
            policy = participants.policy
            authority = participants.authority
            claimant = participants.claimant
            approver = participants.approver
            if type(policy) is not SingleOwnerAuthorityPolicyV1:
                raise TypeError("policy type substitution")
            if type(authority) is not CurrentAccountActorAuthorityV3:
                raise TypeError("authority type substitution")
            if type(claimant) is not AccountOwnerAssignmentActor:
                raise TypeError("claimant type substitution")
            if type(approver) is not AccountOwnerAssignmentActor:
                raise TypeError("approver type substitution")
            policy.__post_init__()
            authority.__post_init__()
            claimant.__post_init__()
            approver.__post_init__()
            observed_at = validate_owner_v3_time(participants.observed_at)
            valid_until = validate_owner_v3_time(participants.valid_until)
            if observed_at != cutoff:
                raise ValueError("participant observation clock substitution")
            if not policy.is_current_at(cutoff):
                raise LookupError("current policy is unavailable")
            validate_single_owner_participants(policy, claimant, approver, cutoff)
            try:
                validate_owner_v3_authentication(authority, claimant, cutoff)
                validate_owner_v3_authentication(authority, approver, cutoff)
            except ValueError as error:
                raise LookupError("current owner authentication is unavailable") from error
            if not cutoff < valid_until <= min(policy.valid_until, authority.valid_until):
                raise LookupError("participant validity is unavailable")
        except LookupError as error:
            raise OwnerTenantAuthorityV3Unavailable(str(error)) from error
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption(
                "current participant projection is corrupt"
            ) from error
        return participants

    def _authority_participants(
        self,
        authority: OwnerTenantAuthorityV3,
        as_of: datetime,
    ) -> CurrentSingleOwnerParticipants:
        """Read current policy/authentication and bind both to one Authority V3 owner."""

        participants = self._participants_at(as_of)
        if (
            participants.policy != authority.policy
            or participants.claimant.actor_id != authority.actor_id
            or participants.claimant.user_id != authority.actor_user_id
        ):
            raise OwnerTenantAuthorityV3Corruption(
                "current authority policy or owner actor was substituted"
            )
        try:
            validate_owner_v3_authentication(
                participants.authority,
                authority.approved_by,
                as_of,
            )
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "current authority actor is unavailable"
            ) from error
        return participants

    @staticmethod
    def _same_inputs(first: _Inputs, second: _Inputs) -> bool:
        """Compare sealed Evidence/policy/auth facts while allowing cutoff advancement."""

        return (
            first.assignment,
            first.participants.policy,
            first.participants.authority,
            first.participants.claimant,
            first.participants.approver,
            first.participants.valid_until,
        ) == (
            second.assignment,
            second.participants.policy,
            second.participants.authority,
            second.participants.claimant,
            second.participants.approver,
            second.participants.valid_until,
        )

    @staticmethod
    def _same_participants(
        first: CurrentSingleOwnerParticipants,
        second: CurrentSingleOwnerParticipants,
    ) -> bool:
        """Compare current policy/authentication facts across two re-reads."""

        return (
            first.policy,
            first.authority,
            first.claimant,
            first.approver,
            first.valid_until,
        ) == (
            second.policy,
            second.authority,
            second.claimant,
            second.approver,
            second.valid_until,
        )

    def _candidate(
        self,
        *,
        authority_id: str,
        authority_version: str,
        assignment: AccountOwnerAssignmentEvidenceV5,
        participants: CurrentSingleOwnerParticipants,
        approved_at: datetime,
        recorded_at: datetime,
        predecessor_hash: str | None,
    ) -> OwnerTenantAuthorityV3:
        """Build an Authority V3 value from exact current V5 and participant facts."""

        return OwnerTenantAuthorityV3(
            authority_id=authority_id,
            authority_version=authority_version,
            assignment=assignment,
            policy=participants.policy,
            approved_by=self._actor(participants.authority, APPROVER_ROLE),
            approved_at=approved_at,
            recorded_at=recorded_at,
            valid_until=min(approved_at + self._validity_period, participants.policy.valid_until),
            supersedes_content_hash=predecessor_hash,
        )

    def _empty_slots(
        self,
        authority_id: str,
        assignment_hash: str,
        as_of: datetime,
    ) -> None:
        """Keep expired roots and assignment mappings occupied forever."""

        if self._repository.get_head(authority_id=authority_id, as_of=as_of) is not None:
            raise OwnerTenantAuthorityV3Conflict("authority chain already has a root")
        if (
            self._repository.get_assignment_head(
                assignment_content_hash=assignment_hash,
                as_of=as_of,
            )
            is not None
        ):
            raise OwnerTenantAuthorityV3Conflict("authority assignment slot is already occupied")

    def _heads(
        self,
        record: PersistedOwnerTenantAuthorityV3,
        as_of: datetime,
    ) -> None:
        """Require the exact record to remain the final logical chain head."""

        current = self._repository.get_head(
            authority_id=record.authority.authority_id,
            as_of=as_of,
        )
        if current is None or self._record(current) != record:
            raise OwnerTenantAuthorityV3Conflict("authority is not the exact logical head")

    def _revocation(
        self,
        authority: OwnerTenantAuthorityV3,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Restore and bind a known revocation before denying current access."""

        value = self._repository.get_revocation(
            authority_content_hash=authority.content_hash,
            as_of=as_of,
        )
        if value is None:
            return None
        record = self._revocation_record(value)
        try:
            validate_owner_tenant_authority_v3_revocation(authority, record.revocation)
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Corruption(
                "authority revocation binding is corrupt"
            ) from error
        if not record.revocation.is_effective_at(as_of):
            raise OwnerTenantAuthorityV3Corruption("authority revocation clock was substituted")
        return record

    def _current(
        self,
        record: PersistedOwnerTenantAuthorityV3,
        cutoff: datetime,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Return a finite current observation only after two policy/auth reads."""

        authority = record.authority
        self._history(authority)
        if not authority.is_current_at(cutoff) or self._revocation(authority, cutoff) is not None:
            return None
        try:
            self._heads(record, cutoff)
            first_assignment = self._authority_assignment(authority, cutoff)
            first = self._authority_participants(authority, cutoff)
            second_cutoff = self._now()
            if second_cutoff < cutoff:
                raise OwnerTenantAuthorityV3Corruption("authority repository clock moved backwards")
            second_assignment = self._authority_assignment(authority, second_cutoff)
            second = self._authority_participants(authority, second_cutoff)
            if first_assignment != second_assignment or not self._same_participants(first, second):
                raise OwnerTenantAuthorityV3Conflict("current authority sources changed")
            observed_at = self._now()
            if observed_at < second_cutoff:
                raise OwnerTenantAuthorityV3Corruption("authority repository clock moved backwards")
            self._heads(record, observed_at)
            if self._authority_assignment(authority, observed_at) != second_assignment:
                raise OwnerTenantAuthorityV3Conflict("current authority sources changed")
            if (
                not authority.is_current_at(observed_at)
                or self._revocation(authority, observed_at) is not None
            ):
                return None
            return CurrentOwnerTenantAuthorityV3(
                authority=authority,
                authentication=second.authority,
                observed_at=observed_at,
                valid_until=min(
                    authority.valid_until,
                    authority.assignment.valid_until,
                    authority.policy.valid_until,
                    second.authority.valid_until,
                    second.valid_until,
                ),
            )
        except (OwnerTenantAuthorityV3Unavailable, OwnerTenantAuthorityV3Conflict, ValueError):
            return None

    @staticmethod
    def _actor(
        authentication: CurrentAccountActorAuthorityV3,
        role: str,
    ) -> AccountOwnerAssignmentActor:
        """Project one explicit Authority V3 operation role from real auth facts."""

        return AccountOwnerAssignmentActor(
            actor_id=authentication.actor_id,
            user_id=authentication.user_id,
            role=role,
            kind="human",
            is_staff=authentication.is_staff,
        )

    @staticmethod
    def _root_matches(
        authority: OwnerTenantAuthorityV3,
        command: IssueOwnerTenantAuthorityV3Command,
    ) -> bool:
        """Compare a replay candidate with the exact active root identity."""

        return (
            authority.authority_id,
            authority.authority_version,
            authority.assignment_evidence_id,
            authority.assignment_evidence_version,
            authority.assignment_evidence_content_hash,
            authority.supersedes_content_hash,
            authority.status,
        ) == (
            command.authority_id,
            command.authority_version,
            command.assignment_evidence_id,
            command.assignment_evidence_version,
            command.expected_assignment_evidence_content_hash,
            None,
            "active",
        )

    @staticmethod
    def _successor_matches(
        authority: OwnerTenantAuthorityV3,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> bool:
        """Compare a replay candidate with the exact predecessor and V5 selectors."""

        return (
            authority.authority_id,
            authority.authority_version,
            authority.assignment_evidence_id,
            authority.assignment_evidence_version,
            authority.assignment_evidence_content_hash,
            authority.supersedes_content_hash,
            authority.status,
        ) == (
            command.authority_id,
            command.authority_version,
            command.assignment_evidence_id,
            command.assignment_evidence_version,
            command.expected_assignment_evidence_content_hash,
            command.expected_predecessor_content_hash,
            "active",
        )


class IssueOwnerTenantAuthorityV3:
    """Expose the root issue operation as a dedicated Application use case."""

    def __init__(self, service: OwnerTenantAuthorityV3Service) -> None:
        """Inject the lifecycle service."""

        self._service = service

    def execute(self, command: IssueOwnerTenantAuthorityV3Command) -> OwnerTenantAuthorityV3:
        """Issue or replay one Authority V3 root."""

        return self._service.issue(command)


class SupersedeOwnerTenantAuthorityV3:
    """Expose the active successor operation as a dedicated Application use case."""

    def __init__(self, service: OwnerTenantAuthorityV3Service) -> None:
        """Inject the lifecycle service."""

        self._service = service

    def execute(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Append or replay one Authority V3 successor."""

        return self._service.successor(command)


class GetExactOwnerTenantAuthorityV3:
    """Expose exact historical Authority V3 reads as a dedicated use case."""

    def __init__(self, service: OwnerTenantAuthorityV3Service) -> None:
        """Inject the lifecycle service."""

        self._service = service

    def execute(
        self,
        command: GetExactOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3 | None:
        """Return one exact historical Authority V3."""

        return self._service.get_exact(command)


class GetCurrentOwnerTenantAuthorityV3:
    """Expose current Authority V3 reads as a dedicated use case."""

    def __init__(self, service: OwnerTenantAuthorityV3Service) -> None:
        """Inject the lifecycle service."""

        self._service = service

    def execute(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Return one finite current Authority V3 observation."""

        return self._service.get_current(command)


class RevokeOwnerTenantAuthorityV3:
    """Expose explicit immutable Authority V3 revocation as a dedicated use case."""

    def __init__(self, service: OwnerTenantAuthorityV3Service) -> None:
        """Inject the lifecycle service."""

        self._service = service

    def execute(
        self,
        command: RevokeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3Revocation:
        """Append or replay one Authority V3 revocation."""

        return self._service.revoke(command)


__all__ = [
    "GetCurrentOwnerTenantAuthorityV3",
    "GetCurrentOwnerTenantAuthorityV3Command",
    "GetExactOwnerTenantAuthorityV3",
    "GetExactOwnerTenantAuthorityV3Command",
    "IssueOwnerTenantAuthorityV3",
    "IssueOwnerTenantAuthorityV3Command",
    "IssueOwnerTenantAuthorityV3SuccessorCommand",
    "OwnerTenantAuthorityV3Service",
    "RevokeOwnerTenantAuthorityV3",
    "RevokeOwnerTenantAuthorityV3Command",
    "SuccessorOwnerTenantAuthorityV3Command",
    "SupersedeOwnerTenantAuthorityV3",
    "SupersedeOwnerTenantAuthorityV3Command",
]
