"""Domain/Application contracts for the Signal-owned R7 calibration sample."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from apps.signal.application.forecast_calibration_sample import (
    ExactForecastCalibrationSampleCommand,
    ForecastCalibrationSampleUnavailable,
    GetExactForecastCalibrationSample,
    RegisterForecastCalibrationSampleDefinition,
    RegisterForecastCalibrationSampleDefinitionCommand,
    RegisterForecastCalibrationSampleReceipt,
    RegisterForecastCalibrationSampleReceiptCommand,
)
from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationExpectedMember,
    ForecastCalibrationInvalidationEvidence,
    ForecastCalibrationResolution,
    ForecastCalibrationSampleDefinition,
    ForecastCalibrationSampleMemberReceipt,
    ForecastCalibrationSampleReceipt,
    ForecastCalibrationSampleSource,
    _utc_text,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from apps.signal.infrastructure.forecast_calibration_sample_codec import (
    ForecastCalibrationSampleCodecError,
    decode_forecast_calibration_sample_definition,
    decode_forecast_calibration_sample_receipt,
    encode_forecast_calibration_sample_definition,
    encode_forecast_calibration_sample_receipt,
)

NOW = datetime(2026, 8, 11, 4, tzinfo=UTC)
WINDOW_START = NOW - timedelta(days=120)
WINDOW_END = NOW - timedelta(days=20)
REVISION_A = UUID("11111111-1111-4111-8111-111111111111")
REVISION_B = UUID("22222222-2222-4222-8222-222222222222")
SET_REVISION = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_canonical_datetime_text_normalizes_equivalent_offsets_to_utc() -> None:
    """Equivalent instants cannot fork a canonical owner hash by offset spelling."""

    utc_value = datetime(2026, 8, 11, 4, tzinfo=UTC)
    plus_eight = datetime(2026, 8, 11, 12, tzinfo=timezone(timedelta(hours=8)))
    assert _utc_text(utc_value) == _utc_text(plus_eight)
    with pytest.raises(ValueError, match="timezone-aware"):
        _utc_text(utc_value.replace(tzinfo=None))


def _binding(revision: UUID, probability: str) -> ScenarioForecastBinding:
    return ScenarioForecastBinding.from_values(
        scenario_revision_id=revision,
        scenario_set_revision_id=SET_REVISION,
        subjective_probability=Decimal(probability),
        subjective_probability_source_version="subjective.v1",
    )


def _expected(
    entry_id: str,
    revision: UUID,
    probability: str,
    *,
    days: int,
) -> ForecastCalibrationExpectedMember:
    published_at = WINDOW_START + timedelta(days=days)
    return ForecastCalibrationExpectedMember.create(
        entry_id=entry_id,
        observation_version="forecast-observation.v1",
        forecast_group_id=f"group-{days}",
        binding=_binding(revision, probability),
        pit_manifest_id=f"pit-{days}",
        pit_manifest_version="pit.v1",
        pit_manifest_hash=(str(days % 10) * 64),
        censoring_rule_version="censor.v1",
        published_at=published_at,
        horizon_end=published_at + timedelta(days=10),
        entry_recorded_at=published_at + timedelta(hours=1),
        outcome_evidence_valid_until=NOW + timedelta(days=30),
        evidence_ref=f"signal://forecast/{entry_id}",
    )


def _source(scope_content_hash: str = "a" * 64) -> ForecastCalibrationSampleSource:
    return ForecastCalibrationSampleSource.create(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        scope_content_hash=scope_content_hash,
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=10),
        censoring_rule_version="censor.v1",
        sample_window_start=WINDOW_START,
        sample_window_end=WINDOW_END,
        available_at=NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(days=30),
        evidence_ref="signal://calibration/sample-1",
        members=(
            _expected("entry-a", REVISION_A, "0.6", days=1),
            _expected("entry-b", REVISION_B, "0.4", days=1),
            _expected("entry-c", REVISION_A, "0.7", days=30),
            _expected("entry-d", REVISION_B, "0.3", days=30),
        ),
    )


def _owner(
    member: ForecastCalibrationExpectedMember,
    state: ForecastCalibrationResolution,
    *,
    scenario_realized: bool | None = None,
) -> ForecastCalibrationEntryOwnerRecord:
    invalidation = None
    if state is ForecastCalibrationResolution.INVALIDATED:
        invalidation = ForecastCalibrationInvalidationEvidence.create(
            evidence_version="invalidation.v1",
            invalidated_at=member.horizon_end - timedelta(days=1),
            invalidation_rule_version="rule.v1",
            evidence_refs=(f"signal://invalidation/{member.entry_id}",),
        )
    outcome_recorded_at = (
        None
        if state is ForecastCalibrationResolution.UNRESOLVED
        else member.horizon_end + timedelta(hours=1)
    )
    return ForecastCalibrationEntryOwnerRecord.create(
        entry_id=member.entry_id,
        binding=member.binding,
        pit_manifest_id=member.pit_manifest_id,
        published_at=member.published_at,
        horizon_end=member.horizon_end,
        entry_recorded_at=member.entry_recorded_at,
        resolution=state,
        scenario_realized=scenario_realized,
        outcome_recorded_at=outcome_recorded_at,
        outcome_source_type=(None if outcome_recorded_at is None else state.value),
        outcome_source_hash=(None if outcome_recorded_at is None else "b" * 64),
        invalidation=invalidation,
    )


def _definition(scope_content_hash: str = "a" * 64) -> ForecastCalibrationSampleDefinition:
    return ForecastCalibrationSampleDefinition.create(
        source=_source(scope_content_hash),
        registered_at=NOW,
    )


def _receipt(scope_content_hash: str = "a" * 64) -> ForecastCalibrationSampleReceipt:
    definition = _definition(scope_content_hash)
    states = (
        (ForecastCalibrationResolution.RESOLVED, True),
        (ForecastCalibrationResolution.RESOLVED, False),
        (ForecastCalibrationResolution.UNRESOLVED, None),
        (ForecastCalibrationResolution.CENSORED, None),
    )
    members = tuple(
        ForecastCalibrationSampleMemberReceipt.from_sources(
            expected=expected,
            owner=_owner(expected, state, scenario_realized=realized),
            recorded_at=NOW,
        )
        for expected, (state, realized) in zip(definition.source.members, states, strict=True)
    )
    return ForecastCalibrationSampleReceipt.create(
        definition=definition,
        pit_as_of=NOW,
        recorded_at=NOW,
        members=members,
    )


def test_source_definition_seals_complete_expected_membership() -> None:
    """The definition owns the denominator before any outcome is read."""

    definition = _definition()

    assert len(definition.source.members) == 4
    assert tuple(item.entry_id for item in definition.source.members) == (
        "entry-a",
        "entry-b",
        "entry-c",
        "entry-d",
    )
    assert definition.source.scenario_revision_ids == (REVISION_A, REVISION_B)
    assert definition.registered_at == NOW
    assert definition.research_only is True
    assert definition.must_not_use_for_decision is True
    assert definition.must_not_execute is True


def test_receipt_preserves_resolved_unresolved_censored_and_invalidation() -> None:
    """Missing outcomes remain explicit denominator members, never dropped rows."""

    receipt = _receipt()
    assert tuple(item.resolution for item in receipt.members) == (
        ForecastCalibrationResolution.RESOLVED,
        ForecastCalibrationResolution.RESOLVED,
        ForecastCalibrationResolution.UNRESOLVED,
        ForecastCalibrationResolution.CENSORED,
    )
    assert receipt.members[0].scenario_realized is True
    assert receipt.members[1].scenario_realized is False
    assert receipt.members[2].scenario_realized is None
    assert receipt.members[2].outcome_recorded_at is None

    expected = _source().members[3]
    invalidated = ForecastCalibrationSampleMemberReceipt.from_sources(
        expected=expected,
        owner=_owner(expected, ForecastCalibrationResolution.INVALIDATED),
        recorded_at=NOW,
    )
    assert invalidated.resolution is ForecastCalibrationResolution.INVALIDATED
    assert invalidated.invalidation is not None
    assert invalidated.invalidation.invalidated_at < expected.horizon_end


def test_member_receipt_rejects_expected_owner_substitution() -> None:
    """A different Forecast Ledger binding cannot satisfy expected membership."""

    expected = _source().members[0]
    owner = _owner(expected, ForecastCalibrationResolution.UNRESOLVED)
    object.__setattr__(owner, "binding", _binding(REVISION_B, "0.6"))
    with pytest.raises(ValueError, match="expected|substitut|binding"):
        ForecastCalibrationSampleMemberReceipt.from_sources(
            expected=expected,
            owner=owner,
            recorded_at=NOW,
        )


def test_commands_are_identity_asof_only_and_query_is_scope_window_pit() -> None:
    """No public command accepts an outcome, probability, receipt, or clock."""

    assert tuple(
        item.name for item in fields(RegisterForecastCalibrationSampleDefinitionCommand)
    ) == ("sample_id", "sample_version", "as_of")
    assert tuple(item.name for item in fields(RegisterForecastCalibrationSampleReceiptCommand)) == (
        "sample_id",
        "sample_version",
        "as_of",
    )
    assert tuple(item.name for item in fields(ExactForecastCalibrationSampleCommand)) == (
        "scope_content_hash",
        "sample_window_start",
        "sample_window_end",
        "as_of",
    )


class _CountingDefinitionWriter:
    def __init__(self) -> None:
        self.calls = 0

    def register(
        self, command: RegisterForecastCalibrationSampleDefinitionCommand
    ) -> ForecastCalibrationSampleDefinition:
        self.calls += 1
        return _definition()


class _CountingReceiptWriter:
    def __init__(self) -> None:
        self.calls = 0

    def register(
        self, command: RegisterForecastCalibrationSampleReceiptCommand
    ) -> ForecastCalibrationSampleReceipt:
        self.calls += 1
        return _receipt()


def test_mutated_commands_fail_before_any_owner_read_or_write() -> None:
    """Frozen-instance and instance-validator bypasses stop at Application."""

    definition_writer = _CountingDefinitionWriter()
    definition_use_case = RegisterForecastCalibrationSampleDefinition(definition_writer)
    definition_command = RegisterForecastCalibrationSampleDefinitionCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=NOW,
    )
    object.__setattr__(definition_command, "sample_id", "")
    object.__setattr__(definition_command, "__post_init__", lambda: None)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="malformed"):
        definition_use_case.execute(definition_command)
    assert definition_writer.calls == 0

    receipt_writer = _CountingReceiptWriter()
    receipt_use_case = RegisterForecastCalibrationSampleReceipt(receipt_writer)
    receipt_command = RegisterForecastCalibrationSampleReceiptCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=NOW,
    )
    object.__setattr__(receipt_command, "as_of", datetime(2026, 8, 11))
    object.__setattr__(receipt_command, "__post_init__", lambda: None)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="malformed"):
        receipt_use_case.execute(receipt_command)
    assert receipt_writer.calls == 0


class _EmptyRepository:
    unit_of_work_key = "django:default"

    def get_for_scope(self, **selectors: object) -> None:
        assert selectors["scope_content_hash"] == "a" * 64
        return None


def test_empty_exact_scope_window_query_preserves_blocking_none() -> None:
    """An empty owner registry does not synthesize an empty/100%-coverage sample."""

    query = GetExactForecastCalibrationSample(_EmptyRepository())
    assert (
        query.execute(
            ExactForecastCalibrationSampleCommand(
                scope_content_hash="a" * 64,
                sample_window_start=WINDOW_START,
                sample_window_end=WINDOW_END,
                as_of=NOW,
            )
        )
        is None
    )


def test_strict_codec_round_trips_definition_and_receipt() -> None:
    """Canonical JSON payloads preserve every nested identity and raw clock."""

    definition = _definition()
    receipt = _receipt()

    assert (
        decode_forecast_calibration_sample_definition(
            encode_forecast_calibration_sample_definition(definition)
        )
        == definition
    )
    assert (
        decode_forecast_calibration_sample_receipt(
            encode_forecast_calibration_sample_receipt(receipt)
        )
        == receipt
    )


def test_strict_codec_rejects_unknown_or_missing_nested_keys() -> None:
    """Schema drift and partial member payloads fail closed."""

    definition_payload = encode_forecast_calibration_sample_definition(_definition())
    definition_payload["unexpected"] = True
    with pytest.raises(ForecastCalibrationSampleCodecError, match="keys"):
        decode_forecast_calibration_sample_definition(definition_payload)

    receipt_payload = encode_forecast_calibration_sample_receipt(_receipt())
    member_payload = receipt_payload["members"][0]
    assert isinstance(member_payload, dict)
    owner_payload = member_payload["owner"]
    assert isinstance(owner_payload, dict)
    owner_payload.pop("outcome_source_hash")
    with pytest.raises(ForecastCalibrationSampleCodecError, match="keys"):
        decode_forecast_calibration_sample_receipt(receipt_payload)
