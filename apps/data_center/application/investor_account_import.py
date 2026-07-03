"""Investor-account import helpers."""

from __future__ import annotations

from typing import Any

from apps.data_center.domain.entities import MacroFact

INVESTOR_ACCOUNT_IMPORT_UNITS = {"户", "万户"}
INVESTOR_ACCOUNT_SUSPICIOUS_MAX_VALUE = 1000.0


def normalize_investor_account_import_value(value: float, *, value_unit: str) -> float:
    """Return canonical account count in 户."""

    if value_unit == "万户":
        return value * 10_000
    return value


def build_investor_account_import_warnings(
    facts: list[MacroFact],
) -> list[dict[str, Any]]:
    """Return operator-facing warnings for suspicious imported account counts."""

    values = [abs(float(fact.value)) for fact in facts]
    if not values:
        return []
    max_value = max(values)
    if 0 < max_value < INVESTOR_ACCOUNT_SUSPICIOUS_MAX_VALUE:
        return [
            {
                "code": "suspicious_low_account_count",
                "message": (
                    "Investor-account values look lower than canonical 户 counts; "
                    "confirm the CSV is not using 万户 units."
                ),
                "max_value": max_value,
                "expected_unit": "户",
            }
        ]
    return []
