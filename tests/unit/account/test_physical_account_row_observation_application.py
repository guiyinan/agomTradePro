"""Pure tests for the Account physical-row observation workflow."""

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.physical_account_row_observation import (
    CapturePhysicalAccountRowObservation,
    CapturePhysicalAccountRowObservationCommand,
    ExactPhysicalSimulatedAccountRow,
    GetCurrentPhysicalAccountRowObservation,
    GetCurrentPhysicalAccountRowObservationCommand,
    GetExactPhysicalAccountRowObservation,
    GetExactPhysicalAccountRowObservationCommand,
    PersistedPhysicalAccountRowObservation,
    PhysicalAccountRowObservationActor,
    PhysicalAccountRowObservationConflict,
    PhysicalAccountRowObservationCorruption,
    PhysicalAccountRowObservationRepository,
    PhysicalAccountRowObservationUnavailable,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)

NOW = datetime(2026, 8, 13, 7, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _actor(**changes: object) -> PhysicalAccountRowObservationActor:
    values: dict[str, object] = {
        "actor_id": "account-evidence-staff-17",
        "user_id": 17,
        "role": "account_evidence_recorder",
    }
    values.update(changes)
    return PhysicalAccountRowObservationActor(**values)  # type: ignore[arg-type]


def _row(**changes: object) -> ExactPhysicalSimulatedAccountRow:
    values: dict[str, object] = {
        "source_id": "simulated-account-row-7",
        "source_version": "simulated-account-row.v3",
        "content_hash": HASH_A,
        "account_namespace": "account",
        "account_id": "physical-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": 29,
        "account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=20),
        "row_updated_at": NOW - timedelta(minutes=2),
        "observed_at": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=10),
    }
    values.update(changes)
    return ExactPhysicalSimulatedAccountRow(**values)  # type: ignore[arg-type]


def _command(**changes: object) -> CapturePhysicalAccountRowObservationCommand:
    values: dict[str, object] = {
        "observation_id": "physical-account-row-observation-7",
        "observation_version": "physical-account-row-observation.v1",
        "raw_source_id": "simulated-account-row-7",
        "raw_source_version": "simulated-account-row.v3",
        "account_namespace": "account",
        "account_id": "physical-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
    }
    values.update(changes)
    return CapturePhysicalAccountRowObservationCommand(**values)  # type: ignore[arg-type]


class _RowProvider:
    def __init__(self, values: list[ExactPhysicalSimulatedAccountRow | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, str, str, str, str, int, datetime]] = []

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRow | None:
        self.calls.append(
            (
                source_id,
                source_version,
                account_namespace,
                account_id,
                underlying_unified_account_namespace,
                underlying_unified_account_id,
                as_of,
            )
        )
        return self.values.pop(0)


class _Repository(PhysicalAccountRowObservationRepository):
    def __init__(self, clocks: list[datetime] | None = None) -> None:
        self.clocks = clocks or [NOW, NOW + timedelta(seconds=1)]
        self.by_identity: dict[tuple[str, str], PersistedPhysicalAccountRowObservation] = {}
        self.heads: dict[tuple[str, str, str, int, str], PersistedPhysicalAccountRowObservation] = (
            {}
        )
        self.append_calls = 0
        self.expected_predecessors: list[str | None] = []
        self.append_result: object | None = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clocks.pop(0)

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        return self.by_identity.get((observation_id, observation_version))

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        raw_source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        return self.heads.get(
            (
                account_namespace,
                account_id,
                underlying_unified_account_namespace,
                underlying_unified_account_id,
                raw_source_id,
            )
        )

    def append(
        self,
        record: PersistedPhysicalAccountRowObservation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservation:
        self.append_calls += 1
        self.expected_predecessors.append(expected_predecessor_hash)
        if self.append_result is not None:
            return cast(PersistedPhysicalAccountRowObservation, self.append_result)
        observation = record.observation
        identity = (observation.observation_id, observation.observation_version)
        logical = (
            observation.account_namespace,
            observation.account_id,
            observation.underlying_unified_account_namespace,
            observation.underlying_unified_account_id,
            observation.raw_source_id,
        )
        if identity in self.by_identity:
            raise PhysicalAccountRowObservationConflict("first-winner conflict")
        current = self.heads.get(logical)
        current_hash = current.observation.content_hash if current is not None else None
        if current_hash != expected_predecessor_hash:
            raise PhysicalAccountRowObservationConflict("predecessor CAS conflict")
        self.by_identity[identity] = record
        self.heads[logical] = record
        return record

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        record = self.by_identity.get((observation_id, observation_version))
        if record is None or record.observation.content_hash != expected_content_hash:
            return None
        return record


def _capture(
    repository: _Repository,
    *,
    rows: list[ExactPhysicalSimulatedAccountRow | None] | None = None,
    actor: PhysicalAccountRowObservationActor | None = None,
) -> tuple[CapturePhysicalAccountRowObservation, _RowProvider]:
    provider = _RowProvider(rows or [_row(), _row()])
    return (
        CapturePhysicalAccountRowObservation(
            row_provider=provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(minutes=5),
        ),
        provider,
    )


def _capture_once(
    repository: _Repository,
    *,
    command: CapturePhysicalAccountRowObservationCommand | None = None,
    row: ExactPhysicalSimulatedAccountRow | None = None,
    actor: PhysicalAccountRowObservationActor | None = None,
) -> PhysicalAccountRowObservation:
    exact_row = row or _row()
    service, _ = _capture(
        repository,
        rows=[exact_row, exact_row],
        actor=actor,
    )
    return service.execute(command or _command())


def test_capture_command_is_id_only_and_double_reads_one_server_cutoff() -> None:
    assert {field.name for field in fields(CapturePhysicalAccountRowObservationCommand)} == {
        "observation_id",
        "observation_version",
        "raw_source_id",
        "raw_source_version",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
    }
    repository = _Repository()
    service, provider = _capture(repository)

    observation = service.execute(_command())

    assert provider.calls == [
        (
            "simulated-account-row-7",
            "simulated-account-row.v3",
            "account",
            "physical-account-7",
            "simulated-account-row",
            7,
            NOW,
        ),
        (
            "simulated-account-row-7",
            "simulated-account-row.v3",
            "account",
            "physical-account-7",
            "simulated-account-row",
            7,
            NOW,
        ),
    ]
    assert observation.recorded_at == NOW + timedelta(seconds=1)
    assert repository.append_calls == 1


def test_capture_preserves_nullable_user_raw_row_fields_and_never_infers_owner() -> None:
    repository = _Repository()
    raw = _row(
        row_user_id=None,
        account_type="simulated",
        is_active=False,
        row_created_at=NOW - timedelta(days=40),
        row_updated_at=NOW - timedelta(hours=2),
    )

    observation = _capture_once(repository, row=raw)

    assert observation.row_user_id is None
    assert observation.account_type == "simulated"
    assert observation.is_active is False
    assert observation.row_created_at == raw.row_created_at
    assert observation.row_updated_at == raw.row_updated_at
    assert observation.owner_assignment_state == "unknown"
    assert observation.raw_source_id == raw.source_id
    assert observation.raw_source_version == raw.source_version
    assert observation.raw_source_content_hash == raw.content_hash
    assert observation.raw_source_valid_until == raw.valid_until
    assert observation.activation_available is False
    assert observation.must_not_execute is True


def test_exact_physical_row_dto_is_strict_and_has_fixed_simulated_authority() -> None:
    row = _row()
    assert row.owner == "simulated_trading"
    assert row.artifact_type == "simulated_account_row"

    with pytest.raises(ValueError, match="SHA-256"):
        _row(content_hash="A" * 64)
    with pytest.raises(TypeError, match="exact boolean"):
        _row(is_active=1)
    with pytest.raises(TypeError, match="exact integer"):
        _row(underlying_unified_account_id=True)
    with pytest.raises(ValueError, match="row_user_id"):
        _row(row_user_id=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _row(observed_at=datetime(2026, 8, 13, 7, 0))
    with pytest.raises(ValueError, match="clock sequence"):
        _row(row_updated_at=NOW)
    with pytest.raises(ValueError, match="authority"):
        _row(owner="account")


def test_actor_and_capture_command_enforce_exact_server_inputs() -> None:
    with pytest.raises(ValueError, match="human staff"):
        _actor(kind="service")
    with pytest.raises(ValueError, match="human staff"):
        _actor(is_staff=False)
    with pytest.raises(ValueError, match="positive integer"):
        _actor(user_id=True)
    with pytest.raises(ValueError, match="canonical token"):
        _command(account_id=" physical-account-7")
    with pytest.raises(TypeError, match="exact integer"):
        _command(underlying_unified_account_id=True)


def test_missing_substituted_or_mismatched_row_fails_without_write() -> None:
    repository = _Repository(clocks=[NOW])
    service, _ = _capture(repository, rows=[None])
    with pytest.raises(PhysicalAccountRowObservationUnavailable, match="unavailable"):
        service.execute(_command())
    assert repository.append_calls == 0

    repository = _Repository(clocks=[NOW])
    service, _ = _capture(repository, rows=[cast(ExactPhysicalSimulatedAccountRow, {})])
    with pytest.raises(PhysicalAccountRowObservationCorruption, match="type substitution"):
        service.execute(_command())
    assert repository.append_calls == 0

    repository = _Repository(clocks=[NOW])
    mismatched = _row(account_id="physical-account-8")
    service, _ = _capture(repository, rows=[mismatched])
    with pytest.raises(PhysicalAccountRowObservationCorruption, match="identity substitution"):
        service.execute(_command())
    assert repository.append_calls == 0


def test_source_change_between_first_and_final_read_fails_closed() -> None:
    repository = _Repository(clocks=[NOW])
    changed = _row(content_hash=HASH_B, row_updated_at=NOW - timedelta(minutes=1))
    service, provider = _capture(repository, rows=[_row(), changed])

    with pytest.raises(PhysicalAccountRowObservationConflict, match="changed during capture"):
        service.execute(_command())

    assert len(provider.calls) == 2
    assert repository.append_calls == 0


def test_repository_clock_and_source_validity_fail_closed() -> None:
    repository = _Repository(clocks=[NOW, NOW - timedelta(seconds=1)])
    with pytest.raises(PhysicalAccountRowObservationCorruption, match="moved backwards"):
        _capture_once(repository)
    assert repository.append_calls == 0

    row = _row(valid_until=NOW + timedelta(milliseconds=500))
    repository = _Repository(clocks=[NOW, NOW + timedelta(seconds=1)])
    with pytest.raises(PhysicalAccountRowObservationUnavailable, match="expired"):
        _capture_once(repository, row=row)
    assert repository.append_calls == 0


def test_successor_binds_logical_head_and_repository_predecessor_cas() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    repository.clocks = [NOW + timedelta(seconds=2), NOW + timedelta(seconds=3)]
    next_row = _row(
        source_version="simulated-account-row.v4",
        content_hash=HASH_B,
        row_updated_at=NOW + timedelta(seconds=1),
        observed_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(minutes=12),
    )
    successor = _capture_once(
        repository,
        command=_command(
            observation_version="physical-account-row-observation.v2",
            raw_source_version="simulated-account-row.v4",
        ),
        row=next_row,
    )

    assert successor.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessors == [None, first.content_hash]
    assert repository.append_calls == 2


def test_first_winner_replay_is_actor_bound_and_must_still_be_logical_head() -> None:
    repository = _Repository()
    original = _capture_once(repository)
    repository.clocks = [NOW + timedelta(seconds=2)]
    replay = _capture_once(repository)
    assert replay == original
    assert repository.append_calls == 1

    repository.clocks = [NOW + timedelta(seconds=3)]
    with pytest.raises(PhysicalAccountRowObservationConflict, match="another actor"):
        _capture_once(repository, actor=_actor(actor_id="other-staff", user_id=18))

    repository.heads.clear()
    repository.clocks = [NOW + timedelta(seconds=4)]
    with pytest.raises(PhysicalAccountRowObservationConflict, match="logical current head"):
        _capture_once(repository)


def test_append_return_substitution_is_rejected() -> None:
    repository = _Repository()
    repository.append_result = {}
    with pytest.raises(PhysicalAccountRowObservationCorruption, match="record type substitution"):
        _capture_once(repository)


def test_exact_historical_reader_is_hash_and_point_in_time_closed() -> None:
    repository = _Repository()
    observation = _capture_once(repository)
    reader = GetExactPhysicalAccountRowObservation(repository)

    before = GetExactPhysicalAccountRowObservationCommand(
        observation_id=observation.observation_id,
        observation_version=observation.observation_version,
        expected_content_hash=observation.content_hash,
        as_of=observation.recorded_at - timedelta(microseconds=1),
    )
    assert reader.execute(before) is None
    assert reader.execute(replace(before, as_of=observation.recorded_at)) == observation
    assert (
        reader.execute(replace(before, expected_content_hash=HASH_B, as_of=observation.recorded_at))
        is None
    )


def test_closed_current_reader_rejects_semantic_changes_and_superseded_head() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    current_reader = GetCurrentPhysicalAccountRowObservation(repository)
    first_command = GetCurrentPhysicalAccountRowObservationCommand.from_observation(
        first,
        as_of=first.recorded_at,
    )
    assert current_reader.execute(first_command) == first
    assert current_reader.execute(replace(first_command, row_user_id=None)) is None

    repository.clocks = [NOW + timedelta(seconds=2), NOW + timedelta(seconds=3)]
    successor_row = _row(
        source_version="simulated-account-row.v4",
        content_hash=HASH_B,
        row_updated_at=NOW + timedelta(seconds=1),
        observed_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(minutes=12),
    )
    successor = _capture_once(
        repository,
        command=_command(
            observation_version="physical-account-row-observation.v2",
            raw_source_version="simulated-account-row.v4",
        ),
        row=successor_row,
    )
    assert current_reader.execute(replace(first_command, as_of=successor.recorded_at)) is None


def test_inactive_successor_is_auditable_but_current_reader_does_not_fallback() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    repository.clocks = [NOW + timedelta(seconds=2), NOW + timedelta(seconds=3)]
    inactive_row = _row(
        source_version="simulated-account-row.v4",
        content_hash=HASH_B,
        is_active=False,
        row_updated_at=NOW + timedelta(seconds=1),
        observed_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(minutes=12),
    )
    inactive = _capture_once(
        repository,
        command=_command(
            observation_version="physical-account-row-observation.v2",
            raw_source_version="simulated-account-row.v4",
        ),
        row=inactive_row,
    )
    current_reader = GetCurrentPhysicalAccountRowObservation(repository)
    assert (
        current_reader.execute(
            GetCurrentPhysicalAccountRowObservationCommand.from_observation(
                first,
                as_of=inactive.recorded_at,
            )
        )
        is None
    )
    assert (
        current_reader.execute(
            GetCurrentPhysicalAccountRowObservationCommand.from_observation(
                inactive,
                as_of=inactive.recorded_at,
            )
        )
        is None
    )
    assert (
        GetExactPhysicalAccountRowObservation(repository).execute(
            GetExactPhysicalAccountRowObservationCommand(
                observation_id=inactive.observation_id,
                observation_version=inactive.observation_version,
                expected_content_hash=inactive.content_hash,
                as_of=inactive.recorded_at,
            )
        )
        == inactive
    )


def test_expired_successor_does_not_restore_an_older_current_row() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    repository.clocks = [NOW + timedelta(seconds=2), NOW + timedelta(seconds=3)]
    short_row = _row(
        source_version="simulated-account-row.v4",
        content_hash=HASH_B,
        row_updated_at=NOW + timedelta(seconds=1),
        observed_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(seconds=4),
    )
    successor = _capture_once(
        repository,
        command=_command(
            observation_version="physical-account-row-observation.v2",
            raw_source_version="simulated-account-row.v4",
        ),
        row=short_row,
    )
    cutoff = NOW + timedelta(seconds=5)
    reader = GetCurrentPhysicalAccountRowObservation(repository)
    assert (
        reader.execute(
            GetCurrentPhysicalAccountRowObservationCommand.from_observation(
                first,
                as_of=cutoff,
            )
        )
        is None
    )
    assert (
        reader.execute(
            GetCurrentPhysicalAccountRowObservationCommand.from_observation(
                successor,
                as_of=cutoff,
            )
        )
        is None
    )


def test_application_module_has_no_orm_or_cross_app_implementation_imports() -> None:
    source = Path("apps/account/application/physical_account_row_observation.py").read_text(
        encoding="utf-8"
    )
    assert ".objects" not in source
    assert "infrastructure" not in source
    assert "from apps.simulated_trading" not in source
    assert "import apps.simulated_trading" not in source
