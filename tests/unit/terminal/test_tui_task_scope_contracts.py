"""Candidate contract tests for TUX09 scope and portable selector views.

The tests move with the three application modules when the candidate is
promoted.  They exercise pure parameter and payload logic only; they do not
start Django, call an owner endpoint, or open a database.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
APPLICATION_ROOT = ROOT / "apps" / "terminal" / "application"


def _load_module(name: str, path: Path) -> ModuleType:
    """Load one candidate module by path for promotion-time pure tests."""

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot load candidate module: {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


def _portfolio_row(index: int, *, nullable_currency: bool = False) -> dict[str, object]:
    """Build one owner-shaped portfolio row for a projection test."""

    return {
        "id": index,
        "name": f"组合 {index}",
        "is_active": True,
        "base_currency_code": None if nullable_currency else "CNY",
        "base_currency_name": None if nullable_currency else "人民币",
    }


class TuiTaskScopeContractTests(unittest.TestCase):
    """Verify strict task inputs and portable owner-response projections."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scope = _load_module(
            "tux09_task_scope_contracts",
            APPLICATION_ROOT / "tui_task_scope_contracts.py",
        )
        cls.selector = _load_module(
            "tux09_task_selector_result",
            APPLICATION_ROOT / "tui_task_selector_result.py",
        )

    def test_scope_normalizes_declared_numeric_strings_only(self) -> None:
        queue = self.scope.validate_task_action_scope("today-focus.queue", {"account_id": "12"})
        self.assertIsNotNone(queue)
        self.assertEqual(queue.to_params(), {"account_id": 12})

        facts = self.scope.validate_task_action_scope(
            "portfolio-check.recorded-facts",
            {"pk": "8", "page": "3", "page_size": "100"},
        )
        self.assertIsNotNone(facts)
        self.assertEqual(facts.to_params(), {"pk": 8, "page": 3, "page_size": 100})

        professional_facts = self.scope.validate_task_action_scope(
            "account.portfolio-recorded-facts", {"pk": 8}
        )
        self.assertIsNotNone(professional_facts)
        self.assertEqual(professional_facts.to_params(), {"pk": 8, "page": 1, "page_size": 20})

    def test_scope_rejects_bad_ids_without_float_truncation_or_actor_override(self) -> None:
        invalid_cases = (
            ("today-focus.queue", {"account_id": True}),
            ("today-focus.queue", {"account_id": 1.2}),
            ("today-focus.queue", {"account_id": "default"}),
            ("today-focus.queue", {"account_id": ""}),
            ("portfolio-check.recorded-facts", {"pk": "1.5"}),
            ("portfolio-check.portfolios", {"page": 0}),
            ("portfolio-check.recorded-facts", {"pk": 8, "page_size": 101}),
            ("today-focus.queue", {"account_id": 8, "user_id": 44}),
            ("today-focus.queue", {"account_id": "9" * 5000}),
        )
        for action_key, params in invalid_cases:
            with self.subTest(action_key=action_key, params=params):
                with self.assertRaises(self.scope.TuiTaskScopeError) as raised:
                    self.scope.validate_task_action_scope(action_key, params)
                self.assertEqual(raised.exception.code, "TUI_TASK_SCOPE_INVALID")
                self.assertTrue(raised.exception.message.strip())

    def test_scope_does_not_change_old_action_semantics(self) -> None:
        self.assertIsNone(
            self.scope.validate_task_action_scope(
                "execution.accounts", {"user_id": "other-user", "pk": 12}
            )
        )

    def test_scope_selectors_reject_undeclared_filter_fields(self) -> None:
        for action_key in (
            "today-focus.market-context",
            "today-focus.account-selector",
            "portfolio-check.portfolios",
        ):
            with self.subTest(action_key=action_key):
                with self.assertRaises(self.scope.TuiTaskScopeError):
                    self.scope.validate_task_action_scope(action_key, {"filter": "all"})

    def test_account_projection_uses_portable_datagrid_and_keeps_all_rows(self) -> None:
        payload = {
            "success": True,
            "count": 2,
            "accounts": [
                {"account_id": 7, "account_name": "实仓", "account_type": "real"},
                {"account_id": 8, "account_name": "模拟仓", "account_type": "simulated"},
            ],
        }
        result = self.selector.project_account_selector_payload(payload, http_status=200)
        self.assertEqual(result["kind"], "datagrid")
        self.assertEqual(result["status"], "已读取")
        self.assertEqual(result["pager"]["client_side"], True)
        self.assertEqual(result["pager"]["pagination_mode"], "page")
        self.assertEqual(result["pager"]["total_rows"], 2)
        self.assertEqual(result["pager"]["total_pages"], 1)
        self.assertEqual(result["rows"][1]["account_id"], 8)
        self.assertEqual(
            [column["key"] for column in result["columns"]],
            ["account_name", "account_type", "account_id"],
        )
        self.assertIn("business_summary", result)
        self.assertIn("next_steps", result)

    def test_account_projection_preserves_empty_and_bounds_input_failures(self) -> None:
        empty = self.selector.project_account_selector_payload(
            {"success": True, "count": 0, "accounts": []}, http_status=200
        )
        self.assertEqual(empty["kind"], "datagrid")
        self.assertEqual(empty["pager"]["total_rows"], 0)
        self.assertEqual(empty["pager"]["total_pages"], 1)
        self.assertEqual(empty["rows"], [])

        for malformed in (None, [], "not-an-object"):
            with self.subTest(malformed=malformed):
                failure = self.selector.project_account_selector_payload(malformed, http_status=200)
                self.assertEqual(failure["kind"], "message")
                self.assertEqual(failure["outcome"], "blocked")

        for http_status in (None, 403, 404, 503):
            with self.subTest(http_status=http_status):
                failure = self.selector.project_account_selector_payload(
                    {"error": "secret owner detail"}, http_status=http_status
                )
                self.assertEqual(failure["kind"], "message")
                self.assertEqual(failure["outcome"], "blocked")
                self.assertNotIn("secret", failure["message"])

        with self.assertRaises(TypeError):
            self.selector.project_account_selector_payload({"success": True})

    def test_account_selector_pages_loaded_rows_without_another_owner_request(self) -> None:
        """The complete owner list stays available through twenty-row client pages."""

        rows = [
            {"account_id": number, "account_name": f"账户 {number}", "account_type": "simulated"}
            for number in range(1, 26)
        ]
        result = self.selector.project_account_selector_payload(
            {"success": True, "count": 25, "accounts": rows}, http_status=200
        )
        self.assertEqual(len(result["rows"]), 25)
        self.assertEqual(result["pager"]["page_size"], 20)
        self.assertEqual(result["pager"]["total_pages"], 2)
        self.assertTrue(result["pager"]["has_next"])

    def test_portfolio_projection_keeps_real_page_and_nullable_currency_shape(self) -> None:
        results = [_portfolio_row(index, nullable_currency=index == 43) for index in range(41, 46)]
        result = self.selector.project_portfolio_selector_payload(
            {
                "count": 45,
                "next": None,
                "previous": "https://owner.invalid/portfolios/?page=2",
                "results": results,
            },
            requested_page=3,
            http_status=200,
        )
        self.assertEqual(result["kind"], "datagrid")
        self.assertEqual(result["pager"]["page"], 3)
        self.assertEqual(result["pager"]["page_size"], 20)
        self.assertEqual(result["pager"]["total_rows"], 45)
        self.assertEqual(result["pager"]["total_pages"], 3)
        self.assertTrue(result["pager"]["has_previous"])
        self.assertFalse(result["pager"]["has_next"])
        self.assertIsNone(result["rows"][2]["base_currency_code"])
        self.assertNotIn("owner.invalid", repr(result))
        self.assertIn("business_summary", result)

    def test_portfolio_projection_preserves_empty_and_bounds_transport_failures(self) -> None:
        empty = self.selector.project_portfolio_selector_payload(
            {"count": 0, "next": None, "previous": None, "results": []},
            requested_page=1,
            http_status=200,
        )
        self.assertEqual(empty["kind"], "datagrid")
        self.assertEqual(empty["pager"]["total_rows"], 0)
        self.assertEqual(empty["pager"]["total_pages"], 1)

        for http_status in (403, 404, 503):
            with self.subTest(http_status=http_status):
                failure = self.selector.project_portfolio_selector_payload(
                    {"error": "secret owner detail"},
                    requested_page=2,
                    http_status=http_status,
                )
                self.assertEqual(failure["kind"], "message")
                self.assertEqual(failure["outcome"], "blocked")
                self.assertNotIn("secret", failure["message"])

    def test_portfolio_projection_rejects_nonmapping_and_contradictory_pages(self) -> None:
        malformed = self.selector.project_portfolio_selector_payload(
            [], requested_page=1, http_status=200
        )
        self.assertEqual(malformed["kind"], "message")
        self.assertEqual(malformed["outcome"], "blocked")

        rows = [_portfolio_row(index) for index in range(41, 46)]
        wrong_row_count = self.selector.project_portfolio_selector_payload(
            {
                "count": 45,
                "next": None,
                "previous": "https://owner.invalid/portfolios/?page=2",
                "results": rows[:4],
            },
            requested_page=3,
            http_status=200,
        )
        self.assertEqual(wrong_row_count["kind"], "message")
        self.assertEqual(wrong_row_count["outcome"], "blocked")

        wrong_links = self.selector.project_portfolio_selector_payload(
            {
                "count": 45,
                "next": "https://owner.invalid/portfolios/?page=4",
                "previous": "https://owner.invalid/portfolios/?page=2",
                "results": rows,
            },
            requested_page=3,
            http_status=200,
        )
        self.assertEqual(wrong_links["kind"], "message")
        self.assertEqual(wrong_links["outcome"], "blocked")

        bad_page = self.selector.project_portfolio_selector_payload(
            {"count": 0, "next": None, "previous": None, "results": []},
            requested_page="default",
            http_status=200,
        )
        self.assertEqual(bad_page["kind"], "message")
        self.assertIn("页码", bad_page["message"])


if __name__ == "__main__":
    unittest.main()
