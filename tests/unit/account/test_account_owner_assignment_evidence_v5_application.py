"""Unit contracts for the re-observation-backed Evidence V5 Application."""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Repository,
    ApproveAccountOwnerAssignmentEvidenceV5,
    ApproveAccountOwnerAssignmentEvidenceV5Command,
    CurrentAccountOwnerAssignmentSubjectV5Reader,
    CurrentSingleOwnerParticipantsReader,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
    PersistedAccountOwnerAssignmentEvidenceV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    GetCurrentAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4_application import (
    _authority,
)
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    """Return one fixed aware test clock."""

    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def _participants(
    subject: AccountOwnerAssignmentSubjectV5,
    *,
    observed_at: datetime,
    authority: CurrentAccountActorAuthorityV3 | None = None,
    valid_until: datetime = _at(30),
) -> CurrentSingleOwnerParticipants:
    """Build a same-owner staff projection for one Subject V5 policy."""

    current_authority = authority or _authority(valid_until=_at(30))
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
        subject.policy,
        current_authority,
        claimant,
        approver,
        observed_at,
        valid_until,
    )


class _SubjectReader:
    """Return controlled exact-current Subject V5 values."""

    def __init__(self, values: list[object | None]) -> None:
        self.values = values
        self.calls: list[GetCurrentAccountOwnerAssignmentSubjectV5Command] = []

    def execute(self, command: GetCurrentAccountOwnerAssignmentSubjectV5Command) -> object | None:
        self.calls.append(command)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _ParticipantsReader:
    """Return current participants with the reader's requested observation clock."""

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
    """Small in-memory first-winner repository double for Application contracts."""

    def __init__(self, *clocks: datetime) -> None:
        self.clocks = list(clocks)
        self.subject: AccountOwnerAssignmentSubjectV5 | None = None
        self.winner: PersistedAccountOwnerAssignmentEvidenceV5 | None = None
        self.account_head: PersistedAccountOwnerAssignmentEvidenceV5 | None = None
        self.underlying_head: PersistedAccountOwnerAssignmentEvidenceV5 | None = None
        self.append_root_calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        """Return a no-op unit of work for the Application contract."""

        return nullcontext()

    def now(self) -> datetime:
        """Return the next deterministic repository clock."""

        return self.clocks.pop(0) if len(self.clocks) > 1 else self.clocks[0]

    def get_subject_winner(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentSubjectV5 | None:
        """Return the registered Subject when its request is knowable."""

        del subject_id, subject_version
        if self.subject is None or self.subject.requested_at > as_of:
            return None
        return self.subject

    def get_winner(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the first winner once it is knowable."""

        del evidence_id, evidence_version
        if self.winner is None or self.winner.evidence.recorded_at > as_of:
            return None
        return self.winner

    def get_account_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the exact account mapping head."""

        del account_namespace, account_id, as_of
        return self.account_head

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the exact underlying mapping head."""

        del underlying_unified_account_namespace, underlying_unified_account_id, as_of
        return self.underlying_head

    def append_root(
        self,
        record: PersistedAccountOwnerAssignmentEvidenceV5,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5:
        """Persist one root and make it both mapping heads."""

        assert expected_account_head_hash is None
        assert expected_underlying_head_hash is None
        assert recorded_at == record.evidence.recorded_at
        self.append_root_calls += 1
        self.winner = self.account_head = self.underlying_head = record
        return record

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
        """Return the exact historical winner for read contracts."""

        del evidence_id, evidence_version, expected_content_hash
        if self.winner is None or self.winner.evidence.recorded_at > as_of:
            return None
        return self.winner


def _approve_command(
    subject: AccountOwnerAssignmentSubjectV5,
) -> ApproveAccountOwnerAssignmentEvidenceV5Command:
    """Build an ID/hash-only approval selector."""

    return ApproveAccountOwnerAssignmentEvidenceV5Command(
        evidence_id="ownership-evidence-v5-7",
        evidence_version="v5.1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        expected_subject_content_hash=subject.content_hash,
    )


def _use_case(
    repository: _Repository,
    subject: AccountOwnerAssignmentSubjectV5,
    *,
    subject_values: list[object | None] | None = None,
    participant_values: list[object | None] | None = None,
) -> ApproveAccountOwnerAssignmentEvidenceV5:
    """Build the approval use case with controlled current readers."""

    values = participant_values or [
        _participants(subject, observed_at=_at(15, 14, 35)),
        _participants(subject, observed_at=_at(15, 14, 40)),
    ]
    current_subjects = subject_values or [subject, subject]
    return ApproveAccountOwnerAssignmentEvidenceV5(
        subject_reader=cast(
            CurrentAccountOwnerAssignmentSubjectV5Reader,
            _SubjectReader(current_subjects),
        ),
        participants_reader=cast(
            CurrentSingleOwnerParticipantsReader,
            _ParticipantsReader(values),
        ),
        repository=cast(AccountOwnerAssignmentEvidenceV5Repository, repository),
        validity_period=timedelta(days=2),
    )


def test_approve_binds_subject_v5_authority_and_replays_first_winner() -> None:
    """Approval persists one root and replay rechecks the exact current graph."""

    subject = _subject()
    repository = _Repository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    evidence = _use_case(repository, subject).execute(_approve_command(subject))
    assert evidence.subject is subject
    assert evidence.claimant.user_id == evidence.approved_by.user_id == 42
    assert evidence.approved_by.role == "account_owner_assignment_approver"
    assert repository.append_root_calls == 1

    repository.clocks = [_at(15, 14, 45)]
    replay = _use_case(
        repository,
        subject,
        subject_values=[subject],
        participant_values=[_participants(subject, observed_at=_at(15, 14, 45))],
    ).execute(_approve_command(subject))
    assert replay == evidence
    assert repository.append_root_calls == 1


def test_approve_rejects_final_subject_or_participant_drift_before_append() -> None:
    """A changed current parent or authority cannot be silently approved."""

    subject = _subject()
    repository = _Repository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    changed_subject = replace(
        subject,
        subject_version="v5.2",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="selector"):
        _use_case(repository, subject, subject_values=[subject, changed_subject]).execute(
            _approve_command(subject)
        )
    assert repository.append_root_calls == 0

    repository = _Repository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    changed_authority = _authority(
        source_content_hash="d" * 64,
        valid_until=_at(30),
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="approval"):
        _use_case(
            repository,
            subject,
            participant_values=[
                _participants(subject, observed_at=_at(15, 14, 35)),
                _participants(
                    subject,
                    observed_at=_at(15, 14, 40),
                    authority=changed_authority,
                ),
            ],
        ).execute(_approve_command(subject))
    assert repository.append_root_calls == 0


def test_exact_is_historical_while_current_requires_both_mapping_heads() -> None:
    """Historical reads survive expiry; current reads require both exact heads."""

    subject = _subject()
    repository = _Repository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    evidence = _use_case(repository, subject).execute(_approve_command(subject))
    record = cast(PersistedAccountOwnerAssignmentEvidenceV5, repository.winner)

    exact = GetExactAccountOwnerAssignmentEvidenceV5(
        cast(AccountOwnerAssignmentEvidenceV5Repository, repository)
    ).execute(
        GetExactAccountOwnerAssignmentEvidenceV5Command(
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
            _at(30),
        )
    )
    assert exact == evidence

    current = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=cast(
            CurrentAccountOwnerAssignmentSubjectV5Reader,
            _SubjectReader([subject]),
        ),
        participants_reader=cast(
            CurrentSingleOwnerParticipantsReader,
            _ParticipantsReader([_participants(subject, observed_at=_at(15, 14, 45))]),
        ),
        repository=cast(AccountOwnerAssignmentEvidenceV5Repository, repository),
    )
    command = GetCurrentAccountOwnerAssignmentEvidenceV5Command(
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
        _at(15, 14, 45),
    )
    assert current.execute(command) == evidence
    repository.underlying_head = None
    assert current.execute(command) is None
    assert repository.account_head == record


def test_current_fails_closed_on_expiry_and_authority_substitution() -> None:
    """Current reads reject TTL expiry and a changed persisted authority source."""

    subject = _subject()
    repository = _Repository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    evidence = _use_case(repository, subject).execute(_approve_command(subject))
    expired = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=cast(
            CurrentAccountOwnerAssignmentSubjectV5Reader,
            _SubjectReader([subject]),
        ),
        participants_reader=cast(
            CurrentSingleOwnerParticipantsReader,
            _ParticipantsReader([_participants(subject, observed_at=evidence.valid_until)]),
        ),
        repository=cast(AccountOwnerAssignmentEvidenceV5Repository, repository),
    )
    assert (
        expired.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV5Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                evidence.valid_until,
            )
        )
        is None
    )

    changed = _authority(source_content_hash="d" * 64, valid_until=_at(30))
    substituted = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=cast(
            CurrentAccountOwnerAssignmentSubjectV5Reader,
            _SubjectReader([subject]),
        ),
        participants_reader=cast(
            CurrentSingleOwnerParticipantsReader,
            _ParticipantsReader(
                [_participants(subject, observed_at=_at(15, 14, 45), authority=changed)]
            ),
        ),
        repository=cast(AccountOwnerAssignmentEvidenceV5Repository, repository),
    )
    assert (
        substituted.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV5Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                _at(15, 14, 45),
            )
        )
        is None
    )


def test_application_has_no_orm_or_infrastructure_imports_and_uses_subject_v5() -> None:
    """The Application module remains Protocol-only and excludes V4 parents."""

    source = Path("apps/account/application/account_owner_assignment_evidence_v5.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("infrastructure" in name or "django" in name for name in imports)
    assert "apps.account.domain.account_owner_assignment_evidence_v4" not in imports
    assert "apps.account.domain.account_owner_assignment_subject_v5" in imports
