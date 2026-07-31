"""Validated query-parameter parsers for data-center endpoints."""

from __future__ import annotations

from math import isfinite

def _parse_bool_param(
    raw_value: str | None,
    *,
    field_name: str,
    default: bool = False,
) -> bool:
    if raw_value is None or raw_value == "":
        return default

    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field_name} 必须是布尔值")


def _parse_positive_float_param(
    raw_value: str | None,
    *,
    field_name: str,
    default: float,
) -> float:
    if raw_value is None or raw_value == "":
        return default

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc

    if not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} 必须是大于 0 的有限数字")
    return value


def _parse_positive_int_param(
    raw_value: str | None,
    *,
    field_name: str,
    default: int,
) -> int:
    if raw_value is None or raw_value == "":
        return default

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc

    if value <= 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return value


