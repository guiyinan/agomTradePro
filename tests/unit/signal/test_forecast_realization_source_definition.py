"""Domain/Application contracts for the Signal realization source registry."""

from dataclasses import fields

import pytest

from apps.signal.application.forecast_realization_source_definition import (
    ExactForecastRealizationSourceDefinitionCommand,
    ForecastRealizationSourceDefinitionUnavailable,
    GetExactForecastRealizationSourceDefinition,
    RegisterForecastRealizationSourceDefinition,
    RegisterForecastRealizationSourceDefinitionCommand,
)
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
)
from apps.signal.infrastructure.forecast_realization_source_definition_codec import (
    ForecastRealizationSourceDefinitionCodecError,
    decode_forecast_realization_source_definition,
    encode_forecast_realization_source_definition,
)
from tests.unit.signal.test_forecast_realization_owner import RECORDED_AT, _source


def _definition() -> ForecastRealizationSourceDefinition:
    return ForecastRealizationSourceDefinition.create(
        source=_source(),
        registered_at=RECORDED_AT,
    )


def test_definition_seals_complete_source_and_research_safety() -> None:
    """One definition binds every result/period/member field through its source hash."""

    definition = _definition()

    assert definition.source.owner_record_id == "realization-manifest-1"
    assert definition.source.result_hash == "a" * 64
    assert definition.source.period_hash == "b" * 64
    assert definition.source.members[0].entry_id == "forecast-1"
    assert definition.source.members[0].expected_observation_hash
    assert definition.registered_at == RECORDED_AT
    assert definition.content_hash
    assert definition.research_only is True
    assert definition.must_not_use_for_decision is True
    assert definition.must_not_execute is True


def test_definition_commands_are_strictly_id_only_and_hash_bound_pit() -> None:
    """Registration cannot accept a finished definition or caller clocks."""

    assert tuple(
        item.name for item in fields(RegisterForecastRealizationSourceDefinitionCommand)
    ) == ("owner_record_id", "owner_record_version")
    assert tuple(item.name for item in fields(ExactForecastRealizationSourceDefinitionCommand)) == (
        "owner_record_id",
        "owner_record_version",
        "expected_content_hash",
        "as_of",
    )


class _EmptyRepository:
    unit_of_work_key = "django:default"

    def get_exact(self, **selectors: object) -> None:
        assert selectors["owner_record_id"] == "realization-manifest-1"
        return None


def test_exact_definition_query_preserves_empty_registry_as_none() -> None:
    """No definition means no source for the downstream realization writer."""

    query = GetExactForecastRealizationSourceDefinition(_EmptyRepository())

    assert (
        query.execute(
            ExactForecastRealizationSourceDefinitionCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
                expected_content_hash="a" * 64,
                as_of=RECORDED_AT,
            )
        )
        is None
    )


def test_definition_strict_codec_round_trips_and_rejects_shape_drift() -> None:
    """Canonical payload decoding accepts neither missing nor surplus fields."""

    definition = _definition()
    payload = encode_forecast_realization_source_definition(definition)

    assert decode_forecast_realization_source_definition(payload) == definition

    surplus = dict(payload)
    surplus["probability"] = "0.9"
    with pytest.raises(ForecastRealizationSourceDefinitionCodecError, match="keys"):
        decode_forecast_realization_source_definition(surplus)

    missing = dict(payload)
    del missing["content_hash"]
    with pytest.raises(ForecastRealizationSourceDefinitionCodecError, match="keys"):
        decode_forecast_realization_source_definition(missing)

    nested = dict(payload)
    nested_source = dict(nested["source"])
    nested_source["current"] = True
    nested["source"] = nested_source
    with pytest.raises(ForecastRealizationSourceDefinitionCodecError, match="keys"):
        decode_forecast_realization_source_definition(nested)


class _CountingWriter:
    def __init__(self) -> None:
        self.calls = 0

    def register(
        self,
        command: RegisterForecastRealizationSourceDefinitionCommand,
    ) -> ForecastRealizationSourceDefinition:
        self.calls += 1
        return _definition()


class _RegisterSubclass(RegisterForecastRealizationSourceDefinitionCommand):
    pass


def test_registration_rejects_subclasses_and_mutated_commands_before_writer() -> None:
    """Caller validator bypasses cannot reach the canonical provider or storage."""

    writer = _CountingWriter()
    use_case = RegisterForecastRealizationSourceDefinition(writer)
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="malformed"):
        use_case.execute(
            _RegisterSubclass(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )

    command = RegisterForecastRealizationSourceDefinitionCommand(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
    )
    object.__setattr__(command, "owner_record_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="malformed"):
        use_case.execute(command)
    assert writer.calls == 0


def test_definition_recursively_revalidates_mutated_nested_members() -> None:
    """A frozen-instance mutation cannot bypass the class-bound nested validators."""

    definition = _definition()
    member = definition.source.members[0]
    object.__setattr__(member, "entry_id", "forged")
    object.__setattr__(member, "__post_init__", lambda: None)

    with pytest.raises(ValueError, match="aliased|hash"):
        definition.validated_copy()
