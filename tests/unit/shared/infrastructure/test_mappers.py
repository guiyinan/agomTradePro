"""Coverage and behavior tests for the shared entity mapper primitives."""

from decimal import Decimal

import pytest

from shared.infrastructure.mappers import (
    DataclassMapper,
    get_mapper,
    register_mapper,
)


class _ExampleEntity:
    """Marker entity used to exercise the mapper registry."""


class _ExampleMapper(DataclassMapper[str, int]):
    """Small concrete mapper for testing the generic base implementation."""

    def to_entity(self, model: int) -> str:
        """Convert an integer model to its string entity representation."""
        return str(model)

    def to_model(self, entity: str, model: int | None = None) -> int:
        """Convert a string entity to an integer model representation."""
        del model
        return int(entity)


def test_mapper_batches_and_registry_round_trip() -> None:
    """Concrete mappers support batch conversion and registry lookup."""
    mapper = _ExampleMapper()

    assert mapper.batch_to_entities([1, 2]) == ["1", "2"]
    assert mapper.batch_to_models(["3", "4"]) == [3, 4]

    register_mapper(_ExampleEntity, _ExampleMapper)
    assert get_mapper(_ExampleEntity) is _ExampleMapper
    assert get_mapper(str) is None


@pytest.mark.parametrize(
    ("value", "target_type", "expected"),
    [
        (None, str, None),
        ("ready", str, "ready"),
        ([1], list[int], [1]),
        (2, float, 2.0),
        ("2.5", float, 2.5),
        (Decimal("3.5"), float, 3.5),
        ("4", int, 4),
        (4.9, int, 4),
        (5, str, "5"),
        (6, Decimal, Decimal("6")),
        (6.5, Decimal, Decimal("6.5")),
        ("7.5", Decimal, Decimal("7.5")),
    ],
)
def test_convert_value_handles_supported_boundary_types(
    value: object,
    target_type: object,
    expected: object,
) -> None:
    """Supported boundary values are normalized without changing other values."""
    mapper = _ExampleMapper()
    result = mapper._convert_value(value, target_type)

    assert result == expected


def test_convert_value_preserves_unsupported_values() -> None:
    """Values outside the supported coercion matrix pass through unchanged."""
    value = object()

    assert _ExampleMapper()._convert_value(value, int) is value


@pytest.mark.parametrize(
    ("value", "target_type", "message"),
    [
        ("inf", float, "converted float must be finite"),
        (float("inf"), int, "converted integer source must be finite"),
        ("NaN", Decimal, "converted decimal must be finite"),
    ],
)
def test_convert_value_rejects_non_finite_numbers(
    value: object,
    target_type: object,
    message: str,
) -> None:
    """Non-finite values never cross the mapper boundary silently."""
    with pytest.raises(ValueError, match=message):
        _ExampleMapper()._convert_value(value, target_type)
