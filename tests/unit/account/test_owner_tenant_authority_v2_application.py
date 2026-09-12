"""Owner decision lifecycle tests with independently advancing live source clocks."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
)
from apps.account.application.owner_tenant_authority_v2 import (
    GetCurrentOwnerTenantAuthorityV2Command,
    GetExactOwnerTenantAuthorityV2Command,
    IssueOwnerTenantAuthorityV2Command,
    OwnerTenantAuthorityV2Service,
    RevokeOwnerTenantAuthorityV2Command,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    CurrentOwnerPhysicalRow,
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Unavailable,
    PersistedOwnerTenantAuthorityV2,
)
from apps.account.application.single_owner_actor_authority import CurrentSingleOwnerParticipants
from tests.unit.account.test_account_owner_assignment_evidence_v4 import _evidence


class _Repository:
    unit_of_work_key = "django:owner-test"

    def __init__(self, clock):
        self.clock = clock
        self.root = None
        self.revocation = None
        self.append_count = 0

    @contextmanager
    def atomic(self):
        previous = (self.root, self.revocation, self.append_count)
        success = False
        try:
            yield
            success = True
        finally:
            if not success:
                self.root, self.revocation, self.append_count = previous

    def now(self):
        return self.clock

    def get_winner(self, *, authority_id, authority_version, as_of):
        if (
            self.root
            and (self.root.authority.authority_id, self.root.authority.authority_version)
            == (authority_id, authority_version)
            and self.root.authority.recorded_at <= as_of
        ):
            return self.root
        return None

    def get_head(self, *, authority_id, as_of):
        if self.root and self.root.authority.authority_id == authority_id:
            return self.root
        return None

    def get_assignment_head(self, *, assignment_content_hash, as_of):
        if self.root and self.root.authority.assignment.content_hash == assignment_content_hash:
            return self.root
        return None

    def get_revocation(self, *, authority_content_hash, as_of):
        if (
            self.revocation
            and self.revocation.revocation.authority_content_hash == authority_content_hash
            and self.revocation.revocation.recorded_at <= as_of
        ):
            return self.revocation
        return None

    def append_root(self, record, *, recorded_at):
        assert record.authority.recorded_at == recorded_at
        if self.root:
            raise OwnerTenantAuthorityV2Conflict("occupied root")
        self.root = record
        self.append_count += 1
        return record

    def append_revocation(self, record, *, expected_authority_content_hash, recorded_at):
        assert self.root.authority.content_hash == expected_authority_content_hash
        assert record.revocation.recorded_at == recorded_at
        if self.revocation:
            raise OwnerTenantAuthorityV2Conflict("occupied revocation")
        self.revocation = record
        return record


class _World:
    unit_of_work_key = "django:owner-test"

    def __init__(self):
        assignment = _evidence()
        self.repository = _Repository(assignment.recorded_at + timedelta(seconds=1))
        self.assignment = replace(
            assignment,
            valid_until=self.repository.clock + timedelta(minutes=5),
            approval_valid_until=self.repository.clock + timedelta(minutes=5),
            content_hash="",
        )
        self.policy = self.assignment.policy
        self.authentication = self._authentication("first")
        self.physical_changes = {}
        self.advance = timedelta(microseconds=1)
        self.current_assignment_reads = 0
        self.invalidate_assignment_on_third = False
        self.people_reads = 0
        self.change_auth_on_second = False
        self.participant_limit = None

    def _authentication(self, source):
        return CurrentAccountActorAuthorityV3(
            principal_id=f"principal-{source}",
            user_id=self.assignment.claimant.user_id,
            authentication_context_hash=sha256(f"context-{source}".encode()).hexdigest(),
            actor_id=self.assignment.claimant.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            rbac_role="admin",
            source_id=f"source-{source}",
            source_version="v3.1",
            source_content_hash=sha256(f"source-{source}".encode()).hexdigest(),
            recorded_at=self.repository.clock,
            valid_until=self.repository.clock + timedelta(minutes=5),
        )

    def reauthenticate(self):
        self.authentication = self._authentication("renewed")

    def execute(self, command):
        if (command.evidence_id, command.evidence_version, command.expected_content_hash) != (
            self.assignment.evidence_id,
            self.assignment.evidence_version,
            self.assignment.content_hash,
        ):
            return None
        if type(command) is GetCurrentAccountOwnerAssignmentEvidenceV4Command:
            self.current_assignment_reads += 1
            if self.invalidate_assignment_on_third and self.current_assignment_reads == 3:
                return None
            return self.assignment if self.assignment.is_current_at(command.as_of) else None
        return self.assignment if self.assignment.recorded_at <= command.as_of else None

    def get_current(self, *, as_of):
        self.people_reads += 1
        if self.change_auth_on_second and self.people_reads == 2:
            self.authentication = self._authentication("changed")
        valid_until = min(self.policy.valid_until, self.authentication.valid_until)
        if self.participant_limit is not None:
            valid_until = min(valid_until, self.participant_limit)
        return CurrentSingleOwnerParticipants(
            self.policy,
            self.authentication,
            self.assignment.claimant,
            self.assignment.approved_by,
            as_of,
            valid_until,
        )

    def read_locked(self, *, namespace, row_pk):
        physical = self.assignment.subject.physical_root.physical_observation
        self.repository.clock += self.advance
        observed = CurrentOwnerPhysicalRow(
            namespace,
            row_pk,
            physical.row_user_id,
            physical.raw_account_type,
            True,
            physical.row_created_at,
            physical.row_updated_at,
            self.repository.clock,
        )
        return replace(observed, **self.physical_changes)

    def service(self, *, validity_period=timedelta(hours=2)):
        return OwnerTenantAuthorityV2Service(
            repository=self.repository,
            current_assignments=self,
            historical_assignments=self,
            participants=self,
            physical=self,
            validity_period=validity_period,
        )

    def issue_command(self):
        return IssueOwnerTenantAuthorityV2Command(
            "owner-decision",
            "v2.1",
            self.assignment.evidence_id,
            self.assignment.evidence_version,
            self.assignment.content_hash,
        )


def _selector(value):
    return GetCurrentOwnerTenantAuthorityV2Command(
        value.authority_id, value.authority_version, value.content_hash
    )


def test_new_session_after_five_minutes_uses_durable_decision_not_expired_assignment():
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    original_record = world.repository.root
    assert decision.valid_until > original_record.authentication.valid_until
    assert world.repository.append_count == 1
    assert world.current_assignment_reads == 3

    world.repository.clock = world.assignment.valid_until
    assert service.get_current(_selector(decision)) is None
    assert not world.assignment.is_current_at(world.repository.clock)
    world.reauthenticate()
    current = service.get_current(_selector(decision))
    assert current.authority == decision
    assert current.authentication.source_id != original_record.authentication.source_id
    assert (
        current.authentication.source_content_hash
        != original_record.authentication.source_content_hash
    )
    assert (
        current.authentication.authentication_context_hash
        != original_record.authentication.authentication_context_hash
    )
    assert current.valid_until == world.authentication.valid_until
    assert current.physical.observed_at <= current.observed_at
    assert world.current_assignment_reads == 3
    assert service.issue(world.issue_command()) == decision
    assert world.repository.root == original_record and world.repository.append_count == 1


def test_initial_approval_cannot_use_expired_assignment_or_expire_during_reads():
    world = _World()
    world.repository.clock = world.assignment.valid_until
    world.reauthenticate()
    with pytest.raises(OwnerTenantAuthorityV2Unavailable):
        world.service().issue(world.issue_command())
    assert world.repository.root is None

    world = _World()
    world.advance = timedelta(minutes=6)
    with pytest.raises(OwnerTenantAuthorityV2Unavailable):
        world.service().issue(world.issue_command())
    assert world.repository.root is None


def test_final_assignment_substitution_after_second_read_never_persists():
    world = _World()
    world.invalidate_assignment_on_third = True
    with pytest.raises(OwnerTenantAuthorityV2Conflict, match="ceased to be current"):
        world.service().issue(world.issue_command())
    assert world.current_assignment_reads == 3
    assert world.repository.root is None and world.repository.append_count == 0


def test_revocation_after_decision_expiry_is_explicit_replayable_and_historical():
    world = _World()
    service = world.service(validity_period=timedelta(seconds=10))
    decision = service.issue(world.issue_command())
    world.repository.clock = decision.valid_until + timedelta(seconds=1)
    world.reauthenticate()
    command = RevokeOwnerTenantAuthorityV2Command(
        decision.authority_id, decision.authority_version, decision.content_hash, "owner-request"
    )
    revoked = service.revoke(command)
    assert revoked.revoked_at > decision.valid_until
    assert service.revoke(command) == revoked
    assert service.get_current(_selector(decision)) is None
    assert (
        service.get_exact(
            GetExactOwnerTenantAuthorityV2Command(
                decision.authority_id,
                decision.authority_version,
                decision.content_hash,
                world.repository.clock,
            )
        )
        == decision
    )
    with pytest.raises(OwnerTenantAuthorityV2Conflict, match="reason"):
        service.revoke(replace(command, reason="changed-reason"))
    assert world.repository.revocation.revocation == revoked


def test_expired_decision_slot_stays_occupied_even_with_current_assignment():
    world = _World()
    service = world.service(validity_period=timedelta(seconds=1))
    decision = service.issue(world.issue_command())
    world.repository.clock = decision.valid_until
    assert world.assignment.is_current_at(world.repository.clock)
    with pytest.raises(OwnerTenantAuthorityV2Conflict, match="occupied"):
        service.issue(replace(world.issue_command(), authority_id="second-root"))
    assert world.repository.append_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": None},
        {"user_id": 999},
        {"is_active": False},
        {"raw_account_type": "substituted"},
        {"namespace": "different"},
        {"row_pk": 999},
    ],
)
def test_live_physical_owner_or_identity_substitution_denies_current(changes):
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    world.physical_changes = changes
    assert service.get_current(_selector(decision)) is None


def test_reused_row_id_future_clock_and_shorter_principal_window_deny_current():
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    physical = world.assignment.subject.physical_root.physical_observation
    world.physical_changes = {"row_created_at": physical.row_created_at + timedelta(microseconds=1)}
    assert service.get_current(_selector(decision)) is None
    world.physical_changes = {"observed_at": world.repository.clock + timedelta(days=1)}
    assert service.get_current(_selector(decision)) is None
    world.physical_changes = {}
    world.participant_limit = world.repository.clock + timedelta(seconds=20)
    assert service.get_current(_selector(decision)).valid_until == world.participant_limit
    world.advance = timedelta(seconds=21)
    assert service.get_current(_selector(decision)) is None


def test_fresh_authentication_cannot_substitute_stable_owner_or_policy():
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    original = world.authentication
    world.authentication = replace(original, user_id=original.user_id + 1)
    assert service.get_current(_selector(decision)) is None
    world.authentication = original
    world.policy = replace(
        world.policy, policy_version="changed", identity_hash="", content_hash=""
    )
    with pytest.raises(OwnerTenantAuthorityV2Corruption):
        service.get_current(_selector(decision))


def test_source_change_during_approval_rolls_back_and_exact_read_cannot_be_live_command():
    world = _World()
    world.change_auth_on_second = True
    with pytest.raises(OwnerTenantAuthorityV2Conflict, match="sources changed"):
        world.service().issue(world.issue_command())
    assert world.repository.root is None
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    with pytest.raises(TypeError, match="live read command"):
        service.get_current(
            GetExactOwnerTenantAuthorityV2Command(
                decision.authority_id,
                decision.authority_version,
                decision.content_hash,
                decision.recorded_at,
            )
        )
    with pytest.raises(OwnerTenantAuthorityV2Conflict):
        service.get_current(replace(_selector(decision), expected_content_hash="f" * 64))


def test_persisted_approval_requires_fresh_actor_at_recording_but_not_at_decision_expiry():
    world = _World()
    decision = world.service().issue(world.issue_command())
    record = world.repository.root
    assert decision.valid_until > record.authentication.valid_until
    with pytest.raises(ValueError, match="authentication"):
        PersistedOwnerTenantAuthorityV2(
            decision, replace(record.authentication, valid_until=decision.recorded_at)
        )


def test_mismatched_transaction_alias_is_rejected_before_source_reads():
    world = _World()
    world.unit_of_work_key = "django:different"
    with pytest.raises(OwnerTenantAuthorityV2Unavailable, match="aliases differ"):
        world.service()
