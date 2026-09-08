"""Validate passive dashboard selector contracts at the metadata boundary."""

from typing import Any

from apps.terminal.application.tui_metadata_constants import STRICT_TUI_DASHBOARD_PANEL_ACTION_KINDS


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
