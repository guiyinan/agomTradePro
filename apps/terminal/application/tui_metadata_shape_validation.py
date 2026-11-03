"""Common shape checks for the published TUI metadata JSON boundary."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError


def _require_fields(item: dict[str, Any], label: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field not in item or item[field] in (None, ""):
            raise TuiMetadataValidationError(f"{label} missing required field: {field}")


def _unique_keys(items: list[dict[str, Any]], label: str) -> set[str]:
    keys: set[str] = set()
    for item in items:
        key = str(item.get("key") or "")
        if not key:
            raise TuiMetadataValidationError(f"{label} entry missing key")
        if key in keys:
            raise TuiMetadataValidationError(f"Duplicate {label} key: {key}")
        keys.add(key)
    return keys
