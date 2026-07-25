from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.terminal.application.tui_workbench_catalog import (
    TUI_SCREEN_DERIVED_INPUT_FIELDS,
    TUI_SCREEN_PUBLIC_SOURCE_FIELDS,
    TuiWorkbenchCatalogMixin,
)


class _CatalogHarness(TuiWorkbenchCatalogMixin):
    @staticmethod
    def _operator_text(value: Any) -> Any:
        return value

    @staticmethod
    def _screen_business_context(
        screen: dict[str, Any], actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del actions
        return dict(screen.get("business_context") or {})

    @staticmethod
    def _metadata() -> dict[str, list[dict[str, Any]]]:
        return {"screens": []}

    @staticmethod
    def _screen_by_key(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(screen["key"]): screen for screen in metadata.get("screens", [])}

    @staticmethod
    def _screen_entry_state(
        screen: dict[str, Any],
        actions: list[dict[str, Any]],
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        del actions, user
        return {
            "mode": screen.get("entry_mode", "auto_run"),
            "field_key": screen.get("entry_field_key", ""),
        }


def _screen_schema_properties() -> set[str]:
    root = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (root / "config" / "tui" / "schema" / "tui_metadata.schema.v3.json").read_text(
            encoding="utf-8"
        )
    )
    return set(schema["$defs"]["screen"]["properties"])


def test_every_screen_schema_field_has_an_explicit_server_projection_policy() -> None:
    assert _screen_schema_properties() == (
        TUI_SCREEN_PUBLIC_SOURCE_FIELDS | TUI_SCREEN_DERIVED_INPUT_FIELDS
    )


def test_screen_public_contract_fields_survive_the_server_projection() -> None:
    screen = {
        "key": "guardrail.screen",
        "label": "Guardrail",
        "module_key": "guardrail",
        "group": "ops",
        "summary": "Projection guardrail.",
        "view_type": "detail",
        "audience": "authenticated",
        "status": "online",
        "chrome_mode": "immersive",
        "dashboard_layout": "task_flow",
        "default_action_key": "",
        "dashboard_panels": [{"key": "primary"}],
        "workflow": {"name": "Guardrail"},
        "user_experience": {"journey": "self_service"},
        "business_context": {"objective": "Keep the contract intact."},
        "action_density": {
            "primary_operation_limit": 10,
            "task_group_limit": 6,
        },
        "entry_mode": "parameter_gate",
        "entry_field_key": "account_id",
    }

    summary = _CatalogHarness()._screen_summary(screen, [])

    assert TUI_SCREEN_PUBLIC_SOURCE_FIELDS <= summary.keys()
    for field in TUI_SCREEN_PUBLIC_SOURCE_FIELDS - {"business_context"}:
        assert summary[field] == screen[field]
    assert summary["business_context"] == screen["business_context"]
    assert summary["entry_state"] == {
        "mode": "parameter_gate",
        "field_key": "account_id",
    }
