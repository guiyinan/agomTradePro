"""Private contract drafts for the bounded TUX-09 task result projection.

These tests use decoded service-shaped dictionaries only.  They do not stand
in for API, authorization, database, browser, or executor tests.
"""

from __future__ import annotations

import unittest
from typing import cast

from apps.terminal.application.tui_task_focus_result import (
    project_portfolio_recorded_facts_payload,
    project_today_focus_market_context_payload,
    project_today_focus_queue_payload,
    project_tui_task_focus_result,
)


def _queue_payload(account_id: str = "7") -> dict[str, object]:
    """Build the current today-queue response shape with one item."""

    return {
        "success": True,
        "outcome": "success",
        "account_id": account_id,
        "account_name": "模拟账户",
        "total": 1,
        "items": [
            {
                "item_id": "approval:42",
                "type": "execution_approval_pending",
                "title": "审批执行：600000.SH",
                "status": "PENDING",
                "priority": 15,
                "account_id": account_id,
                "security_code": "600000.SH",
                "source_id": "request-42",
                "next_action": "审批执行",
                "target_screen": "command-center.decision-flow",
                "created_at": "2026-10-18T05:00:00+00:00",
            }
        ],
    }


def _market_payload() -> dict[str, object]:
    """Build the current market-context section shape."""

    return {
        "success": True,
        "outcome": "success",
        "status": "warning",
        "rows": [
            {
                "area": "宏观象限",
                "status": "未知",
                "summary": "宏观观测已超过允许时效。",
                "freshness": "已过期",
                "reliability": "不可用于决策",
                "observed_at": "2026-10-17",
                "severity": "blocked",
                "must_not_use_for_decision": True,
                "blocking_reason": "宏观观测已超过允许时效。",
            },
            {
                "area": "政策",
                "status": "稳定",
                "summary": "政策状态按数据基准日评估",
                "freshness": "今日截面",
                "reliability": "状态可用",
                "observed_at": "2026-10-18",
                "severity": "ok",
            },
        ],
        "total": 2,
    }


def _quote_evidence(
    asset_code: str,
    snapshot_at: str | None,
    fetched_at: str | None,
    freshness_status: str,
    freshness: str,
    must_not_use_for_decision: bool,
    blocked_reason: str | None,
    blocking_reason: str,
) -> dict[str, object]:
    """Build synthetic per-security evidence without asserting provider facts."""

    return {
        "asset_code": asset_code,
        "snapshot_at": snapshot_at,
        "fetched_at": fetched_at,
        "freshness_status": freshness_status,
        "freshness": freshness,
        "must_not_use_for_decision": must_not_use_for_decision,
        "blocked_reason": blocked_reason,
        "blocking_reason": blocking_reason,
    }


def _decision_market_payload() -> dict[str, object]:
    """Build a synthetic decision-data row with separate clocks per security."""

    return {
        "success": True,
        "outcome": "success",
        "rows": [
            {
                "area": "决策资料",
                "status": "已检查",
                "severity": "warning",
                "summary": "证券行情按标的分别核验。",
                "freshness": "存在时效差异",
                "reliability": "需查看限制",
                "observed_at": "",
                "must_not_use_for_decision": True,
                "blocking_reason": "本次判断含有受限证券行情。",
                "blocked_reasons": ["SYNTHETIC_OWNER_BLOCK_CODE_01"],
                "checked_at": "2026-10-28T10:00:00+08:00",
                "thermometer_observed_at": "2026-10-27T15:00:00+08:00",
                "thermometer_as_of_date": "2026-10-27",
                "thermometer_snapshot_date": "2026-10-28",
                "quote_source_times": "合成行情时间汇总（仅治理使用）",
                "quote_evidence": [
                    _quote_evidence(
                        "600000.SH",
                        "2026-10-28T09:30:00+08:00",
                        "2026-10-28T09:31:00+08:00",
                        "SYNTHETIC_FRESHNESS_CODE_03",
                        "行情时间较早",
                        True,
                        "SYNTHETIC_QUOTE_BLOCK_CODE_04",
                        "该证券行情时间较早，当前不可用于决策。",
                    ),
                    _quote_evidence(
                        "000001.SZ",
                        "2026-10-28T09:45:00+08:00",
                        "2026-10-28T09:46:00+08:00",
                        "SYNTHETIC_FRESHNESS_CODE_05",
                        "时间待核验",
                        False,
                        None,
                        "该证券行情时间资料待核验。",
                    ),
                ],
            }
        ],
        "total": 1,
    }


def _decision_row(payload: dict[str, object]) -> dict[str, object]:
    """Return the sole synthetic decision-data row for focused mutations."""

    return cast(list[dict[str, object]], payload["rows"])[0]


def _position(portfolio_id: int, position_id: int) -> dict[str, object]:
    """Build one position with legal zero/null native fields."""

    return {
        "id": position_id,
        "portfolio": portfolio_id,
        "portfolio_name": "测试组合",
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "asset_class": "stock",
        "shares": 0.0,
        "avg_cost": "0.000000",
        "current_price": None,
        "market_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "valuation_known": False,
        "valuation_status": "unknown",
        "source": "stored_position",
        "source_id": None,
        "currency_code": None,
        "currency_name": None,
        "currency_symbol": None,
        "opened_at": None,
        "updated_at": "2026-10-18T06:00:00+00:00",
    }


def _facts_payload(
    *,
    portfolio_id: int = 9,
    page: int = 1,
    page_size: int = 20,
    positions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build the recorded-facts response, including nulls and zeros."""

    rows = positions if positions is not None else [_position(portfolio_id, 101)]
    expected_rows = 0 if not rows else min(page_size, len(rows))
    return {
        "success": True,
        "outcome": "success",
        "portfolio_id": portfolio_id,
        "portfolio_name": "测试组合",
        "portfolio_is_active": True,
        "owner_user_id": 12,
        "owner_username": "账户持有人",
        "access_role": "observer",
        "positions": {
            "count": len(rows),
            "page": page,
            "page_size": page_size,
            "has_next": False,
            "items": rows[:expected_rows],
        },
        "statistics": {
            "total_value": None,
            "total_cost": "0.00",
            "total_pnl": None,
            "total_pnl_pct": None,
            "position_count": len(rows),
            "asset_class_breakdown": None,
            "region_breakdown": None,
            "valuation_known": False,
            "valuation_status": "unknown",
            "total_capital_inflow": "0.00",
            "total_capital_outflow": "0.00",
            "net_capital_flow": "0.00",
            "currency_status": "stored_values_without_fx_normalization",
        },
        "position_read_clock": {
            "read_started_at": "2026-10-18T06:00:00+00:00",
            "read_finished_at": "2026-10-18T06:00:01+00:00",
            "clock_kind": "application_read_boundary",
            "source_time_status": "not_provided",
        },
        "statistics_read_clock": {
            "read_started_at": "2026-10-18T06:00:02+00:00",
            "read_finished_at": "2026-10-18T06:00:03+00:00",
            "clock_kind": "application_read_boundary",
            "source_time_status": "not_provided",
        },
    }


def _facts_target() -> dict[str, str]:
    """Build the caller-supplied closed professional target."""

    return {
        "screen_key": "execution.accounts",
        "action_key": "account.portfolio-recorded-facts",
        "label": "继续查看专业记录",
    }


def _first_position(payload: dict[str, object]) -> dict[str, object]:
    """Return the single stored-position fixture row for focused mutations."""

    positions = cast(dict[str, object], payload["positions"])
    return cast(list[dict[str, object]], positions["items"])[0]


class TuiTaskFocusResultContractTests(unittest.TestCase):
    """Check identity, units, clocks, outcomes, and bounded failures."""

    def test_queue_uses_compact_fields_and_expandable_rows(self) -> None:
        result = project_today_focus_queue_payload(
            _queue_payload(), requested_account_id=7, http_status=200
        )

        self.assertEqual(result["kind"], "detail")
        self.assertEqual(result["next_steps"], [])
        self.assertEqual(result["fields"][0]["key"], "account_name")
        restriction = result["sections"][0]["restriction_message"]
        self.assertIn("事项时间", restriction)
        self.assertIn("记录/生成时间", restriction)
        row_text = str(result["sections"][0]["rows"][0])
        self.assertIn("2026-10-18T05:00:00+00:00", row_text)

    def test_queue_closed_target_is_the_only_continuation(self) -> None:
        result = project_today_focus_queue_payload(
            _queue_payload(),
            requested_account_id=7,
            http_status=200,
            professional_target={
                "screen_key": "command-center.decision-flow",
                "action_key": "decision.workspace.summary",
                "label": "查看决策上下文",
            },
        )

        self.assertEqual(result["next_steps"][0]["params"], {"account_id": 7})

    def test_queue_never_uses_default_or_previous_account(self) -> None:
        result = project_today_focus_queue_payload(
            _queue_payload("default"), requested_account_id=7, http_status=200
        )

        self.assertEqual(result["kind"], "message")
        self.assertEqual(result["outcome"], "blocked")
        self.assertNotIn("approval:42", str(result))

    def test_queue_forbidden_is_bounded(self) -> None:
        result = project_today_focus_queue_payload(
            _queue_payload(), requested_account_id=7, http_status=403
        )

        self.assertEqual(result["kind"], "message")
        self.assertNotIn("request-42", str(result))

    def test_market_context_uses_sections_and_keeps_each_observation_time(self) -> None:
        result = project_today_focus_market_context_payload(_market_payload(), http_status=200)

        self.assertEqual(result["kind"], "detail")
        self.assertEqual(result["nested"][0]["count"], 2)
        self.assertIn("2026-10-17", str(result["sections"][0]))
        self.assertNotIn("统一 as_of", str(result))

    def test_market_context_malformed_row_is_blocked(self) -> None:
        payload = _market_payload()
        payload["rows"] = [{"area": "宏观象限"}]
        payload["total"] = 1

        result = project_today_focus_market_context_payload(payload, http_status=200)

        self.assertEqual(result["kind"], "message")

    def test_cached_legacy_decision_aggregate_cannot_claim_a_unified_source_clock(self) -> None:
        """A synthetic pre-upgrade cached row must be re-read instead of relabelled."""

        payload = _market_payload()
        payload["rows"] = [
            {
                "area": "决策数据",
                "status": "OK",
                "severity": "ok",
                "observed_at": "2026-10-27",
                "summary": "决策数据链路可用",
            }
        ]
        payload["total"] = 1
        result = project_today_focus_market_context_payload(payload, http_status=200)
        self.assertEqual(result["kind"], "message")
        self.assertNotIn("决策数据链路可用", str(result))

    def test_decision_market_context_keeps_each_security_clock_and_friendly_reason(self) -> None:
        """Synthetic evidence retains distinct quote clocks and user-facing reasons."""

        result = project_today_focus_market_context_payload(
            _decision_market_payload(), http_status=200
        )

        self.assertEqual(result["kind"], "detail")
        self.assertIn("2026-10-28T10:00:00+08:00", str(result["fields"]))
        self.assertIn("2026-10-27T15:00:00+08:00", str(result["fields"]))
        self.assertIn("2026-10-27", str(result["fields"]))
        self.assertIn("2026-10-28", str(result["fields"]))
        sections = cast(list[dict[str, object]], result["sections"])
        self.assertEqual(sections[1]["label"], "检查与温度计时间")
        self.assertEqual(sections[2]["label"], "逐只证券行情证据")
        quotes = cast(list[dict[str, object]], sections[2]["rows"])
        first_quote = str(quotes[0])
        second_quote = str(quotes[1])
        for value in (
            "600000.SH",
            "2026-10-28T09:30:00+08:00",
            "2026-10-28T09:31:00+08:00",
            "行情时间较早",
            "不可用于决策",
            "该证券行情时间较早，当前不可用于决策。",
        ):
            self.assertIn(value, first_quote)
        for value in (
            "000001.SZ",
            "2026-10-28T09:45:00+08:00",
            "2026-10-28T09:46:00+08:00",
            "时间待核验",
            "该证券行情时间资料待核验。",
        ):
            self.assertIn(value, second_quote)

    def test_decision_market_context_shows_aggregate_owner_reason_in_first_layer(self) -> None:
        """A restriction beyond the four-row preview remains visible immediately."""

        payload = _decision_market_payload()
        decision_row = _decision_row(payload)
        leading_rows = [
            {"area": f"普通范围 {number}", "status": "已检查", "severity": "ok"}
            for number in range(1, 5)
        ]
        payload["rows"] = leading_rows + [decision_row]
        payload["total"] = 5

        result = project_today_focus_market_context_payload(payload, http_status=200)

        self.assertEqual(result["kind"], "detail")
        first_layer = f"{result['business_summary']} {result['fields']}"
        self.assertIn("本次判断含有受限证券行情。", first_layer)
        self.assertIn("不可用于决策", first_layer)

    def test_decision_market_context_keeps_null_clocks_unknown_without_inventing_values(
        self,
    ) -> None:
        """Unavailable synthetic clocks stay unavailable and do not become zero or now."""

        payload = _decision_market_payload()
        row = _decision_row(payload)
        row["thermometer_observed_at"] = None
        row["thermometer_as_of_date"] = None
        row["thermometer_snapshot_date"] = None
        quotes = cast(list[dict[str, object]], row["quote_evidence"])
        quotes[0]["snapshot_at"] = None
        quotes[0]["fetched_at"] = None

        result = project_today_focus_market_context_payload(payload, http_status=200)

        self.assertEqual(result["kind"], "detail")
        section_text = str(result["sections"])
        for label in (
            "检查时间",
            "温度计观测日期/时间",
            "温度计数据基准日",
            "温度计快照日期",
            "行情观测时间",
            "行情抓取时间",
        ):
            self.assertIn(label, section_text)
        self.assertGreaterEqual(section_text.count("未提供"), 6)
        self.assertNotIn("0.0", str(result))
        self.assertNotIn("1970-01-01", str(result))

    def test_decision_market_context_keeps_machine_codes_out_of_view_model(self) -> None:
        """Synthetic future owner codes and governance-only text stay internal."""

        payload = _decision_market_payload()
        result = project_today_focus_market_context_payload(payload, http_status=200)
        rendered = str(result)

        self.assertEqual(result["kind"], "detail")
        for internal_value in (
            "SYNTHETIC_OWNER_BLOCK_CODE_01",
            "SYNTHETIC_FRESHNESS_CODE_03",
            "SYNTHETIC_FRESHNESS_CODE_05",
            "SYNTHETIC_QUOTE_BLOCK_CODE_04",
            "合成行情时间汇总（仅治理使用）",
        ):
            self.assertNotIn(internal_value, rendered)
        self.assertIn("本次判断含有受限证券行情。", rendered)
        self.assertIn("该证券行情时间较早，当前不可用于决策。", rendered)

    def test_decision_market_context_accepts_empty_internal_status_strings(self) -> None:
        """Empty synthetic machine codes remain valid when human evidence is present."""

        payload = _decision_market_payload()
        quote = cast(list[dict[str, object]], _decision_row(payload)["quote_evidence"])[0]
        quote["freshness_status"] = ""
        quote["blocked_reason"] = ""

        result = project_today_focus_market_context_payload(payload, http_status=200)

        self.assertEqual(result["kind"], "detail")
        self.assertIn("行情时间较早", str(result))
        self.assertNotIn("freshness_status", str(result))

    def test_decision_market_context_blocks_malformed_quote_evidence(self) -> None:
        """Malformed synthetic evidence shape or booleans cannot yield detail output."""

        invalid_quote_fields: tuple[tuple[str, object], ...] = (
            ("asset_code", 600000),
            ("snapshot_at", 123),
            ("fetched_at", False),
            ("freshness_status", ["unexpected"]),
            ("freshness", 1),
            ("must_not_use_for_decision", 1),
            ("blocked_reason", {"raw": "not-a-scalar"}),
            ("blocking_reason", ["not-human-text"]),
        )
        for key, value in invalid_quote_fields:
            payload = _decision_market_payload()
            quotes = cast(list[dict[str, object]], _decision_row(payload)["quote_evidence"])
            quotes[0][key] = value
            result = project_today_focus_market_context_payload(payload, http_status=200)
            with self.subTest(field=key):
                self.assertEqual(result["kind"], "message")
                self.assertNotIn("600000.SH", str(result))

        malformed_shapes: tuple[tuple[str, object], ...] = (
            ("quote_evidence", "not-a-list"),
            ("quote_evidence", ["not-an-object"]),
            ("must_not_use_for_decision", 1),
            ("blocked_reasons", ["SYNTHETIC_CODE", 9]),
            ("checked_at", None),
            ("thermometer_as_of_date", 20261027),
        )
        for key, value in malformed_shapes:
            payload = _decision_market_payload()
            _decision_row(payload)[key] = value
            result = project_today_focus_market_context_payload(payload, http_status=200)
            with self.subTest(row_field=key):
                self.assertEqual(result["kind"], "message")

    def test_recorded_facts_preserves_zero_null_native_unit_and_read_clock(self) -> None:
        result = project_portfolio_recorded_facts_payload(
            _facts_payload(),
            requested_portfolio_id=9,
            requested_page=1,
            requested_page_size=20,
            http_status=200,
        )

        self.assertEqual(result["kind"], "detail")
        self.assertIn("估值未知或未确认时不可用于决策", result["business_summary"])
        self.assertEqual(result["fields"][0]["key"], "portfolio_name")
        self.assertEqual([item["key"] for item in result["nested"]], ["positions"])
        self.assertEqual(
            result["pager"],
            {
                "client_side": False,
                "pagination_mode": "page",
                "page": 1,
                "page_size": 20,
                "total_rows": 1,
                "total_pages": 1,
                "has_previous": False,
                "has_next": False,
            },
        )
        text = str(result["sections"])
        self.assertIn("记录数量', 'value': '0.0", text)
        self.assertIn("记录现价', 'value': '未知", text)
        self.assertIn("记录市值', 'value': '未知", text)
        self.assertIn("记录总额（原始单位）', 'value': '未知", text)
        self.assertIn("不可用于决策", text)
        self.assertIn("币种代码', 'value': '未提供", text)
        self.assertIn("源观测时间", text)
        self.assertNotIn("CNY", text)
        self.assertNotIn("FX", text)

    def test_recorded_facts_preserves_explicit_known_zero_valuations(self) -> None:
        payload = _facts_payload()
        position = _first_position(payload)
        position.update(
            {
                "current_price": "0.0000",
                "market_value": "0.00",
                "unrealized_pnl": "0.00",
                "unrealized_pnl_pct": 0.0,
                "valuation_known": True,
                "valuation_status": "unconfirmed",
            }
        )
        statistics = cast(dict[str, object], payload["statistics"])
        statistics.update(
            {
                "total_value": "0.00",
                "total_pnl": "0.00",
                "total_pnl_pct": 0.0,
                "asset_class_breakdown": {"stock": 0.0},
                "region_breakdown": {"CN": 0.0},
                "valuation_known": True,
                "valuation_status": "unconfirmed",
            }
        )

        result = project_portfolio_recorded_facts_payload(
            payload, requested_portfolio_id=9, http_status=200
        )

        self.assertEqual(result["kind"], "detail")
        self.assertIn("记录市值', 'value': '0.00", str(result["sections"]))
        self.assertIn("记录总额（原始单位）', 'value': '0.00", str(result["sections"]))
        self.assertIn("估值未知或未确认时不可用于决策", str(result["sections"]))

    def test_recorded_facts_keeps_nulls_when_knowledge_flag_is_true(self) -> None:
        payload = _facts_payload()
        position = _first_position(payload)
        position["valuation_known"] = True
        position["valuation_status"] = "unconfirmed"
        statistics = cast(dict[str, object], payload["statistics"])
        statistics["valuation_known"] = True
        statistics["valuation_status"] = "unconfirmed"

        result = project_portfolio_recorded_facts_payload(
            payload, requested_portfolio_id=9, http_status=200
        )

        self.assertEqual(result["kind"], "detail")
        self.assertIn("记录现价', 'value': '未提供", str(result["sections"]))
        self.assertIn("记录总额（原始单位）', 'value': '未提供", str(result["sections"]))

    def test_recorded_facts_rejects_supplied_breakdowns_when_totals_are_unknown(self) -> None:
        for key, value in (
            ("asset_class_breakdown", {"股票": 0.0}),
            ("region_breakdown", {"CN": 0.0}),
        ):
            payload = _facts_payload()
            statistics = cast(dict[str, object], payload["statistics"])
            statistics[key] = value
            result = project_portfolio_recorded_facts_payload(
                payload, requested_portfolio_id=9, http_status=200
            )
            with self.subTest(key=key):
                self.assertEqual(result["kind"], "message")

    def test_recorded_facts_requires_explicit_consistent_valuation_knowledge(self) -> None:
        for missing_key in ("valuation_known", "valuation_status"):
            payload = _facts_payload()
            position = _first_position(payload)
            del position[missing_key]
            result = project_portfolio_recorded_facts_payload(
                payload, requested_portfolio_id=9, http_status=200
            )
            with self.subTest(missing_key=missing_key):
                self.assertEqual(result["kind"], "message")

        for key, value in (
            ("valuation_known", 1),
            ("valuation_known", None),
            ("valuation_status", "ready"),
        ):
            payload = _facts_payload()
            _first_position(payload)[key] = value
            result = project_portfolio_recorded_facts_payload(
                payload, requested_portfolio_id=9, http_status=200
            )
            with self.subTest(key=key, value=value):
                self.assertEqual(result["kind"], "message")

        inconsistent = _facts_payload()
        position = _first_position(inconsistent)
        position["market_value"] = "0.00"
        result = project_portfolio_recorded_facts_payload(
            inconsistent, requested_portfolio_id=9, http_status=200
        )
        self.assertEqual(result["kind"], "message")

        inconsistent_statistics = _facts_payload()
        statistics = cast(dict[str, object], inconsistent_statistics["statistics"])
        statistics["total_value"] = "0.00"
        result = project_portfolio_recorded_facts_payload(
            inconsistent_statistics, requested_portfolio_id=9, http_status=200
        )
        self.assertEqual(result["kind"], "message")

        missing_statistics_flag = _facts_payload()
        statistics = cast(dict[str, object], missing_statistics_flag["statistics"])
        del statistics["valuation_known"]
        result = project_portfolio_recorded_facts_payload(
            missing_statistics_flag, requested_portfolio_id=9, http_status=200
        )
        self.assertEqual(result["kind"], "message")

    def test_recorded_facts_keeps_pages_two_and_three_reachable(self) -> None:
        rows = [_position(9, 101 + index) for index in range(5)]
        payload = _facts_payload(positions=rows, page=3)
        positions = cast(dict[str, object], payload["positions"])
        positions["count"] = 45
        positions["page"] = 3
        positions["page_size"] = 20
        positions["has_next"] = False
        positions["items"] = rows

        result = project_portfolio_recorded_facts_payload(
            payload,
            requested_portfolio_id=9,
            requested_page=3,
            requested_page_size=20,
            http_status=200,
        )

        self.assertEqual(result["kind"], "detail")
        self.assertEqual(result["pager"]["page"], 3)
        self.assertEqual(result["pager"]["total_rows"], 45)
        self.assertEqual(len(result["sections"][0]["rows"]), 5)

    def test_recorded_facts_out_of_range_page_is_plain_empty_page(self) -> None:
        payload = _facts_payload()
        positions = cast(dict[str, object], payload["positions"])
        positions.update(
            {"count": 45, "page": 200, "page_size": 20, "has_next": False, "items": []}
        )

        result = project_portfolio_recorded_facts_payload(
            payload,
            requested_portfolio_id=9,
            requested_page=200,
            requested_page_size=20,
            http_status=200,
        )

        self.assertEqual(result["kind"], "detail")
        self.assertEqual(result["pager"]["page"], 200)
        self.assertEqual(result["pager"]["total_pages"], 3)
        self.assertEqual(result["sections"][0]["rows"], [])
        self.assertIn("第 200 页没有记录", result["business_summary"])
        self.assertNotIn("格式无法识别", result["business_summary"])

    def test_recorded_facts_rejects_foreign_position_row(self) -> None:
        row = _facts_payload()["positions"]
        assert isinstance(row, dict)
        items = cast(list[dict[str, object]], row["items"])
        items[0]["portfolio"] = 10

        result = project_portfolio_recorded_facts_payload(
            _facts_payload(positions=items),
            requested_portfolio_id=9,
            http_status=200,
        )

        self.assertEqual(result["kind"], "message")
        self.assertNotIn("浦发银行", str(result))

    def test_recorded_facts_rejects_mismatched_page_facts(self) -> None:
        payload = _facts_payload(page=2, page_size=20)

        result = project_portfolio_recorded_facts_payload(
            payload,
            requested_portfolio_id=9,
            requested_page=1,
            requested_page_size=20,
            http_status=200,
        )

        self.assertEqual(result["kind"], "message")

    def test_recorded_facts_forbidden_does_not_show_previous_detail(self) -> None:
        result = project_portfolio_recorded_facts_payload(
            _facts_payload(), requested_portfolio_id=9, http_status=403
        )

        self.assertEqual(result["kind"], "message")
        self.assertNotIn("测试组合", str(result))

    def test_recorded_facts_failed_and_blocked_outcomes_do_not_show_facts(self) -> None:
        for outcome in ("failed", "blocked"):
            payload = _facts_payload()
            payload["outcome"] = outcome
            result = project_portfolio_recorded_facts_payload(
                payload, requested_portfolio_id=9, http_status=200
            )

            self.assertEqual(result["kind"], "message")
            self.assertEqual(result["owner_outcome"], outcome)
            self.assertNotIn("测试组合", str(result))

    def test_recorded_facts_partial_noop_and_missing_outcome_are_conservative(self) -> None:
        for outcome, status in (("partial", "部分读取"), ("noop", "未产生记录")):
            payload = _facts_payload()
            payload["outcome"] = outcome
            result = project_portfolio_recorded_facts_payload(
                payload, requested_portfolio_id=9, http_status=200
            )
            self.assertEqual(result["kind"], "detail")
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["next_steps"], [])

        missing = _facts_payload()
        del missing["outcome"]
        result = project_portfolio_recorded_facts_payload(
            missing, requested_portfolio_id=9, http_status=200
        )
        self.assertEqual(result["kind"], "detail")
        self.assertNotIn("outcome", result)
        self.assertEqual(result["next_steps"], [])
        self.assertIn("结果状态未提供", result["business_summary"])

    def test_recorded_facts_unknown_outcome_is_blocked(self) -> None:
        payload = _facts_payload()
        payload["outcome"] = "ready_for_trading"

        result = project_portfolio_recorded_facts_payload(
            payload, requested_portfolio_id=9, http_status=200
        )

        self.assertEqual(result["kind"], "message")
        self.assertNotIn("测试组合", str(result))

    def test_recorded_facts_unknown_currency_status_is_blocked(self) -> None:
        payload = _facts_payload()
        statistics = payload["statistics"]
        assert isinstance(statistics, dict)
        statistics["currency_status"] = "unknown"

        result = project_portfolio_recorded_facts_payload(
            payload, requested_portfolio_id=9, http_status=200
        )

        self.assertEqual(result["kind"], "message")

    def test_professional_alias_uses_only_closed_target_and_safe_pk(self) -> None:
        result = project_tui_task_focus_result(
            "account.portfolio-recorded-facts",
            _facts_payload(),
            requested_params={"pk": 9, "page": 1, "page_size": 20},
            http_status=200,
            professional_target=cast(dict[str, str], _facts_target()),
        )

        self.assertEqual(result["kind"], "detail")
        self.assertEqual(result["next_steps"][0]["screen_key"], "execution.accounts")
        self.assertEqual(result["next_steps"][0]["action_key"], "account.portfolio-recorded-facts")
        self.assertEqual(result["next_steps"][0]["params"], {"pk": 9})

    def test_invalid_target_parameters_are_not_copied(self) -> None:
        target = _facts_target()
        target["params"] = "secret"
        result = project_portfolio_recorded_facts_payload(
            _facts_payload(),
            requested_portfolio_id=9,
            http_status=200,
            professional_target=cast(dict[str, str], target),
        )

        self.assertEqual(result["next_steps"], [])

    def test_nonfinite_or_malformed_money_is_not_presented_as_stored_value(self) -> None:
        for value in ("NaN", "Infinity", "not-money"):
            with self.subTest(value=value):
                payload = _facts_payload()
                statistics = cast(dict[str, object], payload["statistics"])
                statistics["valuation_known"] = True
                statistics["valuation_status"] = "unconfirmed"
                statistics["total_pnl"] = "0.00"
                statistics["total_pnl_pct"] = 0.0
                statistics["total_value"] = value
                result = project_portfolio_recorded_facts_payload(
                    payload, requested_portfolio_id=9, http_status=200
                )
                self.assertEqual(result["kind"], "message")
                self.assertNotIn(value, str(result))

    def test_unknown_action_and_non_mapping_do_not_fall_back_to_raw_detail(self) -> None:
        secret_sentinel = "MALFORMED_OWNER_SECRET_8F4E"
        unknown = project_tui_task_focus_result(
            "unknown.action", {"secret": "do not show"}, requested_params={}, http_status=200
        )
        malformed = project_tui_task_focus_result(
            "today-focus.queue",
            [secret_sentinel],
            requested_params={"account_id": 7},
            http_status=200,
        )

        self.assertEqual(unknown["kind"], "message")
        self.assertEqual(malformed["kind"], "message")
        self.assertNotIn("secret", str(unknown))
        self.assertNotIn(secret_sentinel, str(malformed))

    def test_overlong_statistics_group_label_blocks_unbounded_owner_text(self) -> None:
        """Malformed owner labels cannot expand the task result without a bound."""

        payload = _facts_payload()
        statistics = cast(dict[str, object], payload["statistics"])
        statistics["asset_class_breakdown"] = {"X" * 5000: 1}
        result = project_portfolio_recorded_facts_payload(
            payload, requested_portfolio_id=9, http_status=200
        )
        self.assertEqual(result["kind"], "message")
        self.assertNotIn("X" * 5000, str(result))

    def test_current_owners_without_outcome_can_offer_only_a_fresh_read_target(self) -> None:
        """Read navigation does not imply a complete or decision-ready result."""

        facts = _facts_payload()
        facts.pop("outcome")
        facts_result = project_portfolio_recorded_facts_payload(
            facts,
            requested_portfolio_id=9,
            http_status=200,
            professional_target={
                "screen_key": "execution.accounts",
                "action_key": "account.portfolio-recorded-facts",
            },
        )
        queue = _queue_payload()
        queue.pop("outcome")
        queue_result = project_today_focus_queue_payload(
            queue,
            requested_account_id=7,
            http_status=200,
            professional_target={
                "screen_key": "command-center.decision-flow",
                "action_key": "decision.workspace.summary",
            },
        )
        for result, params in ((facts_result, {"pk": 9}), (queue_result, {"account_id": 7})):
            self.assertEqual(result["kind"], "detail")
            self.assertNotIn("outcome", result)
            self.assertIn("不能据此判断完整性", result["business_summary"])
            self.assertEqual(result["next_steps"][0]["params"], params)

    def test_primary_fields_show_market_restrictions_and_first_queue_item(self) -> None:
        """A user sees useful facts before opening optional long sections."""

        market = project_today_focus_market_context_payload(_market_payload(), http_status=200)
        market_text = str(market["fields"])
        for value in ("宏观象限", "未知", "已过期", "不可用于决策", "2026-10-17"):
            self.assertIn(value, market_text)
        queue = project_today_focus_queue_payload(
            _queue_payload(), requested_account_id=7, http_status=200
        )
        queue_text = str(queue["fields"])
        self.assertIn("审批执行：600000.SH", queue_text)
        self.assertIn("审批执行", queue_text)
        self.assertIn("待处理", queue_text)

    def test_restricted_market_row_after_preview_keeps_its_owner_reason_in_first_layer(
        self,
    ) -> None:
        """A fifth-row decision restriction cannot be hidden inside optional evidence."""

        payload: dict[str, object] = {
            "total": 6,
            "rows": [
                {
                    "area": f"范围 {number}",
                    "status": "missing",
                    "must_not_use_for_decision": number == 5,
                    "blocking_reason": "SOURCE_OBSERVATION_MISSING_5" if number == 5 else None,
                }
                for number in range(1, 7)
            ],
        }
        result = project_today_focus_market_context_payload(payload, http_status=200)
        self.assertEqual(result["kind"], "detail")
        self.assertIn("范围 5", result["business_summary"])
        self.assertIn("SOURCE_OBSERVATION_MISSING_5", result["business_summary"])
        self.assertIn("不可用于决策", result["business_summary"])
        self.assertNotIn("outcome", result)
        self.assertEqual(len(result["sections"][0]["rows"]), 6)


if __name__ == "__main__":
    unittest.main()
