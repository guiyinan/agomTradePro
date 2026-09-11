"""Unit coverage for the Evidence V5-backed Authority V3 Application."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    CurrentSingleOwnerParticipants,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3,
    GetCurrentOwnerTenantAuthorityV3Command,
    GetExactOwnerTenantAuthorityV3,
    GetExactOwnerTenantAuthorityV3Command,
    IssueOwnerTenantAuthorityV3Command,
    OwnerTenantAuthorityV3Service,
    RevokeOwnerTenantAuthorityV3Command,
    SupersedeOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Repository,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    OwnerTenantAuthorityV3,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence


def _authority_source(
    assignment: AccountOwnerAssignmentEvidenceV5,
    *,
    source: str = "first",
    valid_until: datetime = datetime(2026, 8, 30, 12, tzinfo=UTC),
) -> CurrentAccountActorAuthorityV3:
    """Build current admin facts for the exact V5 claimant."""

    digest = sha256(f"authority-{source}".encode()).hexdigest()
    return CurrentAccountActorAuthorityV3(
        principal_id=f"principal-{source}",
        user_id=assignment.claimant.user_id,
        authentication_context_hash=digest,
        actor_id=assignment.claimant.actor_id,
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        source_id=f"source-{source}",
        source_version="v3.1",
        source_content_hash=sha256(f"source-{source}".encode()).hexdigest(),
        recorded_at=assignment.recorded_at,
        valid_until=valid_until,
    )


class _EvidenceReader:
    """Serve controlled exact/current Evidence V5 projections."""

    def __init__(
        self,
        assignment: AccountOwnerAssignmentEvidenceV5,
        current_values: list[object | None] | None = None,
    ) -> None:
        self.assignment = assignment
        self.current_values = current_values or [assignment]
        self.current_calls: list[GetCurrentAccountOwnerAssignmentEvidenceV5Command] = []
        self.exact_calls: list[GetExactAccountOwnerAssignmentEvidenceV5Command] = []

    def execute(self, command: object) -> object | None:
        """Return the next configured current value or exact historical assignment."""

        if type(command) is GetCurrentAccountOwnerAssignmentEvidenceV5Command:
            self.current_calls.append(command)
            return (
                self.current_values.pop(0)
                if len(self.current_values) > 1
                else self.current_values[0]
            )
        if type(command) is GetExactAccountOwnerAssignmentEvidenceV5Command:
            self.exact_calls.append(command)
            return self.assignment
        raise AssertionError(f"unexpected command: {type(command)!r}")


class _ParticipantsReader:
    """Serve current policy and actor projections with requested observation clocks."""

    def __init__(
        self,
        assignment: AccountOwnerAssignmentEvidenceV5,
        values: list[CurrentAccountActorAuthorityV3] | None = None,
    ) -> None:
        self.assignment = assignment
        self.values = values or [_authority_source(assignment)]
        self.calls: list[datetime] = []

    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants:
        """Return one current participant projection for the requested cutoff."""

        self.calls.append(as_of)
        authority = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        return CurrentSingleOwnerParticipants(
            self.assignment.policy,
            authority,
            self.assignment.claimant,
            self.assignment.approved_by,
            as_of,
            min(self.assignment.policy.valid_until, authority.valid_until),
        )


class _Repository:
    """In-memory first-winner repository with rollback semantics."""

    def __init__(self, *clocks: datetime) -> None:
        self.clocks = list(clocks)
        self.records: dict[tuple[str, str], PersistedOwnerTenantAuthorityV3] = {}
        self.head: PersistedOwnerTenantAuthorityV3 | None = None
        self.assignment_head: PersistedOwnerTenantAuthorityV3 | None = None
        self.revocation: PersistedOwnerTenantAuthorityV3Revocation | None = None
        self.append_count = 0
        self.revocation_append_count = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Roll back all repository mutations when an application use case fails."""

        snapshot = (
            dict(self.records),
            self.head,
            self.assignment_head,
            self.revocation,
            self.append_count,
            self.revocation_append_count,
        )
        try:
            yield
        except BaseException:
            (
                self.records,
                self.head,
                self.assignment_head,
                self.revocation,
                self.append_count,
                self.revocation_append_count,
            ) = snapshot
            raise

    def now(self) -> datetime:
        """Return the next deterministic repository clock."""

        if not self.clocks:
            raise AssertionError("test clock exhausted")
        return self.clocks.pop(0) if len(self.clocks) > 1 else self.clocks[0]

    def get_winner(
        self,
        *,
        authority_id: str,
        authority_version: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return one first winner once it is knowable at the cutoff."""

        record = self.records.get((authority_id, authority_version))
        if record is None:
            return None
        if type(record) is not PersistedOwnerTenantAuthorityV3:
            return record
        if record.authority.recorded_at > as_of:
            return None
        return record

    def get_head(
        self,
        *,
        authority_id: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the logical head when it is knowable at the cutoff."""

        if self.head is None or self.head.authority.authority_id != authority_id:
            return None
        return self.head if self.head.authority.recorded_at <= as_of else None

    def get_assignment_head(
        self,
        *,
        assignment_content_hash: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the occupied root slot for an exact Evidence V5 hash."""

        if self.assignment_head is None:
            return None
        if self.assignment_head.authority.assignment.content_hash != assignment_content_hash:
            return None
        return self.assignment_head if self.assignment_head.authority.recorded_at <= as_of else None

    def get_revocation(
        self,
        *,
        authority_content_hash: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Return one known revocation for an exact Authority V3 hash."""

        if self.revocation is None:
            return None
        if self.revocation.revocation.authority_content_hash != authority_content_hash:
            return None
        return self.revocation if self.revocation.revocation.recorded_at <= as_of else None

    def append(
        self,
        record: PersistedOwnerTenantAuthorityV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3:
        """Append a root or CAS successor and return its exact first winner."""

        authority = record.authority
        assert authority.recorded_at == recorded_at
        key = (authority.authority_id, authority.authority_version)
        if key in self.records:
            return self.records[key]
        if expected_predecessor_hash is None:
            assert self.head is None
            self.assignment_head = record
        else:
            assert self.head is not None
            assert self.head.authority.content_hash == expected_predecessor_hash
        self.records[key] = record
        self.head = record
        self.append_count += 1
        return record

    def append_revocation(
        self,
        record: PersistedOwnerTenantAuthorityV3Revocation,
        *,
        expected_authority_content_hash: str,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation:
        """Append the one immutable revocation first winner."""

        assert self.head is not None
        assert self.head.authority.content_hash == expected_authority_content_hash
        assert record.revocation.recorded_at == recorded_at
        if self.revocation is not None:
            return self.revocation
        self.revocation = record
        self.revocation_append_count += 1
        return record


class _World:
    """Assemble V5 evidence, current policy/authentication, and Authority V3 service."""

    def __init__(self) -> None:
        self.assignment = _evidence()
        start = self.assignment.recorded_at + timedelta(minutes=5)
        self.repository = _Repository(start, start + timedelta(microseconds=1))
        self.evidence_reader = _EvidenceReader(self.assignment, [self.assignment, self.assignment])
        self.participants_reader = _ParticipantsReader(self.assignment)

    def service(
        self, *, validity_period: timedelta = timedelta(hours=2)
    ) -> OwnerTenantAuthorityV3Service:
        """Build the V3 service from only public Application reader contracts."""

        return OwnerTenantAuthorityV3Service(
            repository=cast(OwnerTenantAuthorityV3Repository, self.repository),
            current_assignments=cast(object, self.evidence_reader),
            historical_assignments=cast(object, self.evidence_reader),
            participants=cast(object, self.participants_reader),
            validity_period=validity_period,
        )

    def issue_command(self, version: str = "v3.1") -> IssueOwnerTenantAuthorityV3Command:
        """Build one root command from the immutable Evidence V5 selectors."""

        return IssueOwnerTenantAuthorityV3Command(
            "authority-7",
            version,
            self.assignment.evidence_id,
            self.assignment.evidence_version,
            self.assignment.content_hash,
        )


def _current_command(authority: OwnerTenantAuthorityV3) -> GetCurrentOwnerTenantAuthorityV3Command:
    """Build one exact current Authority V3 selector."""

    return GetCurrentOwnerTenantAuthorityV3Command(
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
    )


def test_issue_replay_and_exact_use_public_evidence_v5_contracts() -> None:
    """Issue one root once, replay it, and read it historically after expiry."""

    world = _World()
    service = world.service(validity_period=timedelta(seconds=30))
    authority = service.issue(world.issue_command())
    assert authority.must_not_execute is True
    assert authority.activation_available is False
    assert authority.assignment is world.assignment
    assert world.repository.append_count == 1
    assert len(world.evidence_reader.current_calls) == 2
    assert len(world.participants_reader.calls) == 2

    replay = service.issue(world.issue_command())
    assert replay == authority
    assert world.repository.append_count == 1

    exact = GetExactOwnerTenantAuthorityV3(service).execute(
        GetExactOwnerTenantAuthorityV3Command(
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
            authority.valid_until + timedelta(minutes=1),
        )
    )
    assert exact == authority
    assert (
        world.evidence_reader.exact_calls[-1].expected_content_hash
        == authority.assignment.content_hash
    )


def test_issue_replay_requires_current_evidence_and_actor_sources() -> None:
    """Reject an immutable root replay after its current Evidence or actor disappears."""

    world = _World()
    service = world.service()
    authority = service.issue(world.issue_command())
    world.repository.clocks = [authority.recorded_at + timedelta(seconds=1)]
    world.evidence_reader.current_values = [None]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="current sources"):
        service.issue(world.issue_command())

    world.evidence_reader.current_values = [world.assignment]
    stale = replace(
        _authority_source(world.assignment),
        valid_until=authority.recorded_at,
    )
    world.participants_reader.values = [stale]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="current sources"):
        service.issue(world.issue_command())


def test_issue_rejects_evidence_or_current_actor_drift_before_append() -> None:
    """Reject substituted current Evidence V5 or authentication between double reads."""

    world = _World()
    changed = replace(
        world.assignment,
        evidence_version="v5.2",
        identity_hash="",
        content_hash="",
    )
    world.evidence_reader.current_values = [world.assignment, changed]
    with pytest.raises(OwnerTenantAuthorityV3Corruption, match="selector"):
        world.service().issue(world.issue_command())
    assert world.repository.append_count == 0

    world = _World()
    first = _authority_source(world.assignment, source="first")
    second = _authority_source(world.assignment, source="changed")
    world.participants_reader.values = [first, second]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="inputs changed"):
        world.service().issue(world.issue_command())
    assert world.repository.append_count == 0


def test_current_reads_final_head_twice_and_fails_closed_after_auth_change() -> None:
    """Require the exact chain head, original Evidence V5, and stable current auth."""

    world = _World()
    authority = world.service().issue(world.issue_command())
    world.repository.clocks = [authority.recorded_at + timedelta(seconds=1)]
    current = GetCurrentOwnerTenantAuthorityV3(world.service()).execute(_current_command(authority))
    assert current is not None
    assert current.authority == authority
    assert current.authentication.actor_id == authority.actor_id
    assert current.valid_until <= authority.valid_until

    world.participants_reader.values = [
        _authority_source(world.assignment, source="first"),
        _authority_source(world.assignment, source="changed"),
    ]
    world.repository.clocks = [authority.recorded_at + timedelta(seconds=2)]
    assert world.service().get_current(_current_command(authority)) is None

    world.evidence_reader.current_values = [None]
    world.participants_reader.values = [_authority_source(world.assignment)]
    world.repository.clocks = [authority.recorded_at + timedelta(seconds=3)]
    assert world.service().get_current(_current_command(authority)) is None


def test_successor_preserves_exact_chain_and_requires_strict_recording_progress() -> None:
    """Append one opaque-version successor, replay it, and reject equal version/time."""

    world = _World()
    service = world.service(validity_period=timedelta(seconds=30))
    root = service.issue(world.issue_command())
    command = SupersedeOwnerTenantAuthorityV3Command(
        root.authority_id,
        "opaque-successor",
        root.authority_version,
        root.content_hash,
        root.assignment_evidence_id,
        root.assignment_evidence_version,
        root.assignment_evidence_content_hash,
    )
    world.repository.clocks = [root.recorded_at]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="recording clock must advance"):
        service.successor(command)

    successor_cutoff = root.recorded_at + timedelta(microseconds=1)
    world.repository.clocks = [successor_cutoff, successor_cutoff + timedelta(microseconds=1)]
    successor = service.successor(command)
    assert successor.supersedes_content_hash == root.content_hash
    assert successor.authority_version == "opaque-successor"
    assert successor.recorded_at > root.recorded_at
    assert successor.policy == root.policy
    assert service.successor(command) == successor
    assert world.repository.append_count == 2

    world.evidence_reader.current_values = [None]
    world.repository.clocks = [successor.recorded_at + timedelta(microseconds=1)]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="current sources"):
        service.successor(command)

    same_version = replace(command, authority_version=root.authority_version)
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="version must advance"):
        service.successor(same_version)


def test_successor_rejects_predecessor_cas_mismatch_and_expired_predecessor() -> None:
    """Never append a successor for a different head or after predecessor expiry."""

    world = _World()
    root = world.service(validity_period=timedelta(seconds=1)).issue(world.issue_command())
    command = SupersedeOwnerTenantAuthorityV3Command(
        root.authority_id,
        "opaque-successor",
        root.authority_version,
        "f" * 64,
        root.assignment_evidence_id,
        root.assignment_evidence_version,
        root.assignment_evidence_content_hash,
    )
    world.repository.clocks = [root.recorded_at + timedelta(microseconds=1)]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="predecessor changed"):
        world.service(validity_period=timedelta(seconds=1)).successor(command)
    assert world.repository.append_count == 1

    world = _World()
    root = world.service(validity_period=timedelta(seconds=1)).issue(world.issue_command())
    command = replace(command, expected_predecessor_content_hash=root.content_hash)
    world.repository.clocks = [root.valid_until + timedelta(microseconds=1)]
    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="predecessor"):
        world.service(validity_period=timedelta(seconds=1)).successor(command)
    assert world.repository.append_count == 1


def test_revocation_is_first_winner_replayable_after_expiry_and_blocks_current() -> None:
    """Allow explicit post-expiry revocation, replay the reason, and fail current closed."""

    world = _World()
    service = world.service(validity_period=timedelta(seconds=1))
    authority = service.issue(world.issue_command())
    revoke_at = authority.valid_until + timedelta(seconds=1)
    world.repository.clocks = [revoke_at, revoke_at + timedelta(microseconds=1), revoke_at]
    command = RevokeOwnerTenantAuthorityV3Command(
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
        "owner-request",
    )
    revoked = service.revoke(command)
    assert revoked.authority_content_hash == authority.content_hash
    assert revoked.revoked_at == revoke_at
    assert service.revoke(command) == revoked
    assert service.get_current(_current_command(authority)) is None
    assert world.repository.revocation_append_count == 1

    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="reason"):
        service.revoke(replace(command, reason="changed-reason"))


def test_invalid_persisted_envelopes_and_current_type_substitution_fail_closed() -> None:
    """Reject substituted persisted authority/authentication and participant values."""

    world = _World()
    authority = world.service().issue(world.issue_command())
    record = cast(PersistedOwnerTenantAuthorityV3, world.repository.head)
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3"):
        PersistedOwnerTenantAuthorityV3(
            cast(OwnerTenantAuthorityV3, object()),
            record.authentication,
        )

    world.participants_reader.values = [cast(CurrentAccountActorAuthorityV3, object())]
    with pytest.raises(OwnerTenantAuthorityV3Corruption, match="participant"):
        world.service().get_current(_current_command(authority))

    world.repository.records[(authority.authority_id, authority.authority_version)] = cast(
        PersistedOwnerTenantAuthorityV3,
        object(),
    )
    with pytest.raises(OwnerTenantAuthorityV3Corruption, match="record"):
        world.service().get_exact(
            GetExactOwnerTenantAuthorityV3Command(
                authority.authority_id,
                authority.authority_version,
                authority.content_hash,
                authority.recorded_at,
            )
        )


def test_application_files_use_only_v3_domain_and_v5_application_ports() -> None:
    """Keep the new Application boundary free from infrastructure and old versions."""

    for name in (
        "apps/account/application/owner_tenant_authority_v3_contracts.py",
        "apps/account/application/owner_tenant_authority_v3.py",
    ):
        tree = ast.parse(Path(name).read_text(encoding="utf-8"))
        imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any(
            "infrastructure" in module or module.startswith("django") for module in imports
        )
        assert not any(
            module.endswith("owner_tenant_authority_v1")
            or module.endswith("owner_tenant_authority_v2")
            or module.endswith("account_owner_assignment_evidence_v4")
            for module in imports
        )
    source = Path("apps/account/application/owner_tenant_authority_v3.py").read_text(
        encoding="utf-8"
    )
    assert "must_not_execute" not in source or "OwnerTenantAuthorityV3" in source
