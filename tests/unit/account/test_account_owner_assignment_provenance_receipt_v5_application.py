"""Unit contracts for ReceiptV5 application persistence and current reads."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5Conflict,
    AccountOwnerAssignmentProvenanceReceiptV5Corruption,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command,
    GetExactAccountOwnerAssignmentProvenanceReceiptV5,
    GetExactAccountOwnerAssignmentProvenanceReceiptV5Command,
    IssueAccountOwnerAssignmentProvenanceReceiptV5,
    IssueAccountOwnerAssignmentProvenanceReceiptV5Command,
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    GetCurrentCanonicalAccountOwnershipReobservationV1Command,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import (
    _receipt,
    _successor,
)


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    """Return one fixed aware test instant."""

    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class _Repository:
    """Minimal in-memory repository with historical and logical-head reads."""

    def __init__(
        self,
        *,
        now: datetime,
        winner: PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None = None,
        exact: PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None = None,
        head: PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None = None,
    ) -> None:
        self.now_value = now
        self.winner = winner
        self.exact = exact
        self.head = head
        self.append_calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        """Return a no-op unit of work for the application contract."""

        return nullcontext()

    def now(self) -> datetime:
        """Return the deterministic repository clock."""

        return self.now_value

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        del receipt_id, receipt_version
        if self.winner is None or self.winner.receipt.recorded_at > as_of:
            return None
        return self.winner

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        del receipt_id
        if self.head is None or self.head.receipt.recorded_at > as_of:
            return None
        return self.head

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV5,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        assert recorded_at == record.receipt.recorded_at
        del expected_predecessor_hash
        self.append_calls += 1
        self.winner = record
        self.head = record
        return record

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        del receipt_id, receipt_version, expected_content_hash
        if self.exact is None or self.exact.receipt.recorded_at > as_of:
            return None
        return self.exact


class _BindingReader:
    """Return one exact permanent BindingV2."""

    def __init__(self, result: object) -> None:
        self.result = result

    def execute(self, command: GetExactCanonicalAccountCreationBindingV2Command) -> object:
        del command
        return self.result


class _PolicyReader:
    """Return all policy heads for the requested scope."""

    def __init__(self, result: tuple[SingleOwnerAuthorityPolicyV1, ...]) -> None:
        self.result = result

    def get_current_for_scope(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
        del account_namespace, account_id, as_of
        return self.result


class _ReobservationReader:
    """Return one exact current ReobservationV1."""

    def __init__(self, result: object) -> None:
        self.result = result

    def execute(self, command: GetCurrentCanonicalAccountOwnershipReobservationV1Command) -> object:
        del command
        return self.result


def _record(
    receipt: AccountOwnerAssignmentProvenanceReceiptV5,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Wrap one V5 receipt with computed durable seals."""

    return PersistedAccountOwnerAssignmentProvenanceReceiptV5(receipt)


def test_issue_replays_first_winner_and_validates_root_or_successor() -> None:
    """Issue appends once, replays once, and accepts a Domain successor."""

    first = _receipt()
    repository = _Repository(now=_at(30))
    issuer = IssueAccountOwnerAssignmentProvenanceReceiptV5(repository)

    assert issuer.execute(IssueAccountOwnerAssignmentProvenanceReceiptV5Command(first)) == first
    assert issuer.execute(IssueAccountOwnerAssignmentProvenanceReceiptV5Command(first)) == first
    assert repository.append_calls == 1

    successor = _successor(first)
    successor_repository = _Repository(now=_at(30), head=_record(first))
    assert (
        IssueAccountOwnerAssignmentProvenanceReceiptV5(successor_repository).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptV5Command(successor, predecessor=first)
        )
        == successor
    )


def test_issue_rejects_future_winner_and_different_first_winner() -> None:
    """Future and conflicting first winners fail closed."""

    first = _receipt()
    future_repository = _Repository(now=_at(14), winner=_record(first))
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5Corruption, match="future"):
        IssueAccountOwnerAssignmentProvenanceReceiptV5(future_repository).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptV5Command(first)
        )

    other = replace(first, receipt_version="v5.9", identity_hash="", content_hash="")
    repository = _Repository(now=_at(30), winner=_record(other))
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5Conflict, match="winner"):
        IssueAccountOwnerAssignmentProvenanceReceiptV5(repository).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptV5Command(first)
        )


def test_exact_is_historical_and_rejects_selector_substitution() -> None:
    """Expired historical exact records remain readable; substitutions fail."""

    first = _receipt()
    repository = _Repository(now=_at(30), exact=_record(first))
    command = GetExactAccountOwnerAssignmentProvenanceReceiptV5Command(
        first.receipt_id, first.receipt_version, first.content_hash, _at(30)
    )
    assert GetExactAccountOwnerAssignmentProvenanceReceiptV5(repository).execute(command) == first

    other = replace(first, receipt_id="different-v5", identity_hash="", content_hash="")
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV5Corruption, match="selector"):
        GetExactAccountOwnerAssignmentProvenanceReceiptV5(
            _Repository(now=_at(30), exact=_record(other))
        ).execute(command)


def test_current_requires_exact_policy_reobservation_and_receipt_head() -> None:
    """Current reads reject policy/re-observation changes and successor fallback."""

    first = _receipt()
    record = _record(first)
    command = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command(
        first.receipt_id, first.receipt_version, first.content_hash, _at(15, 15)
    )
    usecase = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
        repository=_Repository(now=_at(30), exact=record, head=record),
        binding_reader=_BindingReader(first.binding),
        policy_reader=_PolicyReader((first.policy,)),
        reobservation_reader=_ReobservationReader(first.reobservation),
    )
    assert usecase.execute(command) == first

    successor = _successor(first)
    assert (
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
            repository=_Repository(now=_at(30), exact=record, head=_record(successor)),
            binding_reader=_BindingReader(first.binding),
            policy_reader=_PolicyReader((first.policy,)),
            reobservation_reader=_ReobservationReader(first.reobservation),
        ).execute(command)
        is None
    )


@pytest.mark.parametrize("reader_kind", ["binding", "policy", "reobservation"])
def test_current_returns_none_when_a_current_parent_is_unavailable(reader_kind: str) -> None:
    """Unavailable current parent evidence never revives a stale receipt."""

    first = _receipt()
    result: object = first.binding
    policy_result = (first.policy,)
    reobservation_result: object = first.reobservation
    if reader_kind == "binding":
        result = None
    elif reader_kind == "policy":
        policy_result = ()
    else:
        reobservation_result = None
    usecase = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
        repository=_Repository(now=_at(30), exact=_record(first), head=_record(first)),
        binding_reader=_BindingReader(result),
        policy_reader=_PolicyReader(policy_result),
        reobservation_reader=_ReobservationReader(reobservation_result),
    )
    assert (
        usecase.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command(
                first.receipt_id,
                first.receipt_version,
                first.content_hash,
                _at(15, 15),
            )
        )
        is None
    )
