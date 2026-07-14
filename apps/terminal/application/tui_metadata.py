"""Validation helpers for published TUI operation metadata."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except ImportError:  # pragma: no cover - local validator still protects runtime.
    Draft202012Validator = None  # type: ignore[assignment]
    JsonSchemaValidationError = Exception  # type: ignore[assignment]

TUI_METADATA_SCHEMA_VERSION = "tui-metadata.v3"
TUI_METADATA_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "tui"
    / "schema"
    / "tui_metadata.schema.v3.json"
)
ALLOWED_TUI_RISKS = {"read", "ai", "write", "unsafe", "admin"}
ALLOWED_TUI_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_TUI_VIEW_TYPES = {
    "auto",
    "status",
    "detail",
    "datagrid",
    "message",
    "queue_workbench",
    "chart",
    "image",
    "kpi_trend",
    "table_chart",
    "host_slot",
    "custom",
}
ALLOWED_TUI_VIEW_MODEL_KINDS = {
    "auto",
    "datagrid",
    "detail",
    "message",
    "chart",
    "image",
    "kpi_trend",
    "table_chart",
    "host_slot",
    "custom",
}
ALLOWED_TUI_SENSITIVE_LEVELS = {"none", "low", "medium", "high", "critical"}
ALLOWED_TUI_FIELD_INPUT_TYPES = {
    "checkbox",
    "date",
    "file",
    "hidden",
    "number",
    "select",
    "text",
    "textarea",
}
ALLOWED_TUI_FIELD_VALUE_TYPES = {
    "boolean",
    "date",
    "datetime",
    "decimal",
    "float",
    "integer",
    "list",
    "object",
    "string",
}
ALLOWED_TUI_FIELD_BINDINGS = {"body", "path", "query"}
ALLOWED_TUI_FIELD_KEYS = {
    "accept",
    "aliases",
    "binding",
    "default",
    "input_type",
    "key",
    "label",
    "max",
    "min",
    "options",
    "placeholder",
    "presentation_semantic",
    "required",
    "semantic",
    "unit",
    "value_type",
}
ALLOWED_TUI_PAGINATION_MODES = {"page", "offset", "cursor"}
ALLOWED_TUI_PAGINATION_KEYS = {
    "mode",
    "page_param",
    "page_size_param",
    "offset_param",
    "limit_param",
    "cursor_param",
    "next_cursor_path",
    "previous_cursor_path",
}
ALLOWED_TUI_VIEW_MODEL_KEYS = {
    "kind",
    "rows_path",
    "total_path",
    "page_path",
    "page_size_path",
    "title_path",
    "status_path",
    "field_presentations",
}
ALLOWED_TUI_RESULT_FIELD_PRESENTATIONS = {"secret", "copyable", "multiline", "metadata"}
ALLOWED_TUI_DASHBOARD_PANEL_KINDS = {
    "datagrid",
    "detail",
    "placeholder",
    "regime_quadrant",
    "status",
    "chart",
    "image",
    "kpi_trend",
    "table_chart",
    "host_slot",
    "custom",
}
ALLOWED_TUI_SCREEN_JOURNEYS = {
    "dashboard",
    "workspace",
    "self_service",
    "admin",
    "toolbox",
    "debug",
}
ALLOWED_TUI_SCREEN_AUDIENCES = {"authenticated", "admin"}
ALLOWED_TUI_PANEL_USER_PRIORITIES = {"p0", "p1", "p2"}
ALLOWED_TUI_PRESENTATION_SEMANTICS = {
    "primary_status",
    "primary_list",
    "supporting_list",
    "copyable_secret",
    "endpoint_list",
    "multiline_prompt",
    "next_step",
    "supporting_detail",
    "debug_only",
}
ALLOWED_TUI_FIELD_PRESENTATION_SEMANTICS = {
    "identifier",
    "primary_selector",
    "api_token",
    "endpoint_url",
    "prompt_text",
    "debug_only",
}
ALLOWED_TUI_DASHBOARD_PANEL_KEYS = {
    "key",
    "title",
    "kind",
    "action_key",
    "status",
    "note",
    "max_rows",
    "user_priority",
    "presentation_semantic",
    "columns",
    "layout_area",
    "target_screen",
}
ALLOWED_TUI_SOURCE_PREFIXES = (
    "approved:",
    "api-collector:",
    "classic-template:",
    "django-model:",
    "ddd-aggregate:",
    "openapi:",
    "published",
)
HIGH_REVIEW_FIELD_TOKENS = (
    "amount",
    "cash",
    "count",
    "fee",
    "market_value",
    "max_age",
    "portfolio_ids",
    "price",
    "quantity",
    "quote",
    "shares",
    "top_n",
    "value",
    "weight",
)
GOVERNED_TUI_RISKS = {"write", "admin"}


class TuiMetadataValidationError(ValueError):
    """Raised when TUI metadata cannot be safely published."""


def validate_tui_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a TUI metadata payload.

    This function is intentionally framework-free so it can be reused by the
    compile-time skill scripts and by runtime repositories before publishing.
    """

    if not isinstance(payload, dict):
        raise TuiMetadataValidationError("TUI metadata payload must be an object")

    payload.setdefault("schema_version", TUI_METADATA_SCHEMA_VERSION)
    if payload["schema_version"] != TUI_METADATA_SCHEMA_VERSION:
        raise TuiMetadataValidationError(
            f"Unsupported TUI metadata schema_version: {payload['schema_version']}"
        )

    for key in ("version", "default_screen", "groups", "modules", "screens", "actions"):
        if key not in payload:
            raise TuiMetadataValidationError(f"Missing required key: {key}")

    groups = _require_list(payload, "groups")
    modules = _require_list(payload, "modules")
    screens = _require_list(payload, "screens")
    actions = _require_list(payload, "actions")

    group_keys = _unique_keys(groups, "groups")
    module_keys = _unique_keys(modules, "modules")
    screen_keys = _unique_keys(screens, "screens")
    action_keys = _unique_keys(actions, "actions")

    default_screen = str(payload["default_screen"])
    if default_screen not in screen_keys:
        raise TuiMetadataValidationError(f"default_screen does not exist: {default_screen}")
    _validate_field_alias_registry(payload.get("field_aliases"))

    for module in modules:
        _require_fields(module, "module", ("key", "label", "group", "summary"))
        if str(module["group"]) not in group_keys:
            raise TuiMetadataValidationError(f"Module references unknown group: {module['key']}")
        module.setdefault("status", "online")

    for screen in screens:
        _require_fields(
            screen, "screen", ("key", "label", "module_key", "group", "summary", "view_type")
        )
        if str(screen["module_key"]) not in module_keys:
            raise TuiMetadataValidationError(f"Screen references unknown module: {screen['key']}")
        if str(screen["group"]) not in group_keys:
            raise TuiMetadataValidationError(f"Screen references unknown group: {screen['key']}")
        if str(screen["view_type"]) not in ALLOWED_TUI_VIEW_TYPES:
            raise TuiMetadataValidationError(f"Screen has unsupported view_type: {screen['key']}")
        screen.setdefault("status", "online")
        screen.setdefault("audience", "authenticated")
        if str(screen["audience"]) not in ALLOWED_TUI_SCREEN_AUDIENCES:
            raise TuiMetadataValidationError(
                f"Screen has unsupported audience: {screen['key']}.{screen['audience']}"
            )
        screen.setdefault("default_action_key", "")
        dashboard_panels = screen.setdefault("dashboard_panels", [])
        if not isinstance(dashboard_panels, list):
            raise TuiMetadataValidationError(
                f"Screen dashboard_panels must be a list: {screen['key']}"
            )
        screen["user_experience"] = _default_screen_user_experience(screen)
        _validate_screen_user_experience(screen)

    screen_module_by_key = {str(screen["key"]): str(screen["module_key"]) for screen in screens}

    for action in actions:
        action.setdefault("method", "GET")
        action.setdefault("risk", "read")
        if "module_key" not in action and action.get("screen_key") in screen_module_by_key:
            action["module_key"] = screen_module_by_key[str(action["screen_key"])]
        _require_fields(
            action,
            "action",
            ("key", "label", "endpoint", "intent", "screen_key", "module_key", "view_type"),
        )
        action["method"] = str(action["method"]).upper()
        if action["key"] not in action_keys:
            raise TuiMetadataValidationError(f"Internal action key mismatch: {action['key']}")
        if action["method"] not in ALLOWED_TUI_METHODS:
            raise TuiMetadataValidationError(f"Action has unsupported method: {action['key']}")
        endpoint = str(action["endpoint"])
        if not endpoint.startswith("/api/"):
            raise TuiMetadataValidationError(
                f"Action endpoint must stay under /api/: {action['key']}"
            )
        if str(action["screen_key"]) not in screen_keys:
            raise TuiMetadataValidationError(f"Action references unknown screen: {action['key']}")
        if str(action["module_key"]) not in module_keys:
            raise TuiMetadataValidationError(f"Action references unknown module: {action['key']}")
        if str(action["risk"]) not in ALLOWED_TUI_RISKS:
            raise TuiMetadataValidationError(f"Action has unsupported risk: {action['key']}")
        if str(action["view_type"]) not in ALLOWED_TUI_VIEW_TYPES:
            raise TuiMetadataValidationError(f"Action has unsupported view_type: {action['key']}")
        fields = action.setdefault("fields", [])
        if not isinstance(fields, list):
            raise TuiMetadataValidationError(f"Action fields must be a list: {action['key']}")
        for field in fields:
            _require_fields(field, "field", ("key", "label"))
            unknown_field_keys = set(field) - ALLOWED_TUI_FIELD_KEYS
            if unknown_field_keys:
                names = ", ".join(sorted(unknown_field_keys))
                raise TuiMetadataValidationError(
                    f"Action field has unsupported keys: {action['key']}.{field['key']}.{names}"
                )
            field.setdefault("input_type", "text")
            field.setdefault("required", False)
            field.setdefault("default", "")
            field.setdefault("placeholder", "")
            _validate_field(action, field)
        view_model = action.setdefault("view_model", {})
        if not isinstance(view_model, dict):
            raise TuiMetadataValidationError(
                f"Action view_model must be an object: {action['key']}"
            )
        for key, value in view_model.items():
            if key not in ALLOWED_TUI_VIEW_MODEL_KEYS:
                raise TuiMetadataValidationError(
                    f"Action view_model has unsupported key: {action['key']}.{key}"
                )
            if key == "field_presentations":
                if not isinstance(value, dict):
                    raise TuiMetadataValidationError(
                        f"Action result field presentations must be an object: {action['key']}"
                    )
                for field_key, presentation in value.items():
                    if not isinstance(field_key, str) or not field_key.strip():
                        raise TuiMetadataValidationError(
                            f"Action result field presentation key must be non-empty: {action['key']}"
                        )
                    if presentation not in ALLOWED_TUI_RESULT_FIELD_PRESENTATIONS:
                        raise TuiMetadataValidationError(
                            f"Action has unsupported result field presentation: "
                            f"{action['key']}.{field_key}.{presentation}"
                        )
                continue
            if not isinstance(value, str):
                raise TuiMetadataValidationError(
                    f"Action view_model path must be a string: {action['key']}.{key}"
                )
            if key == "kind" and value not in ALLOWED_TUI_VIEW_MODEL_KINDS:
                raise TuiMetadataValidationError(
                    f"Action view_model has unsupported kind: {action['key']}.{value}"
                )
        action.setdefault("description", "")
        action.setdefault("source", "published")
        action.setdefault("raw_debug", True)
        action.setdefault("confirmation_required", _default_confirmation_required(action))
        action.setdefault("requires_password", False)
        action.setdefault("audit_required", _default_audit_required(action))
        action.setdefault("sensitive_level", _default_sensitive_level(action))
        action.setdefault("executor", "")
        action.setdefault("task_group", "")
        action.setdefault("task_tier", "")
        action.setdefault("sequence", 999)
        action["result_semantics"] = _normalize_result_semantics(action)
        if "pagination" in action:
            _validate_action_pagination(action)
        _validate_governance_contract(action)
        _validate_action_source(action)
        _validate_confirmed_operation_contract(action)
        _validate_result_semantics(action)

    for screen in screens:
        default_action_key = str(screen.get("default_action_key") or "").strip()
        if default_action_key and default_action_key not in action_keys:
            raise TuiMetadataValidationError(
                f"Screen references unknown default action: {screen['key']}"
            )
        for panel in screen.get("dashboard_panels", []):
            if not isinstance(panel, dict):
                raise TuiMetadataValidationError(
                    f"Dashboard panel must be an object: {screen['key']}"
                )
            _require_fields(panel, "dashboard panel", ("key", "title", "kind"))
            unknown_keys = set(panel) - ALLOWED_TUI_DASHBOARD_PANEL_KEYS
            if unknown_keys:
                names = ", ".join(sorted(unknown_keys))
                raise TuiMetadataValidationError(
                    f"Dashboard panel has unsupported keys: {screen['key']}.{names}"
                )
            if str(panel["kind"]) not in ALLOWED_TUI_DASHBOARD_PANEL_KINDS:
                raise TuiMetadataValidationError(
                    f"Dashboard panel has unsupported kind: {screen['key']}.{panel['key']}"
                )
            action_key = str(panel.get("action_key") or "").strip()
            if action_key and action_key not in action_keys:
                raise TuiMetadataValidationError(
                    f"Dashboard panel references unknown action: {screen['key']}.{panel['key']}"
                )
            target_screen = str(panel.get("target_screen") or "").strip()
            if target_screen and target_screen not in screen_keys:
                raise TuiMetadataValidationError(
                    f"Dashboard panel references unknown target screen: "
                    f"{screen['key']}.{panel['key']}"
                )
            columns = panel.setdefault("columns", [])
            if not isinstance(columns, list):
                raise TuiMetadataValidationError(
                    f"Dashboard panel columns must be a list: {screen['key']}.{panel['key']}"
                )
            panel.setdefault("target_screen", "")
            for column in columns:
                if not isinstance(column, dict):
                    raise TuiMetadataValidationError(
                        f"Dashboard panel column must be an object: {screen['key']}.{panel['key']}"
                    )
                _require_fields(column, "dashboard panel column", ("key", "label"))
            try:
                panel["max_rows"] = int(panel.get("max_rows", 8))
            except (TypeError, ValueError) as exc:
                raise TuiMetadataValidationError(
                    f"Dashboard panel max_rows must be an integer: {screen['key']}.{panel['key']}"
                ) from exc
            panel.setdefault("action_key", "")
            panel.setdefault(
                "user_priority",
                "p0" if not any(
                    isinstance(existing, dict) and existing.get("user_priority") == "p0"
                    for existing in screen.get("dashboard_panels", [])
                ) else "p2",
            )
            panel.setdefault(
                "presentation_semantic",
                _default_panel_presentation_semantic(panel),
            )
            _validate_dashboard_panel(screen, panel)
        if screen.get("dashboard_panels") and not any(
            isinstance(panel, dict) and panel.get("user_priority") == "p0"
            for panel in screen.get("dashboard_panels", [])
        ):
            raise TuiMetadataValidationError(
                f"Dashboard screen must expose a p0 panel: {screen['key']}"
            )
            panel.setdefault("status", "")
            panel.setdefault("note", "")
            panel.setdefault("layout_area", "")

    payload.setdefault("registry_key", "default")
    payload.setdefault("interaction_model", "published-metadata-to-pc-tools")
    payload.setdefault(
        "principles",
        [
            "Runtime reads published metadata only.",
            "Raw JSON remains debug-only.",
            "Every action execution re-enters backend API permission checks.",
        ],
    )
    _validate_with_json_schema(payload)
    return payload


def compact_tui_metadata_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a storage-friendly metadata payload.

    The runtime validator restores these default values on load. Keeping the
    file compact avoids treating the published graph as a hand-authored API
    dump while preserving the same validated in-memory contract.
    """

    compacted = copy.deepcopy(payload)
    screen_module_by_key = {
        str(screen.get("key")): str(screen.get("module_key"))
        for screen in compacted.get("screens", [])
        if isinstance(screen, dict)
    }

    for module in compacted.get("modules", []):
        if isinstance(module, dict) and module.get("status") == "online":
            module.pop("status", None)

    for screen in compacted.get("screens", []):
        if not isinstance(screen, dict):
            continue
        if screen.get("status") == "online":
            screen.pop("status", None)
        if screen.get("default_action_key") == "":
            screen.pop("default_action_key", None)
        if screen.get("dashboard_panels") == []:
            screen.pop("dashboard_panels", None)
        for panel in screen.get("dashboard_panels", []) or []:
            if not isinstance(panel, dict):
                continue
            for key, default in (
                ("action_key", ""),
                ("status", ""),
                ("note", ""),
                ("layout_area", ""),
                ("target_screen", ""),
                ("columns", []),
            ):
                if panel.get(key) == default:
                    panel.pop(key, None)
            if panel.get("max_rows") == 8:
                panel.pop("max_rows", None)

    for action in compacted.get("actions", []):
        if not isinstance(action, dict):
            continue
        if action.get("method") == "GET":
            action.pop("method", None)
        if action.get("risk") == "read":
            action.pop("risk", None)
        if action.get("fields") == []:
            action.pop("fields", None)
        if action.get("view_model") == {}:
            action.pop("view_model", None)
        if action.get("pagination") == {}:
            action.pop("pagination", None)
        if action.get("raw_debug") is True:
            action.pop("raw_debug", None)
        if action.get("description") == "":
            action.pop("description", None)
        if action.get("confirmation_required") == _default_confirmation_required(action):
            action.pop("confirmation_required", None)
        if action.get("requires_password") is False:
            action.pop("requires_password", None)
        if action.get("audit_required") == _default_audit_required(action):
            action.pop("audit_required", None)
        if action.get("sensitive_level") == _default_sensitive_level(action):
            action.pop("sensitive_level", None)
        if action.get("executor") == "":
            action.pop("executor", None)
        if action.get("task_group") == "":
            action.pop("task_group", None)
        if action.get("task_tier") == "":
            action.pop("task_tier", None)
        if action.get("sequence") == 999:
            action.pop("sequence", None)
        if action.get("module_key") == screen_module_by_key.get(str(action.get("screen_key"))):
            action.pop("module_key", None)
        if action.get("result_semantics") == []:
            action.pop("result_semantics", None)

    return compacted


def _require_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TuiMetadataValidationError(f"{key} must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise TuiMetadataValidationError(f"{key} entries must be objects")
    return value


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


def _validate_field(action: dict[str, Any], field: dict[str, Any]) -> None:
    field_key = str(field["key"])
    input_type = str(field["input_type"])
    if input_type not in ALLOWED_TUI_FIELD_INPUT_TYPES:
        raise TuiMetadataValidationError(
            f"Action field has unsupported input_type: {action['key']}.{field_key}.{input_type}"
        )

    if input_type == "number" and not field.get("value_type"):
        field["value_type"] = (
            "integer" if field_key.endswith("_id") or field_key == "pk" else "float"
        )
    if input_type == "checkbox" and not field.get("value_type"):
        field["value_type"] = "boolean"
    if input_type in {"text", "textarea", "hidden", "select", "file"} and not field.get(
        "value_type"
    ):
        field["value_type"] = "string"

    value_type = field.get("value_type")
    if value_type and str(value_type) not in ALLOWED_TUI_FIELD_VALUE_TYPES:
        raise TuiMetadataValidationError(
            f"Action field has unsupported value_type: {action['key']}.{field_key}.{value_type}"
        )
    binding = field.get("binding")
    if binding and str(binding) not in ALLOWED_TUI_FIELD_BINDINGS:
        raise TuiMetadataValidationError(
            f"Action field has unsupported binding: {action['key']}.{field_key}.{binding}"
        )
    if input_type == "select" and not isinstance(field.get("options"), list):
        raise TuiMetadataValidationError(
            f"Select field must define options: {action['key']}.{field_key}"
        )
    if field.get("aliases") is not None and not _is_string_list(field.get("aliases")):
        raise TuiMetadataValidationError(
            f"Action field aliases must be a string list: {action['key']}.{field_key}"
        )
    if field.get("semantic") is not None and not isinstance(field.get("semantic"), str):
        raise TuiMetadataValidationError(
            f"Action field semantic must be a string: {action['key']}.{field_key}"
        )
    if field.get("accept") is not None and not isinstance(field.get("accept"), str):
        raise TuiMetadataValidationError(
            f"Action file field accept must be a string: {action['key']}.{field_key}"
        )
    field.setdefault("presentation_semantic", _default_field_presentation_semantic(field_key))
    presentation_semantic = str(field.get("presentation_semantic") or "")
    if presentation_semantic not in ALLOWED_TUI_FIELD_PRESENTATION_SEMANTICS:
        raise TuiMetadataValidationError(
            f"Action field has unsupported presentation_semantic: "
            f"{action['key']}.{field_key}.{presentation_semantic}"
        )
    if presentation_semantic == "prompt_text" and input_type != "textarea":
        raise TuiMetadataValidationError(
            f"Prompt field must use textarea: {action['key']}.{field_key}"
        )
    if presentation_semantic == "endpoint_url" and input_type != "text":
        raise TuiMetadataValidationError(
            f"Endpoint field must use text input: {action['key']}.{field_key}"
        )
    if presentation_semantic in {"api_token", "endpoint_url", "prompt_text"} and str(
        field.get("value_type") or ""
    ) != "string":
        raise TuiMetadataValidationError(
            f"Sensitive/copyable field must use string value_type: {action['key']}.{field_key}"
        )


def _validate_field_alias_registry(registry: Any) -> None:
    if registry is None:
        return
    if not isinstance(registry, dict):
        raise TuiMetadataValidationError("field_aliases must be an object")
    for key, values in registry.items():
        if not isinstance(key, str) or not key.strip():
            raise TuiMetadataValidationError("field_aliases keys must be non-empty strings")
        if not _is_string_list(values):
            raise TuiMetadataValidationError(f"field_aliases entry must be a string list: {key}")


def _validate_action_pagination(action: dict[str, Any]) -> None:
    pagination = action.get("pagination")
    if not isinstance(pagination, dict):
        raise TuiMetadataValidationError(f"Action pagination must be an object: {action['key']}")
    unknown_keys = set(pagination) - ALLOWED_TUI_PAGINATION_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise TuiMetadataValidationError(
            f"Action pagination has unsupported keys: {action['key']}.{names}"
        )
    mode = str(pagination.get("mode") or "")
    if mode not in ALLOWED_TUI_PAGINATION_MODES:
        raise TuiMetadataValidationError(
            f"Action pagination has unsupported mode: {action['key']}.{mode}"
        )
    for key, value in pagination.items():
        if key == "mode":
            continue
        if not isinstance(value, str):
            raise TuiMetadataValidationError(
                f"Action pagination value must be a string: {action['key']}.{key}"
            )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_action_source(action: dict[str, Any]) -> None:
    source = str(action.get("source") or "").strip()
    if not source:
        raise TuiMetadataValidationError(f"Action source is required: {action['key']}")
    if not any(
        source == prefix or source.startswith(prefix) for prefix in ALLOWED_TUI_SOURCE_PREFIXES
    ):
        raise TuiMetadataValidationError(f"Action has unsupported source: {action['key']}.{source}")


def _validate_governance_contract(action: dict[str, Any]) -> None:
    for key in ("confirmation_required", "requires_password", "audit_required"):
        if not isinstance(action.get(key), bool):
            raise TuiMetadataValidationError(
                f"Action governance flag must be boolean: {action['key']}.{key}"
            )
    if str(action.get("sensitive_level") or "") not in ALLOWED_TUI_SENSITIVE_LEVELS:
        raise TuiMetadataValidationError(f"Action has unsupported sensitive_level: {action['key']}")
    if not isinstance(action.get("executor"), str):
        raise TuiMetadataValidationError(f"Action executor must be a string: {action['key']}")
    if not isinstance(action.get("task_group"), str):
        raise TuiMetadataValidationError(f"Action task_group must be a string: {action['key']}")
    if str(action.get("task_tier") or "") not in {
        "",
        "primary",
        "support",
        "advanced",
        "operation",
    }:
        raise TuiMetadataValidationError(f"Action has unsupported task_tier: {action['key']}")
    try:
        action["sequence"] = int(action.get("sequence", 999))
    except (TypeError, ValueError) as exc:
        raise TuiMetadataValidationError(
            f"Action sequence must be an integer: {action['key']}"
        ) from exc
    if _default_confirmation_required(action) and not action["confirmation_required"]:
        raise TuiMetadataValidationError(
            f"Governed action must require confirmation: {action['key']}"
        )
    if _default_audit_required(action) and not action["audit_required"]:
        raise TuiMetadataValidationError(f"Governed action must require audit: {action['key']}")


def _default_confirmation_required(action: dict[str, Any]) -> bool:
    risk = str(action.get("risk") or "read").strip().lower()
    method = str(action.get("method") or "GET").strip().upper()
    return risk == "write" or (risk == "admin" and method != "GET")


def _default_audit_required(action: dict[str, Any]) -> bool:
    risk = str(action.get("risk") or "read").strip().lower()
    method = str(action.get("method") or "GET").strip().upper()
    return risk in GOVERNED_TUI_RISKS and method != "GET"


def _default_sensitive_level(action: dict[str, Any]) -> str:
    risk = str(action.get("risk") or "read").strip().lower()
    if risk == "admin":
        return "critical"
    if risk in {"write", "unsafe"}:
        return "high"
    if risk == "ai":
        return "medium"
    return "none"


def _validate_confirmed_operation_contract(action: dict[str, Any]) -> None:
    risk = str(action.get("risk") or "read")
    if risk != "write":
        return
    if str(action.get("method", "GET")).upper() == "GET":
        raise TuiMetadataValidationError(f"Write action cannot use GET: {action['key']}")
    for field in action.get("fields") or []:
        key = str(field.get("key") or "").lower()
        if not any(token in key for token in HIGH_REVIEW_FIELD_TOKENS):
            continue
        if not field.get("value_type"):
            raise TuiMetadataValidationError(
                f"Reviewed write field must declare value_type: {action['key']}.{field['key']}"
            )
        if field.get("input_type") == "number" and str(field.get("value_type")) not in {
            "decimal",
            "float",
            "integer",
        }:
            raise TuiMetadataValidationError(
                f"Numeric write field has incompatible value_type: {action['key']}.{field['key']}"
            )


def _default_screen_user_experience(screen: dict[str, Any]) -> dict[str, str]:
    existing = dict(screen.get("user_experience") or {})
    workflow = dict(screen.get("workflow") or {})
    business_context = dict(screen.get("business_context") or {})
    summary = str(screen.get("summary") or "").strip()
    label = str(screen.get("label") or "").strip()
    next_label = str(dict(workflow.get("next") or {}).get("label") or "").strip()
    journey = str(existing.get("journey") or _default_screen_journey(screen))
    return {
        "journey": journey,
        "primary_task": str(existing.get("primary_task") or summary or label).strip(),
        "primary_outcome": str(
            existing.get("primary_outcome")
            or business_context.get("decision_output")
            or summary
            or label
        ).strip(),
        "empty_state_hint": str(
            existing.get("empty_state_hint")
            or (
                "先查看 P0 面板，再进入需要展开的任务。"
                if journey == "dashboard"
                else "先运行本屏主任务，必要时补充参数或切换到支撑检查。"
            )
        ).strip(),
        "next_step_hint": str(
            existing.get("next_step_hint")
            or (
                f"完成当前检查后进入「{next_label}」。"
                if next_label
                else "根据结果继续下一项主流程，或进入可执行操作。"
            )
        ).strip(),
    }


def _default_screen_journey(screen: dict[str, Any]) -> str:
    key = str(screen.get("key") or "")
    label = str(screen.get("label") or "")
    if screen.get("dashboard_panels"):
        return "dashboard"
    if "self-service" in key or "接入" in label:
        return "self_service"
    if "admin" in key or "管理员" in label or "治理" in label:
        return "admin"
    return "workspace"


def _validate_screen_user_experience(screen: dict[str, Any]) -> None:
    user_experience = screen.get("user_experience")
    if not isinstance(user_experience, dict):
        raise TuiMetadataValidationError(
            f"Screen user_experience must be an object: {screen['key']}"
        )
    required_fields = (
        "journey",
        "primary_task",
        "primary_outcome",
        "empty_state_hint",
        "next_step_hint",
    )
    _require_fields(user_experience, "screen user_experience", required_fields)
    journey = str(user_experience.get("journey") or "")
    if journey not in ALLOWED_TUI_SCREEN_JOURNEYS:
        raise TuiMetadataValidationError(
            f"Screen user_experience has unsupported journey: {screen['key']}.{journey}"
        )
    for key in required_fields[1:]:
        if _contains_internal_contract_token(str(user_experience.get(key) or "")):
            raise TuiMetadataValidationError(
                f"Screen user_experience leaks internal contract text: {screen['key']}.{key}"
            )
    if journey == "dashboard" and not screen.get("dashboard_panels"):
        raise TuiMetadataValidationError(
            f"Dashboard journey screen must define dashboard_panels: {screen['key']}"
        )
    if journey != "dashboard" and not str(screen.get("default_action_key") or "").strip():
        raise TuiMetadataValidationError(
            f"Workspace screen must define default_action_key: {screen['key']}"
        )


def _default_panel_presentation_semantic(panel: dict[str, Any]) -> str:
    key = str(panel.get("key") or "").lower()
    title = str(panel.get("title") or "").lower()
    kind = str(panel.get("kind") or "")
    if kind == "datagrid":
        return "supporting_list"
    if "prompt" in key or "prompt" in title:
        return "multiline_prompt"
    if "endpoint" in key or "endpoint" in title:
        return "endpoint_list"
    if "status" in key or "状态" in title:
        return "primary_status"
    return "supporting_detail"


def _validate_dashboard_panel(screen: dict[str, Any], panel: dict[str, Any]) -> None:
    user_priority = str(panel.get("user_priority") or "")
    if user_priority not in ALLOWED_TUI_PANEL_USER_PRIORITIES:
        raise TuiMetadataValidationError(
            f"Dashboard panel has unsupported user_priority: {screen['key']}.{panel['key']}"
        )
    presentation_semantic = str(panel.get("presentation_semantic") or "")
    if presentation_semantic not in ALLOWED_TUI_PRESENTATION_SEMANTICS:
        raise TuiMetadataValidationError(
            f"Dashboard panel has unsupported presentation_semantic: "
            f"{screen['key']}.{panel['key']}.{presentation_semantic}"
        )
    if presentation_semantic in {"copyable_secret", "endpoint_list", "multiline_prompt"}:
        if str(panel.get("kind") or "") != "detail":
            raise TuiMetadataValidationError(
                f"Copyable/detail artifact panel must use detail kind: "
                f"{screen['key']}.{panel['key']}"
            )
        if not str(panel.get("action_key") or "").strip():
            raise TuiMetadataValidationError(
                f"Copyable/detail artifact panel must bind an action: "
                f"{screen['key']}.{panel['key']}"
            )
    if presentation_semantic == "primary_status" and str(panel.get("kind") or "") not in {
        "detail",
        "status",
        "regime_quadrant",
    }:
        raise TuiMetadataValidationError(
            f"Primary status panel must use detail/status/regime_quadrant kind: "
            f"{screen['key']}.{panel['key']}"
        )
    if user_priority == "p0" and not (
        str(panel.get("action_key") or "").strip() or str(panel.get("target_screen") or "").strip()
    ):
        raise TuiMetadataValidationError(
            f"P0 panel must point to a task or target screen: {screen['key']}.{panel['key']}"
        )


def _default_result_semantics(action: dict[str, Any]) -> list[str]:
    action_key = str(action.get("key") or "").lower()
    semantics: list[str] = []
    if "mcp-self-status" in action_key or "create-my-mcp-token" in action_key:
        semantics.extend(["primary_status", "copyable_secret"])
    elif "endpoint" in action_key:
        semantics.append("endpoint_list")
    elif "prompt" in action_key:
        semantics.append("multiline_prompt")
    elif "status" in action_key and str(action.get("view_type") or "") in {"detail", "status"}:
        semantics.append("primary_status")
    return semantics


def _normalize_result_semantics(action: dict[str, Any]) -> list[str]:
    value = action.get("result_semantics")
    if value is None:
        return _default_result_semantics(action)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TuiMetadataValidationError(
            f"Action result_semantics must be a string list: {action['key']}"
        )
    return value


def _validate_result_semantics(action: dict[str, Any]) -> None:
    view_type = str(action.get("view_type") or "")
    view_model_kind = str((action.get("view_model") or {}).get("kind") or "")
    for semantic in action.get("result_semantics") or []:
        if semantic not in ALLOWED_TUI_PRESENTATION_SEMANTICS:
            raise TuiMetadataValidationError(
                f"Action result_semantics has unsupported value: {action['key']}.{semantic}"
            )
        if semantic in {"copyable_secret", "endpoint_list", "multiline_prompt"}:
            if view_type != "detail" and view_model_kind not in {"", "detail"}:
                raise TuiMetadataValidationError(
                    f"Copyable/detail artifact action must use detail view: {action['key']}"
                )
        if semantic == "primary_status" and view_type not in {"detail", "status", "message"}:
            raise TuiMetadataValidationError(
                f"Primary status action must use detail/status/message view: {action['key']}"
            )


def _default_field_presentation_semantic(field_key: str) -> str:
    normalized = field_key.lower()
    if normalized in {"api_token", "access_token", "token_value", "display_token"} or any(
        token in normalized for token in ("secret", "api_key")
    ):
        return "api_token"
    if "endpoint" in normalized or normalized.endswith("_url") or normalized == "url":
        return "endpoint_url"
    if normalized.endswith("_id") or normalized in {"pk", "token_id"}:
        return "primary_selector"
    if normalized in {
        "prompt",
        "prompt_text",
        "prompt_body",
        "system_prompt",
        "user_prompt",
        "user_prompt_template",
    } or normalized.endswith("_prompt"):
        return "prompt_text"
    return "identifier"


def _contains_internal_contract_token(value: str) -> bool:
    lowered = value.lower()
    forbidden_tokens = ("/api/", "auto.api", "param.api", "get ", "post ", "<int:", "<str:")
    return any(token in lowered for token in forbidden_tokens)


def _validate_with_json_schema(payload: dict[str, Any]) -> None:
    if Draft202012Validator is None:
        return
    schema = json.loads(TUI_METADATA_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    path = ".".join(str(part) for part in first.path) or "<root>"
    raise TuiMetadataValidationError(f"JSON Schema validation failed at {path}: {first.message}")
