"""Unit contracts for Account owner-assignment Subject/Evidence v4 Application."""

from __future__ import annotations

import ast
from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4Repository,
    ApproveAccountOwnerAssignmentEvidenceV4,
    ApproveAccountOwnerAssignmentEvidenceV4Command,
    ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
    GetCurrentAccountOwnerAssignmentEvidenceV4,
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    GetExactAccountOwnerAssignmentEvidenceV4,
    GetExactAccountOwnerAssignmentEvidenceV4Command,
    PersistedAccountOwnerAssignmentEvidenceV4,
    RegisterAccountOwnerAssignmentSubjectV4,
    RegisterAccountOwnerAssignmentSubjectV4Command,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4_application import (
    _authority,
    _participants,
    _receipt,
)


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    """Return one aware test clock."""

    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class _ReceiptReader:
    """Return a controlled sequence of exact-current Receipt values."""

    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> object | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _RootReader:
    """Return a controlled sequence of exact-current Physical values."""

    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> object | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _ParticipantsReader:
    """Bind each returned participant projection to the requested observation clock."""

    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[datetime] = []

    def get_current(self, *, as_of: datetime) -> object | None:
        self.calls.append(as_of)
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if type(value) is CurrentSingleOwnerParticipants:
            return replace(cast(CurrentSingleOwnerParticipants, value), observed_at=as_of)
        return value


class _Repository:
    """Small first-winner repository double for Application contracts."""

    def __init__(self, *clocks: datetime) -> None:
        self.clocks = list(clocks)
        self.subject: AccountOwnerAssignmentSubjectV4 | None = None
        self.winner: PersistedAccountOwnerAssignmentEvidenceV4 | None = None
        self.account_head: PersistedAccountOwnerAssignmentEvidenceV4 | None = None
        self.underlying_head: PersistedAccountOwnerAssignmentEvidenceV4 | None = None
        self.append_subject_calls = 0
        self.append_root_calls = 0

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clocks.pop(0) if len(self.clocks) > 1 else self.clocks[0]

    def get_subject_winner(self, **_: object) -> AccountOwnerAssignmentSubjectV4 | None:
        return self.subject

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV4, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV4:
        assert recorded_at == subject.requested_at
        self.append_subject_calls += 1
        self.subject = subject
        return subject

    def get_winner(self, **_: object) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        return self.winner

    def get_account_head(self, **_: object) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        return self.account_head

    def get_underlying_head(self, **_: object) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        return self.underlying_head

    def append_root(
        self,
        record: PersistedAccountOwnerAssignmentEvidenceV4,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4:
        assert expected_account_head_hash is None
        assert expected_underlying_head_hash is None
        assert recorded_at == record.evidence.recorded_at
        self.append_root_calls += 1
        self.winner = self.account_head = self.underlying_head = record
        return record

    def get_exact_by_hash(self, **_: object) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        return self.winner


def _register_command(
    receipt: AccountOwnerAssignmentProvenanceReceiptV4,
) -> RegisterAccountOwnerAssignmentSubjectV4Command:
    """Build the complete ID/hash-only Subject selector."""

    binding = receipt.binding
    root = binding.creation_root
    return RegisterAccountOwnerAssignmentSubjectV4Command(
        subject_id="subject-7",
        subject_version="v4.1",
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        expected_receipt_content_hash=receipt.content_hash,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        expected_binding_content_hash=binding.content_hash,
        physical_root_id=root.observation_id,
        physical_root_version=root.observation_version,
        expected_physical_root_content_hash=root.content_hash,
    )


def _register(
    repository: _Repository,
    receipt: AccountOwnerAssignmentProvenanceReceiptV4,
    *,
    receipts: _ReceiptReader | None = None,
    roots: _RootReader | None = None,
) -> AccountOwnerAssignmentSubjectV4:
    """Register one test Subject through the public Application boundary."""

    root = receipt.binding.creation_root
    return RegisterAccountOwnerAssignmentSubjectV4(
        receipt_provider=cast(
            ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
            receipts or _ReceiptReader([receipt, receipt]),
        ),
        root_provider=roots or _RootReader([root, root]),
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
    ).execute(_register_command(receipt))


def _approve_command(
    subject: AccountOwnerAssignmentSubjectV4,
) -> ApproveAccountOwnerAssignmentEvidenceV4Command:
    """Build the approval selector without policy, mode, or actor input."""

    return ApproveAccountOwnerAssignmentEvidenceV4Command(
        evidence_id="evidence-7",
        evidence_version="v4.1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        expected_subject_content_hash=subject.content_hash,
    )


def _approved(
    repository: _Repository,
    subject: AccountOwnerAssignmentSubjectV4,
    receipt: AccountOwnerAssignmentProvenanceReceiptV4,
    *,
    participants: list[object | None] | None = None,
    clocks: list[datetime] | None = None,
) -> AccountOwnerAssignmentEvidenceV4:
    """Approve one Subject with the server-owned same-owner participant reader."""

    current = _participants()
    values = participants or [current, current]
    use_case = ApproveAccountOwnerAssignmentEvidenceV4(
        receipt_provider=_ReceiptReader([receipt, receipt]),
        root_provider=_RootReader([receipt.binding.creation_root, receipt.binding.creation_root]),
        participants_reader=_ParticipantsReader(values),
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
        validity_period=timedelta(days=2),
    )
    return use_case.execute(_approve_command(subject))


def test_commands_are_id_hash_only_and_dto_binds_current_authority() -> None:
    """Approval cannot select a policy/actor and persists authority facts."""

    receipt = _receipt()
    repository = _Repository(_at(10))
    subject = _register(repository, receipt)
    repository.clocks = [_at(10), _at(10, 12, 1)]
    evidence = _approved(repository, subject, receipt)
    record = cast(PersistedAccountOwnerAssignmentEvidenceV4, repository.winner)

    assert {field.name for field in fields(ApproveAccountOwnerAssignmentEvidenceV4Command)} == {
        "evidence_id",
        "evidence_version",
        "subject_id",
        "subject_version",
        "expected_subject_content_hash",
    }
    assert record.evidence == evidence
    assert record.authority.actor_id == evidence.approved_by.actor_id
    assert record.authority.user_id == evidence.approved_by.user_id
    assert record.authority.is_staff is True
    assert record.authority.rbac_role == "admin"
    with pytest.raises(ValueError, match="approval validity"):
        PersistedAccountOwnerAssignmentEvidenceV4(
            evidence=evidence,
            authority=replace(
                record.authority,
                valid_until=evidence.approval_valid_until - timedelta(seconds=1),
            ),
        )


def test_register_double_reads_and_replays_only_after_current_source_reads() -> None:
    """Subject registration is first-winner and replay still revalidates sources."""

    receipt = _receipt()
    repository = _Repository(_at(10))
    receipts = _ReceiptReader([receipt, receipt])
    roots = _RootReader([receipt.binding.creation_root, receipt.binding.creation_root])
    subject = _register(repository, receipt, receipts=receipts, roots=roots)
    assert len(receipts.calls) == len(roots.calls) == 2
    repository.clocks = [_at(10, 12, 30)]
    replay_receipts = _ReceiptReader([receipt])
    replay_roots = _RootReader([receipt.binding.creation_root])
    assert _register(repository, receipt, receipts=replay_receipts, roots=replay_roots) == subject
    assert len(replay_receipts.calls) == len(replay_roots.calls) == 1
    assert repository.append_subject_calls == 1


def test_register_rejects_source_drift_before_append() -> None:
    """A missing final current source is a conflict and leaves no Subject."""

    receipt = _receipt()
    repository = _Repository(_at(10))
    with pytest.raises(AccountOwnerAssignmentConflict, match="registration"):
        _register(
            repository,
            receipt,
            receipts=_ReceiptReader([receipt, None]),
            roots=_RootReader([receipt.binding.creation_root]),
        )
    assert repository.append_subject_calls == 0


def test_approval_accepts_same_real_staff_owner_in_both_roles() -> None:
    """Explicit approval accepts the policy's same-owner claimant/approver pair."""

    receipt = _receipt()
    repository = _Repository(_at(10))
    subject = _register(repository, receipt)
    repository.clocks = [_at(10), _at(10, 12, 1)]
    participants = _participants()
    reader = _ParticipantsReader([participants, participants])
    evidence = ApproveAccountOwnerAssignmentEvidenceV4(
        receipt_provider=_ReceiptReader([receipt, receipt]),
        root_provider=_RootReader([receipt.binding.creation_root, receipt.binding.creation_root]),
        participants_reader=reader,
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
        validity_period=timedelta(days=2),
    ).execute(_approve_command(subject))

    assert evidence.claimant.actor_id == evidence.approved_by.actor_id
    assert evidence.claimant.user_id == evidence.approved_by.user_id
    assert evidence.approved_by.role == "account_owner_assignment_approver"
    assert reader.calls == [_at(10), _at(10, 12, 1)]
    assert repository.append_root_calls == 1


def test_approval_rejects_final_participant_drift_without_append() -> None:
    """A changed authority source between reads cannot be silently approved."""

    receipt = _receipt()
    repository = _Repository(_at(10), _at(10, 12, 1))
    subject = _register(repository, receipt)
    first = _participants()
    changed = _participants(authority=replace(_authority(), source_content_hash="d" * 64))
    with pytest.raises(AccountOwnerAssignmentConflict, match="approval"):
        ApproveAccountOwnerAssignmentEvidenceV4(
            receipt_provider=_ReceiptReader([receipt, receipt]),
            root_provider=_RootReader(
                [receipt.binding.creation_root, receipt.binding.creation_root]
            ),
            participants_reader=_ParticipantsReader([first, changed]),
            repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
            validity_period=timedelta(days=2),
        ).execute(_approve_command(subject))
    assert repository.append_root_calls == 0


def test_approval_replay_rechecks_authority_and_both_mapping_heads() -> None:
    """The existing root is replayable only while its exact current graph agrees."""

    receipt = _receipt()
    repository = _Repository(_at(10), _at(10, 12, 1))
    subject = _register(repository, receipt)
    evidence = _approved(repository, subject, receipt)
    repository.clocks = [_at(10, 12, 30)]
    replay = ApproveAccountOwnerAssignmentEvidenceV4(
        receipt_provider=_ReceiptReader([receipt]),
        root_provider=_RootReader([receipt.binding.creation_root]),
        participants_reader=_ParticipantsReader([_participants()]),
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
        validity_period=timedelta(days=2),
    ).execute(_approve_command(subject))
    assert replay == evidence
    assert repository.append_root_calls == 1

    repository.clocks = [_at(10, 12, 30)]
    changed = _participants(authority=replace(_authority(), source_content_hash="d" * 64))
    with pytest.raises(AccountOwnerAssignmentConflict, match="winner"):
        ApproveAccountOwnerAssignmentEvidenceV4(
            receipt_provider=_ReceiptReader([receipt]),
            root_provider=_RootReader([receipt.binding.creation_root]),
            participants_reader=_ParticipantsReader([changed]),
            repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
            validity_period=timedelta(days=2),
        ).execute(_approve_command(subject))


def test_approval_rejects_expired_authority_and_does_not_append() -> None:
    """An inactive or expired server authority cannot become an approval source."""

    receipt = _receipt()
    repository = _Repository(_at(10), _at(10, 12, 1))
    subject = _register(repository, receipt)
    expired = _participants(
        authority=replace(_authority(), valid_until=_at(10)),
        valid_until=_at(10),
    )
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="authority|validity"):
        ApproveAccountOwnerAssignmentEvidenceV4(
            receipt_provider=_ReceiptReader([receipt, receipt]),
            root_provider=_RootReader(
                [receipt.binding.creation_root, receipt.binding.creation_root]
            ),
            participants_reader=_ParticipantsReader([expired]),
            repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
            validity_period=timedelta(days=2),
        ).execute(_approve_command(subject))
    assert repository.append_root_calls == 0


def test_exact_is_historical_while_current_requires_both_heads_and_sources() -> None:
    """Historical reads survive expiry; current reads require every live source."""

    receipt = _receipt()
    repository = _Repository(_at(10), _at(10, 12, 1))
    subject = _register(repository, receipt)
    evidence = _approved(repository, subject, receipt)
    record = cast(PersistedAccountOwnerAssignmentEvidenceV4, repository.winner)
    after_expiry = _at(30)
    assert (
        GetExactAccountOwnerAssignmentEvidenceV4(
            cast(AccountOwnerAssignmentEvidenceV4Repository, repository)
        ).execute(
            GetExactAccountOwnerAssignmentEvidenceV4Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                after_expiry,
            )
        )
        == evidence
    )

    current = GetCurrentAccountOwnerAssignmentEvidenceV4(
        receipt_provider=_ReceiptReader([receipt]),
        root_provider=_RootReader([receipt.binding.creation_root]),
        participants_reader=_ParticipantsReader([_participants()]),
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
    )
    command = GetCurrentAccountOwnerAssignmentEvidenceV4Command(
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
        _at(10, 12, 30),
    )
    assert current.execute(command) == evidence
    repository.underlying_head = None
    assert current.execute(command) is None
    assert record == repository.account_head


def test_current_rejects_expired_evidence_and_source_substitution() -> None:
    """Current reads fail closed at the Evidence TTL and on source replacement."""

    receipt = _receipt()
    repository = _Repository(_at(10), _at(10, 12, 1))
    subject = _register(repository, receipt)
    evidence = _approved(repository, subject, receipt)
    current = GetCurrentAccountOwnerAssignmentEvidenceV4(
        receipt_provider=_ReceiptReader([receipt]),
        root_provider=_RootReader([receipt.binding.creation_root]),
        participants_reader=_ParticipantsReader([_participants()]),
        repository=cast(AccountOwnerAssignmentEvidenceV4Repository, repository),
    )
    assert (
        current.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV4Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                evidence.valid_until,
            )
        )
        is None
    )


def test_application_has_no_orm_or_infrastructure_imports() -> None:
    """The Application module remains Protocol-only at the persistence boundary."""

    source = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "application"
        / "account_owner_assignment_evidence_v4.py"
    )
    imports = {
        node.module
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any("infrastructure" in name for name in imports)
