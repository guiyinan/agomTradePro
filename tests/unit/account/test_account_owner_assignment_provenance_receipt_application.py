"""Pure tests for the Account owner-assignment provenance receipt workflow."""

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptConflict,
    AccountOwnerAssignmentProvenanceReceiptCorruption,
    AccountOwnerAssignmentProvenanceReceiptRepository,
    AccountOwnerAssignmentProvenanceReceiptUnavailable,
    ExactCurrentPhysicalAccountRowObservationProvider,
    GetCurrentAccountOwnerAssignmentProvenanceReceipt,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand,
    GetExactAccountOwnerAssignmentProvenanceReceipt,
    GetExactAccountOwnerAssignmentProvenanceReceiptCommand,
    IssueAccountOwnerAssignmentProvenanceReceipt,
    IssueAccountOwnerAssignmentProvenanceReceiptCommand,
    PersistedAccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _actor(**changes: object) -> AccountOwnerAssignmentServerActor:
    values: dict[str, object] = {
        "actor_id": "claimant:19",
        "user_id": 19,
        "role": "account_owner_claimant",
        "kind": "human",
        "is_staff": False,
    }
    values.update(changes)
    return AccountOwnerAssignmentServerActor(**values)  # type: ignore[arg-type]


def _migration_actor(**changes: object) -> AccountOwnerAssignmentServerActor:
    values: dict[str, object] = {
        "actor_id": "migration-reviewer:23",
        "user_id": 23,
        "role": "legacy_assignment_reviewer",
        "kind": "human",
        "is_staff": True,
    }
    values.update(changes)
    return AccountOwnerAssignmentServerActor(**values)  # type: ignore[arg-type]


def _row(**changes: object) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": "physical-account-row-7",
        "observation_version": "physical-account-row.v1",
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "raw_source_owner": "simulated_trading",
        "raw_source_artifact_type": "simulated_account_row",
        "raw_source_id": "simulated-account-row-7",
        "raw_source_version": "simulated-account-row.v1",
        "raw_source_content_hash": HASH_A,
        "row_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=10),
        "row_updated_at": NOW - timedelta(minutes=4),
        "observed_at": NOW - timedelta(minutes=3),
        "recorded_at": NOW - timedelta(minutes=2),
        "raw_source_valid_until": NOW + timedelta(days=30),
        "ttl_valid_until": NOW + timedelta(days=20),
        "valid_until": NOW + timedelta(days=20),
    }
    values.update(changes)
    if "valid_until" in changes:
        values["raw_source_valid_until"] = changes["valid_until"]
        values["ttl_valid_until"] = changes["valid_until"]
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def _command(**changes: object) -> IssueAccountOwnerAssignmentProvenanceReceiptCommand:
    values: dict[str, object] = {
        "receipt_id": "account-assignment-provenance-7",
        "receipt_version": "account-assignment-provenance.v1",
        "provenance_kind": "creation",
        "row_observation_id": "physical-account-row-7",
        "row_observation_version": "physical-account-row.v1",
    }
    values.update(changes)
    return IssueAccountOwnerAssignmentProvenanceReceiptCommand(**values)  # type: ignore[arg-type]


class _RowProvider(ExactCurrentPhysicalAccountRowObservationProvider):
    def __init__(self, values: list[PhysicalAccountRowObservation | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservation | None:
        self.calls.append((observation_id, observation_version, as_of))
        return self.values.pop(0)


class _Repository(AccountOwnerAssignmentProvenanceReceiptRepository):
    def __init__(self, *, clock: datetime = NOW) -> None:
        self.clock = clock
        self.by_identity: dict[
            tuple[str, str], PersistedAccountOwnerAssignmentProvenanceReceipt
        ] = {}
        self.heads: dict[str, PersistedAccountOwnerAssignmentProvenanceReceipt] = {}
        self.append_calls = 0
        self.expected_predecessors: list[str | None] = []
        self.recorded_at_values: list[datetime] = []
        self.append_result: object | None = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        return self.by_identity.get((receipt_id, receipt_version))

    def get_current_head(
        self,
        *,
        receipt_id: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        return self.heads.get(receipt_id)

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
        self.append_calls += 1
        self.expected_predecessors.append(expected_predecessor_hash)
        self.recorded_at_values.append(recorded_at)
        if self.append_result is not None:
            return cast(
                PersistedAccountOwnerAssignmentProvenanceReceipt,
                self.append_result,
            )
        receipt = record.receipt
        identity = (receipt.receipt_id, receipt.receipt_version)
        if identity in self.by_identity:
            raise AccountOwnerAssignmentProvenanceReceiptConflict("receipt first-winner conflict")
        current = self.heads.get(receipt.receipt_id)
        current_hash = current.receipt.content_hash if current is not None else None
        if current_hash != expected_predecessor_hash:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "receipt predecessor CAS conflict"
            )
        self.by_identity[identity] = record
        self.heads[receipt.receipt_id] = record
        return record

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        record = self.by_identity.get((receipt_id, receipt_version))
        if record is None or record.receipt.content_hash != expected_content_hash:
            return None
        return record


def _service(
    repository: _Repository,
    *,
    rows: list[PhysicalAccountRowObservation | None] | None = None,
    actor: AccountOwnerAssignmentServerActor | None = None,
) -> tuple[IssueAccountOwnerAssignmentProvenanceReceipt, _RowProvider]:
    provider = _RowProvider(rows or [_row(), _row()])
    return (
        IssueAccountOwnerAssignmentProvenanceReceipt(
            row_provider=provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(days=10),
        ),
        provider,
    )


def _issue_once(
    repository: _Repository,
    *,
    command: IssueAccountOwnerAssignmentProvenanceReceiptCommand | None = None,
    row: PhysicalAccountRowObservation | None = None,
    actor: AccountOwnerAssignmentServerActor | None = None,
) -> AccountOwnerAssignmentProvenanceReceipt:
    exact_row = row or _row()
    service, _ = _service(
        repository,
        rows=[exact_row, exact_row],
        actor=actor,
    )
    return service.execute(command or _command())


def test_issue_command_is_five_field_id_only_and_row_is_double_read_at_one_cutoff() -> None:
    assert {
        field.name for field in fields(IssueAccountOwnerAssignmentProvenanceReceiptCommand)
    } == {
        "receipt_id",
        "receipt_version",
        "provenance_kind",
        "row_observation_id",
        "row_observation_version",
    }
    repository = _Repository()
    service, provider = _service(repository)

    receipt = service.execute(_command())

    assert provider.calls == [
        ("physical-account-row-7", "physical-account-row.v1", NOW),
        ("physical-account-row-7", "physical-account-row.v1", NOW),
    ]
    assert receipt.issued_at == receipt.recorded_at == NOW
    assert repository.recorded_at_values == [NOW]
    assert repository.append_calls == 1


def test_creation_is_an_explicit_self_claim_bound_to_matching_physical_row_user() -> None:
    receipt = _issue_once(_Repository())

    assert receipt.provenance_kind == "creation"
    assert receipt.artifact_type == "account_creation_receipt"
    assert receipt.assignment_state == "authoritative"
    assert receipt.assigned_owner_user_id == receipt.claimant.user_id == 19
    assert receipt.claimant == _actor().to_domain()
    assert receipt.row_observation_owner == "account"
    assert receipt.row_observation_artifact_type == "physical_account_row_observation"
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True


def test_manual_reclaim_uses_current_claimant_and_never_infers_legacy_row_user() -> None:
    repository = _Repository()
    row = _row(row_user_id=1)
    receipt = _issue_once(
        repository,
        command=_command(provenance_kind="manual_reclaim"),
        row=row,
    )

    assert row.row_user_id == 1
    assert receipt.provenance_kind == "manual_reclaim"
    assert receipt.artifact_type == "account_owner_reclaim_receipt"
    assert receipt.assigned_owner_user_id == receipt.claimant.user_id == 19
    assert receipt.assigned_owner_user_id != row.row_user_id


def test_migration_is_staff_attested_legacy_state_and_never_claims_owner() -> None:
    repository = _Repository()
    row = _row(row_user_id=1)
    receipt = _issue_once(
        repository,
        command=_command(provenance_kind="migration"),
        row=row,
        actor=_migration_actor(),
    )

    assert receipt.provenance_kind == "migration"
    assert receipt.artifact_type == "account_legacy_default_assignment_receipt"
    assert receipt.assignment_state == "legacy_default"
    assert receipt.assigned_owner_user_id is None
    assert receipt.claimant == _migration_actor().to_domain()
    assert row.row_user_id == 1


def test_kind_is_closed_and_actor_semantics_fail_before_write() -> None:
    repository = _Repository()
    with pytest.raises(ValueError, match="provenance_kind"):
        _command(provenance_kind="0013")
    assert repository.append_calls == 0

    service, _ = _service(
        repository,
        actor=_actor(role="legacy_assignment_reviewer"),
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptUnavailable,
        match="claimant role",
    ):
        service.execute(_command())
    assert repository.append_calls == 0

    service, _ = _service(
        repository,
        actor=_actor(role="legacy_assignment_reviewer", is_staff=False),
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptUnavailable,
        match="human staff reviewer",
    ):
        service.execute(_command(provenance_kind="migration"))
    assert repository.append_calls == 0


def test_creation_row_user_mismatch_cannot_be_relabeled_as_creation() -> None:
    repository = _Repository()
    row = _row(row_user_id=1)
    service, _ = _service(repository, rows=[row])

    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptUnavailable,
        match="creation claimant",
    ):
        service.execute(_command())

    assert repository.append_calls == 0


def test_missing_0013_row_or_absent_issue_action_produces_zero_writes() -> None:
    repository = _Repository()
    assert repository.append_calls == 0

    service, _ = _service(
        repository,
        rows=[None],
        actor=_migration_actor(),
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptUnavailable,
        match="exact current physical row",
    ):
        service.execute(_command(provenance_kind="migration"))

    assert repository.append_calls == 0


def test_substituted_mismatched_inactive_or_expired_row_fails_without_write() -> None:
    repository = _Repository()
    service, _ = _service(
        repository,
        rows=[cast(PhysicalAccountRowObservation, {})],
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptCorruption,
        match="type substitution",
    ):
        service.execute(_command())
    assert repository.append_calls == 0

    repository = _Repository()
    mismatched = _row(observation_id="physical-account-row-8")
    service, _ = _service(repository, rows=[mismatched])
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptCorruption,
        match="identity substitution",
    ):
        service.execute(_command())
    assert repository.append_calls == 0

    for row in (
        _row(is_active=False),
        _row(
            raw_source_valid_until=NOW,
            ttl_valid_until=NOW,
            valid_until=NOW,
        ),
    ):
        repository = _Repository()
        service, _ = _service(repository, rows=[row])
        with pytest.raises(
            AccountOwnerAssignmentProvenanceReceiptUnavailable,
            match="exact current physical row",
        ):
            service.execute(_command())
        assert repository.append_calls == 0


def test_row_change_between_reads_fails_closed_without_write() -> None:
    repository = _Repository()
    changed = replace(
        _row(),
        raw_source_content_hash=HASH_B,
        content_hash="",
    )
    service, provider = _service(repository, rows=[_row(), changed])

    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        match="changed during issuance",
    ):
        service.execute(_command())

    assert len(provider.calls) == 2
    assert repository.append_calls == 0


def test_authoritative_clock_and_strict_row_bounded_validity() -> None:
    row = _row(valid_until=NOW + timedelta(hours=1))
    receipt = _issue_once(_Repository(), row=row)
    assert receipt.valid_until == row.valid_until

    repository = _Repository(clock=NOW.replace(tzinfo=None))
    service, _ = _service(repository)
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptCorruption,
        match="timezone-aware",
    ):
        service.execute(_command())
    assert repository.append_calls == 0


def test_successor_uses_logical_head_and_repository_predecessor_cas() -> None:
    repository = _Repository()
    first = _issue_once(repository)
    repository.clock = NOW + timedelta(days=1)
    next_row = replace(
        _row(),
        observation_version="physical-account-row.v2",
        raw_source_version="simulated-account-row.v2",
        raw_source_content_hash=HASH_B,
        row_updated_at=NOW + timedelta(hours=20),
        observed_at=NOW + timedelta(hours=21),
        recorded_at=NOW + timedelta(hours=22),
        raw_source_valid_until=NOW + timedelta(days=40),
        ttl_valid_until=NOW + timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        supersedes_content_hash=_row().content_hash,
        identity_hash="",
        content_hash="",
    )
    successor = _issue_once(
        repository,
        command=_command(
            receipt_version="account-assignment-provenance.v2",
            row_observation_version="physical-account-row.v2",
        ),
        row=next_row,
    )

    assert successor.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessors == [None, first.content_hash]
    assert repository.append_calls == 2


def test_first_winner_replay_is_actor_bound_and_must_remain_logical_head() -> None:
    repository = _Repository()
    original = _issue_once(repository)

    replay = _issue_once(repository)
    assert replay == original
    assert repository.append_calls == 1

    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        match="another actor",
    ):
        _issue_once(
            repository,
            actor=_actor(actor_id="claimant:other", user_id=20),
            row=_row(row_user_id=20),
        )

    repository.heads.clear()
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        match="logical current head",
    ):
        _issue_once(repository)


def test_repository_substitution_and_concurrent_first_winner_fail_closed() -> None:
    repository = _Repository()
    repository.append_result = {}
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptCorruption,
        match="record type substitution",
    ):
        _issue_once(repository)

    repository = _Repository()
    other = _issue_once(repository)
    repository = _Repository()
    repository.append_result = PersistedAccountOwnerAssignmentProvenanceReceipt(
        replace(other, receipt_id="other-receipt", identity_hash="", content_hash=""),
        _actor(),
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        match="first winner differs",
    ):
        _issue_once(repository)


def test_exact_historical_reader_is_identity_hash_and_pit_closed() -> None:
    repository = _Repository()
    receipt = _issue_once(repository)
    reader = GetExactAccountOwnerAssignmentProvenanceReceipt(repository)
    command = GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        expected_content_hash=receipt.content_hash,
        as_of=receipt.recorded_at,
    )

    assert reader.execute(command) == receipt
    assert (
        reader.execute(
            replace(
                command,
                as_of=receipt.recorded_at - timedelta(microseconds=1),
            )
        )
        is None
    )
    assert reader.execute(replace(command, expected_content_hash=HASH_B)) is None


def test_closed_current_inactive_reader_rejects_selector_drift_and_superseded_head() -> None:
    repository = _Repository()
    receipt = _issue_once(repository)
    reader = GetCurrentAccountOwnerAssignmentProvenanceReceipt(repository)
    command = GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
        receipt=receipt,
        as_of=receipt.recorded_at,
    )

    assert receipt.status == "inactive"
    assert reader.execute(command) == receipt
    assert (
        reader.execute(
            replace(
                command,
                receipt=replace(
                    receipt,
                    valid_until=receipt.valid_until - timedelta(seconds=1),
                    content_hash="",
                ),
            )
        )
        is None
    )

    repository.clock = NOW + timedelta(days=1)
    next_row = replace(
        _row(),
        observation_version="physical-account-row.v2",
        raw_source_version="simulated-account-row.v2",
        raw_source_content_hash=HASH_B,
        row_updated_at=NOW + timedelta(hours=20),
        observed_at=NOW + timedelta(hours=21),
        recorded_at=NOW + timedelta(hours=22),
        raw_source_valid_until=NOW + timedelta(days=40),
        ttl_valid_until=NOW + timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        supersedes_content_hash=_row().content_hash,
        identity_hash="",
        content_hash="",
    )
    successor = _issue_once(
        repository,
        command=_command(
            receipt_version="account-assignment-provenance.v2",
            row_observation_version="physical-account-row.v2",
        ),
        row=next_row,
    )
    assert reader.execute(replace(command, as_of=successor.recorded_at)) is None


def test_expired_final_receipt_does_not_restore_older_current_receipt() -> None:
    repository = _Repository()
    first = _issue_once(repository)
    repository.clock = NOW + timedelta(hours=2)
    next_row = replace(
        _row(),
        observation_version="physical-account-row.v2",
        raw_source_version="simulated-account-row.v2",
        raw_source_content_hash=HASH_B,
        row_updated_at=NOW + timedelta(minutes=30),
        observed_at=NOW + timedelta(minutes=40),
        recorded_at=NOW + timedelta(minutes=50),
        raw_source_valid_until=NOW + timedelta(hours=5),
        ttl_valid_until=NOW + timedelta(hours=4),
        valid_until=NOW + timedelta(hours=4),
        supersedes_content_hash=_row().content_hash,
        identity_hash="",
        content_hash="",
    )
    successor = _issue_once(
        repository,
        command=_command(
            receipt_version="account-assignment-provenance.v2",
            row_observation_version="physical-account-row.v2",
        ),
        row=next_row,
    )
    cutoff = successor.valid_until + timedelta(microseconds=1)
    reader = GetCurrentAccountOwnerAssignmentProvenanceReceipt(repository)

    assert (
        reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=first,
                as_of=cutoff,
            )
        )
        is None
    )
    assert (
        reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=successor,
                as_of=cutoff,
            )
        )
        is None
    )


def test_errors_extend_account_owner_assignment_application_taxonomy() -> None:
    assert issubclass(
        AccountOwnerAssignmentProvenanceReceiptUnavailable,
        AccountOwnerAssignmentUnavailable,
    )
    assert issubclass(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        AccountOwnerAssignmentConflict,
    )
    assert issubclass(
        AccountOwnerAssignmentProvenanceReceiptCorruption,
        AccountOwnerAssignmentCorruption,
    )


def test_application_module_has_no_orm_or_cross_app_implementation_imports() -> None:
    source = Path(
        "apps/account/application/account_owner_assignment_provenance_receipt.py"
    ).read_text(encoding="utf-8")
    assert ".objects" not in source
    assert "infrastructure" not in source
    assert "from apps.simulated_trading" not in source
    assert "import apps.simulated_trading" not in source
