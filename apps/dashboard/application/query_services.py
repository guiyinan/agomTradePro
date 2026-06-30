"""Application-level dashboard query helpers for TUI/runtime consumers."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Protocol

from apps.dashboard.application.queries import get_alpha_homepage_query
from apps.dashboard.application.repository_provider import get_auto_advisor_report_repository


class AutoAdvisorSheetProviderProtocol(Protocol):
    """Read an account advisor sheet for dashboard console aggregation."""

    def get_sheet(self, *, account_id: str, user: Any) -> dict[str, Any]:
        """Return advisor sheet payload."""


class AutoAdvisorPerformanceProviderProtocol(Protocol):
    """Read account performance history for weekly reports."""

    def get_history(self, *, account_id: str, user: Any, days: int) -> list[dict[str, Any]]:
        """Return chart-ready performance rows."""


class DecisionRhythmAdvisorSheetProvider:
    """Advisor sheet provider backed by decision_rhythm application services."""

    def get_sheet(self, *, account_id: str, user: Any) -> dict[str, Any]:
        """Generate the current advisor sheet for one account."""

        from apps.decision_rhythm.application.advisor_services import (
            GenerateAdvisorDecisionSheetUseCase,
        )

        return GenerateAdvisorDecisionSheetUseCase().execute(account_id=account_id, user=user)


class SimulatedTradingPerformanceProvider:
    """Performance provider backed by simulated_trading application services."""

    def get_history(self, *, account_id: str, user: Any, days: int) -> list[dict[str, Any]]:
        """Return daily net-value rows for one account."""

        from apps.simulated_trading.application.query_services import (
            get_user_performance_payload,
        )

        user_id = int(getattr(user, "id", 0) or 0)
        return get_user_performance_payload(
            user_id=user_id,
            account_id=int(account_id),
            days=days,
        )


def has_dashboard_alpha_history(user: Any | None) -> bool:
    """Return whether the current user has Alpha history rows for same-screen drilldown."""

    if user is None or not bool(getattr(user, "is_authenticated", False)):
        return False
    return bool(get_alpha_homepage_query().list_history(user_id=int(user.id)))


def build_auto_advisor_console_payload(
    *,
    account_id: str,
    user: Any,
    sheet_provider: AutoAdvisorSheetProviderProtocol | None = None,
) -> dict[str, Any]:
    """Build the homepage auto-advisor console payload from the advisor sheet."""

    provider = sheet_provider or DecisionRhythmAdvisorSheetProvider()
    sheet = provider.get_sheet(account_id=account_id, user=user)
    order_summary = dict(sheet.get("order_summary") or {})
    risk_summary = dict(sheet.get("risk_summary") or {})
    execution_plan = dict(sheet.get("execution_plan") or {})
    data_health = dict(sheet.get("data_health") or {})
    blockers = list(sheet.get("blockers") or [])
    warnings = list(sheet.get("warnings") or [])
    decision_cards = list(sheet.get("decision_cards") or [])
    exposure_summary = dict(sheet.get("exposure_summary") or {})
    alerts = _auto_advisor_console_alerts(
        blockers=blockers,
        warnings=warnings,
        execution_plan=execution_plan,
        data_health=data_health,
        exposure_summary=exposure_summary,
    )

    return {
        "status": "ok",
        "account": sheet.get("account") or {},
        "generated_at": sheet.get("generated_at"),
        "today_tradeability": {
            "conclusion": sheet.get("today_conclusion"),
            "can_trade": sheet.get("today_conclusion") == "ACT",
            "requires_review": sheet.get("today_conclusion") == "REVIEW",
            "blocked": sheet.get("today_conclusion") == "BLOCKED",
            "actionable_order_count": order_summary.get("actionable", 0),
            "blocked_order_count": order_summary.get("blocked", 0),
        },
        "macro_regime": _current_regime_payload(),
        "portfolio_risk": {
            "top_position_weight": risk_summary.get("top_position_weight"),
            "overweight_positions": risk_summary.get("overweight_positions", []),
            "exposure_alerts": risk_summary.get("exposure_alerts", []),
            "blocker_count": risk_summary.get("blocker_count", 0),
            "warning_count": risk_summary.get("warning_count", 0),
        },
        "today_advice": {
            "order_summary": order_summary,
            "top_decision_cards": decision_cards[:5],
            "order_intents": list(sheet.get("order_intents") or [])[:5],
        },
        "must_handle_alerts": alerts,
        "data_freshness": {
            "status": data_health.get("status"),
            "must_not_use_for_decision": bool(data_health.get("must_not_use_for_decision")),
            "blocked_reasons": list(data_health.get("blocked_reasons") or []),
            "quote_count": len(data_health.get("quotes") or {}),
        },
        "execution": {
            "execution_mode": execution_plan.get("execution_mode"),
            "confirmation_status": execution_plan.get("confirmation_status"),
            "requires_human_confirmation": bool(
                execution_plan.get("requires_human_confirmation")
            ),
            "broker_execution_enabled": bool(
                execution_plan.get("broker_execution_enabled")
            ),
            "orders_count": execution_plan.get("orders_count", 0),
        },
        "next_actions": list(sheet.get("next_actions") or [])[:5],
    }


def build_auto_advisor_query_payload(
    *,
    account_id: str,
    user: Any,
    question: str,
    sheet_provider: AutoAdvisorSheetProviderProtocol | None = None,
) -> dict[str, Any]:
    """Answer common personal auto-advisor questions from the advisor sheet."""

    normalized_question = " ".join(str(question or "").strip().split())
    if not normalized_question:
        raise ValueError("question is required")

    provider = sheet_provider or DecisionRhythmAdvisorSheetProvider()
    sheet = provider.get_sheet(account_id=account_id, user=user)
    intent = _detect_auto_advisor_query_intent(normalized_question)
    response = _answer_auto_advisor_query(intent=intent, question=normalized_question, sheet=sheet)
    return {
        "status": "ok",
        "account": sheet.get("account") or {},
        "generated_at": sheet.get("generated_at"),
        "query": {
            "question": normalized_question,
            "intent": intent,
            "supported_intents": [
                "largest_risk",
                "reduce_reason",
                "invalidated_positions",
                "market_shock_loss",
                "unexecuted_recommendations",
                "overview",
            ],
        },
        "answer": response["answer"],
        "highlights": response["highlights"],
        "evidence": response["evidence"],
    }


def build_auto_advisor_weekly_report_payload(
    *,
    account_id: str,
    user: Any,
    as_of: date | None = None,
    sheet_provider: AutoAdvisorSheetProviderProtocol | None = None,
    performance_provider: AutoAdvisorPerformanceProviderProtocol | None = None,
) -> dict[str, Any]:
    """Build a personal weekly auto-advisor report from the advisor sheet."""

    report_date = as_of or date.today()
    provider = sheet_provider or DecisionRhythmAdvisorSheetProvider()
    sheet = provider.get_sheet(account_id=account_id, user=user)
    perf_provider = performance_provider or SimulatedTradingPerformanceProvider()
    performance_history = perf_provider.get_history(
        account_id=account_id,
        user=user,
        days=14,
    )
    week_start = report_date - timedelta(days=report_date.weekday())
    week_end = week_start + timedelta(days=6)
    invalidated = _answer_invalidated_positions(sheet)
    unexecuted = _answer_unexecuted_recommendations(sheet)
    largest_risk = _answer_largest_risk(sheet)

    return {
        "status": "ok",
        "account": sheet.get("account") or {},
        "generated_at": sheet.get("generated_at"),
        "week": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
            "as_of": report_date.isoformat(),
        },
        "portfolio_change": _weekly_portfolio_change_section(
            sheet=sheet,
            performance_history=performance_history,
            week_start=week_start,
            report_date=report_date,
        ),
        "largest_risk_exposure": {
            "summary": largest_risk["answer"],
            "items": largest_risk["highlights"],
        },
        "system_vs_actual": _weekly_system_vs_actual_section(sheet),
        "unexecuted_recommendations": {
            "summary": unexecuted["answer"],
            "items": unexecuted["highlights"],
        },
        "invalidated_recommendations": {
            "summary": invalidated["answer"],
            "items": invalidated["highlights"],
        },
        "investment_diary": _weekly_investment_diary_section(
            sheet=sheet,
            report_date=report_date,
            largest_risk=largest_risk,
            unexecuted=unexecuted,
            invalidated=invalidated,
        ),
        "next_week_watchlist": _weekly_next_watchlist_section(sheet),
        "evidence": {
            "today_conclusion": sheet.get("today_conclusion"),
            "order_summary": sheet.get("order_summary") or {},
            "data_health": sheet.get("data_health") or {},
            "execution_plan": sheet.get("execution_plan") or {},
        },
    }


def build_auto_advisor_weekly_report_history_payload(
    *,
    user: Any,
    account_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return persisted auto-advisor weekly reports for dashboard/CLI output."""

    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        raise ValueError("authenticated user is required")
    normalized_account_id = int(account_id) if account_id not in {None, ""} else None
    bounded_limit = max(1, min(int(limit or 20), 100))
    reports = get_auto_advisor_report_repository().list_recent_reports(
        user_id=user_id,
        account_id=normalized_account_id,
        limit=bounded_limit,
    )
    return {
        "status": "ok",
        "count": len(reports),
        "reports": reports,
    }


def build_auto_advisor_notifications_payload(
    *,
    user: Any,
    account_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return stored auto-advisor notification/output items."""

    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        raise ValueError("authenticated user is required")
    normalized_account_id = int(account_id) if account_id not in {None, ""} else None
    bounded_limit = max(1, min(int(limit or 20), 100))
    notifications = get_auto_advisor_report_repository().list_recent_notifications(
        user_id=user_id,
        account_id=normalized_account_id,
        limit=bounded_limit,
    )
    return {
        "status": "ok",
        "count": len(notifications),
        "notifications": notifications,
    }


def _auto_advisor_console_alerts(
    *,
    blockers: list[dict[str, Any]],
    warnings: list[str],
    execution_plan: dict[str, Any],
    data_health: dict[str, Any],
    exposure_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    alerts.extend(
        {
            "level": "blocker",
            "code": str(blocker.get("type") or "blocking_order"),
            "asset_code": blocker.get("asset_code"),
            "message": str(blocker.get("message") or ""),
        }
        for blocker in blockers[:10]
    )
    if data_health.get("must_not_use_for_decision"):
        alerts.append(
            {
                "level": "blocker",
                "code": "data_not_decision_grade",
                "message": "数据健康状态不允许直接决策。",
            }
        )
    if execution_plan.get("requires_human_confirmation"):
        alerts.append(
            {
                "level": "review",
                "code": "execution_confirmation_required",
                "message": "存在需要人工确认的执行计划。",
            }
        )
    alerts.extend(
        {
            "level": "review",
            "code": "exposure_alert",
            "asset_code": alert.get("asset_code"),
            "message": str(alert.get("message") or ""),
        }
        for alert in (exposure_summary.get("alerts") or [])[:10]
    )
    alerts.extend(
        {"level": "warning", "code": "advisor_warning", "message": warning}
        for warning in warnings[:10]
    )
    return alerts


def _detect_auto_advisor_query_intent(question: str) -> str:
    text = question.lower()
    if any(token in text for token in ("最大风险", "风险是什么", "风险暴露", "主要风险")):
        return "largest_risk"
    if any(token in text for token in ("为什么建议减仓", "为什么减仓", "减仓原因", "建议减仓")):
        return "reduce_reason"
    if "证伪" in text:
        return "invalidated_positions"
    if (
        any(token in text for token in ("跌", "下跌", "回撤", "下挫"))
        and any(token in text for token in ("损失", "亏", "影响", "亏损"))
    ):
        return "market_shock_loss"
    if any(token in text for token in ("没执行", "未执行", "没有执行", "上次没", "漏执行")):
        return "unexecuted_recommendations"
    return "overview"


def _answer_auto_advisor_query(
    *,
    intent: str,
    question: str,
    sheet: dict[str, Any],
) -> dict[str, Any]:
    if intent == "largest_risk":
        return _answer_largest_risk(sheet)
    if intent == "reduce_reason":
        return _answer_reduce_reason(sheet)
    if intent == "invalidated_positions":
        return _answer_invalidated_positions(sheet)
    if intent == "market_shock_loss":
        return _answer_market_shock_loss(sheet=sheet, question=question)
    if intent == "unexecuted_recommendations":
        return _answer_unexecuted_recommendations(sheet)
    return _answer_auto_advisor_overview(sheet)


def _answer_largest_risk(sheet: dict[str, Any]) -> dict[str, Any]:
    risk_summary = dict(sheet.get("risk_summary") or {})
    data_health = dict(sheet.get("data_health") or {})
    blockers = list(sheet.get("blockers") or [])
    top_weight = _optional_float(risk_summary.get("top_position_weight"))
    overweight_positions = list(risk_summary.get("overweight_positions") or [])
    exposure_alerts = list(risk_summary.get("exposure_alerts") or [])
    highlights: list[dict[str, Any]] = []

    if top_weight is not None:
        highlights.append(
            {
                "code": "top_position_weight",
                "message": f"最大单一持仓权重约 {_format_percent(top_weight)}。",
                "value": top_weight,
            }
        )
    if overweight_positions:
        highlights.append(
            {
                "code": "overweight_positions",
                "message": "存在超配持仓: " + ", ".join(map(str, overweight_positions[:5])),
                "assets": overweight_positions[:10],
            }
        )
    highlights.extend(
        {
            "code": "exposure_alert",
            "asset_code": alert.get("asset_code"),
            "message": str(alert.get("message") or "组合暴露需要复核。"),
        }
        for alert in exposure_alerts[:5]
    )
    highlights.extend(
        {
            "code": str(blocker.get("type") or "blocking_order"),
            "asset_code": blocker.get("asset_code"),
            "message": str(blocker.get("message") or "存在阻断项。"),
        }
        for blocker in blockers[:5]
    )
    if data_health.get("must_not_use_for_decision"):
        highlights.append(
            {
                "code": "data_health_blocked",
                "message": "数据健康状态不允许直接决策。",
                "blocked_reasons": list(data_health.get("blocked_reasons") or []),
            }
        )

    if highlights:
        answer = "当前最大风险优先看: " + "；".join(
            item["message"] for item in highlights[:3] if item.get("message")
        )
    else:
        answer = "当前建议单没有识别到明确硬风险，仍需复核数据 freshness 和组合暴露。"

    return {
        "answer": answer,
        "highlights": highlights,
        "evidence": {
            "risk_summary": risk_summary,
            "data_health_status": data_health.get("status"),
            "today_conclusion": sheet.get("today_conclusion"),
        },
    }


def _answer_reduce_reason(sheet: dict[str, Any]) -> dict[str, Any]:
    reduce_items = [
        item
        for item in _advisor_query_items(sheet)
        if _item_action(item) == "REDUCE"
    ]
    highlights = [
        {
            "asset_code": item.get("asset_code"),
            "asset_name": item.get("asset_name"),
            "current_weight": item.get("current_weight"),
            "target_weight": item.get("target_weight"),
            "risk_gate_status": item.get("risk_gate_status"),
            "blocking_status": item.get("blocking_status"),
            "reasons": _item_reasons(item),
            "risk_notes": list(item.get("risk_notes") or []),
        }
        for item in reduce_items[:10]
    ]
    if not highlights:
        answer = "今天没有识别到 REDUCE 减仓建议。"
    else:
        first = highlights[0]
        reason = "；".join(first["reasons"][:2]) or "组合规则要求降低风险暴露。"
        answer = (
            f"今天共有 {len(reduce_items)} 条减仓建议。"
            f"首要标的是 {_asset_label(first)}，原因是 {reason}"
        )
    return {
        "answer": answer,
        "highlights": highlights,
        "evidence": {
            "order_summary": sheet.get("order_summary") or {},
            "today_conclusion": sheet.get("today_conclusion"),
        },
    }


def _answer_invalidated_positions(sheet: dict[str, Any]) -> dict[str, Any]:
    invalidated: list[dict[str, Any]] = []
    order_items = [dict(item) for item in list(sheet.get("order_intents") or [])]
    for item in order_items:
        signal_check = (
            ((item.get("risk_gate") or {}).get("execution_guard") or {})
            .get("checks", {})
            .get("signal_invalidation", {})
        )
        invalidated_signals = list(signal_check.get("invalidated") or [])
        if invalidated_signals or signal_check.get("passed") is False:
            invalidated.append(
                {
                    "asset_code": item.get("asset_code"),
                    "asset_name": item.get("asset_name"),
                    "action": _item_action(item),
                    "reason": signal_check.get("reason") or "来源信号证伪检查未通过。",
                    "invalidated": invalidated_signals,
                    "blocking_status": item.get("blocking_status"),
                }
            )

    if not invalidated:
        answer = "当前建议单没有发现来源信号已证伪的持仓或建议。"
    else:
        answer = "已证伪或证伪检查失败的标的: " + ", ".join(
            _asset_label(item) for item in invalidated[:5]
        )
    return {
        "answer": answer,
        "highlights": invalidated[:10],
        "evidence": {"checked_order_count": len(order_items)},
    }


def _answer_market_shock_loss(*, sheet: dict[str, Any], question: str) -> dict[str, Any]:
    shock_pct = _extract_percent(question, default=3.0)
    account = dict(sheet.get("account") or {})
    market_value = _optional_float(account.get("market_value"))
    total_asset = _optional_float(account.get("total_asset"))
    if market_value is None:
        market_value = sum(
            _optional_float(item.get("market_value")) or 0.0
            for item in list(sheet.get("holdings") or [])
        )
    if not market_value:
        return {
            "answer": "当前建议单缺少持仓市值，无法估算下跌冲击损失。",
            "highlights": [],
            "evidence": {"account": account},
        }

    estimated_loss = market_value * shock_pct / 100.0
    exposure_ratio = market_value / total_asset if total_asset else None
    answer = (
        f"按持仓市值线性估算，组合若整体下跌 {_format_percent(shock_pct / 100.0)}，"
        f"账面损失约 {_format_money(estimated_loss)}。"
    )
    return {
        "answer": answer,
        "highlights": [
            {
                "code": "linear_market_shock",
                "shock_percent": shock_pct,
                "market_value": market_value,
                "estimated_loss": round(estimated_loss, 2),
                "exposure_ratio": exposure_ratio,
                "message": "该估算未纳入个股 beta、对冲、流动性和隔夜跳空。",
            }
        ],
        "evidence": {"account": account},
    }


def _answer_unexecuted_recommendations(sheet: dict[str, Any]) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    for item in _advisor_query_items(sheet):
        tracking = dict(item.get("tracking") or {})
        if tracking.get("is_executed") or tracking.get("review_status") == "EXECUTED":
            continue
        source_ids = list(tracking.get("source_recommendation_ids") or [])
        if not source_ids:
            continue
        pending.append(
            {
                "asset_code": item.get("asset_code"),
                "asset_name": item.get("asset_name"),
                "action": _item_action(item),
                "review_status": tracking.get("review_status"),
                "source_recommendation_ids": source_ids,
                "performance": _tracking_performance_summary(tracking),
            }
        )

    if not pending:
        answer = "当前建议单没有可追踪的未执行来源建议。"
    else:
        answer = "未执行或待复核的来源建议包括: " + ", ".join(
            _asset_label(item) for item in pending[:5]
        )
    return {
        "answer": answer,
        "highlights": pending[:10],
        "evidence": {"tracked_order_count": len(_advisor_query_items(sheet))},
    }


def _answer_auto_advisor_overview(sheet: dict[str, Any]) -> dict[str, Any]:
    order_summary = dict(sheet.get("order_summary") or {})
    execution_plan = dict(sheet.get("execution_plan") or {})
    answer = (
        f"今日结论是 {sheet.get('today_conclusion') or 'UNKNOWN'}，"
        f"可行动订单 {order_summary.get('actionable', 0)} 条，"
        f"阻断订单 {order_summary.get('blocked', 0)} 条，"
        f"确认状态 {execution_plan.get('confirmation_status') or '-'}。"
    )
    return {
        "answer": answer,
        "highlights": list(sheet.get("decision_cards") or [])[:5],
        "evidence": {
            "order_summary": order_summary,
            "execution_plan": execution_plan,
            "data_health": sheet.get("data_health") or {},
        },
    }


def _weekly_portfolio_change_section(
    *,
    sheet: dict[str, Any],
    performance_history: list[dict[str, Any]],
    week_start: date,
    report_date: date,
) -> dict[str, Any]:
    account = dict(sheet.get("account") or {})
    allocation = list(sheet.get("allocation") or [])
    historical = _weekly_portfolio_change_from_history(
        performance_history=performance_history,
        week_start=week_start,
        report_date=report_date,
    )
    if historical is not None:
        historical["allocation"] = allocation
        return historical
    return {
        "status": "CURRENT_SNAPSHOT_ONLY",
        "message": "当前周报首版使用 advisor sheet 当前快照；历史周初资产变化待接入账户净值序列。",
        "total_asset": account.get("total_asset"),
        "market_value": account.get("market_value"),
        "available_cash": account.get("available_cash") or account.get("cash"),
        "holding_count": account.get("holding_count"),
        "allocation": allocation,
    }


def _weekly_portfolio_change_from_history(
    *,
    performance_history: list[dict[str, Any]],
    week_start: date,
    report_date: date,
) -> dict[str, Any] | None:
    rows = [
        (parsed, dict(row))
        for row in performance_history
        if (parsed := _date_from_text(row.get("date"))) is not None
    ]
    rows = [
        (row_date, row)
        for row_date, row in sorted(rows, key=lambda item: item[0])
        if week_start <= row_date <= report_date
    ]
    if len(rows) < 2:
        return None

    start_date, start_row = rows[0]
    end_date, end_row = rows[-1]
    start_value = _optional_float(start_row.get("portfolio_value"))
    end_value = _optional_float(end_row.get("portfolio_value"))
    if start_value is None or end_value is None or start_value <= 0:
        return None
    absolute_change = end_value - start_value
    change_pct = absolute_change / start_value
    return {
        "status": "HISTORICAL",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_value": start_value,
        "end_value": end_value,
        "absolute_change": round(absolute_change, 2),
        "change_pct": round(change_pct, 6),
        "cash_balance": end_row.get("cash_balance"),
        "invested_value": end_row.get("invested_value"),
        "position_count": end_row.get("position_count"),
        "history_points": len(rows),
    }


def _weekly_system_vs_actual_section(sheet: dict[str, Any]) -> dict[str, Any]:
    items = _advisor_query_items(sheet)
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for item in items:
        action = _item_action(item) or "UNKNOWN"
        action_counts[action] = action_counts.get(action, 0) + 1
        tracking = dict(item.get("tracking") or {})
        review_status = str(tracking.get("review_status") or "UNKNOWN")
        status_counts[review_status] = status_counts.get(review_status, 0) + 1
    execution = dict(sheet.get("execution_plan") or {})
    return {
        "summary": (
            f"系统本周建议 {len(items)} 条，"
            f"已执行 {status_counts.get('EXECUTED', 0)} 条，"
            f"待复核 {status_counts.get('PENDING_REVIEW', 0)} 条。"
        ),
        "decision_count": len(items),
        "action_counts": action_counts,
        "review_status_counts": status_counts,
        "execution": {
            "mode": execution.get("execution_mode"),
            "confirmation_status": execution.get("confirmation_status"),
            "requires_human_confirmation": bool(
                execution.get("requires_human_confirmation")
            ),
            "broker_execution_enabled": bool(execution.get("broker_execution_enabled")),
        },
    }


def _weekly_next_watchlist_section(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    watchlist: list[dict[str, Any]] = []
    data_health = dict(sheet.get("data_health") or {})
    if data_health.get("must_not_use_for_decision") or data_health.get("status") in {
        "warning",
        "blocked",
    }:
        watchlist.append(
            {
                "type": "data_health",
                "priority": "high",
                "message": "下周先复核数据 freshness 和阻断原因。",
                "evidence": {
                    "status": data_health.get("status"),
                    "blocked_reasons": list(data_health.get("blocked_reasons") or []),
                },
            }
        )
    watchlist.extend(
        {
            "type": "blocked_order",
            "priority": "high",
            "asset_code": blocker.get("asset_code"),
            "message": str(blocker.get("message") or "复核阻断订单。"),
            "code": str(blocker.get("type") or "blocking_order"),
        }
        for blocker in list(sheet.get("blockers") or [])[:5]
    )
    for item in _advisor_query_items(sheet)[:5]:
        if item.get("blocking_status") != "OK" or item.get("risk_gate_status") == "REVIEW":
            watchlist.append(
                {
                    "type": "decision_card",
                    "priority": "medium",
                    "asset_code": item.get("asset_code"),
                    "message": "下周继续观察或复核该建议。",
                    "action": _item_action(item),
                    "risk_gate_status": item.get("risk_gate_status"),
                    "blocking_status": item.get("blocking_status"),
                }
            )
    return watchlist[:10]


def _weekly_investment_diary_section(
    *,
    sheet: dict[str, Any],
    report_date: date,
    largest_risk: dict[str, Any],
    unexecuted: dict[str, Any],
    invalidated: dict[str, Any],
) -> dict[str, Any]:
    account = dict(sheet.get("account") or {})
    execution = dict(sheet.get("execution_plan") or {})
    data_health = dict(sheet.get("data_health") or {})
    items = _advisor_query_items(sheet)
    action_counts: dict[str, int] = {}
    for item in items:
        action = _item_action(item) or "UNKNOWN"
        action_counts[action] = action_counts.get(action, 0) + 1

    blockers = list(sheet.get("blockers") or [])
    reflection_tags = _weekly_diary_reflection_tags(
        sheet=sheet,
        largest_risk=largest_risk,
        unexecuted=unexecuted,
        invalidated=invalidated,
    )
    entry = {
        "entry_date": report_date.isoformat(),
        "entry_type": "WEEKLY_REVIEW",
        "account_id": account.get("account_id") or account.get("id"),
        "account_name": account.get("account_name") or account.get("name"),
        "today_conclusion": sheet.get("today_conclusion"),
        "decision_count": len(items),
        "action_counts": action_counts,
        "largest_risk_summary": largest_risk.get("answer"),
        "unexecuted_summary": unexecuted.get("answer"),
        "invalidated_summary": invalidated.get("answer"),
        "confirmation_status": execution.get("confirmation_status"),
        "requires_human_confirmation": bool(execution.get("requires_human_confirmation")),
        "data_health_status": data_health.get("status"),
        "blocked_order_count": len(blockers),
        "reflection_tags": reflection_tags,
        "lessons": _weekly_diary_lessons(
            largest_risk=largest_risk,
            unexecuted=unexecuted,
            invalidated=invalidated,
            blockers=blockers,
            execution=execution,
            data_health=data_health,
        ),
        "manual_note_prompts": [
            "本周我是否按系统建议执行，原因是什么？",
            "哪些风险是我主观忽略或高估的？",
            "下周若同类信号再次出现，我会如何调整仓位？",
        ],
        "evidence": {
            "order_summary": sheet.get("order_summary") or {},
            "execution_plan": execution,
            "data_health": data_health,
        },
    }
    return {
        "status": "DERIVED_FROM_ADVISOR_SHEET",
        "persistence": "not_persisted",
        "summary": (
            f"{report_date.isoformat()} 生成 1 条投资日记，"
            f"结论 {sheet.get('today_conclusion') or '-'}，"
            f"待人工确认 {bool(execution.get('requires_human_confirmation'))}。"
        ),
        "entries": [entry],
    }


def _weekly_diary_reflection_tags(
    *,
    sheet: dict[str, Any],
    largest_risk: dict[str, Any],
    unexecuted: dict[str, Any],
    invalidated: dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    if largest_risk.get("highlights"):
        tags.append("risk_review")
    if unexecuted.get("highlights"):
        tags.append("execution_gap")
    if invalidated.get("highlights"):
        tags.append("invalidation_review")
    if list(sheet.get("blockers") or []):
        tags.append("blocked_decision")
    if dict(sheet.get("execution_plan") or {}).get("requires_human_confirmation"):
        tags.append("manual_confirmation")
    return tags or ["routine_review"]


def _weekly_diary_lessons(
    *,
    largest_risk: dict[str, Any],
    unexecuted: dict[str, Any],
    invalidated: dict[str, Any],
    blockers: list[Any],
    execution: dict[str, Any],
    data_health: dict[str, Any],
) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    if largest_risk.get("highlights"):
        lessons.append(
            {
                "code": "largest_risk_review",
                "message": largest_risk.get("answer"),
            }
        )
    if unexecuted.get("highlights"):
        lessons.append(
            {
                "code": "unexecuted_recommendation_review",
                "message": unexecuted.get("answer"),
            }
        )
    if invalidated.get("highlights"):
        lessons.append(
            {
                "code": "invalidated_signal_review",
                "message": invalidated.get("answer"),
            }
        )
    if blockers:
        lessons.append(
            {
                "code": "blocked_order_review",
                "message": f"存在 {len(blockers)} 条阻断项，下次执行前先处理阻断原因。",
            }
        )
    if execution.get("requires_human_confirmation"):
        lessons.append(
            {
                "code": "confirmation_review",
                "message": "本周建议仍需人工确认，实际交易前必须记录确认原因。",
            }
        )
    if data_health.get("status") not in {None, "", "ok"}:
        lessons.append(
            {
                "code": "data_health_review",
                "message": "数据 freshness 非正常，复盘时优先确认数据是否影响判断。",
            }
        )
    return lessons[:8]


def _advisor_query_items(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    cards = [dict(item) for item in list(sheet.get("decision_cards") or [])]
    if cards:
        return cards
    return [dict(item) for item in list(sheet.get("order_intents") or [])]


def _item_action(item: dict[str, Any]) -> str:
    return str(item.get("action") or item.get("side") or "").upper()


def _item_reasons(item: dict[str, Any]) -> list[str]:
    reasons = list(item.get("primary_reasons") or [])
    if not reasons and item.get("reason"):
        reasons = [str(item.get("reason"))]
    return [str(reason) for reason in reasons if str(reason).strip()]


def _asset_label(item: dict[str, Any]) -> str:
    asset_code = str(item.get("asset_code") or "-")
    asset_name = str(item.get("asset_name") or "").strip()
    return f"{asset_name}({asset_code})" if asset_name else asset_code


def _extract_percent(question: str, *, default: float) -> float:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%?", question)
    if not matches:
        return default
    try:
        return float(matches[0])
    except ValueError:
        return default


def _tracking_performance_summary(tracking: dict[str, Any]) -> dict[str, Any]:
    performance = dict(tracking.get("performance") or {})
    windows = dict(performance.get("windows") or {})
    best_window: dict[str, Any] = {}
    for key in ("60d", "20d", "7d"):
        window = dict(windows.get(key) or {})
        if window.get("directional_return") is not None:
            best_window = {"window": key, **window}
            break
    return {
        "status": performance.get("status"),
        "best_available_window": best_window,
        "error_attribution": performance.get("error_attribution") or {},
    }


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_text(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_money(value: float) -> str:
    return f"{value:,.2f}"


def _current_regime_payload() -> dict[str, Any]:
    try:
        from apps.regime.application.current_regime import resolve_current_regime

        current = resolve_current_regime(date.today())
        return {
            "status": "ok",
            "current": getattr(current, "dominant_regime", None),
            "confidence": getattr(current, "confidence", None),
            "distribution": getattr(current, "distribution", None),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "current": None,
            "confidence": None,
            "distribution": {},
            "reason": str(exc),
        }
