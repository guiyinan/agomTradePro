"""Unit contracts for durable Subject V5 application reads and registration."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5Conflict,
    AccountOwnerAssignmentSubjectV5Corruption,
    GetCurrentAccountOwnerAssignmentSubjectV5,
    GetCurrentAccountOwnerAssignmentSubjectV5Command,
    GetExactAccountOwnerAssignmentSubjectV5,
    GetExactAccountOwnerAssignmentSubjectV5Command,
    PersistedAccountOwnerAssignmentSubjectV5,
    RegisterAccountOwnerAssignmentSubjectV5,
    RegisterAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class _Repository:
    def __init__(
        self,
        *,
        now: datetime,
        winner: object | None = None,
        exact: object | None = None,
    ) -> None:
        self.now_value = now
        self.winner = winner
        self.exact = exact
        self.append_calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.now_value

    def get_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> object | None:
        del subject_id, subject_version, as_of
        return self.winner

    def append(
        self,
        record: PersistedAccountOwnerAssignmentSubjectV5,
        *,
        requested_at: datetime,
    ) -> PersistedAccountOwnerAssignmentSubjectV5:
        assert requested_at == record.subject.requested_at
        self.append_calls += 1
        self.winner = record
        return record

    def get_exact_by_hash(
        self,
        *,
        subject_id: str,
        subject_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> object | None:
        del subject_id, subject_version, expected_content_hash, as_of
        return self.exact


class _ReceiptReader:
    def __init__(self, result: object | None) -> None:
        self.result = result

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command
    ) -> object | None:
        del command
        return self.result


def _record(subject: AccountOwnerAssignmentSubjectV5) -> PersistedAccountOwnerAssignmentSubjectV5:
    return PersistedAccountOwnerAssignmentSubjectV5(subject)


def test_register_appends_once_and_replays_exact_first_winner() -> None:
    """Registration appends one immutable winner and replays its exact envelope."""

    subject = _subject()
    repository = _Repository(now=_at(30))
    usecase = RegisterAccountOwnerAssignmentSubjectV5(repository)
    command = RegisterAccountOwnerAssignmentSubjectV5Command(subject)

    assert usecase.execute(command) == subject
    assert usecase.execute(command) == subject
    assert repository.append_calls == 1


def test_register_rejects_future_and_conflicting_winners() -> None:
    """Repository clocks and first-winner identity remain fail closed."""

    subject = _subject()
    with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption, match="future"):
        RegisterAccountOwnerAssignmentSubjectV5(_Repository(now=_at(14))).execute(
            RegisterAccountOwnerAssignmentSubjectV5Command(subject)
        )

    other = replace(subject, subject_version="v5.9", identity_hash="", content_hash="")
    with pytest.raises(AccountOwnerAssignmentSubjectV5Conflict, match="winner"):
        RegisterAccountOwnerAssignmentSubjectV5(
            _Repository(now=_at(30), winner=_record(other))
        ).execute(RegisterAccountOwnerAssignmentSubjectV5Command(subject))


def test_exact_is_historical_and_rejects_selector_substitution() -> None:
    """Expired subjects remain exact-readable while wrong selectors fail closed."""

    subject = _subject()
    command = GetExactAccountOwnerAssignmentSubjectV5Command(
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
        _at(30),
    )
    assert (
        GetExactAccountOwnerAssignmentSubjectV5(
            _Repository(now=_at(30), exact=_record(subject))
        ).execute(command)
        == subject
    )
    other = replace(subject, subject_id="other-subject-v5", identity_hash="", content_hash="")
    with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption, match="selector"):
        GetExactAccountOwnerAssignmentSubjectV5(
            _Repository(now=_at(30), exact=_record(other))
        ).execute(command)


def test_current_requires_exact_current_receipt() -> None:
    """A subject is current only while its exact Receipt V5 graph is current."""

    subject = _subject()
    command = GetCurrentAccountOwnerAssignmentSubjectV5Command(
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
        _at(15, 14, 45),
    )
    usecase = GetCurrentAccountOwnerAssignmentSubjectV5(
        repository=_Repository(now=_at(30), exact=_record(subject)),
        current_receipt_reader=_ReceiptReader(subject.receipt),
    )
    assert usecase.execute(command) == subject

    unavailable = GetCurrentAccountOwnerAssignmentSubjectV5(
        repository=_Repository(now=_at(30), exact=_record(subject)),
        current_receipt_reader=_ReceiptReader(None),
    )
    assert unavailable.execute(command) is None


def test_current_rejects_receipt_type_and_value_substitution() -> None:
    """Current readers cannot replace the exact V5 receipt type or identity."""

    subject = _subject()
    command = GetCurrentAccountOwnerAssignmentSubjectV5Command(
        subject.subject_id,
        subject.subject_version,
        subject.content_hash,
        _at(15, 14, 45),
    )
    for replacement in (
        object(),
        replace(subject.receipt, receipt_version="v5.9", identity_hash="", content_hash=""),
    ):
        with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption):
            GetCurrentAccountOwnerAssignmentSubjectV5(
                repository=_Repository(now=_at(30), exact=_record(subject)),
                current_receipt_reader=_ReceiptReader(replacement),
            ).execute(command)


def test_repository_record_type_substitution_is_corruption() -> None:
    """Repositories cannot return arbitrary objects as sealed Subject V5 records."""

    subject = _subject()
    with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption, match="record type"):
        GetExactAccountOwnerAssignmentSubjectV5(_Repository(now=_at(30), exact=object())).execute(
            GetExactAccountOwnerAssignmentSubjectV5Command(
                subject.subject_id,
                subject.subject_version,
                subject.content_hash,
                _at(30),
            )
        )
