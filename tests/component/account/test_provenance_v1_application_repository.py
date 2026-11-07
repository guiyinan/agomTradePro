"""Component checks for the V1 receipt Application and its real ORM ledger.

The physical-row observation is a controlled test source record. Its persisted
row is read back through the real PhysicalAccountRowObservation repository and
public current reader before the V1 Application sees it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptConflict,
    AccountOwnerAssignmentProvenanceReceiptCorruption,
    AccountOwnerAssignmentProvenanceReceiptUnavailable,
    ExactCurrentPhysicalAccountRowObservationProvider,
    GetCurrentAccountOwnerAssignmentProvenanceReceipt,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand,
    GetExactAccountOwnerAssignmentProvenanceReceipt,
    GetExactAccountOwnerAssignmentProvenanceReceiptCommand,
    IssueAccountOwnerAssignmentProvenanceReceipt,
    IssueAccountOwnerAssignmentProvenanceReceiptCommand,
)
from apps.account.application.physical_account_row_observation import (
    GetCurrentPhysicalAccountRowObservation,
    GetCurrentPhysicalAccountRowObservationCommand,
    PersistedPhysicalAccountRowObservation,
    PhysicalAccountRowObservationActor,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    AccountOwnerAssignmentProvenanceReceiptModel,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
)
from apps.account.infrastructure.physical_account_row_observation_models import (
    PhysicalAccountRowObservationModel,
)
from apps.account.infrastructure.physical_account_row_observation_repository import (
    DjangoPhysicalAccountRowObservationRepository,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
RECEIPT_ID = "ref02-provenance-account-7"
RECEIPT_VERSION = "account-assignment-provenance.v1"
ROW_ID = "ref02-physical-row-7"
ROW_VERSION = "physical-account-row.v1"


class _Clock:
    """Mutable, explicit test clock shared by the two real repositories."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _assert_isolated_postgresql_connection() -> None:
    """Keep this ledger integration evidence on the configured PostgreSQL test DB."""

    if connection.vendor != "postgresql":
        pytest.skip("V1 append-only ledger component evidence requires PostgreSQL")
    database = connection.settings_dict
    test_database = database.get("TEST")
    assert isinstance(test_database, dict)
    test_name = test_database.get("NAME")
    assert isinstance(test_name, str) and test_name
    assert database.get("NAME") == test_name


def _claimant(
    *,
    actor_id: str = "claimant:19",
    user_id: int = 19,
) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id=actor_id,
        user_id=user_id,
        role="account_owner_claimant",
        kind="human",
        is_staff=False,
    )


def _capture_actor() -> PhysicalAccountRowObservationActor:
    return PhysicalAccountRowObservationActor(
        actor_id="physical-row-observer:23",
        user_id=23,
        role="account_evidence_recorder",
        kind="human",
        is_staff=True,
    )


def _row(
    *,
    observation_id: str = ROW_ID,
    observation_version: str = ROW_VERSION,
    account_id: str = "real-account-7",
    underlying_account_id: int = 7,
    row_user_id: int | None = 19,
    raw_source_id: str = "simulated-account-row-7",
    raw_source_version: str = "simulated-account-row.v1",
    raw_source_content_hash: str = "a" * 64,
    created_at: datetime = NOW - timedelta(days=2),
    updated_at: datetime = NOW - timedelta(minutes=5),
    observed_at: datetime = NOW - timedelta(minutes=3),
    recorded_at: datetime = NOW - timedelta(minutes=2),
    raw_valid_until: datetime = NOW + timedelta(days=2),
    ttl_valid_until: datetime = NOW + timedelta(days=1),
    supersedes_content_hash: str | None = None,
) -> PhysicalAccountRowObservation:
    """Build one fully sealed test source observation with explicit clocks."""

    return PhysicalAccountRowObservation(
        observation_id=observation_id,
        observation_version=observation_version,
        account_namespace="account",
        account_id=account_id,
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=underlying_account_id,
        raw_source_owner="simulated_trading",
        raw_source_artifact_type="simulated_account_row",
        raw_source_id=raw_source_id,
        raw_source_version=raw_source_version,
        raw_source_content_hash=raw_source_content_hash,
        row_user_id=row_user_id,
        account_type="real",
        is_active=True,
        row_created_at=created_at,
        row_updated_at=updated_at,
        observed_at=observed_at,
        recorded_at=recorded_at,
        raw_source_valid_until=raw_valid_until,
        ttl_valid_until=ttl_valid_until,
        valid_until=min(raw_valid_until, ttl_valid_until),
        supersedes_content_hash=supersedes_content_hash,
    )


def _persist_row(
    repository: DjangoPhysicalAccountRowObservationRepository,
    observation: PhysicalAccountRowObservation,
    *,
    expected_predecessor_hash: str | None = None,
) -> None:
    record = PersistedPhysicalAccountRowObservation(
        observation=observation,
        captured_by=_capture_actor(),
    )
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=observation.recorded_at,
        )


class _CurrentPhysicalRowReader(ExactCurrentPhysicalAccountRowObservationProvider):
    """Test composition from the V1 row port to the real physical-row reader.

    The source observation itself remains an explicit test fixture; lookup,
    current-head qualification, expiry, and persisted integrity checks use the
    real ORM repository and public Application reader.
    """

    def __init__(self, repository: DjangoPhysicalAccountRowObservationRepository) -> None:
        self._repository = repository
        self._current = GetCurrentPhysicalAccountRowObservation(repository)

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservation | None:
        """Adapt the ID/version V1 selector through the full current-row reader."""

        record = self._repository.get_winner(
            observation_id=observation_id,
            observation_version=observation_version,
            as_of=as_of,
        )
        if record is None:
            return None
        observation = record.observation
        command = GetCurrentPhysicalAccountRowObservationCommand.from_observation(
            observation,
            as_of=as_of,
        )
        return self._current.execute(command)


def _issue(
    *,
    receipt_repository: DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
    row_repository: DjangoPhysicalAccountRowObservationRepository,
    actor: AccountOwnerAssignmentServerActor | None = None,
    validity_period: timedelta = timedelta(days=10),
) -> IssueAccountOwnerAssignmentProvenanceReceipt:
    """Compose the actual V1 issuer with the explicit physical-row adapter."""

    return IssueAccountOwnerAssignmentProvenanceReceipt(
        row_provider=_CurrentPhysicalRowReader(row_repository),
        repository=receipt_repository,
        actor=actor or _claimant(),
        validity_period=validity_period,
    )


def _receipt_count() -> int:
    return AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default").count()


def _row_count() -> int:
    return PhysicalAccountRowObservationModel._default_manager.using("default").count()


@pytest.mark.django_db(transaction=True)
def test_application_create_exact_current_and_replay_use_real_v1_ledger() -> None:
    _assert_isolated_postgresql_connection()
    clock = _Clock(NOW)
    row_repository = DjangoPhysicalAccountRowObservationRepository(
        using="default",
        clock=clock,
    )
    receipt_repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
        using="default", clock=clock
    )
    row = _row()
    _persist_row(row_repository, row)
    command = IssueAccountOwnerAssignmentProvenanceReceiptCommand(
        receipt_id=RECEIPT_ID,
        receipt_version=RECEIPT_VERSION,
        provenance_kind="creation",
        row_observation_id=ROW_ID,
        row_observation_version=ROW_VERSION,
    )

    assert (_row_count(), _receipt_count()) == (1, 0)
    receipt = _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
    ).execute(command)

    assert (_row_count(), _receipt_count()) == (1, 1)
    assert receipt.receipt_id == RECEIPT_ID
    assert receipt.receipt_version == RECEIPT_VERSION
    assert receipt.account_id == row.account_id
    assert receipt.underlying_unified_account_id == row.underlying_unified_account_id
    assert receipt.row_observation_id == row.observation_id
    assert receipt.row_observation_version == row.observation_version
    assert receipt.row_observation_identity_hash == row.identity_hash
    assert receipt.row_observation_content_hash == row.content_hash
    assert receipt.row_observation_valid_until == row.valid_until
    assert receipt.claimant == _claimant().to_domain()
    assert receipt.issued_at == receipt.recorded_at == NOW
    assert receipt.valid_until == min(row.valid_until, NOW + timedelta(days=10))
    assert receipt.permission == "evidence_only"
    assert receipt.status == "inactive"
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True
    persisted = receipt_repository.get_current_head(
        receipt_id=RECEIPT_ID,
        as_of=NOW,
    )
    assert persisted is not None
    assert persisted.issued_by == _claimant()

    exact_reader = GetExactAccountOwnerAssignmentProvenanceReceipt(receipt_repository)
    exact_command = GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        expected_content_hash=receipt.content_hash,
        as_of=NOW,
    )
    assert exact_reader.execute(exact_command) == receipt
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptCorruption):
        exact_reader.execute(replace(exact_command, expected_content_hash="f" * 64))
    assert (
        exact_reader.execute(
            replace(
                exact_command,
                receipt_id="ref02-unknown-receipt",
                expected_content_hash="e" * 64,
            )
        )
        is None
    )
    assert (_row_count(), _receipt_count()) == (1, 1)
    current_reader = GetCurrentAccountOwnerAssignmentProvenanceReceipt(receipt_repository)
    assert (
        current_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=receipt,
                as_of=NOW,
            )
        )
        == receipt
    )
    foreign_scope = replace(
        receipt,
        account_id="foreign-account",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptCorruption):
        current_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=foreign_scope,
                as_of=NOW,
            )
        )
    assert (_row_count(), _receipt_count()) == (1, 1)

    replay = _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
    ).execute(command)
    assert replay == receipt
    assert (_row_count(), _receipt_count()) == (1, 1)


@pytest.mark.django_db(transaction=True)
def test_wrong_row_and_actor_scope_do_not_write_or_rebind_first_winner() -> None:
    _assert_isolated_postgresql_connection()
    clock = _Clock(NOW)
    row_repository = DjangoPhysicalAccountRowObservationRepository(
        using="default",
        clock=clock,
    )
    receipt_repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
        using="default", clock=clock
    )
    row = _row()
    _persist_row(row_repository, row)
    _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
    ).execute(
        IssueAccountOwnerAssignmentProvenanceReceiptCommand(
            receipt_id=RECEIPT_ID,
            receipt_version=RECEIPT_VERSION,
            provenance_kind="creation",
            row_observation_id=ROW_ID,
            row_observation_version=ROW_VERSION,
        )
    )
    original = receipt_repository.get_current_head(
        receipt_id=RECEIPT_ID,
        as_of=NOW,
    )
    assert original is not None
    before = (_row_count(), _receipt_count())

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptUnavailable):
        _issue(
            receipt_repository=receipt_repository,
            row_repository=row_repository,
        ).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id="ref02-missing-source",
                receipt_version=RECEIPT_VERSION,
                provenance_kind="creation",
                row_observation_id="missing-physical-row",
                row_observation_version=ROW_VERSION,
            )
        )
    assert (_row_count(), _receipt_count()) == before

    foreign_row = _row(
        observation_id="ref02-physical-row-foreign",
        account_id="foreign-account",
        underlying_account_id=8,
        row_user_id=20,
        raw_source_id="simulated-account-row-8",
    )
    _persist_row(row_repository, foreign_row)
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptConflict):
        _issue(
            receipt_repository=receipt_repository,
            row_repository=row_repository,
            actor=_claimant(actor_id="claimant:20", user_id=20),
        ).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=RECEIPT_ID,
                receipt_version=RECEIPT_VERSION,
                provenance_kind="creation",
                row_observation_id=foreign_row.observation_id,
                row_observation_version=foreign_row.observation_version,
            )
        )
    assert (_row_count(), _receipt_count()) == (2, 1)
    assert (
        receipt_repository.get_current_head(
            receipt_id=RECEIPT_ID,
            as_of=NOW,
        )
        == original
    )


@pytest.mark.django_db(transaction=True)
def test_expired_physical_source_and_receipt_are_not_current_or_writable() -> None:
    _assert_isolated_postgresql_connection()
    clock = _Clock(NOW)
    row_repository = DjangoPhysicalAccountRowObservationRepository(
        using="default",
        clock=clock,
    )
    receipt_repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
        using="default", clock=clock
    )
    expired_source = _row(
        observation_id="ref02-expired-physical-row",
        account_id="expired-source-account",
        underlying_account_id=9,
        raw_source_id="simulated-account-row-9",
        updated_at=NOW - timedelta(minutes=4),
        observed_at=NOW - timedelta(minutes=3),
        recorded_at=NOW - timedelta(minutes=2),
        raw_valid_until=NOW - timedelta(minutes=1),
        ttl_valid_until=NOW - timedelta(minutes=1),
    )
    _persist_row(row_repository, expired_source)
    before = (_row_count(), _receipt_count())

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptUnavailable):
        _issue(
            receipt_repository=receipt_repository,
            row_repository=row_repository,
        ).execute(
            IssueAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id="ref02-expired-source-receipt",
                receipt_version=RECEIPT_VERSION,
                provenance_kind="creation",
                row_observation_id=expired_source.observation_id,
                row_observation_version=expired_source.observation_version,
            )
        )
    assert (_row_count(), _receipt_count()) == before

    current_source = _row(
        observation_id="ref02-valid-physical-row",
        account_id="valid-source-account",
        underlying_account_id=10,
        row_user_id=19,
        raw_source_id="simulated-account-row-10",
    )
    _persist_row(row_repository, current_source)
    receipt = _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
        validity_period=timedelta(minutes=5),
    ).execute(
        IssueAccountOwnerAssignmentProvenanceReceiptCommand(
            receipt_id="ref02-short-lived-receipt",
            receipt_version=RECEIPT_VERSION,
            provenance_kind="creation",
            row_observation_id=current_source.observation_id,
            row_observation_version=current_source.observation_version,
        )
    )
    assert receipt.valid_until == NOW + timedelta(minutes=5)
    clock.value = receipt.valid_until

    exact_reader = GetExactAccountOwnerAssignmentProvenanceReceipt(receipt_repository)
    assert (
        exact_reader.execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                expected_content_hash=receipt.content_hash,
                as_of=clock.value,
            )
        )
        is None
    )
    current_reader = GetCurrentAccountOwnerAssignmentProvenanceReceipt(receipt_repository)
    assert (
        current_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=receipt,
                as_of=clock.value,
            )
        )
        is None
    )
    assert (_row_count(), _receipt_count()) == (2, 1)


@pytest.mark.django_db(transaction=True)
def test_changed_current_physical_row_cannot_rewrite_v1_first_winner() -> None:
    _assert_isolated_postgresql_connection()
    clock = _Clock(NOW)
    row_repository = DjangoPhysicalAccountRowObservationRepository(
        using="default",
        clock=clock,
    )
    receipt_repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
        using="default", clock=clock
    )
    first_row = _row()
    _persist_row(row_repository, first_row)
    first_receipt = _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
    ).execute(
        IssueAccountOwnerAssignmentProvenanceReceiptCommand(
            receipt_id=RECEIPT_ID,
            receipt_version=RECEIPT_VERSION,
            provenance_kind="creation",
            row_observation_id=first_row.observation_id,
            row_observation_version=first_row.observation_version,
        )
    )

    successor_time = NOW + timedelta(hours=1)
    successor = replace(
        first_row,
        observation_version="physical-account-row.v2",
        raw_source_version="simulated-account-row.v2",
        raw_source_content_hash="b" * 64,
        row_updated_at=successor_time,
        observed_at=successor_time + timedelta(minutes=1),
        recorded_at=successor_time + timedelta(minutes=2),
        raw_source_valid_until=successor_time + timedelta(days=2),
        ttl_valid_until=successor_time + timedelta(days=1),
        valid_until=successor_time + timedelta(days=1),
        supersedes_content_hash=first_row.content_hash,
        identity_hash="",
        content_hash="",
    )
    _persist_row(
        row_repository,
        successor,
        expected_predecessor_hash=first_row.content_hash,
    )
    clock.value = successor.recorded_at + timedelta(minutes=1)
    same_receipt_identity_new_row = IssueAccountOwnerAssignmentProvenanceReceiptCommand(
        receipt_id=RECEIPT_ID,
        receipt_version=RECEIPT_VERSION,
        provenance_kind="creation",
        row_observation_id=successor.observation_id,
        row_observation_version=successor.observation_version,
    )
    with pytest.raises(
        AccountOwnerAssignmentProvenanceReceiptConflict,
        match="identity has another first winner",
    ):
        _issue(
            receipt_repository=receipt_repository,
            row_repository=row_repository,
        ).execute(same_receipt_identity_new_row)

    assert (_row_count(), _receipt_count()) == (2, 1)
    exact_reader = GetExactAccountOwnerAssignmentProvenanceReceipt(receipt_repository)
    assert (
        exact_reader.execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=RECEIPT_ID,
                receipt_version=RECEIPT_VERSION,
                expected_content_hash=first_receipt.content_hash,
                as_of=clock.value,
            )
        )
        == first_receipt
    )


@pytest.mark.django_db(transaction=True)
def test_tampered_v1_ledger_fails_closed_without_appending_another_row() -> None:
    _assert_isolated_postgresql_connection()
    clock = _Clock(NOW)
    row_repository = DjangoPhysicalAccountRowObservationRepository(
        using="default",
        clock=clock,
    )
    receipt_repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
        using="default", clock=clock
    )
    row = _row()
    _persist_row(row_repository, row)
    receipt = _issue(
        receipt_repository=receipt_repository,
        row_repository=row_repository,
    ).execute(
        IssueAccountOwnerAssignmentProvenanceReceiptCommand(
            receipt_id=RECEIPT_ID,
            receipt_version=RECEIPT_VERSION,
            provenance_kind="creation",
            row_observation_id=row.observation_id,
            row_observation_version=row.observation_version,
        )
    )
    before = (_row_count(), _receipt_count())
    table = connection.ops.quote_name(AccountOwnerAssignmentProvenanceReceiptModel._meta.db_table)
    column = connection.ops.quote_name("ledger_header_hash")
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {column} = %s",
            ["f" * 64],
        )

    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptCorruption):
        GetCurrentAccountOwnerAssignmentProvenanceReceipt(receipt_repository).execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=receipt,
                as_of=NOW,
            )
        )
    assert (_row_count(), _receipt_count()) == before
