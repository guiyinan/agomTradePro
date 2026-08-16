"""User-facing Beta market summary for the Alpha research workflow."""

from __future__ import annotations

from datetime import date

from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.regime.domain.entities import RegimeNavigatorOutput
from core.integration.sentiment_readiness import (
    CurrentSentimentProjection,
    SentimentIndexProjection,
)

_SENTIMENT_BLOCKED_MESSAGES = {
    "sentiment_index_missing": "暂无A股情绪指数。",
    "sentiment_index_stale": "A股情绪指数已过期，仅供诊断。",
    "sentiment_data_insufficient": "A股情绪样本不足，仅供诊断。",
}

_BETA_BLOCKED_MESSAGES = {
    "navigator_unavailable": "Regime 判断尚未形成。",
    "regime_context_missing": "Regime 判断所需的市场环境数据尚未就绪。",
    "regime_context_stale": "Regime 判断所需的市场环境数据已过期。",
    "pulse_snapshot_missing": "市场脉搏数据尚未就绪。",
    "pulse_snapshot_stale": "市场脉搏数据已过期。",
    "pulse_snapshot_unreliable": "市场脉搏数据未通过可靠性校验。",
}


def _percent(value: float | None) -> float | None:
    """Convert one finite fraction to a display percentage."""

    if value is None:
        return None
    return round(float(value) * 100, 2)


def _sentiment_payload(current: CurrentSentimentProjection) -> dict[str, object]:
    """Return current or diagnostic sentiment fields without hiding staleness."""

    index: SentimentIndexProjection | None = current.index or current.diagnostic_index
    if index is None:
        return {
            "market_sentiment": "暂无数据",
            "sentiment_index": None,
            "sentiment_confidence_percent": None,
        }

    payload = index.to_dict()
    level = str(payload.get("level") or "数据不足")
    if current.must_not_use_for_decision:
        level = f"{level}（仅供诊断）"
    return {
        "market_sentiment": level,
        "sentiment_index": round(float(index.composite_index), 3),
        "sentiment_confidence_percent": _percent(index.confidence_level),
    }


def _user_blocked_reason(reason: str | None) -> str:
    """Translate stable internal blockers into user-facing decision language."""

    if not reason:
        return "关键市场数据不可用于决策。"
    mapped = _BETA_BLOCKED_MESSAGES.get(reason)
    if mapped is not None:
        return mapped
    if "_" in reason and reason.isascii():
        return "Regime 或市场脉搏数据未通过决策校验。"
    return reason


def build_beta_market_summary_row(
    *,
    as_of_date: date,
    navigator: RegimeNavigatorOutput | None,
    action: RegimeActionRecommendation | None,
    sentiment: CurrentSentimentProjection,
) -> dict[str, object]:
    """Build one readable Beta conclusion while preserving decision blockers."""

    beta_blocked = action is None or action.must_not_use_for_decision
    equity_weight = _percent(action.asset_weights.get("equity") if action is not None else None)
    risk_budget = _percent(action.risk_budget_pct if action is not None else None)
    position_limit = _percent(action.position_limit_pct if action is not None else None)

    if action is None:
        beta_conclusion = "暂不判断：Regime 与 Pulse 尚未形成联合结论。"
        beta_blocked_reason = "关键市场数据尚未就绪。"
        reasoning = "请先刷新环境与脉搏数据。"
    elif action.must_not_use_for_decision:
        beta_conclusion = "暂不判断：关键市场数据未通过新鲜度或可靠性校验。"
        beta_blocked_reason = _user_blocked_reason(action.blocked_reason)
        reasoning = action.reasoning
    else:
        weight_text = (
            f"权益建议 {equity_weight:.0f}%" if equity_weight is not None else "权益权重待确认"
        )
        risk_text = f"风险预算 {risk_budget:.0f}%" if risk_budget is not None else "风险预算待确认"
        beta_conclusion = f"可用于判断：{weight_text}，{risk_text}。"
        beta_blocked_reason = ""
        reasoning = action.reasoning

    sentiment_fields = _sentiment_payload(sentiment)
    sentiment_blocked_reason = _SENTIMENT_BLOCKED_MESSAGES.get(
        sentiment.blocked_reason,
        sentiment.blocked_reason,
    )
    return {
        "as_of_date": as_of_date.isoformat(),
        "beta_conclusion": beta_conclusion,
        "decision_status": "不可用于决策" if beta_blocked else "可用于决策",
        "regime": navigator.regime_name if navigator is not None else "未知",
        "regime_confidence_percent": (
            _percent(navigator.confidence) if navigator is not None else None
        ),
        "pulse_summary": action.pulse_contribution if action is not None else "暂无脉搏结论",
        **sentiment_fields,
        "sentiment_decision_status": (
            "仅供诊断" if sentiment.must_not_use_for_decision else "可用于判断"
        ),
        "sentiment_blocked_reason": sentiment_blocked_reason,
        "equity_weight_percent": equity_weight,
        "risk_budget_percent": risk_budget,
        "single_position_limit_percent": position_limit,
        "reasoning": reasoning,
        "alpha_usage": (
            "Alpha 仅供研究，暂不形成可执行建议。"
            if beta_blocked
            else "可继续查看 Alpha 选股清单，并逐只核对约束与证伪条件。"
        ),
        "freshness_status": (navigator.data_freshness if navigator is not None else "missing"),
        "observed_at": (
            action.context_observed_at.isoformat()
            if action is not None and action.context_observed_at is not None
            else (action.generated_at.isoformat() if action is not None else None)
        ),
        "must_not_use_for_decision": beta_blocked,
        "blocked_reason": beta_blocked_reason,
    }
