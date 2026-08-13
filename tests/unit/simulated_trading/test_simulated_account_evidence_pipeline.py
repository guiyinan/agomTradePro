from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
    SimulatedAccountRawObservationConflict,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline import (
    SimulatedAccountEvidencePipeline,
    SimulatedAccountEvidencePipelineAliases,
    SimulatedAccountEvidencePipelineCorruption,
    UnverifiedCanonicalAccountReference,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


class _Connection:
    in_atomic_block = True


def _mutation(version: str) -> SimulatedAccountPhysicalRowMutation:
    return SimulatedAccountPhysicalRowMutation(
        observation_id="opaque-row-stream-7",
        mutation_version=version,
        row_pk=7,
        row_user_id=19,
        raw_account_type="simulated",
        is_active=True,
        row_created_at=NOW - timedelta(days=2),
        row_updated_at=NOW - timedelta(hours=2),
        observed_at=NOW - timedelta(hours=1),
    )


def _raw(*, terminal: bool) -> SimulatedAccountRawObservation:
    mutation = _mutation("event-1")
    return SimulatedAccountRawObservation(
        observation_id=mutation.observation_id,
        observation_version=mutation.mutation_version,
        row_pk=mutation.row_pk,
        row_user_id=mutation.row_user_id,
        raw_account_type=mutation.raw_account_type,
        is_active=mutation.is_active if not terminal else False,
        row_created_at=mutation.row_created_at,
        row_updated_at=mutation.row_updated_at,
        is_present=not terminal,
        is_tombstone=terminal,
        observed_at=mutation.observed_at,
        valid_until=NOW + timedelta(days=2),
    )


def _source(raw: SimulatedAccountRawObservation) -> SimulatedAccountRowSourceV2:
    return SimulatedAccountRowSourceV2(
        source_id=raw.observation_id,
        source_version=raw.observation_version,
        account_namespace="account",
        account_id="0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=raw.row_pk,
        row_user_id=raw.row_user_id,
        raw_account_type=raw.raw_account_type,
        is_active=raw.is_active,
        row_created_at=raw.row_created_at,
        row_updated_at=raw.row_updated_at,
        is_present=raw.is_present,
        is_tombstone=raw.is_tombstone,
        observed_at=raw.observed_at,
        recorded_at=NOW - timedelta(minutes=30),
        source_valid_until=raw.valid_until,
        ttl_valid_until=NOW + timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        raw_observation_id=raw.observation_id,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
    )


def _account(source: SimulatedAccountRowSourceV2) -> PhysicalAccountRowObservationV2:
    return PhysicalAccountRowObservationV2(
        observation_id=source.source_id,
        observation_version=source.source_version,
        account_namespace=source.account_namespace,
        account_id=source.account_id,
        underlying_unified_account_namespace=source.underlying_unified_account_namespace,
        underlying_unified_account_id=source.underlying_unified_account_id,
        row_user_id=source.row_user_id,
        raw_account_type=source.raw_account_type,
        is_active=source.is_active,
        row_created_at=source.row_created_at,
        row_updated_at=source.row_updated_at,
        is_present=source.is_present,
        is_tombstone=source.is_tombstone,
        source_id=source.source_id,
        source_version=source.source_version,
        source_identity_hash=source.identity_hash,
        source_content_hash=source.content_hash,
        source_supersedes_content_hash=source.supersedes_content_hash,
        source_observed_at=source.observed_at,
        source_recorded_at=source.recorded_at,
        source_valid_until=source.source_valid_until,
        source_ttl_valid_until=source.ttl_valid_until,
        source_effective_valid_until=source.valid_until,
        raw_observation_id=source.raw_observation_id,
        raw_observation_version=source.raw_observation_version,
        raw_observation_identity_hash=source.raw_observation_identity_hash,
        raw_observation_content_hash=source.raw_observation_content_hash,
        raw_observation_supersedes_content_hash=(source.raw_observation_supersedes_content_hash),
        raw_observation_observed_at=source.raw_observation_observed_at,
        raw_observation_valid_until=source.raw_observation_valid_until,
        recorded_at=NOW - timedelta(minutes=20),
        ttl_valid_until=NOW + timedelta(hours=12),
        valid_until=NOW + timedelta(hours=12),
    )


class _RawWriter:
    def __init__(self, value: SimulatedAccountRawObservation, calls: list[str]) -> None:
        self.value = value
        self.calls = calls

    def record_create(self, mutation: SimulatedAccountPhysicalRowMutation):
        self.calls.append("raw:create")
        return self.value

    def record_update(self, mutation: SimulatedAccountPhysicalRowMutation):
        self.calls.append("raw:update")
        return self.value

    def record_delete(self, mutation: SimulatedAccountPhysicalRowMutation):
        self.calls.append("raw:delete")
        return self.value


class _SourceCapture:
    def __init__(self, value: SimulatedAccountRowSourceV2, calls: list[str]) -> None:
        self.value = value
        self.calls = calls
        self.commands: list[CaptureSimulatedAccountRowSourceV2Command] = []

    def execute(self, command: CaptureSimulatedAccountRowSourceV2Command):
        self.calls.append("source:v2")
        self.commands.append(command)
        return self.value


class _AccountCapture:
    def __init__(self, value: PhysicalAccountRowObservationV2, calls: list[str]) -> None:
        self.value = value
        self.calls = calls
        self.commands: list[CapturePhysicalAccountRowObservationV2Command] = []

    def execute(self, command: CapturePhysicalAccountRowObservationV2Command):
        self.calls.append("account:v2")
        self.commands.append(command)
        return self.value


@pytest.mark.parametrize(
    ("method_name", "terminal"),
    [("record_create", False), ("record_update", False), ("record_delete", True)],
)
def test_all_mutations_run_raw_source_v2_account_v2_in_order(
    monkeypatch: pytest.MonkeyPatch, method_name: str, terminal: bool
) -> None:
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline.connections",
        {"owner": _Connection()},
    )
    calls: list[str] = []
    raw = _raw(terminal=terminal)
    source = _source(raw)
    account_observation = _account(source)
    source_capture = _SourceCapture(source, calls)
    account_capture = _AccountCapture(account_observation, calls)
    pipeline = SimulatedAccountEvidencePipeline(
        aliases=SimulatedAccountEvidencePipelineAliases("owner", "owner", "owner", "owner"),
        raw_writer=_RawWriter(raw, calls),
        source_capture=source_capture,
        account_capture=account_capture,
    )
    reference = UnverifiedCanonicalAccountReference("account", "0007", "simulated-account-row", 7)
    result = getattr(pipeline, method_name)(_mutation("event-1"), reference)
    assert calls == [f"raw:{method_name.removeprefix('record_')}", "source:v2", "account:v2"]
    assert source_capture.commands == [
        CaptureSimulatedAccountRowSourceV2Command(
            raw.observation_id,
            raw.observation_version,
            raw.content_hash,
            "account",
            "0007",
            "simulated-account-row",
            7,
        )
    ]
    assert account_capture.commands[0].expected_source_content_hash == source.content_hash
    assert result.account_v2.is_tombstone is terminal


def test_alias_or_missing_outer_transaction_fails_before_raw_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="share"):
        SimulatedAccountEvidencePipelineAliases("owner", "raw", "owner", "owner")
    _Connection.in_atomic_block = False
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline.connections",
        {"owner": _Connection()},
    )
    calls: list[str] = []
    raw = _raw(terminal=False)
    pipeline = SimulatedAccountEvidencePipeline(
        aliases=SimulatedAccountEvidencePipelineAliases("owner", "owner", "owner", "owner"),
        raw_writer=_RawWriter(raw, calls),
        source_capture=_SourceCapture(_source(raw), calls),
        account_capture=_AccountCapture(_account(_source(raw)), calls),
    )
    with pytest.raises(SimulatedAccountRawObservationConflict, match="transaction"):
        pipeline.record_create(
            _mutation("event-1"),
            UnverifiedCanonicalAccountReference("account", "0007", "row", 7),
        )
    assert calls == []
    _Connection.in_atomic_block = True


def test_source_failure_propagates_and_account_stage_is_not_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline.connections",
        {"owner": _Connection()},
    )
    calls: list[str] = []
    raw = _raw(terminal=False)

    class _FailingSource(_SourceCapture):
        def execute(self, command: CaptureSimulatedAccountRowSourceV2Command):
            self.calls.append("source:v2")
            raise RuntimeError("source append failed")

    pipeline = SimulatedAccountEvidencePipeline(
        aliases=SimulatedAccountEvidencePipelineAliases("owner", "owner", "owner", "owner"),
        raw_writer=_RawWriter(raw, calls),
        source_capture=_FailingSource(_source(raw), calls),
        account_capture=_AccountCapture(_account(_source(raw)), calls),
    )
    with pytest.raises(RuntimeError, match="source append"):
        pipeline.record_create(
            _mutation("event-1"),
            UnverifiedCanonicalAccountReference("account", "0007", "row", 7),
        )
    assert calls == ["raw:create", "source:v2"]


@pytest.mark.parametrize("substituted_stage", ["raw", "source", "account"])
def test_stage_result_substitution_fails_closed(
    monkeypatch: pytest.MonkeyPatch, substituted_stage: str
) -> None:
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline.connections",
        {"owner": _Connection()},
    )
    calls: list[str] = []
    raw = _raw(terminal=False)
    source = _source(raw)

    class _SubstitutedRaw(_RawWriter):
        def record_create(self, mutation: SimulatedAccountPhysicalRowMutation):
            self.calls.append("raw:create")
            return {"content_hash": raw.content_hash}

    class _SubstitutedSource(_SourceCapture):
        def execute(self, command: CaptureSimulatedAccountRowSourceV2Command):
            self.calls.append("source:v2")
            return {"content_hash": source.content_hash}

    class _SubstitutedAccount(_AccountCapture):
        def execute(self, command: CapturePhysicalAccountRowObservationV2Command):
            self.calls.append("account:v2")
            return {"content_hash": self.value.content_hash}

    pipeline = SimulatedAccountEvidencePipeline(
        aliases=SimulatedAccountEvidencePipelineAliases("owner", "owner", "owner", "owner"),
        raw_writer=(
            _SubstitutedRaw(raw, calls) if substituted_stage == "raw" else _RawWriter(raw, calls)
        ),
        source_capture=(
            _SubstitutedSource(source, calls)
            if substituted_stage == "source"
            else _SourceCapture(source, calls)
        ),
        account_capture=(
            _SubstitutedAccount(_account(source), calls)
            if substituted_stage == "account"
            else _AccountCapture(_account(source), calls)
        ),
    )
    with pytest.raises(SimulatedAccountEvidencePipelineCorruption, match="substituted"):
        pipeline.record_create(
            _mutation("event-1"),
            UnverifiedCanonicalAccountReference("account", "0007", "row", 7),
        )
