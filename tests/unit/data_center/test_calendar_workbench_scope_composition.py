"""Composition ownership for the read-only calendar workbench scope context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.db import DEFAULT_DB_ALIAS

from apps.data_center import calendar_workbench_scope_composition as composition
from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_CAPABILITY,
    CALENDAR_CAPTURE_VALIDATOR_KEY,
    CalendarCaptureBindingCandidate,
    CalendarCaptureConfigurationCandidates,
    CalendarCaptureConfigurationError,
    CalendarCaptureContractCandidate,
    CalendarCapturePolicyCandidate,
    CalendarCaptureProviderCandidate,
)
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchScopeMetadataStatus,
)
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from core.exceptions import DataValidationError

NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
OLD = NOW - timedelta(minutes=2)
DATASET = DatasetKey("data_center.exchange_calendar_snapshot", "2.0", "1.0")


def _candidates() -> CalendarCaptureConfigurationCandidates:
    """Build a version-exact metadata fixture with no credential values."""

    contract = DatasetContract(
        key=DATASET,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=(DatasetFieldContract("calendar_date", "date", None, False, False),),
        calendar_response_max_age_seconds=900,
    )
    policy = PublicationPolicy(
        dataset=DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    binding = ProviderBinding(
        dataset=DATASET,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
        priority=10,
        freshness_seconds=None,
        validator_key=CALENDAR_CAPTURE_VALIDATOR_KEY,
        enabled=True,
    )
    return CalendarCaptureConfigurationCandidates(
        contracts=(CalendarCaptureContractCandidate(contract, True, OLD, OLD),),
        policies=(CalendarCapturePolicyCandidate(policy, True, OLD, OLD),),
        bindings=(CalendarCaptureBindingCandidate(binding, True, OLD, OLD),),
        providers=(CalendarCaptureProviderCandidate(7, "tushare", True, OLD, OLD),),
    )


class _FakeConnection:
    """Expose the transaction state inspected by the composition boundary."""

    def __init__(
        self,
        *,
        alias: str = DEFAULT_DB_ALIAS,
        in_atomic_block: bool = False,
        autocommit: bool = True,
    ) -> None:
        self.alias = alias
        self.in_atomic_block = in_atomic_block
        self._autocommit = autocommit
        self.atomic_blocks: list[object] = []

    def get_autocommit(self) -> bool:
        """Return the controlled connection autocommit state."""

        return self._autocommit


class _FakeConnections:
    """Resolve only the configured operational database alias."""

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __getitem__(self, alias: str) -> _FakeConnection:
        assert alias == DEFAULT_DB_ALIAS
        return self.connection


class _Clock:
    """Return a chosen server clock value and record the read boundary."""

    def __init__(self, events: list[str], value: object = NOW) -> None:
        self.events = events
        self.value = value

    def now(self) -> datetime:
        """Return the test-controlled clock value."""

        self.events.append("clock")
        return self.value  # type: ignore[return-value]


class _CandidateRepository:
    """Expose only candidate reads; provider-secret lookup is forbidden here."""

    def __init__(
        self,
        connection: _FakeConnection,
        events: list[str],
        candidates: CalendarCaptureConfigurationCandidates,
    ) -> None:
        self.connection = connection
        self.events = events
        self.candidates = candidates
        self.provider_config_calls = 0

    def load_candidates(self, *, using: str) -> CalendarCaptureConfigurationCandidates:
        """Return candidates only while the composition owns one outer block."""

        assert using == DEFAULT_DB_ALIAS
        assert self.connection.alias == DEFAULT_DB_ALIAS
        assert self.connection.in_atomic_block
        assert not self.connection.get_autocommit()
        assert len(self.connection.atomic_blocks) == 1
        self.events.append("load-candidates")
        return self.candidates

    def get_provider_config(self, provider_id: int, *, using: str) -> None:
        """Fail if metadata composition attempts credential-bearing resolution."""

        del provider_id, using
        self.provider_config_calls += 1
        raise AssertionError("metadata scope must not resolve provider credentials")


def _patch_composition(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connection: _FakeConnection,
    repository: _CandidateRepository,
    clock: _Clock,
) -> list[str]:
    """Replace only Django boundary objects while retaining real App use cases."""

    events = repository.events

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        assert using == DEFAULT_DB_ALIAS
        assert not connection.in_atomic_block
        assert connection.get_autocommit()
        block = object()
        connection.in_atomic_block = True
        connection._autocommit = False
        connection.atomic_blocks.append(block)
        events.append("atomic-enter")
        try:
            yield
        finally:
            events.append("atomic-exit")
            connection.atomic_blocks.pop()
            connection.in_atomic_block = False
            connection._autocommit = True

    monkeypatch.setattr(composition, "connections", _FakeConnections(connection))
    monkeypatch.setattr(composition, "transaction", SimpleNamespace(atomic=atomic))
    monkeypatch.setattr(
        composition,
        "DjangoCalendarCaptureConfigurationRepository",
        lambda: repository,
    )
    monkeypatch.setattr(composition, "_ServerClock", lambda: clock)
    return events


def test_read_scope_owns_one_default_transaction_and_never_resolves_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return metadata only after one default transaction exits successfully."""

    connection = _FakeConnection()
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    events = _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events),
    )

    result = composition.read_calendar_workbench_scope_context()

    assert result.metadata_status is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED
    assert result.metadata is not None
    assert result.metadata.provider_id == 7
    assert result.known_at == NOW
    assert events.count("atomic-enter") == 1
    assert events.count("atomic-exit") == 1
    assert events.index("clock") < events.index("load-candidates")
    assert not connection.in_atomic_block
    assert connection.get_autocommit()
    assert repository.provider_config_calls == 0


def test_explicit_calendar_configuration_read_preserves_cutoff_without_server_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Select existing metadata at the manual caller's cutoff without new I/O."""

    connection = _FakeConnection()
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events, object()),
    )
    reader = getattr(composition, "read_calendar_capture_configuration_at", None)
    assert callable(reader), "feature missing: exact-cutoff calendar configuration read"

    result = reader(as_of=NOW)

    assert result.dataset == DATASET
    assert result.known_at == NOW
    assert events == ["atomic-enter", "load-candidates", "atomic-exit"]
    assert repository.provider_config_calls == 0


def test_explicit_calendar_configuration_read_rejects_later_known_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current metadata cannot be backdated into an earlier manual cutoff."""

    connection = _FakeConnection()
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events),
    )
    reader = getattr(composition, "read_calendar_capture_configuration_at", None)
    assert callable(reader), "feature missing: exact-cutoff calendar configuration read"

    with pytest.raises(CalendarCaptureConfigurationError) as error:
        reader(as_of=OLD - timedelta(microseconds=1))

    assert error.value.code == "CALENDAR_CAPTURE_METADATA_NOT_KNOWN"
    assert "clock" not in events
    assert events.count("atomic-exit") == 1
    assert not connection.in_atomic_block


def test_exact_cutoff_reference_reuses_one_existing_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read exact-cutoff metadata without adding a transaction savepoint."""

    connection = _FakeConnection(in_atomic_block=True, autocommit=False)
    connection.atomic_blocks.append(object())
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events, object()),
    )
    reader = getattr(
        composition,
        "read_calendar_capture_configuration_reference_at",
        None,
    )
    assert callable(reader), "feature missing: outer-transaction calendar reference"

    result = reader(as_of=NOW)

    assert result.dataset == DATASET
    assert result.known_at == NOW
    assert events == ["load-candidates"]
    assert len(connection.atomic_blocks) == 1
    assert not connection.get_autocommit()
    assert repository.provider_config_calls == 0


def test_exact_cutoff_reference_delegates_to_owned_reader_without_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the composition-owned transaction when no outer one exists."""

    connection = _FakeConnection()
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events, object()),
    )
    reader = getattr(
        composition,
        "read_calendar_capture_configuration_reference_at",
        None,
    )
    assert callable(reader), "feature missing: outer-transaction calendar reference"

    result = reader(as_of=NOW)

    assert result.dataset == DATASET
    assert result.known_at == NOW
    assert events == ["atomic-enter", "load-candidates", "atomic-exit"]
    assert not connection.in_atomic_block
    assert repository.provider_config_calls == 0


@pytest.mark.parametrize(
    ("connection", "expected_code"),
    [
        (
            _FakeConnection(in_atomic_block=True, autocommit=False),
            "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED",
        ),
        (
            _FakeConnection(alias="secondary", in_atomic_block=True, autocommit=False),
            "CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED",
        ),
    ],
)
def test_exact_cutoff_reference_rejects_nested_or_nondefault_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
    connection: _FakeConnection,
    expected_code: str,
) -> None:
    """Reject nested transactions and aliases before repository access."""

    connection.atomic_blocks.extend((object(), object()))
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events),
    )
    reader = getattr(
        composition,
        "read_calendar_capture_configuration_reference_at",
        None,
    )
    assert callable(reader), "feature missing: outer-transaction calendar reference"

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        reader(as_of=NOW)

    assert raised.value.code == expected_code
    assert events == []
    assert repository.provider_config_calls == 0


def test_original_exact_cutoff_reader_still_rejects_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the original API restricted to transactions it owns itself."""

    connection = _FakeConnection(in_atomic_block=True, autocommit=False)
    connection.atomic_blocks.append(object())
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events),
    )

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        composition.read_calendar_capture_configuration_at(as_of=NOW)

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
    assert events == []
    assert repository.provider_config_calls == 0


@pytest.mark.parametrize(
    ("connection", "expected_code"),
    [
        (
            _FakeConnection(in_atomic_block=True, autocommit=False),
            "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED",
        ),
        (
            _FakeConnection(in_atomic_block=False, autocommit=False),
            "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED",
        ),
        (
            _FakeConnection(alias="secondary"),
            "CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED",
        ),
    ],
)
def test_rejects_caller_owned_or_nondefault_transaction_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    connection: _FakeConnection,
    expected_code: str,
) -> None:
    """Reject a foreign transaction and alias before building configuration IO."""

    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    events = _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events),
    )

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        composition.read_calendar_workbench_scope_context()

    assert raised.value.code == expected_code
    assert events == []
    assert repository.provider_config_calls == 0


def test_invalid_clock_fails_before_candidate_read_and_outer_transaction_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not query catalog metadata when the server clock is not aware UTC."""

    connection = _FakeConnection()
    events: list[str] = []
    repository = _CandidateRepository(connection, events, _candidates())
    events = _patch_composition(
        monkeypatch,
        connection=connection,
        repository=repository,
        clock=_Clock(events, NOW.replace(tzinfo=None)),
    )

    with pytest.raises(DataValidationError) as raised:
        composition.read_calendar_workbench_scope_context()

    assert raised.value.code == "CALENDAR_WORKBENCH_SCOPE_CLOCK_INVALID"
    assert "load-candidates" not in events
    assert events.count("atomic-exit") == 1
    assert not connection.in_atomic_block
    assert repository.provider_config_calls == 0
