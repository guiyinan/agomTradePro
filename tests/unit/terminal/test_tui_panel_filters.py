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


def test_panel_filters_keep_passive_primary_list_compatibility():
    action = {
        "method": "GET",
        "risk": "read",
        "fields": [
            {"key": "top_n", "presentation_semantic": "primary_selector", "input_type": "number"}
        ],
    }

    _validate_dashboard_filter_fields(
        {"filter_fields": ["top_n"], "presentation_semantic": "primary_list"}, action
    )


def test_panel_filters_accept_explicit_passive_supporting_chart_selector():
    action = {
        "effect": "read",
        "method": "GET",
        "risk": "read",
        "fields": [
            {
                "key": "range",
                "presentation_semantic": "primary_selector",
                "input_type": "select",
            }
        ],
    }

    _validate_dashboard_filter_fields(
        {
            "filter_fields": ["range"],
            "kind": "chart",
            "presentation_semantic": "supporting_detail",
        },
        action,
    )


@pytest.mark.parametrize(
    ("action_changes", "field"),
    [
        (
            {"effect": "update", "method": "POST", "risk": "write"},
            {"key": "range", "presentation_semantic": "primary_selector", "input_type": "select"},
        ),
        (
            {"confirmation_required": True},
            {"key": "range", "presentation_semantic": "primary_selector", "input_type": "select"},
        ),
        (
            {"effect": "update"},
            {"key": "range", "presentation_semantic": "primary_selector", "input_type": "select"},
        ),
        (
            {},
            {"key": "token", "presentation_semantic": "primary_selector", "input_type": "password"},
        ),
        (
            {},
            {
                "key": "token",
                "presentation_semantic": "primary_selector",
                "input_type": "text",
                "sensitive_level": "high",
            },
        ),
        (
            {},
            {
                "key": "token",
                "presentation_semantic": "primary_selector",
                "input_type": "text",
                "sensitive_level": "critical",
            },
        ),
        (
            {},
            {"key": "token", "presentation_semantic": "api_token", "input_type": "text"},
        ),
    ],
)
def test_supporting_chart_filters_reject_write_confirmation_and_secret_fields(
    action_changes, field
):
    action = {
        "effect": "read",
        "method": "GET",
        "risk": "read",
        "fields": [field],
        **action_changes,
    }

    with pytest.raises(TuiMetadataValidationError):
        _validate_dashboard_filter_fields(
            {
                "filter_fields": [field["key"]],
                "kind": "chart",
                "presentation_semantic": "supporting_detail",
            },
            action,
        )
