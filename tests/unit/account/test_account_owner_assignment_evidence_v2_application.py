from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2Conflict,
    AccountOwnerAssignmentEvidenceV2Corruption,
    AccountOwnerAssignmentEvidenceV2Unavailable,
    ApproveAccountOwnerAssignmentEvidenceV2,
    ApproveAccountOwnerAssignmentEvidenceV2Command,
    GetCurrentAccountOwnerAssignmentEvidenceV2,
    GetCurrentAccountOwnerAssignmentEvidenceV2Command,
    GetExactAccountOwnerAssignmentEvidenceV2,
    GetExactAccountOwnerAssignmentEvidenceV2Command,
    RegisterAccountOwnerAssignmentSubjectV2,
    RegisterAccountOwnerAssignmentSubjectV2Command,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v2 import (
    _receipt,
    _row,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _PhysicalProvider:
    def __init__(self, values: list[PhysicalAccountRowObservationV2 | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, str, str, datetime]] = []

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None:
        self.calls.append((observation_id, observation_version, expected_content_hash, as_of))
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _ReceiptProvider:
    def __init__(self, values: list[AccountOwnerAssignmentProvenanceReceiptV2 | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, str, str, datetime]] = []

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV2 | None:
        self.calls.append((receipt_id, receipt_version, expected_content_hash, as_of))
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _Repository:
    def __init__(self, now: datetime) -> None:
        self.clock = now
        self.subject: AccountOwnerAssignmentSubjectV2 | None = None
        self.winner: AccountOwnerAssignmentEvidenceV2 | None = None
        self.account_head: AccountOwnerAssignmentEvidenceV2 | None = None
        self.underlying_head: AccountOwnerAssignmentEvidenceV2 | None = None
        self.append_subject_calls = 0
        self.append_calls = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return self.clock

    def get_subject_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV2 | None:
        return self.subject

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV2, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV2:
        self.append_subject_calls += 1
        if self.subject is None:
            self.subject = subject
        return self.subject

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        return self.winner

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        return self.account_head

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        return self.underlying_head

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidenceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2:
        self.append_calls += 1
        if self.winner is None:
            self.winner = evidence
            self.account_head = evidence
            self.underlying_head = evidence
        return self.winner

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        value = self.winner
        if (
            value is None
            or value.evidence_id != evidence_id
            or value.evidence_version != evidence_version
            or value.content_hash != expected_content_hash
            or value.recorded_at > as_of
        ):
            return None
        return value


def _register_command(
    row: PhysicalAccountRowObservationV2,
    receipt: AccountOwnerAssignmentProvenanceReceiptV2,
) -> RegisterAccountOwnerAssignmentSubjectV2Command:
    return RegisterAccountOwnerAssignmentSubjectV2Command(
        "assignment-7",
        "v1",
        row.observation_id,
        row.observation_version,
        row.content_hash,
        receipt.receipt_id,
        receipt.receipt_version,
        receipt.content_hash,
    )


def _registered(
    repository: _Repository,
    row: PhysicalAccountRowObservationV2,
    receipt: AccountOwnerAssignmentProvenanceReceiptV2,
) -> AccountOwnerAssignmentSubjectV2:
    return RegisterAccountOwnerAssignmentSubjectV2(
        physical_provider=_PhysicalProvider([row]),
        receipt_provider=_ReceiptProvider([receipt]),
        repository=repository,
    ).execute(_register_command(row, receipt))


def _approver(actor_id: str = "approver-9", user_id: int = 9) -> AccountOwnerAssignmentActor:
    return AccountOwnerAssignmentActor(
        actor_id, user_id, "account_owner_assignment_approver", is_staff=True
    )


def test_register_command_is_id_hash_only() -> None:
    assert {field.name for field in fields(RegisterAccountOwnerAssignmentSubjectV2Command)} == {
        "evidence_id",
        "evidence_version",
        "physical_observation_id",
        "physical_observation_version",
        "expected_physical_content_hash",
        "receipt_id",
        "receipt_version",
        "expected_receipt_content_hash",
    }
    assert {field.name for field in fields(ApproveAccountOwnerAssignmentEvidenceV2Command)} == {
        "evidence_id",
        "evidence_version",
        "expected_subject_content_hash",
    }


def test_register_double_reads_and_replays_first_winner() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    physical = _PhysicalProvider([row, row, row, row])
    receipts = _ReceiptProvider([receipt, receipt, receipt, receipt])
    use_case = RegisterAccountOwnerAssignmentSubjectV2(
        physical_provider=physical, receipt_provider=receipts, repository=repository
    )
    first = use_case.execute(_register_command(row, receipt))
    replay = use_case.execute(_register_command(row, receipt))
    assert replay == first and repository.append_subject_calls == 1
    assert len(physical.calls) == len(receipts.calls) == 4


def test_register_rejects_same_cutoff_upstream_drift_before_append() -> None:
    row, receipt = _row(), _receipt()
    changed = replace(receipt, valid_until=_at(8), content_hash="")
    repository = _Repository(_at(7))
    use_case = RegisterAccountOwnerAssignmentSubjectV2(
        physical_provider=_PhysicalProvider([row, row]),
        receipt_provider=_ReceiptProvider([receipt, changed]),
        repository=repository,
    )
    with pytest.raises(
        (AccountOwnerAssignmentEvidenceV2Conflict, AccountOwnerAssignmentEvidenceV2Corruption)
    ):
        use_case.execute(_register_command(row, receipt))
    assert repository.append_subject_calls == 0


def test_staff_approval_creates_dual_head_and_actor_bound_replay() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    subject = _registered(repository, row, receipt)
    use_case = ApproveAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([row, row, row, row]),
        receipt_provider=_ReceiptProvider([receipt, receipt, receipt, receipt]),
        repository=repository,
        approver=_approver(),
        validity_period=timedelta(days=2),
    )
    command = ApproveAccountOwnerAssignmentEvidenceV2Command(
        subject.subject_id, subject.subject_version, subject.content_hash
    )
    first = use_case.execute(command)
    replay = use_case.execute(command)
    assert replay == first and repository.append_calls == 1
    assert repository.account_head == repository.underlying_head == first


def test_approval_rejects_self_approval_and_split_heads() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    subject = _registered(repository, row, receipt)
    command = ApproveAccountOwnerAssignmentEvidenceV2Command(
        subject.subject_id, subject.subject_version, subject.content_hash
    )
    self_approver = AccountOwnerAssignmentActor(
        receipt.claimant.actor_id,
        receipt.claimant.user_id,
        "account_owner_assignment_approver",
        is_staff=True,
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Unavailable, match="independent"):
        ApproveAccountOwnerAssignmentEvidenceV2(
            physical_provider=_PhysicalProvider([row, row]),
            receipt_provider=_ReceiptProvider([receipt, receipt]),
            repository=repository,
            approver=self_approver,
            validity_period=timedelta(days=1),
        ).execute(command)
    assert repository.append_calls == 0

    repository.account_head = AccountOwnerAssignmentEvidenceV2(
        evidence_id=subject.subject_id,
        evidence_version=subject.subject_version,
        subject=subject,
        assignment_state="authoritative",
        assigned_owner_user_id=8,
        approved_by=_approver(),
        approved_at=_at(7),
        recorded_at=_at(7),
        approval_valid_until=_at(8),
        valid_until=_at(8),
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Corruption, match="heads"):
        ApproveAccountOwnerAssignmentEvidenceV2(
            physical_provider=_PhysicalProvider([row, row]),
            receipt_provider=_ReceiptProvider([receipt, receipt]),
            repository=repository,
            approver=_approver(),
            validity_period=timedelta(days=1),
        ).execute(command)


def test_different_approver_cannot_replay_existing_winner() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    subject = _registered(repository, row, receipt)
    command = ApproveAccountOwnerAssignmentEvidenceV2Command(
        subject.subject_id, subject.subject_version, subject.content_hash
    )
    first = ApproveAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([row, row]),
        receipt_provider=_ReceiptProvider([receipt, receipt]),
        repository=repository,
        approver=_approver(),
        validity_period=timedelta(days=1),
    )
    first.execute(command)
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Conflict, match="another approver"):
        ApproveAccountOwnerAssignmentEvidenceV2(
            physical_provider=_PhysicalProvider([row, row]),
            receipt_provider=_ReceiptProvider([receipt, receipt]),
            repository=repository,
            approver=_approver("approver-10", 10),
            validity_period=timedelta(days=1),
        ).execute(command)


def test_exact_historical_and_closed_current_reads_are_separate() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    subject = _registered(repository, row, receipt)
    evidence = ApproveAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([row, row]),
        receipt_provider=_ReceiptProvider([receipt, receipt]),
        repository=repository,
        approver=_approver(),
        validity_period=timedelta(days=1),
    ).execute(
        ApproveAccountOwnerAssignmentEvidenceV2Command(
            subject.subject_id, subject.subject_version, subject.content_hash
        )
    )
    assert (
        GetExactAccountOwnerAssignmentEvidenceV2(repository).execute(
            GetExactAccountOwnerAssignmentEvidenceV2Command(
                evidence.evidence_id, evidence.evidence_version, evidence.content_hash, _at(7)
            )
        )
        == evidence
    )
    current = GetCurrentAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([row]),
        receipt_provider=_ReceiptProvider([receipt]),
        repository=repository,
    )
    assert (
        current.execute(GetCurrentAccountOwnerAssignmentEvidenceV2Command(evidence, _at(7)))
        == evidence
    )
    repository.underlying_head = None
    assert (
        current.execute(GetCurrentAccountOwnerAssignmentEvidenceV2Command(evidence, _at(7))) is None
    )


def test_current_read_fails_closed_when_upstream_is_no_longer_current() -> None:
    row, receipt = _row(), _receipt()
    repository = _Repository(_at(7))
    subject = _registered(repository, row, receipt)
    evidence = ApproveAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([row, row]),
        receipt_provider=_ReceiptProvider([receipt, receipt]),
        repository=repository,
        approver=_approver(),
        validity_period=timedelta(days=1),
    ).execute(
        ApproveAccountOwnerAssignmentEvidenceV2Command(
            subject.subject_id, subject.subject_version, subject.content_hash
        )
    )
    reader = GetCurrentAccountOwnerAssignmentEvidenceV2(
        physical_provider=_PhysicalProvider([None]),
        receipt_provider=_ReceiptProvider([receipt]),
        repository=repository,
    )
    assert (
        reader.execute(GetCurrentAccountOwnerAssignmentEvidenceV2Command(evidence, _at(7))) is None
    )
