"""Explicit decision approval/revocation and freshly authenticated owner reads."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    GetExactAccountOwnerAssignmentEvidenceV4Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    CurrentSingleOwnerParticipantsReader,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    CurrentOwnerAssignmentV4Reader,
    CurrentOwnerPhysicalRow,
    CurrentOwnerPhysicalRowReader,
    HistoricalOwnerAssignmentV4Reader,
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Repository,
    OwnerTenantAuthorityV2Unavailable,
    PersistedOwnerTenantAuthorityV2,
    PersistedOwnerTenantAuthorityV2Revocation,
    validate_owner_v2_authentication,
    validate_owner_v2_time,
)
from apps.account.application.single_owner_actor_authority import CurrentSingleOwnerParticipants
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    APPROVER_ROLE,
    REVOKER_ROLE,
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
    validate_owner_tenant_authority_v2_revocation,
)
from apps.account.domain.single_owner_authority_policy_v1 import validate_single_owner_participants


def _token(value: object) -> None:
    """Require one exact bounded selector or reason token."""
    if type(value) is not str or not value or len(value) > 192 or any(c.isspace() for c in value):
        raise ValueError("owner v2 selector must be a bounded canonical token")


def _digest(value: object) -> None:
    """Require a complete lowercase SHA-256 selector."""
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("owner v2 hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class IssueOwnerTenantAuthorityV2Command:
    """Approve a selected current assignment; scope, policy and clocks stay server-owned."""

    authority_id: str
    authority_version: str
    assignment_evidence_id: str
    assignment_evidence_version: str
    expected_assignment_evidence_content_hash: str

    def __post_init__(self) -> None:
        """Validate closed immutable selectors before opening a transaction."""
        for value in (
            self.authority_id,
            self.authority_version,
            self.assignment_evidence_id,
            self.assignment_evidence_version,
        ):
            _token(value)
        _digest(self.expected_assignment_evidence_content_hash)


@dataclass(frozen=True, slots=True)
class GetCurrentOwnerTenantAuthorityV2Command:
    """Select a decision for a live request; callers cannot choose a historical clock."""

    authority_id: str
    authority_version: str
    expected_content_hash: str

    def __post_init__(self) -> None:
        """Validate the exact decision selector."""
        _token(self.authority_id)
        _token(self.authority_version)
        _digest(self.expected_content_hash)


@dataclass(frozen=True, slots=True)
class GetExactOwnerTenantAuthorityV2Command(GetCurrentOwnerTenantAuthorityV2Command):
    """Read historical evidence only; this operation grants no current scope."""

    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact selector and the explicit historical cutoff."""
        GetCurrentOwnerTenantAuthorityV2Command.__post_init__(self)
        validate_owner_v2_time(self.as_of)


@dataclass(frozen=True, slots=True)
class RevokeOwnerTenantAuthorityV2Command(GetCurrentOwnerTenantAuthorityV2Command):
    """Explicitly revoke an exact decision, including an already expired decision."""

    reason: str

    def __post_init__(self) -> None:
        """Validate the exact target and stable reason used for replay."""
        GetCurrentOwnerTenantAuthorityV2Command.__post_init__(self)
        _token(self.reason)


def validate_owner_v2_physical(
    assignment: AccountOwnerAssignmentEvidenceV4,
    row: CurrentOwnerPhysicalRow,
    as_of: datetime,
) -> None:
    """Match live ownership to immutable creation identity without reusing its expired TTL."""
    if type(row) is not CurrentOwnerPhysicalRow:
        raise TypeError("live physical row type substitution")
    row.__post_init__()
    physical = assignment.subject.physical_root.physical_observation
    if (
        row.namespace != physical.underlying_unified_account_namespace
        or row.row_pk != physical.underlying_unified_account_id
        or row.user_id != physical.row_user_id
        or row.user_id != assignment.assigned_owner_user_id
        or row.raw_account_type != physical.raw_account_type
        or row.is_active is not True
        or row.row_created_at != physical.row_created_at
        or row.row_updated_at < physical.row_updated_at
        or row.observed_at > validate_owner_v2_time(as_of)
    ):
        raise ValueError("live physical ownership does not match the sealed creation")


@dataclass(frozen=True, slots=True)
class CurrentOwnerTenantAuthorityV2:
    """A request-bound read observation capped by fresh authentication, not a new decision."""

    authority: OwnerTenantAuthorityV2
    authentication: CurrentAccountActorAuthorityV3
    physical: CurrentOwnerPhysicalRow
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Keep the live observation finite and bound to the exact decision owner."""
        if type(self.authority) is not OwnerTenantAuthorityV2:
            raise TypeError("authority must be exact OwnerTenantAuthorityV2")
        self.authority.__post_init__()
        validate_owner_v2_time(self.observed_at)
        validate_owner_v2_time(self.valid_until)
        validate_owner_v2_authentication(
            self.authentication, self.authority.approved_by, self.observed_at
        )
        validate_owner_v2_physical(self.authority.assignment, self.physical, self.observed_at)
        if not self.authority.is_current_at(
            self.observed_at
        ) or not self.observed_at < self.valid_until <= min(
            self.authority.valid_until,
            self.authority.policy.valid_until,
            self.authentication.valid_until,
        ):
            raise ValueError("current owner observation exceeds its exact source validity")


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Keep two independent source reads comparable without freezing read time."""

    participants: CurrentSingleOwnerParticipants
    physical: CurrentOwnerPhysicalRow


class OwnerTenantAuthorityV2Service:
    """Orchestrate explicit decisions with injected durable and locked live sources."""

    def __init__(
        self,
        *,
        repository: OwnerTenantAuthorityV2Repository,
        current_assignments: CurrentOwnerAssignmentV4Reader,
        historical_assignments: HistoricalOwnerAssignmentV4Reader,
        participants: CurrentSingleOwnerParticipantsReader,
        physical: CurrentOwnerPhysicalRowReader,
        validity_period: timedelta,
    ) -> None:
        """Bind one transaction identity and explicit server-owned decision lifetime."""
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("decision validity_period must be an exact positive timedelta")
        _token(repository.unit_of_work_key)
        if repository.unit_of_work_key != physical.unit_of_work_key:
            raise OwnerTenantAuthorityV2Unavailable(
                "physical and decision transaction aliases differ"
            )
        self._repository = repository
        self._current_assignments = current_assignments
        self._historical_assignments = historical_assignments
        self._participants = participants
        self._physical = physical
        self._validity_period = validity_period

    def issue(self, command: IssueOwnerTenantAuthorityV2Command) -> OwnerTenantAuthorityV2:
        """Explicitly approve a first root, or revalidate and return its immutable winner."""
        if type(command) is not IssueOwnerTenantAuthorityV2Command:
            raise TypeError("expected exact issue command")
        command.__post_init__()
        with self._repository.atomic():
            start = self._now()
            winner = self._winner(command.authority_id, command.authority_version, start)
            if winner is not None:
                assignment = winner.authority.assignment
                if (
                    assignment.evidence_id,
                    assignment.evidence_version,
                    assignment.content_hash,
                ) != (
                    command.assignment_evidence_id,
                    command.assignment_evidence_version,
                    command.expected_assignment_evidence_content_hash,
                ):
                    raise OwnerTenantAuthorityV2Conflict("issue replay changed assignment selector")
                if self._current(winner, start) is None:
                    raise OwnerTenantAuthorityV2Conflict("decision replay is no longer current")
                return winner.authority
            assignment = self._current_assignment(command, start)
            self._empty_slots(command.authority_id, assignment.content_hash, start)
            first = self._inputs(assignment, start)
            second_cutoff = self._now()
            if self._current_assignment(command, second_cutoff) != assignment:
                raise OwnerTenantAuthorityV2Conflict("assignment changed during approval")
            second = self._inputs(assignment, second_cutoff)
            try:
                confirmed = self._current_assignment(command, self._now())
            except OwnerTenantAuthorityV2Unavailable as error:
                raise OwnerTenantAuthorityV2Conflict(
                    "assignment ceased to be current before recording"
                ) from error
            if confirmed != assignment:
                raise OwnerTenantAuthorityV2Conflict("assignment changed before recording")
            recorded_at = self._now()
            self._finish(assignment, first, second, recorded_at)
            if not assignment.is_current_at(recorded_at):
                raise OwnerTenantAuthorityV2Unavailable(
                    "assignment expired before decision recording"
                )
            self._empty_slots(command.authority_id, assignment.content_hash, recorded_at)
            value = OwnerTenantAuthorityV2(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                assignment=assignment,
                policy=second.participants.policy,
                approved_by=self._actor(second.participants.authority, APPROVER_ROLE),
                approved_at=start,
                recorded_at=recorded_at,
                valid_until=min(start + self._validity_period, assignment.policy.valid_until),
            )
            record = PersistedOwnerTenantAuthorityV2(value, second.participants.authority)
            result = self._repository.append_root(record, recorded_at=recorded_at)
            if result != record:
                raise OwnerTenantAuthorityV2Corruption(
                    "decision append returned a substituted winner"
                )
            return value

    def get_exact(
        self, command: GetExactOwnerTenantAuthorityV2Command
    ) -> OwnerTenantAuthorityV2 | None:
        """Read an exact historical decision and provenance without granting current access."""
        if type(command) is not GetExactOwnerTenantAuthorityV2Command:
            raise TypeError("expected exact historical read command")
        command.__post_init__()
        with self._repository.atomic():
            record = self._selected(command, command.as_of)
            if record is None:
                return None
            self._history(record.authority)
            return record.authority

    def get_current(
        self, command: GetCurrentOwnerTenantAuthorityV2Command
    ) -> CurrentOwnerTenantAuthorityV2 | None:
        """Revalidate durable decision, policy, fresh authentication and live physical owner."""
        if type(command) is not GetCurrentOwnerTenantAuthorityV2Command:
            raise TypeError("expected exact live read command")
        command.__post_init__()
        with self._repository.atomic():
            start = self._now()
            record = self._selected(command, start)
            if record is None:
                return None
            return self._current(record, start)

    def revoke(
        self, command: RevokeOwnerTenantAuthorityV2Command
    ) -> OwnerTenantAuthorityV2Revocation:
        """Explicitly append or replay revocation without requiring an unexpired decision."""
        if type(command) is not RevokeOwnerTenantAuthorityV2Command:
            raise TypeError("expected exact revoke command")
        command.__post_init__()
        with self._repository.atomic():
            start = self._now()
            record = self._selected(command, start)
            if record is None:
                raise OwnerTenantAuthorityV2Unavailable("exact decision is unavailable")
            value = record.authority
            self._history(value)
            first = self._people(value.assignment, start)
            second = self._people(value.assignment, self._now())
            recorded_at = self._now()
            if not self._same_people(first, second):
                raise OwnerTenantAuthorityV2Conflict("authentication changed during revocation")
            validate_owner_v2_authentication(second.authority, value.approved_by, recorded_at)
            if (
                recorded_at < start
                or not second.policy.is_current_at(recorded_at)
                or recorded_at >= second.valid_until
            ):
                raise OwnerTenantAuthorityV2Unavailable("policy expired during revocation")
            self._heads(record, recorded_at)
            existing = self._revocation(value, recorded_at)
            if existing is not None:
                if existing.revocation.reason != command.reason:
                    raise OwnerTenantAuthorityV2Conflict("revocation replay changed reason")
                return existing.revocation
            revocation = OwnerTenantAuthorityV2Revocation(
                authority_content_hash=value.content_hash,
                policy_content_hash=value.policy.content_hash,
                revoked_by=self._actor(second.authority, REVOKER_ROLE),
                revoked_at=start,
                recorded_at=recorded_at,
                reason=command.reason,
            )
            validate_owner_tenant_authority_v2_revocation(value, revocation)
            candidate = PersistedOwnerTenantAuthorityV2Revocation(revocation, second.authority)
            result = self._repository.append_revocation(
                candidate,
                expected_authority_content_hash=value.content_hash,
                recorded_at=recorded_at,
            )
            if result != candidate:
                raise OwnerTenantAuthorityV2Corruption(
                    "revocation append returned a substituted winner"
                )
            return revocation

    def _now(self) -> datetime:
        """Validate the injected authoritative clock."""
        return validate_owner_v2_time(self._repository.now())

    def _winner(
        self, authority_id: str, authority_version: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Validate exact identity, record type and knowability of a stored winner."""
        result = self._repository.get_winner(
            authority_id=authority_id, authority_version=authority_version, as_of=as_of
        )
        if result is None:
            return None
        if type(result) is not PersistedOwnerTenantAuthorityV2:
            raise OwnerTenantAuthorityV2Corruption("decision record type substitution")
        result.__post_init__()
        value = result.authority
        if (value.authority_id, value.authority_version) != (
            authority_id,
            authority_version,
        ) or value.recorded_at > as_of:
            raise OwnerTenantAuthorityV2Corruption("decision selector or source clock substitution")
        return result

    def _selected(
        self, command: GetCurrentOwnerTenantAuthorityV2Command, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Select the exact sealed winner with no current fallback."""
        record = self._winner(command.authority_id, command.authority_version, as_of)
        if record is not None and record.authority.content_hash != command.expected_content_hash:
            raise OwnerTenantAuthorityV2Conflict("decision content hash differs")
        return record

    def _history(self, value: OwnerTenantAuthorityV2) -> None:
        """Recheck complete durable assignment at the original decision time only."""
        assignment = value.assignment
        result = self._historical_assignments.execute(
            GetExactAccountOwnerAssignmentEvidenceV4Command(
                assignment.evidence_id,
                assignment.evidence_version,
                assignment.content_hash,
                value.recorded_at,
            )
        )
        if type(result) is not AccountOwnerAssignmentEvidenceV4 or result != assignment:
            raise OwnerTenantAuthorityV2Corruption(
                "historical assignment is missing or substituted"
            )
        result.__post_init__()

    def _current_assignment(
        self, command: IssueOwnerTenantAuthorityV2Command, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV4:
        """Require exact current assignment for initial approval only."""
        result = self._current_assignments.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV4Command(
                command.assignment_evidence_id,
                command.assignment_evidence_version,
                command.expected_assignment_evidence_content_hash,
                as_of,
            )
        )
        if result is None:
            raise OwnerTenantAuthorityV2Unavailable("current assignment is unavailable")
        if type(result) is not AccountOwnerAssignmentEvidenceV4:
            raise OwnerTenantAuthorityV2Corruption("assignment type substitution")
        result.__post_init__()
        if (result.evidence_id, result.evidence_version, result.content_hash) != (
            command.assignment_evidence_id,
            command.assignment_evidence_version,
            command.expected_assignment_evidence_content_hash,
        ):
            raise OwnerTenantAuthorityV2Corruption("assignment selector substitution")
        if not result.is_current_at(as_of):
            raise OwnerTenantAuthorityV2Unavailable("assignment has expired")
        return result

    def _people(
        self, assignment: AccountOwnerAssignmentEvidenceV4, as_of: datetime
    ) -> CurrentSingleOwnerParticipants:
        """Revalidate the exact selected policy and real stable owner under fresh authentication."""
        result = self._participants.get_current(as_of=as_of)
        if result is None:
            raise OwnerTenantAuthorityV2Unavailable("current owner participants unavailable")
        if type(result) is not CurrentSingleOwnerParticipants:
            raise OwnerTenantAuthorityV2Corruption("participant type substitution")
        validate_single_owner_participants(result.policy, result.claimant, result.approver, as_of)
        validate_owner_v2_authentication(result.authority, assignment.claimant, as_of)
        if (
            result.policy != assignment.policy
            or result.claimant != assignment.claimant
            or result.observed_at != as_of
        ):
            raise OwnerTenantAuthorityV2Corruption(
                "participant policy, owner or observation substitution"
            )
        if validate_owner_v2_time(result.valid_until) > min(
            result.policy.valid_until, result.authority.valid_until
        ):
            raise OwnerTenantAuthorityV2Corruption("participant validity substitution")
        if result.valid_until <= as_of:
            raise OwnerTenantAuthorityV2Unavailable("participant authentication window expired")
        return result

    def _inputs(self, assignment: AccountOwnerAssignmentEvidenceV4, as_of: datetime) -> _Inputs:
        """Read fresh participants and retain the exact physical row lock."""
        people = self._people(assignment, as_of)
        physical = assignment.subject.physical_root.physical_observation
        row = self._physical.read_locked(
            namespace=physical.underlying_unified_account_namespace,
            row_pk=physical.underlying_unified_account_id,
        )
        if row is None:
            raise OwnerTenantAuthorityV2Unavailable("live physical row is missing")
        if type(row) is not CurrentOwnerPhysicalRow:
            raise OwnerTenantAuthorityV2Corruption("physical row type substitution")
        row.__post_init__()
        if row.observed_at < as_of:
            raise OwnerTenantAuthorityV2Unavailable("physical observation predates this read")
        return _Inputs(people, row)

    @staticmethod
    def _same_people(
        first: CurrentSingleOwnerParticipants, second: CurrentSingleOwnerParticipants
    ) -> bool:
        """Compare sealed source facts while allowing actual observation cutoff to advance."""
        return (
            first.policy,
            first.authority,
            first.claimant,
            first.approver,
            first.valid_until,
        ) == (second.policy, second.authority, second.claimant, second.approver, second.valid_until)

    def _finish(
        self,
        assignment: AccountOwnerAssignmentEvidenceV4,
        first: _Inputs,
        second: _Inputs,
        as_of: datetime,
    ) -> None:
        """Validate both live observations at the final recording clock under retained locks."""
        if not self._same_people(first.participants, second.participants):
            raise OwnerTenantAuthorityV2Conflict("owner sources changed during revalidation")
        for inputs in (first, second):
            validate_owner_v2_physical(assignment, inputs.physical, as_of)
            validate_owner_v2_authentication(
                inputs.participants.authority, assignment.claimant, as_of
            )
            if (
                not inputs.participants.policy.is_current_at(as_of)
                or as_of >= inputs.participants.valid_until
            ):
                raise OwnerTenantAuthorityV2Unavailable("policy expired during revalidation")
        if first.physical.row_updated_at != second.physical.row_updated_at:
            raise OwnerTenantAuthorityV2Conflict("physical row changed during revalidation")

    def _empty_slots(self, authority_id: str, assignment_hash: str, as_of: datetime) -> None:
        """Never release an expired decision slot for a second root."""
        if (
            self._repository.get_head(authority_id=authority_id, as_of=as_of) is not None
            or self._repository.get_assignment_head(
                assignment_content_hash=assignment_hash, as_of=as_of
            )
            is not None
        ):
            raise OwnerTenantAuthorityV2Conflict("decision root slot is already occupied")

    def _heads(self, record: PersistedOwnerTenantAuthorityV2, as_of: datetime) -> None:
        """Require both logical root indexes to identify this exact durable record."""
        value = record.authority
        if (
            self._repository.get_head(authority_id=value.authority_id, as_of=as_of) != record
            or self._repository.get_assignment_head(
                assignment_content_hash=value.assignment.content_hash, as_of=as_of
            )
            != record
        ):
            raise OwnerTenantAuthorityV2Conflict("decision is not the exact logical root")

    def _revocation(
        self, value: OwnerTenantAuthorityV2, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2Revocation | None:
        """Validate a known revocation before treating it as an effective denial."""
        record = self._repository.get_revocation(
            authority_content_hash=value.content_hash, as_of=as_of
        )
        if record is not None:
            if type(record) is not PersistedOwnerTenantAuthorityV2Revocation:
                raise OwnerTenantAuthorityV2Corruption("revocation record type substitution")
            record.__post_init__()
            validate_owner_tenant_authority_v2_revocation(value, record.revocation)
            if not record.revocation.is_effective_at(as_of):
                raise OwnerTenantAuthorityV2Corruption("revocation future source substitution")
        return record

    def _current(
        self, record: PersistedOwnerTenantAuthorityV2, start: datetime
    ) -> CurrentOwnerTenantAuthorityV2 | None:
        """Keep historical approval distinct from all current request gates."""
        value = record.authority
        self._history(value)
        if not value.is_current_at(start) or self._revocation(value, start) is not None:
            return None
        try:
            self._heads(record, start)
            first = self._inputs(value.assignment, start)
            self._history(value)
            second = self._inputs(value.assignment, self._now())
            finish = self._now()
            self._finish(value.assignment, first, second, finish)
            self._heads(record, finish)
            if not value.is_current_at(finish) or self._revocation(value, finish) is not None:
                return None
            return CurrentOwnerTenantAuthorityV2(
                value,
                second.participants.authority,
                second.physical,
                finish,
                min(
                    value.valid_until,
                    value.policy.valid_until,
                    second.participants.authority.valid_until,
                    second.participants.valid_until,
                ),
            )
        except (OwnerTenantAuthorityV2Unavailable, OwnerTenantAuthorityV2Conflict, ValueError):
            return None

    @staticmethod
    def _actor(
        authentication: CurrentAccountActorAuthorityV3, role: str
    ) -> AccountOwnerAssignmentActor:
        """Project the explicit operation role while preserving actual human identity and staff facts."""
        return AccountOwnerAssignmentActor(
            actor_id=authentication.actor_id,
            user_id=authentication.user_id,
            role=role,
            kind="human",
            is_staff=authentication.is_staff,
        )
