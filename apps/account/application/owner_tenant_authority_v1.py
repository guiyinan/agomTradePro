"""Approved lifecycle and exact-current reads for owner/tenant authority v1."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountOwnerAssignmentApproverProviderV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3Command,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
)
from apps.account.domain.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1,
    validate_owner_tenant_authority_v1_root,
    validate_owner_tenant_authority_v1_successor,
)


class OwnerTenantAuthorityV1Unavailable(RuntimeError):
    """The exact current upstream authority cannot be proven."""


class OwnerTenantAuthorityV1Conflict(RuntimeError):
    """An immutable winner or compare-and-swap predecessor differs."""


class OwnerTenantAuthorityV1Corruption(RuntimeError):
    """A provider or repository returned substituted authority data."""


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
class IssueOwnerTenantAuthorityV1Command:
    """Approve one root from an exact-current Account assignment evidence seal."""

    authority_id: str
    authority_version: str
    tenant_id: str
    owner_id: str
    assignment_evidence_id: str
    assignment_evidence_version: str
    expected_assignment_evidence_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "authority_id",
            "authority_version",
            "tenant_id",
            "owner_id",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _token(getattr(self, name), name)
        _digest(
            self.expected_assignment_evidence_content_hash,
            "expected_assignment_evidence_content_hash",
        )


@dataclass(frozen=True, slots=True)
class SupersedeOwnerTenantAuthorityV1Command:
    """Renew or revoke one exact current authority head."""

    authority_id: str
    authority_version: str
    predecessor_version: str
    expected_predecessor_content_hash: str
    assignment_evidence_id: str
    assignment_evidence_version: str
    expected_assignment_evidence_content_hash: str
    status: str

    def __post_init__(self) -> None:
        for name in (
            "authority_id",
            "authority_version",
            "predecessor_version",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _token(getattr(self, name), name)
        for name in (
            "expected_predecessor_content_hash",
            "expected_assignment_evidence_content_hash",
        ):
            _digest(getattr(self, name), name)
        if self.status not in {"active", "revoked"}:
            raise ValueError("status must be active or revoked")


@dataclass(frozen=True, slots=True)
class GetExactOwnerTenantAuthorityV1Command:
    """Read one exact immutable authority row at a PIT cutoff."""

    authority_id: str
    authority_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.authority_id, "authority_id")
        _token(self.authority_version, "authority_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentOwnerTenantAuthorityV1Command(GetExactOwnerTenantAuthorityV1Command):
    """Read an exact row only when it is the active final chain head."""


class CurrentOwnerTenantAuthorityApproverProvider(Protocol):
    """Resolve a repeatedly revalidated authenticated human staff approver."""

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None:
        """Return an eligible server actor or ``None`` when unavailable."""


@dataclass(frozen=True, slots=True)
class DelegatingOwnerTenantAuthorityApproverProviderV1:
    """Reuse the exact-current Account admin proof under a dedicated role."""

    delegate: CurrentAccountOwnerAssignmentApproverProviderV3

    def __post_init__(self) -> None:
        if type(self.delegate) is not CurrentAccountOwnerAssignmentApproverProviderV3:
            raise TypeError(
                "delegate must be an exact CurrentAccountOwnerAssignmentApproverProviderV3"
            )

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None:
        """Revalidate the admin and project only the dedicated approval capability."""

        actor = self.delegate.get_current(as_of=as_of)
        if actor is None:
            return None
        if type(actor) is not AccountOwnerAssignmentServerActor:
            raise OwnerTenantAuthorityV1Corruption("admin actor type substitution")
        actor.__post_init__()
        if not actor.is_staff or actor.role != "account_owner_assignment_approver":
            return None
        return AccountOwnerAssignmentServerActor(
            actor_id=actor.actor_id,
            user_id=actor.user_id,
            role="owner_tenant_authority_approver",
            kind=actor.kind,
            is_staff=True,
        )


class CurrentOwnerAssignmentEvidenceV3Reader(Protocol):
    """Read one exact-current Account assignment evidence root."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        """Return the exact current assignment or ``None``."""


class OwnerTenantAuthorityV1Repository(Protocol):
    """Persist first winners and one compare-and-swap successor per head."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database unit used by this repository."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned transaction."""

    def now(self) -> datetime:
        """Return the authoritative server clock."""

    def get_winner(
        self, *, authority_id: str, authority_version: str, as_of: datetime
    ) -> OwnerTenantAuthorityV1 | None:
        """Return the immutable first winner for one version."""

    def get_head(self, *, authority_id: str, as_of: datetime) -> OwnerTenantAuthorityV1 | None:
        """Return the final logical chain head without active fallback."""

    def get_exact(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> OwnerTenantAuthorityV1 | None:
        """Return one exact knowable authority row."""

    def append(
        self,
        authority: OwnerTenantAuthorityV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> OwnerTenantAuthorityV1:
        """Append a root or exact CAS successor."""


class _AuthorityWriter:
    def __init__(
        self,
        *,
        assignments: CurrentOwnerAssignmentEvidenceV3Reader,
        approvers: CurrentOwnerTenantAuthorityApproverProvider,
        repository: OwnerTenantAuthorityV1Repository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._assignments = assignments
        self._approvers = approvers
        self._repository = repository
        self._validity_period = validity_period

    def _inputs(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        evidence_hash: str,
        cutoff: datetime,
    ) -> tuple[AccountOwnerAssignmentEvidenceV3, AccountOwnerAssignmentServerActor]:
        try:
            assignment = self._assignments.execute(
                GetCurrentAccountOwnerAssignmentEvidenceV3Command(
                    evidence_id,
                    evidence_version,
                    evidence_hash,
                    cutoff,
                )
            )
        except AccountOwnerAssignmentUnavailable as error:
            raise OwnerTenantAuthorityV1Unavailable(
                "exact-current account owner assignment is unavailable"
            ) from error
        except AccountOwnerAssignmentCorruption as error:
            raise OwnerTenantAuthorityV1Corruption("account owner assignment is corrupt") from error
        if assignment is None:
            raise OwnerTenantAuthorityV1Unavailable(
                "exact-current account owner assignment is unavailable"
            )
        if type(assignment) is not AccountOwnerAssignmentEvidenceV3:
            raise OwnerTenantAuthorityV1Corruption("assignment evidence type substitution")
        try:
            assignment.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV1Corruption("assignment evidence is corrupt") from error
        if (
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
        ) != (evidence_id, evidence_version, evidence_hash):
            raise OwnerTenantAuthorityV1Corruption("assignment selector substitution")
        if not assignment.is_current_at(cutoff):
            raise OwnerTenantAuthorityV1Unavailable("account owner assignment is not current")
        approver = self._approvers.get_current(as_of=cutoff)
        if approver is None:
            raise OwnerTenantAuthorityV1Unavailable(
                "current owner/tenant authority approver is unavailable"
            )
        if type(approver) is not AccountOwnerAssignmentServerActor:
            raise OwnerTenantAuthorityV1Corruption("authority approver type substitution")
        try:
            approver.__post_init__()
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV1Corruption("authority approver is corrupt") from error
        if (
            not approver.is_staff
            or approver.kind != "human"
            or approver.role != "owner_tenant_authority_approver"
        ):
            raise OwnerTenantAuthorityV1Unavailable(
                "current owner/tenant authority approver is ineligible"
            )
        claimant = assignment.subject.claimant
        if approver.actor_id == claimant.actor_id or approver.user_id == claimant.user_id:
            raise OwnerTenantAuthorityV1Unavailable(
                "authority owner and approver must be independent"
            )
        return assignment, approver

    def _stable_inputs(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        evidence_hash: str,
        cutoff: datetime,
    ) -> tuple[AccountOwnerAssignmentEvidenceV3, AccountOwnerAssignmentServerActor]:
        first = self._inputs(
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
            cutoff=cutoff,
        )
        second = self._inputs(
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
            cutoff=cutoff,
        )
        if first != second:
            raise OwnerTenantAuthorityV1Conflict("authority approval inputs changed")
        return second

    def _candidate(
        self,
        *,
        authority_id: str,
        authority_version: str,
        tenant_id: str,
        owner_id: str,
        assignment: AccountOwnerAssignmentEvidenceV3,
        approver: AccountOwnerAssignmentServerActor,
        approved_at: datetime,
        recorded_at: datetime,
        status: str,
        predecessor_hash: str | None,
    ) -> OwnerTenantAuthorityV1:
        binding = assignment.subject.binding
        claimant = assignment.subject.claimant
        valid_until = min(assignment.valid_until, recorded_at + self._validity_period)
        return OwnerTenantAuthorityV1(
            authority_id=authority_id,
            authority_version=authority_version,
            tenant_id=tenant_id,
            owner_id=owner_id,
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            actor_id=claimant.actor_id,
            actor_user_id=claimant.user_id,
            assignment_evidence_id=assignment.evidence_id,
            assignment_evidence_version=assignment.evidence_version,
            assignment_evidence_content_hash=assignment.content_hash,
            status=status,
            approved_by=approver.to_domain(),
            approved_at=approved_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=predecessor_hash,
        )


class IssueOwnerTenantAuthorityV1(_AuthorityWriter):
    """Create one independently approved immutable authority root."""

    def execute(self, command: IssueOwnerTenantAuthorityV1Command) -> OwnerTenantAuthorityV1:
        """Issue or historically replay the root first winner."""

        if type(command) is not IssueOwnerTenantAuthorityV1Command:
            raise TypeError("command must be exact IssueOwnerTenantAuthorityV1Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner = self._repository.get_winner(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                as_of=cutoff,
            )
            if winner is not None:
                checked = _authority(winner)
                if not _root_matches(checked, command):
                    raise OwnerTenantAuthorityV1Conflict(
                        "authority root identity has another winner"
                    )
                return checked
            if self._repository.get_head(authority_id=command.authority_id, as_of=cutoff):
                raise OwnerTenantAuthorityV1Conflict("authority chain already has a root")
            assignment, approver = self._stable_inputs(
                evidence_id=command.assignment_evidence_id,
                evidence_version=command.assignment_evidence_version,
                evidence_hash=command.expected_assignment_evidence_content_hash,
                cutoff=cutoff,
            )
            recorded_at = _clock(self._repository.now())
            current_assignment, current_approver = self._stable_inputs(
                evidence_id=command.assignment_evidence_id,
                evidence_version=command.assignment_evidence_version,
                evidence_hash=command.expected_assignment_evidence_content_hash,
                cutoff=recorded_at,
            )
            if (assignment, approver) != (current_assignment, current_approver):
                raise OwnerTenantAuthorityV1Conflict("authority approval inputs changed")
            candidate = self._candidate(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                tenant_id=command.tenant_id,
                owner_id=command.owner_id,
                assignment=current_assignment,
                approver=current_approver,
                approved_at=cutoff,
                recorded_at=recorded_at,
                status="active",
                predecessor_hash=None,
            )
            validate_owner_tenant_authority_v1_root(candidate)
            persisted = _authority(
                self._repository.append(
                    candidate,
                    expected_predecessor_hash=None,
                    recorded_at=recorded_at,
                )
            )
            if persisted != candidate:
                raise OwnerTenantAuthorityV1Conflict("authority root first winner differs")
            return persisted


class SupersedeOwnerTenantAuthorityV1(_AuthorityWriter):
    """Renew or revoke one exact active authority head."""

    def execute(self, command: SupersedeOwnerTenantAuthorityV1Command) -> OwnerTenantAuthorityV1:
        """Append or replay an exact compare-and-swap successor."""

        if type(command) is not SupersedeOwnerTenantAuthorityV1Command:
            raise TypeError("command must be exact SupersedeOwnerTenantAuthorityV1Command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _clock(self._repository.now())
            winner = self._repository.get_winner(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                as_of=cutoff,
            )
            if winner is not None:
                checked = _authority(winner)
                if not _successor_matches(checked, command):
                    raise OwnerTenantAuthorityV1Conflict(
                        "authority successor identity has another winner"
                    )
                return checked
            predecessor = self._repository.get_head(authority_id=command.authority_id, as_of=cutoff)
            if predecessor is None:
                raise OwnerTenantAuthorityV1Unavailable("authority predecessor is unavailable")
            previous = _authority(predecessor)
            if (
                previous.authority_version != command.predecessor_version
                or previous.content_hash != command.expected_predecessor_content_hash
            ):
                raise OwnerTenantAuthorityV1Conflict("authority predecessor changed")
            assignment, approver = self._stable_inputs(
                evidence_id=command.assignment_evidence_id,
                evidence_version=command.assignment_evidence_version,
                evidence_hash=command.expected_assignment_evidence_content_hash,
                cutoff=cutoff,
            )
            recorded_at = _clock(self._repository.now())
            current_assignment, current_approver = self._stable_inputs(
                evidence_id=command.assignment_evidence_id,
                evidence_version=command.assignment_evidence_version,
                evidence_hash=command.expected_assignment_evidence_content_hash,
                cutoff=recorded_at,
            )
            if (assignment, approver) != (current_assignment, current_approver):
                raise OwnerTenantAuthorityV1Conflict("authority approval inputs changed")
            head = self._repository.get_head(authority_id=command.authority_id, as_of=recorded_at)
            if head != previous:
                raise OwnerTenantAuthorityV1Conflict("authority predecessor changed")
            candidate = self._candidate(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                tenant_id=previous.tenant_id,
                owner_id=previous.owner_id,
                assignment=current_assignment,
                approver=current_approver,
                approved_at=cutoff,
                recorded_at=recorded_at,
                status=command.status,
                predecessor_hash=previous.content_hash,
            )
            validate_owner_tenant_authority_v1_successor(previous, candidate)
            persisted = _authority(
                self._repository.append(
                    candidate,
                    expected_predecessor_hash=previous.content_hash,
                    recorded_at=recorded_at,
                )
            )
            if persisted != candidate:
                raise OwnerTenantAuthorityV1Conflict("authority successor winner differs")
            return persisted


class GetExactOwnerTenantAuthorityV1:
    """Read one immutable authority by an exact content-addressed selector."""

    def __init__(self, repository: OwnerTenantAuthorityV1Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactOwnerTenantAuthorityV1Command
    ) -> OwnerTenantAuthorityV1 | None:
        """Return the exact knowable authority row or ``None``."""

        if type(command) is not GetExactOwnerTenantAuthorityV1Command:
            raise TypeError("command must be exact GetExactOwnerTenantAuthorityV1Command")
        command.__post_init__()
        value = self._repository.get_exact(
            authority_id=command.authority_id,
            authority_version=command.authority_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        authority = _authority(value)
        if (
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
        ) != (
            command.authority_id,
            command.authority_version,
            command.expected_content_hash,
        ):
            raise OwnerTenantAuthorityV1Corruption("authority selector substitution")
        return authority if authority.is_knowable_at(command.as_of) else None


class GetCurrentOwnerTenantAuthorityV1:
    """Read an exact authority only when it is the active final chain head."""

    def __init__(
        self,
        repository: OwnerTenantAuthorityV1Repository,
        *,
        assignment_reader: CurrentOwnerAssignmentEvidenceV3Reader,
    ) -> None:
        if assignment_reader is None:
            raise TypeError("assignment_reader is required")
        self._repository = repository
        self._assignments = assignment_reader
        self._exact = GetExactOwnerTenantAuthorityV1(repository)

    @property
    def unit_of_work_key(self) -> str:
        """Expose the authority repository's transaction identity."""

        return self._repository.unit_of_work_key

    def execute(
        self, command: GetCurrentOwnerTenantAuthorityV1Command
    ) -> OwnerTenantAuthorityV1 | None:
        """Return current authority without predecessor fallback."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV1Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV1Command")
        command.__post_init__()
        exact = self._exact.execute(
            GetExactOwnerTenantAuthorityV1Command(
                command.authority_id,
                command.authority_version,
                command.expected_content_hash,
                command.as_of,
            )
        )
        if exact is None or not exact.is_current_at(command.as_of):
            return None
        head = self._repository.get_head(authority_id=command.authority_id, as_of=command.as_of)
        if head is None:
            return None
        current = _authority(head)
        if current != exact:
            return None
        assignment = _read_current_assignment(
            self._assignments,
            authority=exact,
            as_of=command.as_of,
        )
        if assignment is None:
            return None
        binding = assignment.subject.binding
        claimant = assignment.subject.claimant
        if (
            binding.account_namespace_claim,
            binding.account_id_claim,
            claimant.actor_id,
            claimant.user_id,
        ) != (
            exact.account_namespace,
            exact.account_id,
            exact.actor_id,
            exact.actor_user_id,
        ):
            raise OwnerTenantAuthorityV1Corruption(
                "current account owner assignment scope substitution"
            )
        return exact


def _clock(value: object) -> datetime:
    try:
        return _aware(value, "repository clock")
    except ValueError as error:
        raise OwnerTenantAuthorityV1Corruption(str(error)) from error


def _read_current_assignment(
    reader: CurrentOwnerAssignmentEvidenceV3Reader,
    *,
    authority: OwnerTenantAuthorityV1,
    as_of: datetime,
) -> AccountOwnerAssignmentEvidenceV3 | None:
    try:
        value = reader.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV3Command(
                authority.assignment_evidence_id,
                authority.assignment_evidence_version,
                authority.assignment_evidence_content_hash,
                as_of,
            )
        )
    except AccountOwnerAssignmentUnavailable:
        return None
    except AccountOwnerAssignmentCorruption as error:
        raise OwnerTenantAuthorityV1Corruption(
            "current account owner assignment is corrupt"
        ) from error
    if value is None:
        return None
    if type(value) is not AccountOwnerAssignmentEvidenceV3:
        raise OwnerTenantAuthorityV1Corruption("current account owner assignment type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV1Corruption(
            "current account owner assignment is corrupt"
        ) from error
    if (
        value.evidence_id,
        value.evidence_version,
        value.content_hash,
    ) != (
        authority.assignment_evidence_id,
        authority.assignment_evidence_version,
        authority.assignment_evidence_content_hash,
    ):
        raise OwnerTenantAuthorityV1Corruption(
            "current account owner assignment selector substitution"
        )
    return value if value.is_current_at(as_of) else None


def _authority(value: object) -> OwnerTenantAuthorityV1:
    if type(value) is not OwnerTenantAuthorityV1:
        raise OwnerTenantAuthorityV1Corruption("authority type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV1Corruption("authority is corrupt") from error
    return value


def _root_matches(
    authority: OwnerTenantAuthorityV1, command: IssueOwnerTenantAuthorityV1Command
) -> bool:
    return (
        authority.authority_id,
        authority.authority_version,
        authority.tenant_id,
        authority.owner_id,
        authority.assignment_evidence_id,
        authority.assignment_evidence_version,
        authority.assignment_evidence_content_hash,
        authority.status,
        authority.supersedes_content_hash,
    ) == (
        command.authority_id,
        command.authority_version,
        command.tenant_id,
        command.owner_id,
        command.assignment_evidence_id,
        command.assignment_evidence_version,
        command.expected_assignment_evidence_content_hash,
        "active",
        None,
    )


def _successor_matches(
    authority: OwnerTenantAuthorityV1,
    command: SupersedeOwnerTenantAuthorityV1Command,
) -> bool:
    return (
        authority.authority_id,
        authority.authority_version,
        authority.assignment_evidence_id,
        authority.assignment_evidence_version,
        authority.assignment_evidence_content_hash,
        authority.status,
        authority.supersedes_content_hash,
    ) == (
        command.authority_id,
        command.authority_version,
        command.assignment_evidence_id,
        command.assignment_evidence_version,
        command.expected_assignment_evidence_content_hash,
        command.status,
        command.expected_predecessor_content_hash,
    )


__all__ = [
    "CurrentOwnerAssignmentEvidenceV3Reader",
    "CurrentOwnerTenantAuthorityApproverProvider",
    "DelegatingOwnerTenantAuthorityApproverProviderV1",
    "GetCurrentOwnerTenantAuthorityV1",
    "GetCurrentOwnerTenantAuthorityV1Command",
    "GetExactOwnerTenantAuthorityV1",
    "GetExactOwnerTenantAuthorityV1Command",
    "IssueOwnerTenantAuthorityV1",
    "IssueOwnerTenantAuthorityV1Command",
    "OwnerTenantAuthorityV1Conflict",
    "OwnerTenantAuthorityV1Corruption",
    "OwnerTenantAuthorityV1Repository",
    "OwnerTenantAuthorityV1Unavailable",
    "SupersedeOwnerTenantAuthorityV1",
    "SupersedeOwnerTenantAuthorityV1Command",
]
