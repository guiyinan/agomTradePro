from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from apps.dashboard.application import query_services
from apps.dashboard.application.query_services import (
    build_auto_advisor_console_payload,
    build_auto_advisor_query_payload,
    build_auto_advisor_weekly_report_payload,
)


class FakeSheetProvider:
    def __init__(self, sheet):
        self.sheet = sheet

    def get_sheet(self, *, account_id: str, user):
        return self.sheet


class FakePerformanceProvider:
    def __init__(self, rows=None):
        self.rows = rows or []

    def get_history(self, *, account_id: str, user, days: int):
        return list(self.rows)


def test_auto_advisor_console_summarizes_today_tradeability_and_alerts(monkeypatch):
    monkeypatch.setattr(
        query_services,
        "_current_regime_payload",
        lambda: {
            "status": "ok",
            "current": "Recovery",
            "confidence": 0.8,
            "distribution": {"Recovery": 1.0},
        },
    )

    payload = build_auto_advisor_console_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        sheet_provider=FakeSheetProvider(
            {
                "account": {"account_id": "1", "account_name": "Growth"},
                "generated_at": "2026-06-30T09:30:00+08:00",
                "today_conclusion": "REVIEW",
                "order_summary": {"total": 2, "actionable": 2, "blocked": 0},
                "risk_summary": {
                    "top_position_weight": 0.32,
                    "overweight_positions": ["AAA"],
                    "blocker_count": 0,
                    "warning_count": 1,
                    "exposure_alerts": [
                        {"asset_code": "BBB", "message": "Technology exposure high"}
                    ],
                },
                "data_health": {
                    "status": "warning",
                    "must_not_use_for_decision": False,
                    "blocked_reasons": [],
                    "quotes": {"AAA": {"status": "fresh"}},
                },
                "exposure_summary": {
                    "alerts": [
                        {"asset_code": "BBB", "message": "Technology exposure high"}
                    ]
                },
                "decision_cards": [{"asset_code": "AAA", "action": "REDUCE"}],
                "order_intents": [{"asset_code": "AAA", "side": "REDUCE"}],
                "blockers": [],
                "warnings": ["data_health:valuation stale"],
                "execution_plan": {
                    "execution_mode": "real_confirm_only",
                    "confirmation_status": "PENDING",
                    "requires_human_confirmation": True,
                    "broker_execution_enabled": False,
                    "orders_count": 2,
                },
                "next_actions": [{"key": "review", "label": "复核", "hint": "确认执行"}],
            }
        ),
    )

    assert payload["today_tradeability"]["conclusion"] == "REVIEW"
    assert payload["today_tradeability"]["requires_review"] is True
    assert payload["macro_regime"]["current"] == "Recovery"
    assert payload["portfolio_risk"]["top_position_weight"] == 0.32
    assert payload["today_advice"]["top_decision_cards"][0]["asset_code"] == "AAA"
    assert payload["data_freshness"]["status"] == "warning"
    assert payload["execution"]["confirmation_status"] == "PENDING"
    assert payload["execution"]["broker_execution_enabled"] is False
    codes = [item["code"] for item in payload["must_handle_alerts"]]
    assert "execution_confirmation_required" in codes
    assert "exposure_alert" in codes
    assert "advisor_warning" in codes


def test_dashboard_homepage_embeds_auto_advisor_console_panel():
    template = Path("core/templates/dashboard/index.html").read_text(encoding="utf-8")

    assert "今日自动投顾主控台" in template
    assert "autoAdvisorConsole" in template
    assert "autoAdvisorAccountSelect" in template
    assert "api_dashboard:auto_advisor_console" in template
    assert "renderAutoAdvisorConsole" in template
    assert "loadAutoAdvisorConsole" in template


def test_auto_advisor_query_answers_largest_risk_from_sheet():
    payload = build_auto_advisor_query_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        question="我现在最大风险是什么",
        sheet_provider=FakeSheetProvider(_query_sheet()),
    )

    assert payload["query"]["intent"] == "largest_risk"
    assert "最大风险" in payload["answer"]
    assert payload["highlights"][0]["code"] == "top_position_weight"
    assert payload["evidence"]["risk_summary"]["top_position_weight"] == 0.32


def test_auto_advisor_query_explains_reduce_recommendations():
    payload = build_auto_advisor_query_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        question="今天为什么建议减仓",
        sheet_provider=FakeSheetProvider(_query_sheet()),
    )

    assert payload["query"]["intent"] == "reduce_reason"
    assert payload["highlights"][0]["asset_code"] == "AAA"
    assert "估值偏高" in payload["answer"]


def test_auto_advisor_query_lists_invalidated_positions():
    payload = build_auto_advisor_query_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        question="哪些持仓已经证伪",
        sheet_provider=FakeSheetProvider(_query_sheet()),
    )

    assert payload["query"]["intent"] == "invalidated_positions"
    assert payload["highlights"][0]["asset_code"] == "CCC"
    assert payload["highlights"][0]["invalidated"][0]["signal_id"] == "sig-1"


def test_auto_advisor_query_estimates_market_shock_loss():
    payload = build_auto_advisor_query_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        question="如果明天跌 3%, 组合损失多少",
        sheet_provider=FakeSheetProvider(_query_sheet()),
    )

    assert payload["query"]["intent"] == "market_shock_loss"
    assert payload["highlights"][0]["shock_percent"] == 3.0
    assert payload["highlights"][0]["estimated_loss"] == 2400.0


def test_auto_advisor_query_summarizes_unexecuted_recommendations():
    payload = build_auto_advisor_query_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        question="哪些建议我上次没执行, 结果如何",
        sheet_provider=FakeSheetProvider(_query_sheet()),
    )

    assert payload["query"]["intent"] == "unexecuted_recommendations"
    assert payload["highlights"][0]["asset_code"] == "AAA"
    assert payload["highlights"][0]["performance"]["best_available_window"]["window"] == "20d"


def test_dashboard_api_root_exposes_auto_advisor_query_endpoint():
    api_urls = Path("apps/dashboard/interface/api_urls.py").read_text(encoding="utf-8")

    assert "auto_advisor_query" in api_urls
    assert "/api/dashboard/auto-advisor-query/" in api_urls


def test_auto_advisor_weekly_report_covers_required_sections():
    payload = build_auto_advisor_weekly_report_payload(
        account_id="1",
        user=SimpleNamespace(id=7, is_authenticated=True),
        as_of=date(2026, 6, 30),
        sheet_provider=FakeSheetProvider(_query_sheet()),
        performance_provider=FakePerformanceProvider(
            [
                {
                    "date": "2026-06-29",
                    "portfolio_value": 98000.0,
                    "cash_balance": 18000.0,
                    "invested_value": 80000.0,
                    "position_count": 3,
                },
                {
                    "date": "2026-06-30",
                    "portfolio_value": 100000.0,
                    "cash_balance": 20000.0,
                    "invested_value": 80000.0,
                    "position_count": 3,
                },
            ]
        ),
    )

    assert payload["week"]["start"] == "2026-06-29"
    assert payload["portfolio_change"]["status"] == "HISTORICAL"
    assert payload["portfolio_change"]["absolute_change"] == 2000.0
    assert payload["largest_risk_exposure"]["items"][0]["code"] == "top_position_weight"
    assert payload["system_vs_actual"]["decision_count"] == 1
    assert payload["unexecuted_recommendations"]["items"][0]["asset_code"] == "AAA"
    assert payload["invalidated_recommendations"]["items"][0]["asset_code"] == "CCC"
    assert payload["investment_diary"]["status"] == "DERIVED_FROM_ADVISOR_SHEET"
    diary_entry = payload["investment_diary"]["entries"][0]
    assert diary_entry["entry_type"] == "WEEKLY_REVIEW"
    assert diary_entry["today_conclusion"] == "REVIEW"
    assert "execution_gap" in diary_entry["reflection_tags"]
    assert diary_entry["manual_note_prompts"]
    assert payload["next_week_watchlist"]


def test_dashboard_api_root_exposes_auto_advisor_weekly_report_endpoint():
    api_urls = Path("apps/dashboard/interface/api_urls.py").read_text(encoding="utf-8")

    assert "auto_advisor_weekly_report" in api_urls
    assert "/api/dashboard/auto-advisor-weekly-report/" in api_urls
    assert "auto_advisor_weekly_report_history" in api_urls
    assert "/api/dashboard/auto-advisor-weekly-report-history/" in api_urls
    assert "auto_advisor_notifications" in api_urls
    assert "/api/dashboard/auto-advisor-notifications/" in api_urls


def _query_sheet():
    return {
        "account": {
            "account_id": "1",
            "account_name": "Growth",
            "total_asset": 100000.0,
            "market_value": 80000.0,
        },
        "generated_at": "2026-06-30T09:30:00+08:00",
        "today_conclusion": "REVIEW",
        "order_summary": {"total": 2, "actionable": 1, "blocked": 1},
        "risk_summary": {
            "top_position_weight": 0.32,
            "overweight_positions": ["AAA"],
            "blocker_count": 1,
            "warning_count": 1,
            "exposure_alerts": [
                {"asset_code": "BBB", "message": "Technology exposure high"}
            ],
        },
        "data_health": {
            "status": "warning",
            "must_not_use_for_decision": False,
            "blocked_reasons": [],
        },
        "blockers": [
            {
                "type": "BLOCKED_EXECUTION_GUARD",
                "asset_code": "CCC",
                "message": "来源信号已被证伪",
            }
        ],
        "decision_cards": [
            {
                "asset_code": "AAA",
                "asset_name": "Alpha",
                "action": "REDUCE",
                "current_weight": 0.32,
                "target_weight": 0.2,
                "primary_reasons": ["估值偏高", "单票权重超限"],
                "risk_notes": ["需要人工确认"],
                "risk_gate_status": "REVIEW",
                "blocking_status": "OK",
                "tracking": {
                    "review_status": "PENDING_REVIEW",
                    "source_recommendation_ids": ["rec-1"],
                    "is_executed": False,
                    "performance": {
                        "windows": {
                            "7d": {"directional_return": None},
                            "20d": {"directional_return": -0.05},
                            "60d": {"directional_return": None},
                        },
                        "error_attribution": {
                            "status": "ATTRIBUTED",
                            "primary_category": "MODEL_MISJUDGMENT",
                        },
                    },
                },
            }
        ],
        "order_intents": [
            {
                "asset_code": "CCC",
                "asset_name": "Gamma",
                "side": "EXIT",
                "blocking_status": "BLOCKED_EXECUTION_GUARD",
                "risk_gate": {
                    "execution_guard": {
                        "checks": {
                            "signal_invalidation": {
                                "passed": False,
                                "reason": "来源信号已被证伪: sig-1",
                                "invalidated": [
                                    {
                                        "signal_id": "sig-1",
                                        "status": "invalidated",
                                        "invalidated_at": "2026-06-29T10:00:00+08:00",
                                    }
                                ],
                            }
                        }
                    }
                },
            }
        ],
        "execution_plan": {
            "confirmation_status": "PENDING",
            "requires_human_confirmation": True,
            "broker_execution_enabled": False,
        },
    }
