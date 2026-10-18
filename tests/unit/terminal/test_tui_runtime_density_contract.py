"""Runtime IA density projection and enforcement contract tests."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from scripts.check_tui_action_copy_and_density import check_tui_action_copy_and_density
from scripts.check_tui_metadata_source_consistency import (
    DEFAULT_IA_PATH,
    DEFAULT_PUBLISHED_PATH,
    load_runtime_payload,
)


class TuiRuntimeDensityContractTests(unittest.TestCase):
    """Keep runtime IA budgets canonical, bounded and user-task safe."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the full normalized runtime graph once for contract assertions."""

        cls.runtime = load_runtime_payload(DEFAULT_PUBLISHED_PATH)
        cls.ia = json.loads(DEFAULT_IA_PATH.read_text(encoding="utf-8"))
        from apps.terminal.infrastructure.tui_information_architecture import (
            screen_action_density,
        )
        from apps.terminal.infrastructure.tui_metadata_repository import (
            PublishedTuiMetadataRepository,
        )

        cls.screen_action_density = staticmethod(screen_action_density)
        cls.repository = PublishedTuiMetadataRepository(published_path=DEFAULT_PUBLISHED_PATH)

    def test_runtime_screens_receive_the_canonical_default_and_overrides(self) -> None:
        """Every runtime IA screen receives the same derived budget as published screens."""

        runtime_screen_keys = {str(item["key"]) for item in self.ia["runtime_screens"]}
        runtime_screens = {
            str(screen["key"]): screen
            for screen in self.runtime["screens"]
            if str(screen.get("key") or "") in runtime_screen_keys
        }
        self.assertEqual(set(runtime_screens), runtime_screen_keys)
        for screen_key, screen in runtime_screens.items():
            self.assertEqual(
                screen["action_density"],
                self.screen_action_density(screen_key, self.ia),
            )

        self.assertEqual(
            runtime_screens["task.today-focus"]["action_density"],
            {"primary_operation_limit": 2, "task_group_limit": 4},
        )
        self.assertEqual(
            runtime_screens["task.portfolio-check"]["action_density"],
            {"primary_operation_limit": 1, "task_group_limit": 4},
        )
        self.assertEqual(
            runtime_screens["cli.terminal"]["action_density"],
            {"primary_operation_limit": 5, "task_group_limit": 4},
        )
        report = check_tui_action_copy_and_density(
            published_payload=json.loads(DEFAULT_PUBLISHED_PATH.read_text(encoding="utf-8")),
            ia_payload=self.ia,
            runtime_payload=self.runtime,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.runtime_screen_density_count, len(runtime_screen_keys))

    def test_density_derivation_rejects_invalid_registry_limits(self) -> None:
        """Invalid or absent budgets cannot silently become unlimited runtime budgets."""

        with self.assertRaises(ValueError):
            self.screen_action_density("task.today-focus", {})
        for field, value in (
            ("default_primary_operation_limit", True),
            ("default_primary_operation_limit", 0),
            ("task_group_limit", -1),
            ("screen_limits", []),
            ("screen_limits", {"task.today-focus": "2"}),
        ):
            invalid = copy.deepcopy(self.ia)
            invalid["action_density"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.screen_action_density("task.today-focus", invalid)

    def test_task_focus_keeps_both_p0_steps_and_contextual_queue_binding(self) -> None:
        """The account queue remains row-driven and cannot become an unscoped step."""

        screens = {str(screen["key"]): screen for screen in self.runtime["screens"]}
        actions = {str(action["key"]): action for action in self.runtime["actions"]}
        screen = screens["task.today-focus"]
        panels = {str(panel["key"]): panel for panel in screen["dashboard_panels"]}
        market = panels["today-focus-market-context"]
        selector = panels["today-focus-account-selector"]
        queue_panel = panels["today-focus-queue"]
        self.assertEqual(market["user_priority"], "p0")
        self.assertEqual(selector["user_priority"], "p0")
        self.assertEqual(market["action_key"], "today-focus.market-context")
        self.assertEqual(selector["action_key"], "today-focus.account-selector")
        self.assertEqual(screen["default_action_key"], "today-focus.market-context")
        self.assertFalse(queue_panel.get("action_key"))

        self.assertEqual(actions["today-focus.market-context"]["task_tier"], "primary")
        self.assertEqual(actions["today-focus.account-selector"]["task_tier"], "primary")
        queue = actions["today-focus.queue"]
        self.assertEqual(queue["method"], "GET")
        self.assertEqual(queue["risk"], "read")
        self.assertEqual(queue["effect"], "read")
        self.assertEqual(queue["task_tier"], "support")
        queue_field = next(field for field in queue["fields"] if field["key"] == "account_id")
        self.assertTrue(queue_field["required"])
        self.assertIn(queue_field.get("default"), (None, ""))
        self.assertEqual(queue_field["binding"], "query")

        row_action = selector["row_actions"][0]
        self.assertEqual(row_action["action_key"], "today-focus.queue")
        self.assertEqual(row_action["param_map"], {"account_id": "account_id"})
        self.assertEqual(row_action["result_panel_key"], queue_panel["key"])
        self.assertNotEqual(screen["default_action_key"], queue["key"])

    def test_metadata_normalization_is_idempotent_and_preserves_action_contracts(self) -> None:
        """Repeated normalization keeps the complete action set and execution policy stable."""

        published = json.loads(DEFAULT_PUBLISHED_PATH.read_text(encoding="utf-8"))
        first = self.repository.validate_and_normalize_runtime_payload(published)
        second = self.repository.validate_and_normalize_runtime_payload(first)
        self.assertEqual(first, second)
        self.assertEqual(
            {str(action["key"]) for action in first["actions"]},
            {str(action["key"]) for action in second["actions"]},
        )

    def test_runtime_overflow_demotes_without_raising_budget_or_removing_actions(self) -> None:
        """Overflow uses existing support/advanced tiers and remains idempotent."""

        screen_key = "cli.terminal"
        budget = self.screen_action_density(screen_key, self.ia)
        screen = {
            "key": screen_key,
            "action_density": dict(budget),
            "default_action_key": "runtime.read.1",
            "dashboard_panels": [
                {
                    "key": "runtime-primary",
                    "action_key": "runtime.read.2",
                    "user_priority": "p0",
                }
            ],
        }
        before_screen = copy.deepcopy(screen)
        actions: list[dict[str, Any]] = [
            {
                "key": f"runtime.read.{index}",
                "screen_key": screen_key,
                "task_tier": "primary",
                "task_group": "01 Runtime",
                "sequence": index,
                "effect": "read",
                "fields": [{"key": "required_value", "required": True}],
            }
            for index in range(1, 7)
        ]
        before = copy.deepcopy(actions)
        before_keys = {str(action["key"]) for action in actions}

        changed = self.repository._enforce_ia_action_density(
            screens=[screen],
            actions=actions,
            ia_screen_keys={screen_key},
        )

        self.assertEqual(changed, 2)
        self.assertEqual(screen["action_density"], budget)
        self.assertEqual(screen, before_screen)
        self.assertEqual({str(action["key"]) for action in actions}, before_keys)
        after_by_key = {str(action["key"]): action for action in actions}
        self.assertEqual(
            [after_by_key[f"runtime.read.{index}"]["task_tier"] for index in range(1, 7)],
            ["primary", "primary", "primary", "primary", "support", "support"],
        )
        self.assertEqual(after_by_key["runtime.read.1"]["task_tier"], "primary")
        self.assertEqual(after_by_key["runtime.read.2"]["task_tier"], "primary")
        self.assertLessEqual(
            sum(action["task_tier"] in {"primary", "operation"} for action in actions),
            budget["primary_operation_limit"],
        )
        self.assertLessEqual(
            sum(action["task_tier"] in {"primary", "operation"} for action in actions),
            budget["task_group_limit"],
        )
        for action in before:
            key = str(action["key"])
            after = after_by_key[key]
            self.assertEqual(
                {field: value for field, value in after.items() if field != "task_tier"},
                {field: value for field, value in action.items() if field != "task_tier"},
            )

        self.assertEqual(
            self.repository._enforce_ia_action_density(
                screens=[screen],
                actions=actions,
                ia_screen_keys={screen_key},
            ),
            0,
        )

    def test_runtime_screen_cap_applies_across_task_groups(self) -> None:
        """Runtime screens cannot exceed their cap by spreading actions across groups."""

        screen_key = "cli.terminal"
        screen = {
            "key": screen_key,
            "action_density": self.screen_action_density(screen_key, self.ia),
        }
        actions: list[dict[str, Any]] = [
            {
                "key": f"runtime.grouped.{index}",
                "screen_key": screen_key,
                "task_tier": "primary",
                "task_group": "01 First" if index <= 3 else "02 Second",
                "sequence": index,
                "effect": "read",
            }
            for index in range(1, 7)
        ]

        changed = self.repository._enforce_ia_action_density(
            screens=[screen],
            actions=actions,
            ia_screen_keys={screen_key},
        )

        self.assertEqual(changed, 1)
        self.assertEqual(actions[-1]["task_tier"], "support")
        self.assertEqual(
            sum(action["task_tier"] in {"primary", "operation"} for action in actions),
            5,
        )

    def test_density_checker_reports_runtime_ia_overflow(self) -> None:
        """The action-density guard includes runtime-owned IA screens."""

        ia_payload: dict[str, Any] = {
            "published_screens": [],
            "runtime_screens": [{"key": "task.today-focus"}],
            "action_density": {
                "default_primary_operation_limit": 5,
                "screen_limits": {"task.today-focus": 2},
                "task_group_limit": 4,
            },
        }
        runtime_actions = [
            {
                "key": f"runtime.today-focus.{index}",
                "screen_key": "task.today-focus",
                "task_group": "01 今日关注",
                "task_tier": "primary",
                "effect": "read",
            }
            for index in range(3)
        ]
        report = check_tui_action_copy_and_density(
            published_payload={"actions": []},
            ia_payload=ia_payload,
            runtime_payload={"actions": runtime_actions},
        )

        self.assertEqual(report.outcome, "blocked")
        self.assertTrue(
            any(
                violation.rule_id == "density:screen_limit"
                and violation.screen_key == "task.today-focus"
                for violation in report.violations
            )
        )
        self.assertEqual(report.runtime_screen_density_count, 1)
        self.assertEqual(report.runtime_screen_densities[0].screen_key, "task.today-focus")
        self.assertEqual(report.runtime_screen_densities[0].primary_operation_count, 3)

    def test_density_checker_reports_runtime_task_group_overflow(self) -> None:
        """Runtime IA groups use the same cap even when the screen cap is not exceeded."""

        ia_payload: dict[str, Any] = {
            "published_screens": [],
            "runtime_screens": [{"key": "task.today-focus"}],
            "action_density": {
                "default_primary_operation_limit": 5,
                "screen_limits": {"task.today-focus": 5},
                "task_group_limit": 4,
            },
        }
        runtime_actions = [
            {
                "key": f"runtime.today-focus.{index}",
                "screen_key": "task.today-focus",
                "task_group": "01 今日关注",
                "task_tier": "primary",
                "effect": "read",
            }
            for index in range(5)
        ]
        report = check_tui_action_copy_and_density(
            published_payload={"actions": []},
            ia_payload=ia_payload,
            runtime_payload={"actions": runtime_actions},
        )

        self.assertEqual(report.over_budget_screen_count, 0)
        self.assertEqual(report.over_budget_task_group_count, 1)
        self.assertTrue(
            any(
                violation.rule_id == "density:task_group_limit"
                and violation.screen_key == "task.today-focus"
                for violation in report.violations
            )
        )


if __name__ == "__main__":
    unittest.main()
