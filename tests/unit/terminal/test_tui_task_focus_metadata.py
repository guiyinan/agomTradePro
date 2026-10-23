"""Contract tests for the TUX09 task metadata bundle and runtime normalization.

These tests intentionally use only the candidate JSON and stdlib metadata module. They are
portable across environments. The complete runtime publication test additionally
checks the actual normalizer; these tests never call an owner endpoint.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
IA_PATH = ROOT / "config" / "tui" / "ia" / "tui_information_architecture.v1.json"
MODULE_PATH = (
    ROOT / "apps" / "terminal" / "infrastructure" / "tui_metadata_runtime_injection_task_focus.py"
)
READ_ONLY_TASK_FOCUS_ACTION_KEYS = {
    "today-focus.market-context",
    "today-focus.account-selector",
    "today-focus.queue",
    "portfolio-check.portfolios",
    "portfolio-check.recorded-facts",
    "account.portfolio-recorded-facts",
}


def _load_candidate_module() -> ModuleType:
    """Load the pure metadata bundle without importing the application."""

    spec = importlib.util.spec_from_file_location("tux09_task_focus_metadata", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot load candidate metadata: {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ia() -> dict[str, Any]:
    """Read the candidate IA document."""

    return json.loads(IA_PATH.read_text(encoding="utf-8"))


class TuiTaskFocusMetadataContractTests(unittest.TestCase):
    """Check task navigation and action contracts before runtime promotion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_candidate_module()
        cls.actions = {
            str(action["key"]): action for action in cls.module.RUNTIME_TASK_FOCUS_ACTIONS
        }
        cls.screens = {
            str(screen["key"]): screen for screen in cls.module.RUNTIME_TASK_FOCUS_SCREENS
        }
        cls.ia = _ia()
        cls.ia_screens = {str(screen["key"]): screen for screen in cls.ia["runtime_screens"]}

    def test_task_entries_use_dedicated_screens_and_keep_professional_mode(self) -> None:
        task_entries = self.ia["experience"]["modes"][0]["entries"]
        entry_by_key = {str(entry["key"]): entry for entry in task_entries}
        self.assertEqual(entry_by_key["today"]["screen_key"], "task.today-focus")
        self.assertEqual(entry_by_key["portfolio"]["screen_key"], "task.portfolio-check")
        self.assertEqual(self.ia["experience"]["modes"][1]["entries"], [])
        self.assertEqual(self.ia["experience"]["home_screen_key"], "command-center.overview")

    def test_task_screens_are_immersive_dashboards(self) -> None:
        for key, default_action in (
            ("task.today-focus", "today-focus.market-context"),
            ("task.portfolio-check", "portfolio-check.portfolios"),
        ):
            screen = self.ia_screens[key]
            self.assertEqual(screen["chrome_mode"], "immersive")
            self.assertEqual(screen["entry_mode"], "dashboard")
            self.assertEqual(screen["user_experience"]["journey"], "dashboard")
            self.assertEqual(screen["default_action_key"], default_action)

    def test_complete_published_runtime_validates_task_dashboard_semantics(self) -> None:
        """Validate injected IA against the real full publication pipeline."""

        from apps.terminal.infrastructure.tui_metadata_repository import (
            PublishedTuiMetadataRepository,
        )

        repository = PublishedTuiMetadataRepository()
        published = json.loads(repository.published_path.read_text(encoding="utf8"))
        metadata = repository.validate_and_normalize_runtime_payload(published)
        screens = {screen["key"]: screen for screen in metadata["screens"]}
        for key in ("task.today-focus", "task.portfolio-check"):
            self.assertIn(key, screens)
            self.assertTrue(screens[key]["dashboard_panels"])
        summary = next(
            action
            for action in metadata["actions"]
            if action["key"] == "decision.workspace.summary"
        )
        account = next(field for field in summary["fields"] if field["key"] == "account_id")
        self.assertTrue(account["required"])
        self.assertIn(account.get("default"), (None, ""))

    def test_confirmed_account_selector_shape_and_queue_input(self) -> None:
        selector = self.actions["today-focus.account-selector"]
        self.assertEqual(selector["endpoint"], "/api/account/accounts/")
        self.assertEqual(selector["label"], "读取本人活跃账户（实仓或模拟仓）")
        self.assertEqual(selector["description"], "读取当前用户本人活跃的实仓与模拟仓账户。")
        self.assertEqual(selector["view_model"]["rows_path"], "accounts")
        self.assertEqual(selector["view_model"]["total_path"], "count")
        self.assertEqual(
            [column["key"] for column in selector["view_model"]["columns"]],
            ["account_name", "account_type", "account_id"],
        )
        self.assertEqual(selector["view_model"]["columns"][-1]["label"], "账户编号")
        queue = self.actions["today-focus.queue"]
        account_field = queue["fields"][0]
        self.assertEqual(account_field["key"], "account_id")
        self.assertTrue(account_field["required"])
        self.assertEqual(account_field["binding"], "query")
        self.assertEqual(account_field["min"], 1)
        self.assertNotIn("default", account_field)
        self.assertEqual(queue["task_tier"], "support")
        self.assertEqual(queue["view_model"]["rows_path"], "items")
        self.assertEqual(queue["view_model"]["total_path"], "total")

    def test_today_market_action_preserves_owner_evidence_shape(self) -> None:
        action = self.actions["today-focus.market-context"]
        self.assertEqual(action["endpoint"], "/api/tui/operator/home/market_context/")
        self.assertEqual(action["view_model"]["rows_path"], "rows")
        self.assertEqual(action["view_model"]["total_path"], "total")
        self.assertEqual(
            [column["key"] for column in action["view_model"]["columns"]],
            ["area", "status", "freshness", "reliability", "observed_at", "summary"],
        )

    def test_portfolio_selector_has_explicit_owner_page_contract(self) -> None:
        action = self.actions["portfolio-check.portfolios"]
        self.assertEqual(action["endpoint"], "/api/account/portfolios/")
        self.assertEqual(action["pagination"], {"mode": "page", "page_param": "page"})
        page = action["fields"][0]
        self.assertEqual(page["key"], "page")
        self.assertEqual(page["default"], 1)
        self.assertEqual(page["min"], 1)
        self.assertFalse(page["required"])
        self.assertEqual(action["view_model"]["rows_path"], "results")
        self.assertEqual(action["view_model"]["total_path"], "count")
        self.assertEqual(
            [column["key"] for column in action["view_model"]["columns"]],
            ["name", "is_active", "base_currency_code", "base_currency_name", "id"],
        )
        self.assertEqual(action["view_model"]["columns"][-1]["label"], "组合编号")

    def test_recorded_facts_is_row_driven_and_bounded(self) -> None:
        action = self.actions["portfolio-check.recorded-facts"]
        self.assertEqual(action["endpoint"], "/api/account/portfolios/<pk>/recorded-facts/")
        self.assertEqual(
            action["pagination"],
            {"mode": "page", "page_param": "page", "page_size_param": "page_size"},
        )
        fields = {str(field["key"]): field for field in action["fields"]}
        self.assertEqual(fields["pk"]["binding"], "path")
        self.assertTrue(fields["pk"]["required"])
        self.assertEqual(fields["page_size"]["default"], 20)
        self.assertEqual(fields["page_size"]["max"], 100)
        screen = self.ia_screens["task.portfolio-check"]
        result_panel = next(
            panel
            for panel in screen["dashboard_panels"]
            if panel["key"] == "portfolio-check-recorded-facts"
        )
        self.assertNotIn("action_key", result_panel)
        selector = next(
            panel
            for panel in screen["dashboard_panels"]
            if panel["key"] == "portfolio-check-selector"
        )
        row_action = selector["row_actions"][0]
        self.assertEqual(row_action["param_map"], {"pk": "id"})
        self.assertEqual(row_action["result_panel_key"], result_panel["key"])

    def test_professional_alias_reuses_owner_endpoint_and_fields(self) -> None:
        task_action = self.actions["portfolio-check.recorded-facts"]
        professional = self.actions["account.portfolio-recorded-facts"]
        self.assertEqual(professional["screen_key"], "execution.accounts")
        self.assertEqual(professional["endpoint"], task_action["endpoint"])
        self.assertEqual(professional["fields"], task_action["fields"])

    def test_read_actions_stay_read_only_and_preview_has_confirmed_write_contract(self) -> None:
        self.assertEqual(
            set(self.actions) - {"account-inspection.run"},
            READ_ONLY_TASK_FOCUS_ACTION_KEYS,
        )
        for action_key in READ_ONLY_TASK_FOCUS_ACTION_KEYS:
            action = self.actions[action_key]
            self.assertEqual(action["method"], "GET")
            self.assertEqual(action["risk"], "read")
            self.assertEqual(action["effect"], "read")
            self.assertFalse(action["raw_debug"])

        preview = self.actions["account-inspection.run"]
        self.assertEqual(preview["method"], "POST")
        self.assertEqual(preview["risk"], "write")
        self.assertEqual(preview["effect"], "create")
        self.assertTrue(preview["confirmation_required"])
        self.assertTrue(preview["audit_required"])
        self.assertFalse(preview["raw_debug"])
        self.assertEqual(
            preview["endpoint"], "/api/account/accounts/<int:account_id>/inspections/run/"
        )
        self.assertEqual(
            [field["key"] for field in preview["fields"]],
            ["account_id", "temporary_target_weights"],
        )
        target_field = preview["fields"][1]
        self.assertEqual(target_field["input_type"], "textarea")
        self.assertEqual(target_field["binding"], "body")
        self.assertEqual(target_field["value_type"], "string")
        self.assertFalse(target_field["required"])
        self.assertEqual(preview["source"], "approved:runtime-m1-account-inspection-preview")
        self.assertNotIn("auto_create_proposal", preview)

    def test_required_id_actions_are_follow_ups_without_default_fallbacks(self) -> None:
        self.assertNotEqual(
            self.ia_screens["task.today-focus"]["default_action_key"],
            "today-focus.queue",
        )
        self.assertNotEqual(
            self.ia_screens["task.portfolio-check"]["default_action_key"],
            "portfolio-check.recorded-facts",
        )
        self.assertEqual(self.actions["today-focus.queue"]["task_tier"], "support")
        self.assertEqual(self.actions["portfolio-check.recorded-facts"]["task_tier"], "support")
        for key in ("today-focus.queue", "portfolio-check.recorded-facts"):
            for field in self.actions[key]["fields"]:
                if field["key"] in {"account_id", "pk"}:
                    self.assertTrue(field["required"])
                    self.assertNotIn("default", field)

    def test_dashboard_row_actions_stay_on_screen_and_target_known_panel(self) -> None:
        for screen_key in ("task.today-focus", "task.portfolio-check"):
            screen = self.ia_screens[screen_key]
            panel_keys = {str(panel["key"]) for panel in screen["dashboard_panels"]}
            for panel in screen["dashboard_panels"]:
                for row_action in panel.get("row_actions", []):
                    action = self.actions[str(row_action["action_key"])]
                    self.assertEqual(action["screen_key"], screen_key)
                    self.assertIn(row_action["result_panel_key"], panel_keys)

    def test_dashboard_row_action_sources_are_visible_columns(self) -> None:
        for screen_key in ("task.today-focus", "task.portfolio-check"):
            for panel in self.ia_screens[screen_key]["dashboard_panels"]:
                column_keys = {str(column["key"]) for column in panel.get("columns", [])}
                for row_action in panel.get("row_actions", []):
                    self.assertTrue(
                        set(row_action["param_map"].values()) <= column_keys,
                        (screen_key, panel["key"], row_action["param_map"]),
                    )


if __name__ == "__main__":
    unittest.main()
