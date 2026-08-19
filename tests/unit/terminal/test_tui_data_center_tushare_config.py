"""TUI contract coverage for explicit Tushare connection configuration."""

from pathlib import Path

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_data_center import (
    RUNTIME_DATA_CENTER_ACTIONS,
)

PUBLISHED_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "tui"
    / "published"
    / "tui_operation_graph.published.json"
)


def _actions_by_key() -> dict[str, dict[str, object]]:
    return {str(action["key"]): action for action in RUNTIME_DATA_CENTER_ACTIONS}


def _fields_by_key(action: dict[str, object]) -> dict[str, dict[str, object]]:
    fields = action["fields"]
    assert isinstance(fields, list)
    return {str(field["key"]): field for field in fields if isinstance(field, dict)}


def test_tui_exposes_typed_tushare_create_and_provider_update_actions() -> None:
    actions = _actions_by_key()
    create_action = actions["data-center.tushare-create"]
    update_action = actions["data-center.provider-update"]

    create_fields = _fields_by_key(create_action)
    assert "extra_config" not in create_fields
    assert create_action["method"] == "POST"
    assert create_fields["name"]["required"] is True
    assert create_fields["priority"]["value_type"] == "integer"
    assert create_fields["api_key"]["input_type"] == "password"
    assert create_fields["api_key"]["presentation_semantic"] == "api_token"
    assert create_fields["http_url"]["presentation_semantic"] == "endpoint_url"
    assert create_fields["tushare_request_mode"]["default"] == "unified_relay"
    assert {
        option["value"]
        for option in create_fields["tushare_request_mode"]["options"]
        if isinstance(option, dict)
    } == {"sdk_path", "unified_relay"}
    assert create_action["confirmation_required"] is True
    assert create_action["audit_required"] is True

    update_fields = _fields_by_key(update_action)
    assert "extra_config" not in update_fields
    assert update_fields["provider_id"]["binding"] == "path"
    assert update_fields["is_active"]["value_type"] == "boolean"
    assert update_fields["is_active"]["required"] is False
    assert update_fields["api_key"]["required"] is False
    assert update_fields["clear_service_address"]["value_type"] == "boolean"
    assert update_action["method"] == "PATCH"


def test_data_center_dashboard_surfaces_connection_mode_and_row_operations() -> None:
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "api-library.data-center"
    )
    assert screen["label"] == "数据与系统健康"
    assert screen["default_action_key"] == "auto.api.get.api.health"
    panels = {
        str(panel["key"]): panel for panel in screen["dashboard_panels"] if isinstance(panel, dict)
    }
    provider_panel = panels["data-center-providers"]

    columns = provider_panel["columns"]
    assert isinstance(columns, list)
    assert any(
        isinstance(column, dict) and column.get("key") == "tushare_request_mode_label"
        for column in columns
    )
    row_actions = provider_panel["row_actions"]
    assert isinstance(row_actions, list)
    assert {item["action_key"] for item in row_actions if isinstance(item, dict)} == {
        "data-center.provider-update",
        "data-center.provider-test",
    }
    assert "data-center-provider-receipt" in panels


def test_tushare_action_copy_does_not_expose_transport_implementation_paths() -> None:
    actions = _actions_by_key()
    user_copy = " ".join(
        str(actions[key][field])
        for key in ("data-center.tushare-create", "data-center.provider-update")
        for field in ("label", "description")
    )

    assert "/api/" not in user_copy
    assert "extra_config" not in user_copy
    assert "HTTP method" not in user_copy
