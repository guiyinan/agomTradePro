"""Validate passive dashboard selector contracts at the metadata boundary."""

from collections.abc import Callable
from typing import Any

from apps.terminal.application.tui_metadata_constants import (
    ALLOWED_TUI_DASHBOARD_FIELD_FORMATS,
    STRICT_TUI_DASHBOARD_PANEL_ACTION_KINDS,
)


class TuiMetadataValidationError(ValueError):
    """Raised when TUI metadata cannot be safely published."""


def validate_dashboard_filter_fields(panel: dict[str, Any], action: dict[str, Any]) -> None:
    """Validate explicitly opted-in passive list selectors against action fields."""

    fields = panel.get("filter_fields", [])
    if not isinstance(fields, list) or not all(isinstance(key, str) for key in fields):
        raise TuiMetadataValidationError("Dashboard filter_fields must be a string list")
    if not fields:
        return
    available = {
        field["key"]
        for field in action.get("fields", [])
        if field.get("presentation_semantic") == "primary_selector"
        and field.get("input_type") not in {"hidden", "password", "file"}
    }
    if (
        len(fields) != len(set(fields))
        or not set(fields) <= available
        or panel.get("presentation_semantic") != "primary_list"
        or action.get("risk") != "read"
        or action.get("method") != "GET"
        or action.get("confirmation_required")
    ):
        raise TuiMetadataValidationError(
            "Dashboard filters require unique selectors on a passive primary list"
        )


def validate_dashboard_field_rules(
    *,
    panel: dict[str, Any],
    screen_key: str,
    panel_key: str,
    require_fields: Callable[[dict[str, Any], str, tuple[str, ...]], None],
) -> None:
    """Validate dashboard field display rules, including explicit percentage units."""

    field_rules = panel.get("field_rules", [])
    if not isinstance(field_rules, list):
        raise TuiMetadataValidationError(
            f"Dashboard panel field_rules must be a list: {screen_key}.{panel_key}"
        )
    for rule in field_rules:
        if not isinstance(rule, dict):
            raise TuiMetadataValidationError(
                f"Dashboard panel field rule must be an object: {screen_key}.{panel_key}"
            )
        require_fields(rule, "dashboard panel field rule", ("label",))
        unknown_rule_keys = set(rule) - {"label", "visible", "format", "percentage_unit"}
        if unknown_rule_keys:
            names = ", ".join(sorted(unknown_rule_keys))
            raise TuiMetadataValidationError(
                f"Dashboard panel field rule has unsupported keys: "
                f"{screen_key}.{panel_key}.{names}"
            )
        if "visible" in rule and not isinstance(rule["visible"], bool):
            raise TuiMetadataValidationError(
                f"Dashboard panel field rule visible must be boolean: " f"{screen_key}.{panel_key}"
            )
        field_format = str(rule.get("format") or "text")
        if field_format not in ALLOWED_TUI_DASHBOARD_FIELD_FORMATS:
            raise TuiMetadataValidationError(
                f"Dashboard panel field rule has unsupported format: "
                f"{screen_key}.{panel_key}.{field_format}"
            )
        if "percentage_unit" in rule:
            percentage_unit = rule["percentage_unit"]
            if not isinstance(percentage_unit, str) or percentage_unit not in {
                "percent",
                "fraction",
            }:
                raise TuiMetadataValidationError(
                    f"Dashboard panel field rule has unsupported percentage unit: "
                    f"{screen_key}.{panel_key}"
                )
            if field_format != "percentage":
                raise TuiMetadataValidationError(
                    f"Dashboard panel field rule percentage_unit requires "
                    f"percentage format: {screen_key}.{panel_key}"
                )


def validate_dashboard_panel_action_kind(
    *,
    screen: dict[str, Any],
    panel: dict[str, Any],
    action: dict[str, Any],
) -> None:
    """Reject strict dashboard renderers wired to incompatible action results."""

    panel_kind = str(panel.get("kind") or "").strip()
    expected_kinds = STRICT_TUI_DASHBOARD_PANEL_ACTION_KINDS.get(panel_kind)
    if expected_kinds is None:
        return
    view_model = action.get("view_model")
    configured_kind = (
        str(view_model.get("kind") or "").strip() if isinstance(view_model, dict) else ""
    )
    action_kind = configured_kind or str(action.get("view_type") or "").strip()
    if action_kind in expected_kinds:
        return
    raise TuiMetadataValidationError(
        "Dashboard panel/action kind mismatch: "
        f"{screen['key']}.{panel['key']} panel={panel_kind} action={action_kind or 'unset'}"
    )
