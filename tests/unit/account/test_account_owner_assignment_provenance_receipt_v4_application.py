"""Unit contracts for policy-bound v4 receipt issuance and current reads."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4Repository,
    CurrentSingleOwnerParticipantsReader,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV4,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command,
    GetExactAccountOwnerAssignmentProvenanceReceiptV4,
    GetExactAccountOwnerAssignmentProvenanceReceiptV4Command,
    IssueAccountOwnerAssignmentProvenanceReceiptV4,
    IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.application.single_owner_actor_authority import CurrentSingleOwnerParticipants
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def _policy(**changes: object) -> SingleOwnerAuthorityPolicyV1:
    binding = _binding()
    values: dict[str, object] = {
        "policy_id": "personal-project",
        "policy_version": "1",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "account_namespace": binding.account_namespace_claim,
        "account_id": binding.account_id_claim,
        "owner_user_id": binding.allocation.requested_row_user_id,
        "authorization_content_hash": "a" * 64,
        "observed_at": _at(8),
        "valid_from": _at(8),
        "valid_until": _at(14),
    }
    values.update(changes)
    return SingleOwnerAuthorityPolicyV1(**values)  # type: ignore[arg-type]


def _authority(
    *,
    actor_id: str = "django-user:42",
    user_id: int = 42,
    source_content_hash: str = "c" * 64,
    recorded_at: datetime = _at(8, 11),
    valid_until: datetime = _at(13),
    is_authenticated: bool = True,
    is_active: bool = True,
    is_staff: bool = True,
    rbac_role: str = "admin",
) -> CurrentAccountActorAuthorityV3:
    return CurrentAccountActorAuthorityV3(
        principal_id="principal-42",
        user_id=user_id,
        authentication_context_hash="b" * 64,
        actor_id=actor_id,
        is_authenticated=is_authenticated,
        is_active=is_active,
        is_staff=is_staff,
        is_superuser=True,
        rbac_role=rbac_role,
        source_id="account-authority-source",
        source_version="v3",
        source_content_hash=source_content_hash,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _participants(
    *,
    policy: SingleOwnerAuthorityPolicyV1 | None = None,
    authority: CurrentAccountActorAuthorityV3 | None = None,
    observed_at: datetime = _at(9),
    valid_until: datetime = _at(13),
) -> CurrentSingleOwnerParticipants:
    current_policy = policy or _policy()
    current_authority = authority or _authority()
    claimant = AccountOwnerAssignmentActor(
        current_authority.actor_id,
        current_authority.user_id,
        "account_owner_claimant",
        is_staff=current_authority.is_staff,
    )
    approver = AccountOwnerAssignmentActor(
        current_authority.actor_id,
        current_authority.user_id,
        "account_owner_assignment_approver",
        is_staff=current_authority.is_staff,
    )
    return CurrentSingleOwnerParticipants(
        current_policy,
        current_authority,
        claimant,
        approver,
        observed_at,
        valid_until,
    )


def _receipt(
    participants: CurrentSingleOwnerParticipants | None = None,
    *,
    receipt_id: str = "creation-claim-7",
    receipt_version: str = "v4.1",
    issued_at: datetime = _at(9),
    recorded_at: datetime = _at(9),
    valid_until: datetime = _at(11),
    supersedes_content_hash: str | None = None,
) -> AccountOwnerAssignmentProvenanceReceiptV4:
    binding = _binding()
    current = participants or _participants()
    physical = binding.creation_root.physical_observation
    return AccountOwnerAssignmentProvenanceReceiptV4(
        receipt_id=receipt_id,
        receipt_version=receipt_version,
        policy=current.policy,
        policy_identity_hash=current.policy.identity_hash,
        policy_content_hash=current.policy.content_hash,
        binding=binding,
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        allocation_identity_hash=binding.allocation.identity_hash,
        allocation_content_hash=binding.allocation.content_hash,
        creation_root_identity_hash=binding.creation_root.identity_hash,
        creation_root_content_hash=binding.creation_root.content_hash,
        binding_identity_hash=binding.identity_hash,
        binding_content_hash=binding.content_hash,
        account_claim_hash=binding.account_claim_hash,
        underlying_claim_hash=binding.underlying_claim_hash,
        physical_observation_content_hash=physical.content_hash,
        physical_source_content_hash=physical.source_content_hash,
        physical_raw_observation_content_hash=physical.raw_observation_content_hash,
        assigned_owner_user_id=current.claimant.user_id,
        claimant=current.claimant,
        issued_at=issued_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
        supersedes_content_hash=supersedes_content_hash,
    )


def _server_actor(actor: AccountOwnerAssignmentActor) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id=actor.actor_id,
        user_id=actor.user_id,
        role=actor.role,
        kind=actor.kind,
        is_staff=actor.is_staff,
    )


class BindingReader:
    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact(self, **kwargs: object) -> object | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class RootReader:
    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> object | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class ParticipantsReader:
    def __init__(self, values: list[object | None], *, align_observation: bool = True) -> None:
        self.values = values
        self.align_observation = align_observation
        self.calls: list[dict[str, object]] = []

    def get_current(self, *, as_of: datetime) -> object | None:
        self.calls.append({"as_of": as_of})
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if (
            value is not None
            and self.align_observation
            and type(value) is CurrentSingleOwnerParticipants
        ):
            return replace(cast(CurrentSingleOwnerParticipants, value), observed_at=as_of)
        return value


class Repository:
    def __init__(
        self,
        *,
        clock: list[datetime] | None = None,
        winner: PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None = None,
        head: PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None = None,
        exact: PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None = None,
    ) -> None:
        self.clock = clock or [_at(9)]
        self.winner = winner
        self.head = head
        self.exact = exact
        self.appended: PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None = None
        self.append_calls: list[dict[str, object]] = []
        self.winner_calls: list[dict[str, object]] = []
        self.head_calls: list[dict[str, object]] = []
        self.exact_calls: list[dict[str, object]] = []

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clock.pop(0) if len(self.clock) > 1 else self.clock[0]

    def get_winner(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.winner_calls.append(kwargs)
        return self.winner

    def get_current_head(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.head_calls.append(kwargs)
        return self.head

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
        self.append_calls.append(
            {
                "record": record,
                "expected_predecessor_hash": expected_predecessor_hash,
                "recorded_at": recorded_at,
            }
        )
        self.appended = self.winner = self.head = self.exact = record
        return record

    def get_exact_by_hash(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.exact_calls.append(kwargs)
        return self.exact


def _command(
    binding: CanonicalAccountCreationBindingV2, **changes: object
) -> IssueAccountOwnerAssignmentProvenanceReceiptV4Command:
    values: dict[str, object] = {
        "receipt_id": "creation-claim-7",
        "receipt_version": "v4.1",
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "expected_binding_content_hash": binding.content_hash,
        "expected_creation_root_content_hash": binding.creation_root.content_hash,
    }
    values.update(changes)
    return IssueAccountOwnerAssignmentProvenanceReceiptV4Command(**values)  # type: ignore[arg-type]


def _issuer(
    bindings: BindingReader,
    roots: RootReader,
    participants: ParticipantsReader,
    repository: Repository,
    *,
    validity_period: timedelta = timedelta(days=2),
) -> IssueAccountOwnerAssignmentProvenanceReceiptV4:
    return IssueAccountOwnerAssignmentProvenanceReceiptV4(
        binding_provider=bindings,
        root_provider=roots,
        participants_reader=participants,
        repository=cast(AccountOwnerAssignmentProvenanceReceiptV4Repository, repository),
        validity_period=validity_period,
    )


def _record(
    participants: CurrentSingleOwnerParticipants | None = None,
    receipt: AccountOwnerAssignmentProvenanceReceiptV4 | None = None,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    current = participants or _participants()
    value = receipt or _receipt(current)
    return PersistedAccountOwnerAssignmentProvenanceReceiptV4(
        value,
        _server_actor(current.claimant),
        current.authority,
    )


def test_persisted_dto_binds_real_staff_actor_and_authority_facts() -> None:
    current = _participants()
    record = _record(current)

    assert record.receipt.claimant.is_staff is True
    assert record.issued_by.user_id == record.authority.user_id == 42
    assert record.issued_by.actor_id == record.authority.actor_id == "django-user:42"
    assert record.authority.rbac_role == "admin"
    assert record.authority.recorded_at <= record.receipt.issued_at
    assert record.receipt.valid_until <= record.authority.valid_until

    with pytest.raises(ValueError, match="actor"):
        PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            record.receipt,
            replace(record.issued_by, actor_id="django-user:7"),
            record.authority,
        )
    with pytest.raises(ValueError, match="authority"):
        PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            record.receipt,
            record.issued_by,
            replace(record.authority, rbac_role="viewer"),
        )
    with pytest.raises(ValueError, match="recorded_at"):
        PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            record.receipt,
            record.issued_by,
            replace(record.authority, recorded_at=record.receipt.issued_at + timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="valid_until"):
        PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            record.receipt,
            record.issued_by,
            replace(
                record.authority, valid_until=record.receipt.valid_until - timedelta(seconds=1)
            ),
        )


def test_commands_are_id_hash_only_and_participants_reader_is_public_protocol() -> None:
    binding = _binding()
    issue = _command(binding)
    exact = GetExactAccountOwnerAssignmentProvenanceReceiptV4Command(
        issue.receipt_id,
        issue.receipt_version,
        "a" * 64,
        _at(9),
    )
    current = GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command(
        issue.receipt_id,
        issue.receipt_version,
        "a" * 64,
        _at(9),
    )
    assert set(issue.__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "binding_id",
        "binding_version",
        "expected_binding_content_hash",
        "expected_creation_root_content_hash",
    }
    assert set(exact.__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "expected_content_hash",
        "as_of",
    }
    assert set(current.__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "expected_content_hash",
        "as_of",
    }
    assert issubclass(type(ParticipantsReader([])), object)
    assert CurrentSingleOwnerParticipantsReader is not None


def test_issue_double_reads_bound_sources_and_caps_all_validity_inputs() -> None:
    binding = _binding()
    root = binding.creation_root
    participants = _participants(observed_at=_at(9))
    bindings = BindingReader([binding, binding])
    roots = RootReader([root, root])
    participant_reader = ParticipantsReader([participants, participants])
    repository = Repository()

    receipt = _issuer(bindings, roots, participant_reader, repository).execute(_command(binding))

    assert len(bindings.calls) == len(roots.calls) == len(participant_reader.calls) == 2
    assert {call["as_of"] for call in bindings.calls} == {_at(9)}
    assert {call["as_of"] for call in roots.calls} == {_at(9)}
    assert receipt.policy == participants.policy
    assert receipt.claimant == participants.claimant
    assert receipt.valid_until <= min(
        participants.policy.valid_until,
        participants.authority.valid_until,
        participants.valid_until,
        root.valid_until,
        binding.allocation.valid_until,
        _at(9) + timedelta(days=2),
    )
    assert repository.append_calls[0]["expected_predecessor_hash"] is None


def test_issue_revalidates_at_latest_clock_and_ignores_reader_observation_timestamp_drift() -> None:
    binding = _binding()
    participants = _participants()
    bindings = BindingReader([binding, binding])
    roots = RootReader([binding.creation_root, binding.creation_root])
    participant_reader = ParticipantsReader([participants, participants])
    later = _at(9) + timedelta(minutes=1)
    repository = Repository(clock=[_at(9), later])

    receipt = _issuer(bindings, roots, participant_reader, repository).execute(_command(binding))

    assert [call["as_of"] for call in participant_reader.calls] == [_at(9), later]
    assert receipt.recorded_at == later


def test_issue_rejects_when_final_clock_passes_cutoff_ttl() -> None:
    binding = _binding()
    current = _participants()

    with pytest.raises(AccountOwnerAssignmentUnavailable, match="expired"):
        _issuer(
            BindingReader([binding, binding]),
            RootReader([binding.creation_root, binding.creation_root]),
            ParticipantsReader([current, current]),
            Repository(clock=[_at(9), _at(9) + timedelta(seconds=2)]),
            validity_period=timedelta(seconds=1),
        ).execute(_command(binding))


def test_issue_rejects_source_drift_and_backwards_repository_clock() -> None:
    binding = _binding()
    first = _participants()
    changed = _participants(
        authority=replace(first.authority, source_content_hash="d" * 64),
    )
    repository = Repository()
    with pytest.raises(AccountOwnerAssignmentConflict, match="changed"):
        _issuer(
            BindingReader([binding, binding]),
            RootReader([binding.creation_root, binding.creation_root]),
            ParticipantsReader([first, changed]),
            repository,
        ).execute(_command(binding))
    assert repository.appended is None

    with pytest.raises(AccountOwnerAssignmentCorruption, match="backwards"):
        _issuer(
            BindingReader([binding, binding]),
            RootReader([binding.creation_root, binding.creation_root]),
            ParticipantsReader([first, first]),
            Repository(clock=[_at(9), _at(8, 23, 59)]),
        ).execute(_command(binding))


def test_winner_replay_rechecks_current_policy_actor_and_auth_source() -> None:
    binding = _binding()
    current = _participants()
    winner = _record(current)
    command = _command(binding)

    replay_repository = Repository(winner=winner, exact=winner, head=winner)
    replay = _issuer(
        BindingReader([binding]),
        RootReader([binding.creation_root]),
        ParticipantsReader([current]),
        replay_repository,
    ).execute(command)
    assert replay == winner.receipt

    revoked_policy = replace(current.policy, status="revoked", identity_hash="", content_hash="")
    with pytest.raises(AccountOwnerAssignmentConflict, match="winner"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([_participants(policy=revoked_policy)]),
            Repository(winner=winner),
        ).execute(command)

    replacement_authority = replace(
        current.authority,
        source_content_hash="d" * 64,
        recorded_at=winner.receipt.issued_at + timedelta(seconds=1),
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="winner"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([_participants(authority=replacement_authority)]),
            Repository(clock=[_at(10)], winner=winner),
        ).execute(command)

    changed_source = _participants(
        authority=replace(current.authority, source_content_hash="d" * 64),
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="winner"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([changed_source]),
            Repository(winner=winner),
        ).execute(command)


def test_issue_rejects_command_root_selector_and_policy_scope_substitution() -> None:
    binding = _binding()
    with pytest.raises(AccountOwnerAssignmentConflict, match="root"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([_participants()]),
            Repository(),
        ).execute(_command(binding, expected_creation_root_content_hash="d" * 64))

    changed_policy = _policy(account_id="account-other")
    with pytest.raises(AccountOwnerAssignmentCorruption, match="scope"):
        _issuer(
            BindingReader([binding, binding]),
            RootReader([binding.creation_root, binding.creation_root]),
            ParticipantsReader(
                [_participants(policy=changed_policy), _participants(policy=changed_policy)]
            ),
            Repository(),
        ).execute(_command(binding))


def test_participants_reader_values_are_strictly_validated_without_post_init() -> None:
    binding = _binding()
    with pytest.raises(AccountOwnerAssignmentCorruption, match="participants"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([{"policy": "single-owner"}]),
            Repository(),
        ).execute(_command(binding))

    future = _participants(observed_at=_at(10))
    with pytest.raises(AccountOwnerAssignmentCorruption, match="observation"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([future], align_observation=False),
            Repository(),
        ).execute(_command(binding))

    with pytest.raises(AccountOwnerAssignmentUnavailable, match="authority"):
        _issuer(
            BindingReader([binding]),
            RootReader([binding.creation_root]),
            ParticipantsReader([_participants(authority=replace(_authority(), is_active=False))]),
            Repository(),
        ).execute(_command(binding))


def test_get_exact_is_historical_and_get_current_rereads_every_live_source() -> None:
    binding = _binding()
    current = _participants()
    record = _record(current)
    repository = Repository(exact=record, head=record)
    exact_reader = BindingReader([binding])
    historical = GetExactAccountOwnerAssignmentProvenanceReceiptV4(
        repository=cast(AccountOwnerAssignmentProvenanceReceiptV4Repository, repository),
        binding_provider=exact_reader,
    ).execute(
        GetExactAccountOwnerAssignmentProvenanceReceiptV4Command(
            record.receipt.receipt_id,
            record.receipt.receipt_version,
            record.receipt.content_hash,
            _at(30),
        )
    )
    assert historical == record.receipt

    participant_reader = ParticipantsReader([current])
    root_reader = RootReader([binding.creation_root])
    live = GetCurrentAccountOwnerAssignmentProvenanceReceiptV4(
        repository=cast(AccountOwnerAssignmentProvenanceReceiptV4Repository, repository),
        binding_provider=BindingReader([binding]),
        root_provider=root_reader,
        participants_reader=participant_reader,
    ).execute(
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command(
            record.receipt.receipt_id,
            record.receipt.receipt_version,
            record.receipt.content_hash,
            _at(9),
        )
    )
    assert live == record.receipt
    assert len(participant_reader.calls) == len(root_reader.calls) == 1


@pytest.mark.parametrize("failure", ["policy", "authority", "root", "head", "source"])
def test_get_current_fails_closed_after_any_live_revalidation_change(failure: str) -> None:
    binding = _binding()
    current = _participants()
    record = _record(current)
    policy_value: CurrentSingleOwnerParticipants | None = current
    if failure == "policy":
        policy_value = None
    elif failure == "authority":
        policy_value = _participants(authority=replace(current.authority, is_active=False))
    elif failure == "source":
        policy_value = _participants(
            authority=replace(current.authority, source_content_hash="d" * 64),
        )
    repository = Repository(exact=record, head=None if failure == "head" else record)
    result = GetCurrentAccountOwnerAssignmentProvenanceReceiptV4(
        repository=cast(AccountOwnerAssignmentProvenanceReceiptV4Repository, repository),
        binding_provider=BindingReader([binding]),
        root_provider=RootReader([None if failure == "root" else binding.creation_root]),
        participants_reader=ParticipantsReader([policy_value]),
    ).execute(
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command(
            record.receipt.receipt_id,
            record.receipt.receipt_version,
            record.receipt.content_hash,
            _at(9),
        )
    )
    assert result is None


def test_get_current_rejects_replaced_authority_without_dto_value_error() -> None:
    binding = _binding()
    current = _participants()
    record = _record(current)
    replacement = _participants(
        authority=replace(
            current.authority,
            source_content_hash="d" * 64,
            recorded_at=record.receipt.issued_at + timedelta(seconds=1),
        )
    )

    result = GetCurrentAccountOwnerAssignmentProvenanceReceiptV4(
        repository=cast(
            AccountOwnerAssignmentProvenanceReceiptV4Repository,
            Repository(exact=record, head=record),
        ),
        binding_provider=BindingReader([binding]),
        root_provider=RootReader([binding.creation_root]),
        participants_reader=ParticipantsReader([replacement]),
    ).execute(
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command(
            record.receipt.receipt_id,
            record.receipt.receipt_version,
            record.receipt.content_hash,
            _at(10),
        )
    )

    assert result is None


def test_get_exact_rejects_repository_record_type_substitution() -> None:
    binding = _binding()
    current = _participants()
    record = _record(current)
    repository = Repository(
        exact=cast(PersistedAccountOwnerAssignmentProvenanceReceiptV4, record.receipt)
    )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="record type"):
        GetExactAccountOwnerAssignmentProvenanceReceiptV4(
            repository=cast(AccountOwnerAssignmentProvenanceReceiptV4Repository, repository),
            binding_provider=BindingReader([binding]),
        ).execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptV4Command(
                record.receipt.receipt_id,
                record.receipt.receipt_version,
                record.receipt.content_hash,
                _at(9),
            )
        )
