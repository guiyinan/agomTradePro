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
    } == {"sdk_path", "unified_relay", "rest_path"}
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
    assert screen["default_action_key"] == "system.health-summary"
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


def test_instrument_reference_actions_are_explicit_and_write_confirmed() -> None:
    actions = _actions_by_key()
    register = actions["data-center.instrument-reference-mapping-register"]
    mapping_read = actions["data-center.instrument-reference-mapping-read"]
    capture = actions["data-center.instrument-reference-capture"]
    snapshot_read = actions["data-center.instrument-reference-snapshot-read"]
    occurrence_read = actions["data-center.instrument-reference-snapshot-occurrences-read"]

    for action in (register, capture):
        assert action["screen_key"] == "api-library.data-center"
        assert action["method"] == "POST"
        assert action["confirmation_required"] is True
        assert action["audit_required"] is True
        assert action["session_auth_required"] is True

    register_fields = _fields_by_key(register)
    assert {
        "mapping_id",
        "mapping_version",
        "source_crosswalk_id",
        "source_crosswalk_version",
        "exchange_suffix_pairs",
        "exchange_rule_market_pairs",
        "exchange_source_market_board_pairs",
    } == set(register_fields)
    assert all(register_fields[key]["required"] is True for key in register_fields)
    assert all("default" not in field for field in register_fields.values())

    capture_fields = _fields_by_key(capture)
    assert {
        "capture_id",
        "provider_configuration_id",
        "mapping_record_id",
        "exchange_scope",
        "list_status_scope",
        "mode",
    } == set(capture_fields)
    assert all(capture_fields[key]["required"] is True for key in capture_fields)
    assert all("default" not in field for field in capture_fields.values())
    assert {option["value"] for option in capture_fields["mode"]["options"]} == {
        "normal",
        "resume",
    }
    assert "security_id" not in capture_fields
    assert "asset_type" not in capture_fields

    assert mapping_read["endpoint"].endswith("{mapping_record_id}/")
    assert _fields_by_key(mapping_read)["mapping_record_id"]["binding"] == "path"
    assert snapshot_read["endpoint"].endswith("{snapshot_id}/")
    assert _fields_by_key(snapshot_read)["snapshot_id"]["binding"] == "path"
    snapshot_view = snapshot_read["view_model"]
    assert isinstance(snapshot_view, dict)
    assert snapshot_view["rows_path"] == "rows"
    assert snapshot_view["total_path"] == "total"
    assert occurrence_read["endpoint"] == snapshot_read["endpoint"]
    occurrence_fields = _fields_by_key(occurrence_read)
    assert occurrence_fields["snapshot_id"]["binding"] == "path"
    assert occurrence_fields["limit"]["max"] == 200
    occurrence_view = occurrence_read["view_model"]
    assert isinstance(occurrence_view, dict)
    assert occurrence_view["rows_path"] == "occurrences"
    assert occurrence_view["total_path"] == "occurrence_total"
    occurrence_columns = occurrence_view["columns"]
    assert isinstance(occurrence_columns, list)
    assert len(occurrence_columns) <= 16
    assert {
        "fetch_round_id",
        "occurrence_id",
        "response_completed_at",
        "response_body_sha256",
        "raw_audit_version",
        "raw_audit_content_hash",
        "raw_audit_run_id",
        "raw_audit_ingested_run_id",
        "row_count",
        "upstream_time_unknown",
        "must_not_use_for_decision",
        "must_not_execute",
    } <= {str(column["key"]) for column in occurrence_columns if isinstance(column, dict)}
    snapshot_columns = snapshot_view["columns"]
    assert isinstance(snapshot_columns, list)
    assert len(snapshot_columns) <= 16
    assert {
        "list_date",
        "delist_date",
        "upstream_time_unknown",
        "must_not_use_for_decision",
    } <= {str(column["key"]) for column in snapshot_columns if isinstance(column, dict)}
    assert "权责方" in register["description"] and "审批" in register["description"]
    assert "决策" in capture["description"] and "执行权限" in capture["description"]
    assert all(
        "/api/" not in str(action[field])
        for action in (register, mapping_read, capture, snapshot_read, occurrence_read)
        for field in ("label", "description")
    )
