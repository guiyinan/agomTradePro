import pytest

from apps.policy.infrastructure.interface_repositories import (
    _parse_optional_bool,
    _parse_optional_id,
)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("0", False),
        ("false", False),
        ("", None),
        (None, None),
    ],
)
def test_optional_bool_query_values_are_parsed_explicitly(
    raw_value: str | None,
    expected: bool | None,
) -> None:
    assert _parse_optional_bool(raw_value, field_name="is_active") is expected


@pytest.mark.parametrize("raw_value", ["yes", "no", "enabled", "2"])
def test_optional_bool_rejects_ambiguous_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="is_active"):
        _parse_optional_bool(raw_value, field_name="is_active")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("", None), ("1", 1), ("007", 7)],
)
def test_optional_database_id_requires_positive_integer(
    raw_value: str,
    expected: int | None,
) -> None:
    assert _parse_optional_id(raw_value, field_name="source_id") == expected


@pytest.mark.parametrize("raw_value", ["0", "-1", "bad", "1.5"])
def test_optional_database_id_rejects_invalid_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="source_id"):
        _parse_optional_id(raw_value, field_name="source_id")
