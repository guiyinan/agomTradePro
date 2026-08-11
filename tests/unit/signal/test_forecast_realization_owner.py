"""Contracts for the Signal-owned R7 realization manifest bridge."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.signal.application.forecast_realization_owner import (
    AppendForecastRealizationManifest,
    AppendForecastRealizationManifestCommand,
    ExactForecastRealizationManifestCommand,
    ForecastRealizationOwnerUnavailable,
    GetExactForecastRealizationManifest,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastOutcomeOwnerRecord,
    ForecastRealizationManifest,
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
    forecast_observation_hash_from_values,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

PUBLISHED_AT = datetime(2026, 7, 1, tzinfo=UTC)
PERIOD_START = datetime(2026, 7, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 8, 1, tzinfo=UTC)
OUTCOME_RECORDED_AT = PERIOD_END + timedelta(hours=1)
MEMBER_AVAILABLE_AT = PERIOD_END + timedelta(hours=2)
MANIFEST_AVAILABLE_AT = PERIOD_END + timedelta(hours=3)
RECORDED_AT = PERIOD_END + timedelta(hours=4)
VALID_UNTIL = PERIOD_END + timedelta(days=30)


def _binding() -> ScenarioForecastBinding:
    return ScenarioForecastBinding(
        scenario_revision_id=UUID("11111111-1111-1111-1111-111111111111"),
        scenario_set_revision_id=UUID("22222222-2222-2222-2222-222222222222"),
        subjective_probability=Decimal("0.6"),
        subjective_probability_source_version="committee.v1",
        model_probability=Decimal("0.55"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="promotion-1",
    )


def _member_source() -> ForecastRealizationMemberSource:
    outcome = _outcome()
    observation_hash = forecast_observation_hash_from_values(
        observation_version="r7-forecast-observation.v1",
        observation_id="forecast-1",
        entry_id="forecast-1",
        forecast_group_id="forecast-group-1",
        binding=outcome.binding,
        pit_manifest_id=outcome.pit_manifest_id,
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash="c" * 64,
        censoring_rule_version="censoring.v1",
        published_at=outcome.published_at,
        horizon_end=outcome.horizon_end,
        scenario_realized=outcome.scenario_realized,
        outcome_recorded_at=outcome.outcome_recorded_at,
        outcome_evidence_valid_until=VALID_UNTIL,
    )
    return ForecastRealizationMemberSource.create(
        entry_id="forecast-1",
        observation_id="forecast-1",
        observation_version="r7-forecast-observation.v1",
        expected_observation_hash=observation_hash,
        forecast_group_id="forecast-group-1",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash="c" * 64,
        censoring_rule_version="censoring.v1",
        outcome_evidence_valid_until=VALID_UNTIL,
        available_at=MEMBER_AVAILABLE_AT,
        evidence_ref="forecast-outcome:forecast-1",
    )


def _source() -> ForecastRealizationManifestSource:
    return ForecastRealizationManifestSource.create(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
        result_id="result-1",
        result_version="result.v1",
        result_hash="a" * 64,
        calendar_id="calendar-1",
        calendar_version="calendar.v1",
        period_id="period-1",
        period_version="period.v1",
        period_hash="b" * 64,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        available_at=MANIFEST_AVAILABLE_AT,
        valid_until=VALID_UNTIL,
        evidence_ref="forecast-realization-manifest:1",
        members=(_member_source(),),
    )


def _outcome() -> ForecastOutcomeOwnerRecord:
    return ForecastOutcomeOwnerRecord.create(
        entry_id="forecast-1",
        binding=_binding(),
        pit_manifest_id="pit-1",
        published_at=PUBLISHED_AT,
        horizon_end=PERIOD_END,
        scenario_realized=True,
        outcome_recorded_at=OUTCOME_RECORDED_AT,
    )


def test_append_command_is_strictly_owner_identity_only() -> None:
    """Callers cannot submit outcomes, clocks, probabilities, or member payloads."""

    assert tuple(item.name for item in fields(AppendForecastRealizationManifestCommand)) == (
        "owner_record_id",
        "owner_record_version",
    )


def test_member_source_cannot_accept_a_raw_outcome() -> None:
    """The pre-append metadata contract has no realization or probability field."""

    names = {item.name for item in fields(ForecastRealizationMemberSource)}

    assert "scenario_realized" not in names
    assert "subjective_probability" not in names
    assert "model_probability" not in names


def test_manifest_is_built_only_from_exact_outcome_records() -> None:
    """Receipt identity/version/hash and all knowledge clocks are sealed."""

    manifest = ForecastRealizationManifest.from_sources(
        source=_source(),
        outcomes=(_outcome(),),
        recorded_at=RECORDED_AT,
    )

    assert manifest.pit_as_of == RECORDED_AT
    assert manifest.recorded_at == RECORDED_AT
    assert manifest.content_hash
    assert manifest.payload_hash
    assert len(manifest.members) == 1
    receipt = manifest.members[0]
    assert receipt.observation_id == "forecast-1"
    assert receipt.observation_version == "r7-forecast-observation.v1"
    assert receipt.observation_hash
    assert receipt.source_outcome_hash == _outcome().content_hash
    assert receipt.scenario_realized is True


def test_manifest_rejects_missing_or_relabelled_outcome_membership() -> None:
    """Metadata cannot turn an absent/different immutable outcome into evidence."""

    with pytest.raises(ValueError, match="membership"):
        ForecastRealizationManifest.from_sources(
            source=_source(),
            outcomes=(),
            recorded_at=RECORDED_AT,
        )

    different_outcome = ForecastOutcomeOwnerRecord.create(
        entry_id="forecast-2",
        binding=_binding(),
        pit_manifest_id="pit-1",
        published_at=PUBLISHED_AT,
        horizon_end=PERIOD_END,
        scenario_realized=True,
        outcome_recorded_at=OUTCOME_RECORDED_AT,
    )
    with pytest.raises(ValueError, match="membership"):
        ForecastRealizationManifest.from_sources(
            source=_source(),
            outcomes=(different_outcome,),
            recorded_at=RECORDED_AT,
        )


def test_manifest_rejects_a_future_server_recording_clock() -> None:
    """The server append cannot extend the source evidence validity."""

    with pytest.raises(ValueError, match="clock|expired"):
        ForecastRealizationManifest.from_sources(
            source=_source(),
            outcomes=(_outcome(),),
            recorded_at=VALID_UNTIL,
        )


def test_exact_query_command_is_hash_bound_and_pit_only() -> None:
    """The query surface cannot grow latest/current or decision semantics."""

    assert tuple(item.name for item in fields(ExactForecastRealizationManifestCommand)) == (
        "result_id",
        "result_version",
        "expected_result_hash",
        "period_id",
        "period_version",
        "expected_period_hash",
        "as_of",
    )


class _EmptyRepository:
    unit_of_work_key = "django:default"

    def get_exact(self, **selectors: object) -> None:
        assert selectors["result_id"] == "result-1"
        return None


class _CountingWriter:
    def __init__(self, value: ForecastRealizationManifest) -> None:
        self.calls = 0
        self.value = value

    def append(
        self,
        command: AppendForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest:
        self.calls += 1
        return self.value


class _CountingRepository:
    unit_of_work_key = "django:default"

    def __init__(self, value: ForecastRealizationManifest | None) -> None:
        self.calls = 0
        self.value = value

    def get_exact(self, **selectors: object) -> ForecastRealizationManifest | None:
        self.calls += 1
        return self.value


def test_exact_query_preserves_missing_receipt_as_none() -> None:
    """An empty production ledger remains unavailable rather than fabricated."""

    query = GetExactForecastRealizationManifest(_EmptyRepository())

    assert (
        query.execute(
            ExactForecastRealizationManifestCommand(
                result_id="result-1",
                result_version="result.v1",
                expected_result_hash="a" * 64,
                period_id="period-1",
                period_version="period.v1",
                expected_period_hash="b" * 64,
                as_of=datetime(2026, 8, 11, tzinfo=UTC),
            )
        )
        is None
    )


@pytest.mark.parametrize("field_name", ["expected_result_hash", "expected_period_hash"])
def test_exact_query_rejects_non_sha256_selectors(field_name: str) -> None:
    """Identity selectors cannot silently accept aliases or partial hashes."""

    values: dict[str, object] = {
        "result_id": "result-1",
        "result_version": "result.v1",
        "expected_result_hash": "a" * 64,
        "period_id": "period-1",
        "period_version": "period.v1",
        "expected_period_hash": "b" * 64,
        "as_of": datetime(2026, 8, 11, tzinfo=UTC),
    }
    values[field_name] = "not-a-hash"

    with pytest.raises(ValueError, match=field_name):
        ExactForecastRealizationManifestCommand(**values)  # type: ignore[arg-type]


def test_append_rejects_subclass_and_instance_validator_override_before_writer() -> None:
    """Nominal command objects cannot replace their own validator."""

    manifest = ForecastRealizationManifest.from_sources(
        source=_source(), outcomes=(_outcome(),), recorded_at=RECORDED_AT
    )
    writer = _CountingWriter(manifest)
    use_case = AppendForecastRealizationManifest(writer)

    class _CommandSubclass(AppendForecastRealizationManifestCommand):
        pass

    with pytest.raises(ForecastRealizationOwnerUnavailable, match="malformed"):
        use_case.execute(_CommandSubclass("manifest-1", "v1"))

    command = AppendForecastRealizationManifestCommand("manifest-1", "v1")
    object.__setattr__(command, "owner_record_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(ValueError, match="owner_record_id"):
        use_case.execute(command)
    assert writer.calls == 0


def test_query_rejects_instance_validator_override_before_repository() -> None:
    """A mutated PIT selector cannot invoke even the read repository."""

    repository = _CountingRepository(None)
    query = GetExactForecastRealizationManifest(repository)
    command = ExactForecastRealizationManifestCommand(
        result_id="result-1",
        result_version="result.v1",
        expected_result_hash="a" * 64,
        period_id="period-1",
        period_version="period.v1",
        expected_period_hash="b" * 64,
        as_of=RECORDED_AT,
    )
    object.__setattr__(command, "expected_result_hash", "forged")
    object.__setattr__(command, "__post_init__", lambda: None)

    with pytest.raises(ValueError, match="expected_result_hash"):
        query.execute(command)
    assert repository.calls == 0


def test_query_rejects_nominal_manifest_substitution() -> None:
    """Repositories must return the exact sealed Domain owner type."""

    canonical = ForecastRealizationManifest.from_sources(
        source=_source(), outcomes=(_outcome(),), recorded_at=RECORDED_AT
    )

    class _ManifestSubclass(ForecastRealizationManifest):
        def validated_copy(self) -> ForecastRealizationManifest:
            return self

    substituted = _ManifestSubclass(**canonical.__dict__)
    repository = _CountingRepository(substituted)
    query = GetExactForecastRealizationManifest(repository)

    with pytest.raises(ForecastRealizationOwnerUnavailable, match="type"):
        query.execute(
            ExactForecastRealizationManifestCommand(
                result_id="result-1",
                result_version="result.v1",
                expected_result_hash="a" * 64,
                period_id="period-1",
                period_version="period.v1",
                expected_period_hash="b" * 64,
                as_of=RECORDED_AT,
            )
        )


def test_nested_receipt_validator_override_cannot_hide_tampering() -> None:
    """Manifest replay invokes class-bound validation for every exact member."""

    manifest = ForecastRealizationManifest.from_sources(
        source=_source(), outcomes=(_outcome(),), recorded_at=RECORDED_AT
    )
    receipt = manifest.members[0]
    object.__setattr__(receipt, "scenario_realized", False)
    object.__setattr__(receipt, "__post_init__", lambda: None)

    with pytest.raises(ValueError, match="receipt content hash"):
        manifest.validated_copy()


def test_outcome_validator_override_cannot_enter_manifest_draft() -> None:
    """The draft class-bound reread rejects a mutated exact outcome source."""

    outcome = _outcome()
    object.__setattr__(outcome, "content_hash", "d" * 64)
    object.__setattr__(outcome, "__post_init__", lambda: None)

    with pytest.raises(ValueError, match="outcome source content hash"):
        ForecastRealizationManifest.from_sources(
            source=_source(), outcomes=(outcome,), recorded_at=RECORDED_AT
        )
