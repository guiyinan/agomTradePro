from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.dashboard.application.beta_market_summary import build_beta_market_summary_row
from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.sentiment.application.current_sentiment import CurrentSentimentResult
from apps.sentiment.domain.entities import SentimentIndex


def _action(*, blocked: bool = False) -> RegimeActionRecommendation:
    return RegimeActionRecommendation(
        asset_weights={"equity": 0.55, "bond": 0.35, "cash": 0.10},
        risk_budget_pct=0.60,
        position_limit_pct=0.10,
        recommended_sectors=["科技"],
        benefiting_styles=["成长"],
        hedge_recommendation=None,
        reasoning="复苏环境与脉搏共同支持适度参与。",
        regime_contribution="复苏期，权益保持中等偏上。",
        pulse_contribution="脉搏偏强（score=+0.30）。",
        generated_at=date(2026, 8, 15),
        confidence=0.78,
        must_not_use_for_decision=blocked,
        blocked_reason="pulse_snapshot_stale" if blocked else "",
        context_observed_at=date(2026, 8, 15),
    )


def _sentiment(*, stale: bool = False) -> CurrentSentimentResult:
    index = SentimentIndex(
        index_date=datetime(2026, 8, 15, tzinfo=UTC),
        news_sentiment=0.8,
        policy_sentiment=0.4,
        composite_index=0.7,
        confidence_level=0.82,
        data_sufficient=True,
    )
    return CurrentSentimentResult(
        index=None if stale else index,
        diagnostic_index=index,
        observed_at=date(2026, 8, 15),
        freshness_status="stale" if stale else "fresh",
        staleness_days=2 if stale else 0,
        must_not_use_for_decision=stale,
        blocked_reason="sentiment_index_stale" if stale else "",
    )


def test_beta_market_summary_explains_how_to_use_alpha_when_context_is_ready() -> None:
    row = build_beta_market_summary_row(
        as_of_date=date(2026, 8, 16),
        navigator=SimpleNamespace(
            regime_name="Recovery",
            confidence=0.76,
            data_freshness="fresh",
        ),
        action=_action(),
        sentiment=_sentiment(),
    )

    assert row["beta_conclusion"] == "可用于判断：权益建议 55%，风险预算 60%。"
    assert row["decision_status"] == "可用于决策"
    assert row["market_sentiment"] == "乐观"
    assert row["sentiment_index"] == 0.7
    assert row["alpha_usage"] == "可继续查看 Alpha 选股清单，并逐只核对约束与证伪条件。"
    assert row["must_not_use_for_decision"] is False


def test_beta_market_summary_blocks_action_but_preserves_stale_sentiment_diagnostics() -> None:
    row = build_beta_market_summary_row(
        as_of_date=date(2026, 8, 16),
        navigator=SimpleNamespace(
            regime_name="Recovery",
            confidence=0.76,
            data_freshness="stale",
        ),
        action=_action(blocked=True),
        sentiment=_sentiment(stale=True),
    )

    assert row["decision_status"] == "不可用于决策"
    assert row["market_sentiment"] == "乐观（仅供诊断）"
    assert row["sentiment_decision_status"] == "仅供诊断"
    assert row["sentiment_blocked_reason"] == "A股情绪指数已过期，仅供诊断。"
    assert row["alpha_usage"] == "Alpha 仅供研究，暂不形成可执行建议。"
    assert row["must_not_use_for_decision"] is True
