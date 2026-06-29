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
}
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
ALLOWED_TUI_DASHBOARD_PANEL_KEYS = {
    "key",
    "title",
    "kind",
    "action_key",
    "status",
    "note",
    "max_rows",
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
        screen.setdefault("default_action_key", "")
        dashboard_panels = screen.setdefault("dashboard_panels", [])
        if not isinstance(dashboard_panels, list):
            raise TuiMetadataValidationError(
                f"Screen dashboard_panels must be a list: {screen['key']}"
            )

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
        if "pagination" in action:
            _validate_action_pagination(action)
        _validate_governance_contract(action)
        _validate_action_source(action)
        _validate_confirmed_operation_contract(action)

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
