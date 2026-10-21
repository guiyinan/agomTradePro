"""Schema and manual-validator parity for dashboard percentage field units."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import apps.terminal.application.tui_metadata as tui_metadata
from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    validate_tui_metadata,
)
from apps.terminal.application.tui_metadata_constants import TUI_METADATA_SCHEMA_PATH


def _metadata_payload(field_rule: dict[str, Any]) -> dict[str, Any]:
    """Build the smallest valid dashboard metadata payload around one field rule."""

    return {
        "version": "tui-workbench.v2",
        "default_screen": "home",
        "groups": [{"key": "daily", "label": "Daily"}],
        "modules": [
            {"key": "overview", "label": "Overview", "group": "daily", "summary": "Overview"}
        ],
        "screens": [
            {
                "key": "home",
                "label": "Home",
                "module_key": "overview",
                "group": "daily",
                "summary": "Overview",
                "view_type": "status",
                "audience": "authenticated",
                "default_action_key": "summary.read",
                "user_experience": {
                    "journey": "dashboard",
                    "primary_task": "Review the portfolio summary",
                    "primary_outcome": "Read the current summary values",
                    "empty_state_hint": "No summary values are available.",
                    "next_step_hint": "Open account details to review the portfolio.",
                },
                "dashboard_panels": [
                    {
                        "key": "portfolio-summary",
                        "title": "Portfolio summary",
                        "kind": "detail",
                        "action_key": "summary.read",
                        "user_priority": "p0",
                        "presentation_semantic": "primary_status",
                        "field_rules": [dict(field_rule)],
                    }
                ],
            }
        ],
        "actions": [
            {
                "key": "summary.read",
                "label": "Read portfolio summary",
                "endpoint": "/api/dashboard/v1/summary/",
                "intent": "read_dashboard_summary",
                "screen_key": "home",
                "module_key": "overview",
                "view_type": "detail",
                "method": "GET",
                "risk": "read",
                "fields": [],
                "source": "published",
            }
        ],
    }


@pytest.mark.parametrize(
    ("field_rule", "expected_valid"),
    [
        ({"label": "Legacy", "format": "percentage"}, True),
        (
            {"label": "Confidence", "format": "percentage", "percentage_unit": "fraction"},
            True,
        ),
        (
            {"label": "Return", "format": "percentage", "percentage_unit": "percent"},
            True,
        ),
        (
            {"label": "Unsupported", "format": "percentage", "percentage_unit": "ratio"},
            False,
        ),
        ({"label": "Missing format", "percentage_unit": "fraction"}, False),
        (
            {"label": "Wrong format", "format": "money", "percentage_unit": "percent"},
            False,
        ),
    ],
)
def test_schema_and_manual_validator_agree_on_percentage_units(
    field_rule: dict[str, str],
    expected_valid: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = json.loads(TUI_METADATA_SCHEMA_PATH.read_text(encoding="utf-8"))
    field_rule_schema = schema["$defs"]["dashboardPanel"]["properties"]["field_rules"]["items"]
    schema_accepts = not list(Draft202012Validator(field_rule_schema).iter_errors(field_rule))

    monkeypatch.setattr(tui_metadata, "Draft202012Validator", None)
    manual_accepts = True
    try:
        validate_tui_metadata(_metadata_payload(field_rule))
    except TuiMetadataValidationError:
        manual_accepts = False

    assert schema_accepts is expected_valid
    assert manual_accepts is expected_valid
