from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime

import pytest

import core.integration.canonical_account_ownership_reobservation as subject
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _at,
    _binding,
)
from tests.unit.account.test_physical_account_row_observation_v2 import (
    _observation,
    _raw,
    _source,
)


def _settings() -> CanonicalAccountCreationEvidenceSettings:
    """Return a complete settings snapshot for composition-only tests."""

    return CanonicalAccountCreationEvidenceSettings(
        schema_version=ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        ttl_seconds=300,
        allocation_recorder_service_id="allocation-recorder-test",
        physical_v2_recorder_service_id="physical-recorder-test",
        allocated_v3_recorder_service_id="allocated-recorder-test",
        binding_recorder_service_id="binding-recorder-test",
    )


@dataclass
class _Operation:
    """Record one stage invocation and return a prebuilt domain value."""

    name: str
    result: object
    events: list[tuple[str, object]]

    def execute(self, command: object) -> object:
        """Record the command without replacing the real application operation."""

        self.events.append((self.name, command))
        return self.result


@dataclass
class _AccountStages:
    """Small test double exposing the public Account composition ports."""

    database_alias: str
    get_exact_binding: _Operation
    physical_capture: _Operation
    allocate: _Operation
    allocated_capture: _Operation
    bind: _Operation


@dataclass
class _OwnerStages:
    """Small test double exposing the public owner source-capture port."""

    database_alias: str
    source_capture: _Operation


class _Reobserver:
    """Record the low-level re-observation command for call-order assertions."""

    def __init__(self, result: object, events: list[tuple[str, object]]) -> None:
        self._result = result
        self._events = events

    def execute(self, command: object) -> object:
        """Return the prepared raw successor after recording its selector."""

        self._events.append(("reobserver", command))
        return self._result


class _DurableRepository:
    """Record the durable append without opening a Django connection."""

    def __init__(self, *, using: str, events: list[tuple[str, object]]) -> None:
        self._using = using
        self._events = events

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self._events.append(("durable-enter", self._using))
        try:
            yield
        finally:
            self._events.append(("durable-exit", self._using))

    def now(self) -> datetime:
        return _at(30)

    def get_winner(
        self, *, observation_id: str, observation_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        del observation_id, observation_version, as_of
        return None

    def append(
        self,
        record: PersistedCanonicalAccountOwnershipReobservationV1,
        *,
        recorded_at: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        self._events.append(("durable-append", recorded_at))
        return record

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        del observation_id, observation_version, expected_content_hash, as_of
        return None


@dataclass
class _Fixture:
    """Complete immutable-chain values used by the composition tests."""

    binding: object
    raw: SimulatedAccountRawObservation
    source: SimulatedAccountRowSourceV2
    physical: object
    command: subject.CanonicalAccountOwnershipReobservationCommand
    requester: CanonicalAccountCreationRequester


def _fixture() -> _Fixture:
    """Build a successor whose old physical identity comes only from Binding-v2."""

    binding = _binding()
    old_physical = binding.creation_root.physical_observation
    command = subject.CanonicalAccountOwnershipReobservationCommand(
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        expected_binding_content_hash=binding.content_hash,
        observation_id="account-row-reobserve-v2",
        observation_version="v2",
    )
    raw = _raw(
        observation_id=command.observation_id,
        observation_version=command.observation_version,
        row_pk=old_physical.underlying_unified_account_id,
        row_user_id=old_physical.row_user_id,
        raw_account_type=old_physical.raw_account_type,
        row_created_at=old_physical.row_created_at,
        row_updated_at=old_physical.row_updated_at,
        observed_at=_at(8),
        valid_until=_at(30),
        supersedes_content_hash=old_physical.raw_observation_content_hash,
    )
    source = _source(
        raw=raw,
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        underlying_unified_account_namespace=(binding.underlying_unified_account_namespace_claim),
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        recorded_at=_at(8),
        ttl_valid_until=_at(20),
        valid_until=_at(20),
        supersedes_content_hash=old_physical.source_content_hash,
    )
    physical = _observation(
        source=source,
        observation_id=command.observation_id,
        observation_version=command.observation_version,
        recorded_at=_at(9),
        ttl_valid_until=_at(15),
        valid_until=_at(15),
        supersedes_content_hash=old_physical.content_hash,
    )
    return _Fixture(
        binding=binding,
        raw=raw,
        source=source,
        physical=physical,
        command=command,
        requester=binding.allocation.requested_by,
    )


def _install_composition(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
    events: list[tuple[str, object]],
) -> None:
    """Inject public-stage doubles while retaining the real Core validation."""

    account_stages = _AccountStages(
        database_alias="ownership-test",
        get_exact_binding=_Operation("get_exact_binding", fixture.binding, events),
        physical_capture=_Operation("physical_capture", fixture.physical, events),
        allocate=_Operation("allocate", None, events),
        allocated_capture=_Operation("allocated_capture", None, events),
        bind=_Operation("bind", None, events),
    )
    owner_stages = _OwnerStages(
        database_alias="ownership-test",
        source_capture=_Operation("source_capture", fixture.source, events),
    )

    def build_account(**_: object) -> _AccountStages:
        """Return the account test stages without touching Django or a database."""

        events.append(("build-account", None))
        return account_stages

    def build_owner(**_: object) -> _OwnerStages:
        """Return the owner test stages without opening a database connection."""

        events.append(("build-owner", None))
        return owner_stages

    def build_reobserver(**_: object) -> _Reobserver:
        """Return a test double for the public existing-row reobserver."""

        events.append(("build-reobserver", None))
        return _Reobserver(fixture.raw, events)

    @contextmanager
    def transaction(*, using: str, user_id: int) -> Iterator[None]:
        """Record the caller-owned transaction envelope and always close it."""

        events.append(("transaction-enter", (using, user_id)))
        try:
            yield
        finally:
            events.append(("transaction-exit", (using, user_id)))

    monkeypatch.setattr(subject, "build_canonical_account_creation_stages", build_account)
    monkeypatch.setattr(subject, "build_simulated_account_creation_stages", build_owner)
    monkeypatch.setattr(subject, "build_existing_account_reobserver", build_reobserver)
    monkeypatch.setattr(subject, "account_creation_transaction", transaction)
    monkeypatch.setattr(
        subject,
        "build_canonical_account_ownership_reobservation_repository",
        lambda *, using: _DurableRepository(using=using, events=events),
    )


def test_reobserve_reads_exact_binding_and_persists_the_durable_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    clock_values = iter((_at(10), _at(11)))
    monkeypatch.setattr(subject, "_server_now", lambda: next(clock_values))

    result = subject.reobserve_canonical_account_ownership(
        command=fixture.command,
        requester=fixture.requester,
        using="ownership-test",
        settings=_settings(),
    )

    assert type(result) is CanonicalAccountOwnershipReobservationV1
    assert result.binding is fixture.binding
    assert result.current_physical is fixture.physical
    assert result.recorded_at == _at(11)
    assert result.valid_until == fixture.physical.valid_until

    stage_events = [
        name
        for name, _ in events
        if name
        in {
            "transaction-enter",
            "get_exact_binding",
            "reobserver",
            "source_capture",
            "physical_capture",
            "durable-enter",
            "durable-append",
            "durable-exit",
            "transaction-exit",
            "allocate",
            "allocated_capture",
            "bind",
        }
    ]
    assert stage_events == [
        "transaction-enter",
        "get_exact_binding",
        "reobserver",
        "source_capture",
        "physical_capture",
        "durable-enter",
        "durable-append",
        "durable-exit",
        "transaction-exit",
    ]

    binding_command = next(value for name, value in events if name == "get_exact_binding")
    assert type(binding_command) is GetExactCanonicalAccountCreationBindingV2Command
    assert binding_command.binding_id == fixture.binding.binding_id
    assert binding_command.binding_version == fixture.binding.binding_version
    assert binding_command.expected_content_hash == fixture.binding.content_hash
    assert binding_command.as_of == _at(10)

    reobserve_command = next(value for name, value in events if name == "reobserver")
    assert type(reobserve_command) is ReobserveExistingAccountRowCommand
    assert reobserve_command.row_pk == fixture.binding.underlying_unified_account_id_claim
    assert reobserve_command.expected_user_id == fixture.binding.allocation.requested_row_user_id
    assert reobserve_command.expected_account_type is AccountType.SIMULATED
    assert (
        reobserve_command.expected_created_at
        == fixture.binding.creation_root.physical_observation.row_created_at
    )

    source_command = next(value for name, value in events if name == "source_capture")
    assert type(source_command) is CaptureSimulatedAccountRowSourceV2Command
    assert source_command.source_id == fixture.raw.observation_id
    assert source_command.source_version == fixture.raw.observation_version
    assert source_command.expected_raw_observation_content_hash == fixture.raw.content_hash

    physical_command = next(value for name, value in events if name == "physical_capture")
    assert type(physical_command) is CapturePhysicalAccountRowObservationV2Command
    assert physical_command.source_id == fixture.source.source_id
    assert physical_command.source_version == fixture.source.source_version
    assert physical_command.expected_source_content_hash == fixture.source.content_hash


def test_missing_binding_fails_before_any_successor_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    monkeypatch.setattr(
        subject,
        "build_canonical_account_creation_stages",
        lambda **_: _AccountStages(
            database_alias="ownership-test",
            get_exact_binding=_Operation("get_exact_binding", None, events),
            physical_capture=_Operation("physical_capture", fixture.physical, events),
            allocate=_Operation("allocate", None, events),
            allocated_capture=_Operation("allocated_capture", None, events),
            bind=_Operation("bind", None, events),
        ),
    )
    monkeypatch.setattr(subject, "_server_now", lambda: _at(10))

    with pytest.raises(subject.CanonicalAccountOwnershipReobservationUnavailable):
        subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=fixture.requester,
            using="ownership-test",
            settings=_settings(),
        )

    names = [name for name, _ in events]
    assert names.index("get_exact_binding") < len(names)
    assert "reobserver" not in names
    assert "source_capture" not in names
    assert "physical_capture" not in names


def test_requester_must_match_binding_owner_before_row_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    monkeypatch.setattr(subject, "_server_now", lambda: _at(10))
    wrong_requester = CanonicalAccountCreationRequester(
        actor_id=fixture.requester.actor_id,
        user_id=fixture.requester.user_id + 1,
    )

    with pytest.raises(subject.CanonicalAccountOwnershipReobservationConflict):
        subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=wrong_requester,
            using="ownership-test",
            settings=_settings(),
        )

    assert "get_exact_binding" in [name for name, _ in events]
    assert "reobserver" not in [name for name, _ in events]
    assert "source_capture" not in [name for name, _ in events]
    assert "physical_capture" not in [name for name, _ in events]


def test_binding_reader_substitution_fails_closed_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    substituted = replace(
        fixture.binding, binding_version="substituted-v2", identity_hash="", content_hash=""
    )
    monkeypatch.setattr(
        subject,
        "build_canonical_account_creation_stages",
        lambda **_: _AccountStages(
            database_alias="ownership-test",
            get_exact_binding=_Operation("get_exact_binding", substituted, events),
            physical_capture=_Operation("physical_capture", fixture.physical, events),
            allocate=_Operation("allocate", None, events),
            allocated_capture=_Operation("allocated_capture", None, events),
            bind=_Operation("bind", None, events),
        ),
    )
    monkeypatch.setattr(subject, "_server_now", lambda: _at(10))

    with pytest.raises(subject.CanonicalAccountOwnershipReobservationCorruption):
        subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=fixture.requester,
            using="ownership-test",
            settings=_settings(),
        )

    assert "reobserver" not in [name for name, _ in events]


def test_successor_substitution_is_rejected_before_physical_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    substituted = replace(
        fixture.source, account_id="forged-account", identity_hash="", content_hash=""
    )
    monkeypatch.setattr(
        subject,
        "build_simulated_account_creation_stages",
        lambda **_: _OwnerStages(
            database_alias="ownership-test",
            source_capture=_Operation("source_capture", substituted, events),
        ),
    )
    monkeypatch.setattr(subject, "_server_now", lambda: _at(10))

    with pytest.raises(subject.CanonicalAccountOwnershipReobservationCorruption):
        subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=fixture.requester,
            using="ownership-test",
            settings=_settings(),
        )

    assert "physical_capture" not in [name for name, _ in events]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("binding_id", True), ("observation_version", 1), ("expected_binding_content_hash", "")],
)
def test_command_rejects_client_identity_type_or_hash(
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture()
    values: dict[str, object] = {
        "binding_id": fixture.command.binding_id,
        "binding_version": fixture.command.binding_version,
        "expected_binding_content_hash": fixture.command.expected_binding_content_hash,
        "observation_id": fixture.command.observation_id,
        "observation_version": fixture.command.observation_version,
    }
    values[field_name] = value

    with pytest.raises((TypeError, ValueError)):
        subject.CanonicalAccountOwnershipReobservationCommand(**values)  # type: ignore[arg-type]


def test_invalid_composition_alias_is_rejected_before_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    monkeypatch.setattr(subject, "_server_now", lambda: _at(10))

    monkeypatch.setattr(
        subject,
        "build_simulated_account_creation_stages",
        lambda **_: _OwnerStages(
            database_alias="different-alias",
            source_capture=_Operation("source_capture", fixture.source, events),
        ),
    )

    with pytest.raises(subject.CanonicalAccountOwnershipReobservationCorruption):
        subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=fixture.requester,
            using="ownership-test",
            settings=_settings(),
        )

    assert not any(name == "transaction-enter" for name, _ in events)


@pytest.mark.parametrize("recording_day", [11, 15, 16])
def test_proof_uses_actual_final_clock_and_rejects_capture_expired_during_sealing(
    monkeypatch: pytest.MonkeyPatch, recording_day: int
) -> None:
    fixture = _fixture()
    events: list[tuple[str, object]] = []
    _install_composition(monkeypatch, fixture, events)
    clocks = iter((_at(10), _at(recording_day)))
    monkeypatch.setattr(subject, "_server_now", lambda: next(clocks))

    if recording_day >= 15:
        with pytest.raises(subject.CanonicalAccountOwnershipReobservationCorruption):
            subject.reobserve_canonical_account_ownership(
                command=fixture.command,
                requester=fixture.requester,
                using="ownership-test",
                settings=_settings(),
            )
    else:
        proof = subject.reobserve_canonical_account_ownership(
            command=fixture.command,
            requester=fixture.requester,
            using="ownership-test",
            settings=_settings(),
        )
        assert proof.recorded_at == _at(recording_day)
        assert proof.recorded_at > proof.current_physical.recorded_at
