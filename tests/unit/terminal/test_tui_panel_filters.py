"""Metadata contracts for explicitly enabled list filters."""

import pytest

from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    _validate_dashboard_filter_fields,
)


@pytest.mark.parametrize("keys", [["unknown"], ["top_n", "top_n"], "top_n"])
def test_panel_filters_reject_invalid_field_references(keys):
    action = {
        "method": "GET",
        "risk": "read",
        "fields": [
            {"key": "top_n", "presentation_semantic": "primary_selector", "input_type": "number"}
        ],
    }
    with pytest.raises(TuiMetadataValidationError):
        _validate_dashboard_filter_fields(
            {"filter_fields": keys, "presentation_semantic": "primary_list"}, action
        )


@pytest.mark.parametrize("risk,method", [("write", "POST"), ("admin", "GET"), ("ai", "GET")])
def test_panel_filters_reject_nonpassive_actions(risk, method):
    action = {
        "method": method,
        "risk": risk,
        "fields": [
            {"key": "top_n", "presentation_semantic": "primary_selector", "input_type": "number"}
        ],
    }
    with pytest.raises(TuiMetadataValidationError):
        _validate_dashboard_filter_fields(
            {"filter_fields": ["top_n"], "presentation_semantic": "primary_list"}, action
        )
