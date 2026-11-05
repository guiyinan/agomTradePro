"""Dashboard row-action binding validation for published TUI metadata."""

from __future__ import annotations

from string import Formatter
from typing import Any

from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError
from apps.terminal.application.tui_metadata_shape_validation import _require_fields


def validate_dashboard_row_actions(
    *,
    screen: dict[str, Any],
    panel: dict[str, Any],
    action_by_key: dict[str, dict[str, Any]],
) -> None:
    """Validate row-to-action bindings before metadata reaches the browser."""

    row_actions = panel.setdefault("row_actions", [])
    screen_key = str(screen["key"])
    panel_key = str(panel["key"])
    if not isinstance(row_actions, list):
        raise TuiMetadataValidationError(
            f"Dashboard panel row_actions must be a list: {screen_key}.{panel_key}"
        )
    column_keys = {
        str(column.get("key") or "")
        for column in panel.get("columns", [])
        if isinstance(column, dict)
    }
    hidden_columns = panel.get("hidden_columns", [])
    if (
        not isinstance(hidden_columns, list)
        or any(not isinstance(key, str) or not key.strip() for key in hidden_columns)
        or len(hidden_columns) != len(set(hidden_columns))
        or column_keys.intersection(hidden_columns)
    ):
        raise TuiMetadataValidationError(
            f"Dashboard panel hidden_columns must be unique and separate from visible columns: "
            f"{screen_key}.{panel_key}"
        )
    row_field_keys = column_keys.union(hidden_columns)
    mapped_hidden_columns: set[str] = set()
    for descriptor in row_actions:
        if not isinstance(descriptor, dict):
            raise TuiMetadataValidationError(
                f"Dashboard row action must be an object: {screen_key}.{panel_key}"
            )
        _require_fields(
            descriptor,
            "dashboard row action",
            ("action_key", "label_template", "param_map"),
        )
        unknown_keys = set(descriptor) - {
            "action_key",
            "label_template",
            "param_map",
            "result_panel_key",
            "refresh_panel_key",
            "visible_when",
        }
        if unknown_keys:
            names = ", ".join(sorted(unknown_keys))
            raise TuiMetadataValidationError(
                f"Dashboard row action has unsupported keys: {screen_key}.{panel_key}.{names}"
            )
        action_key = str(descriptor["action_key"])
        condition = descriptor.get("visible_when")
        if condition is not None and (
            not isinstance(condition, dict)
            or set(condition) - {"field", "values", "negate"}
            or condition.get("field") not in column_keys
            or not isinstance(condition.get("values"), list)
            or not condition["values"]
            or any(not isinstance(value, str | int | float | bool) for value in condition["values"])
            or not isinstance(condition.get("negate", False), bool)
        ):
            raise TuiMetadataValidationError(
                f"Dashboard row action has invalid visible_when: {screen_key}.{panel_key}"
            )
        action = action_by_key.get(action_key)
        if action is None:
            raise TuiMetadataValidationError(
                f"Dashboard panel references unknown row action: {screen_key}.{panel_key}.{action_key}"
            )
        if str(action.get("screen_key") or "") != screen_key:
            raise TuiMetadataValidationError(
                f"Dashboard row action belongs to another screen: "
                f"{screen_key}.{panel_key}.{action_key}"
            )
        screen_panel_keys = {
            str(item.get("key") or "")
            for item in screen.get("dashboard_panels", [])
            if isinstance(item, dict)
        }
        for target_key in ("result_panel_key", "refresh_panel_key"):
            target_panel_key = str(descriptor.get(target_key) or "").strip()
            if target_panel_key and target_panel_key not in screen_panel_keys:
                raise TuiMetadataValidationError(
                    f"Dashboard row action references unknown {target_key}: "
                    f"{screen_key}.{panel_key}.{action_key}.{target_panel_key}"
                )
        param_map = descriptor["param_map"]
        if not isinstance(param_map, dict):
            raise TuiMetadataValidationError(
                f"Dashboard row action param_map must be an object: {screen_key}.{panel_key}"
            )
        action_fields = {
            str(field.get("key") or ""): field
            for field in action.get("fields", [])
            if isinstance(field, dict)
        }
        unknown_params = set(param_map) - set(action_fields)
        if unknown_params:
            names = ", ".join(sorted(unknown_params))
            raise TuiMetadataValidationError(
                f"Dashboard row action maps unknown parameter: {action_key}.{names}"
            )
        for param_key, row_field in param_map.items():
            if not isinstance(row_field, str) or row_field not in row_field_keys:
                raise TuiMetadataValidationError(
                    f"Dashboard row action references unknown row field: "
                    f"{action_key}.{param_key}.{row_field}"
                )
            if row_field in hidden_columns:
                mapped_hidden_columns.add(row_field)
        missing_required = [
            key
            for key, field in action_fields.items()
            if field.get("required")
            and str(field.get("binding") or "body") != "body"
            and key not in param_map
            and not ("default" in field and field.get("default") not in (None, ""))
        ]
        if missing_required:
            names = ", ".join(sorted(missing_required))
            raise TuiMetadataValidationError(
                f"Dashboard row action is missing required parameter mapping: "
                f"{action_key}.{names}"
            )
        label_template = str(descriptor["label_template"])
        template_fields = {
            field_name for _, field_name, _, _ in Formatter().parse(label_template) if field_name
        }
        unknown_template_fields = template_fields - column_keys
        if unknown_template_fields:
            names = ", ".join(sorted(unknown_template_fields))
            raise TuiMetadataValidationError(
                f"Dashboard row action label references unknown row field: " f"{action_key}.{names}"
            )

    if set(hidden_columns) - mapped_hidden_columns:
        raise TuiMetadataValidationError(
            f"Dashboard panel hidden_columns must only supply row-action parameters: "
            f"{screen_key}.{panel_key}"
        )
