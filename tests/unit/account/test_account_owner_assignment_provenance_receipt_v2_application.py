from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2Conflict,
    AccountOwnerAssignmentProvenanceReceiptV2Corruption,
    AccountOwnerAssignmentProvenanceReceiptV2Unavailable,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV2,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command,
    GetExactAccountOwnerAssignmentProvenanceReceiptV2,
    GetExactAccountOwnerAssignmentProvenanceReceiptV2Command,
    IssueAccountOwnerAssignmentProvenanceReceiptV2,
    IssueAccountOwnerAssignmentProvenanceReceiptV2Command,
    PersistedAccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _row(**changes: object) -> PhysicalAccountRowObservationV2:
    is_active = changes.pop("is_active", True)
    is_present = changes.pop("is_present", True)
    is_tombstone = changes.pop("is_tombstone", False)
    raw = SimulatedAccountRawObservation(
        "raw-7",
        "v1",
        7,
        8,
        "SIMULATED",
        is_active,
        _at(1),
        _at(2),
        is_present,
        is_tombstone,
        _at(3),
        _at(20),
    )
    source = SimulatedAccountRowSourceV2(
        raw.observation_id,
        raw.observation_version,
        "account",
        "0007",
        "simulated-account-row",
        7,
        8,
        "SIMULATED",
        is_active,
        _at(1),
        _at(2),
        is_present,
        is_tombstone,
        _at(3),
        _at(4),
        _at(20),
        _at(12),
        _at(12),
        raw.observation_id,
        raw.observation_version,
        raw.identity_hash,
        raw.content_hash,
        _at(3),
        _at(20),
        None,
    )
    values: dict[str, object] = {
        "observation_id": "physical-7",
        "observation_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": 8,
        "raw_account_type": "SIMULATED",
        "is_active": is_active,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": is_present,
        "is_tombstone": is_tombstone,
        "source_id": source.source_id,
        "source_version": source.source_version,
        "source_identity_hash": source.identity_hash,
        "source_content_hash": source.content_hash,
        "source_supersedes_content_hash": None,
        "source_observed_at": _at(3),
        "source_recorded_at": _at(4),
        "source_valid_until": _at(20),
        "source_ttl_valid_until": _at(12),
        "source_effective_valid_until": _at(12),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_supersedes_content_hash": None,
        "raw_observation_observed_at": _at(3),
        "raw_observation_valid_until": _at(20),
        "recorded_at": _at(5),
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
    }
    values.update(changes)
    return PhysicalAccountRowObservationV2(**values)  # type: ignore[arg-type]


class Provider:
    def __init__(self, rows: list[PhysicalAccountRowObservationV2 | None]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> PhysicalAccountRowObservationV2 | None:
        self.calls.append(kwargs)
        return self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]


class Repository:
    def __init__(self, now: datetime = _at(6)) -> None:
        self.clock = now
        self.winner: PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None = None
        self.head: PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None = None
        self.exact: PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None = None
        self.expected_predecessor_hash: str | None = "unset"

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.winner

    def get_current_head(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.head

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
        self.expected_predecessor_hash = expected_predecessor_hash
        self.winner = self.head = self.exact = record
        return record

    def get_exact_by_hash(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.exact


def _actor(
    user_id: int = 8,
    role: str = "account_owner_claimant",
    *,
    staff: bool = False,
) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(f"human-{user_id}", user_id, role, is_staff=staff)


def _command(
    row: PhysicalAccountRowObservationV2, **changes: object
) -> IssueAccountOwnerAssignmentProvenanceReceiptV2Command:
    values: dict[str, object] = {
        "receipt_id": "claim-7",
        "receipt_version": "v1",
        "provenance_kind": "creation",
        "row_observation_id": row.observation_id,
        "row_observation_version": row.observation_version,
        "expected_row_observation_content_hash": row.content_hash,
    }
    values.update(changes)
    return IssueAccountOwnerAssignmentProvenanceReceiptV2Command(**values)  # type: ignore[arg-type]


def _issuer(
    provider: Provider, repository: Repository, actor: AccountOwnerAssignmentServerActor
) -> IssueAccountOwnerAssignmentProvenanceReceiptV2:
    return IssueAccountOwnerAssignmentProvenanceReceiptV2(
        row_provider=provider,
        repository=repository,
        actor=actor,
        validity_period=timedelta(days=2),
    )


def test_command_is_strictly_id_hash_only_and_expected_hash_is_forwarded() -> None:
    row = _row()
    command = _command(row)
    assert set(command.__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "provenance_kind",
        "row_observation_id",
        "row_observation_version",
        "expected_row_observation_content_hash",
    }
    provider, repository = Provider([row]), Repository()
    receipt = _issuer(provider, repository, _actor()).execute(command)
    assert receipt.row_observation_content_hash == row.content_hash
    assert provider.calls[0]["expected_content_hash"] == row.content_hash
    assert len(provider.calls) == 2
    assert provider.calls[0]["as_of"] == provider.calls[1]["as_of"] == _at(6)


def test_provider_substitution_and_same_cutoff_drift_fail_closed() -> None:
    row = _row()
    substituted = _row(observation_id="other")
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Corruption):
        _issuer(Provider([substituted]), Repository(), _actor()).execute(_command(row))
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Unavailable):
        _issuer(Provider([row, None]), Repository(), _actor()).execute(_command(row))


@pytest.mark.parametrize(
    ("row", "now"),
    [
        (_row(is_active=False), _at(6)),
        (_row(is_present=False, is_tombstone=True, is_active=False), _at(6)),
        (_row(), _at(10)),
    ],
)
def test_terminal_inactive_and_expired_rows_are_unavailable(
    row: PhysicalAccountRowObservationV2, now: datetime
) -> None:
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Unavailable):
        _issuer(Provider([row]), Repository(now), _actor()).execute(_command(row))


def test_actor_matrix_creation_manual_and_migration() -> None:
    row = _row()
    creation_repository = Repository()
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Unavailable):
        _issuer(Provider([row]), creation_repository, _actor(9)).execute(_command(row))
    assert creation_repository.winner is None
    manual = _issuer(Provider([row]), Repository(), _actor(9)).execute(
        _command(row, provenance_kind="manual_reclaim")
    )
    assert manual.assigned_owner_user_id == 9
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Unavailable):
        _issuer(
            Provider([row]),
            Repository(),
            _actor(9, "legacy_assignment_reviewer"),
        ).execute(_command(row, provenance_kind="migration"))
    migration = _issuer(
        Provider([row]),
        Repository(),
        _actor(9, "legacy_assignment_reviewer", staff=True),
    ).execute(_command(row, provenance_kind="migration"))
    assert migration.assigned_owner_user_id is None


def test_first_winner_is_actor_bound_and_must_remain_logical_head() -> None:
    row = _row()
    repository = Repository()
    receipt = _issuer(Provider([row]), repository, _actor()).execute(_command(row))
    assert repository.expected_predecessor_hash is None
    assert _issuer(Provider([row]), repository, _actor()).execute(_command(row)) == receipt
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Conflict):
        _issuer(Provider([row]), repository, _actor(9)).execute(
            _command(row, provenance_kind="manual_reclaim")
        )
    repository.head = None
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Conflict):
        _issuer(Provider([row]), repository, _actor()).execute(_command(row))


def test_successor_uses_head_cas() -> None:
    row = _row()
    repository = Repository()
    first = _issuer(Provider([row]), repository, _actor()).execute(_command(row))
    repository.winner = None
    repository.clock = _at(7)
    second = _issuer(Provider([row]), repository, _actor()).execute(
        _command(row, receipt_version="v2")
    )
    assert second.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessor_hash == first.content_hash


def test_exact_and_closed_current_revalidate_upstream_and_never_fallback() -> None:
    row = _row()
    repository = Repository()
    receipt = _issuer(Provider([row]), repository, _actor()).execute(_command(row))
    exact = GetExactAccountOwnerAssignmentProvenanceReceiptV2(
        repository=repository, row_provider=Provider([row])
    ).execute(
        GetExactAccountOwnerAssignmentProvenanceReceiptV2Command(
            receipt.receipt_id, receipt.receipt_version, receipt.content_hash, _at(7)
        )
    )
    assert exact == receipt
    current = GetCurrentAccountOwnerAssignmentProvenanceReceiptV2(
        repository=repository, row_provider=Provider([row])
    ).execute(GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command(receipt, _at(7)))
    assert current == receipt
    assert (
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV2(
            repository=repository, row_provider=Provider([None])
        ).execute(GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command(receipt, _at(7)))
        is None
    )
