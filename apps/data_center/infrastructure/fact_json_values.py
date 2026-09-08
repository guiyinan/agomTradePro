"""Normalize numeric and boolean values from persisted fact JSON."""

from shared.numeric import safe_float


def _optional_json_float(value: object, field_name: str) -> float | None:
    """Parse a nullable finite number from persisted JSON."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    parsed = safe_float(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a finite number")
    return parsed


def _required_json_float(value: object, field_name: str) -> float:
    """Parse a required finite number from persisted JSON."""

    parsed = _optional_json_float(value, field_name)
    if parsed is None:
        raise ValueError(f"{field_name} is required")
    return parsed


def _json_bool(value: object, field_name: str) -> bool:
    """Require real booleans instead of truthy strings from persisted JSON."""

    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _optional_json_nonnegative_int(value: object, field_name: str) -> int | None:
    """Parse a nullable non-negative integer from persisted JSON."""

    if value is None:
        return None
    parsed = _optional_json_float(value, field_name)
    if parsed is None or not parsed.is_integer() or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return int(parsed)
