"""Constants shared by the TUI metadata validator."""

from pathlib import Path

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
    "password",
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
    "chart_type",
    "rows_path",
    "table_rows_path",
    "chart_rows_path",
    "total_path",
    "page_path",
    "page_size_path",
    "title_path",
    "status_path",
    "empty_message",
    "field_presentations",
    "columns",
    "table_columns",
    "chart_columns",
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
ALLOWED_TUI_DASHBOARD_LAYOUTS = {"adaptive_grid", "task_flow"}
ALLOWED_TUI_PANEL_USER_PRIORITIES = {"p0", "p1", "p2"}
ALLOWED_TUI_PRESENTATION_SEMANTICS = {
    "primary_status",
    "primary_list",
    "supporting_list",
    "copyable_secret",
    "endpoint_list",
    "multiline_prompt",
    "setup_guide",
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
    "empty_message",
    "error_message",
    "stale_message",
    "max_rows",
    "user_priority",
    "presentation_semantic",
    "columns",
    "field_rules",
    "row_actions",
    "layout_area",
    "target_screen",
    "audience",
}
ALLOWED_TUI_ACTION_EFFECTS = {
    "read",
    "create",
    "update",
    "toggle",
    "delete",
    "execute",
}
ALLOWED_TUI_CHART_TYPES = {"line", "bar", "pie"}
ALLOWED_TUI_DASHBOARD_FIELD_FORMATS = {
    "text",
    "money",
    "percentage",
    "datetime",
}
STRICT_TUI_DASHBOARD_PANEL_ACTION_KINDS = {
    "datagrid": {"datagrid"},
    "regime_quadrant": {"detail", "status"},
    "chart": {"chart"},
    "image": {"image"},
    "kpi_trend": {"kpi_trend"},
    "table_chart": {"table_chart"},
    "host_slot": {"host_slot"},
    "custom": {"custom"},
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
