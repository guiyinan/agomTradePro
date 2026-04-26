"""Application-facing orchestration helpers for fund interface views."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.fund.application.services import FundMultiDimScorer
from apps.fund.application.use_cases import (
    AnalyzeFundStyleRequest,
    AnalyzeFundStyleUseCase,
    CalculateFundPerformanceRequest,
    CalculateFundPerformanceUseCase,
    RankFundsUseCase,
    ScreenFundsRequest,
    ScreenFundsUseCase,
)
from apps.fund.infrastructure.providers import DjangoFundAssetRepository, DjangoFundRepository
from apps.policy.application.repository_provider import get_current_policy_repository
from apps.regime.application.current_regime import resolve_current_regime
from apps.sentiment.application.repository_provider import get_sentiment_index_repository
from apps.signal.application.repository_provider import get_signal_repository


def build_dashboard_context() -> dict[str, Any]:
    """Build the fund dashboard HTML context."""

    latest_regime = resolve_current_regime(as_of_date=date.today())
    latest_policy = get_current_policy_repository().get_current_policy_level()
    latest_sentiment = get_sentiment_index_repository().get_latest()
    active_signals = get_signal_repository().get_active_signals()

    regime_display = {
        "Recovery": "复苏",
        "Overheat": "过热",
        "Stagflation": "滞胀",
        "Deflation": "通缩",
    }
    policy_display = {
        "P0": "P0（极度宽松）",
        "P1": "P1（宽松）",
        "P2": "P2（收紧）",
        "P3": "P3（极度收紧）",
    }

    sentiment_level = "中性"
    if latest_sentiment:
        idx = latest_sentiment.composite_index
        if idx >= 1.5:
            sentiment_level = "极度乐观"
        elif idx >= 0.5:
            sentiment_level = "乐观"
        elif idx <= -1.5:
            sentiment_level = "极度悲观"
        elif idx <= -0.5:
            sentiment_level = "悲观"

    return {
        "current_regime": latest_regime.dominant_regime if latest_regime else "Unknown",
        "regime_display": (
            regime_display.get(latest_regime.dominant_regime) if latest_regime else "未知"
        ),
        "regime_confidence": f"{latest_regime.confidence:.1%}" if latest_regime else "N/A",
        "current_policy": latest_policy.value if latest_policy else "P1",
        "policy_display": (
            policy_display.get(latest_policy.value) if latest_policy else "P1（宽松）"
        ),
        "sentiment_index": (
            f"{latest_sentiment.composite_index:.2f}" if latest_sentiment else "0.00"
        ),
        "sentiment_level": sentiment_level,
        "sentiment_date": (
            latest_sentiment.index_date.strftime("%Y-%m-%d") if latest_sentiment else "-"
        ),
        "active_signals_count": len(active_signals),
    }


def screen_funds(screen_request: ScreenFundsRequest):
    """Execute fund screening."""

    return ScreenFundsUseCase(DjangoFundRepository()).execute(screen_request)


def analyze_fund_style(analyze_request: AnalyzeFundStyleRequest):
    """Execute fund style analysis."""

    return AnalyzeFundStyleUseCase(DjangoFundRepository()).execute(analyze_request)


def calculate_fund_performance(perf_request: CalculateFundPerformanceRequest):
    """Execute fund performance calculation."""

    return CalculateFundPerformanceUseCase(DjangoFundRepository()).execute(perf_request)


def rank_funds(regime: str, max_count: int):
    """Return ranked funds for the given regime."""

    return RankFundsUseCase(DjangoFundRepository()).execute(regime, max_count)


def get_fund_info(fund_code: str):
    """Return fund info for one code."""

    return DjangoFundRepository().get_fund_info(fund_code)


def get_fund_nav(fund_code: str, start_date, end_date):
    """Return fund nav data."""

    return DjangoFundRepository().get_fund_nav(fund_code, start_date, end_date)


def get_fund_holdings(fund_code: str, report_date):
    """Return fund holding data."""

    return DjangoFundRepository().get_fund_holdings(fund_code, report_date)


def screen_funds_multidim(*, filters: dict, context_data: dict, max_count: int) -> dict[str, Any]:
    """Execute multi-dimensional fund screening."""

    active_signals = DjangoSignalRepository().get_active_signals()
    context = ScoreContext(
        current_regime=context_data.get("regime", "Recovery"),
        policy_level=context_data.get("policy_level", "P0"),
        sentiment_index=context_data.get("sentiment_index", 0.0),
        active_signals=active_signals,
    )
    scorer = FundMultiDimScorer(DjangoFundAssetRepository())
    result = scorer.screen_funds(filters=filters, context=context, max_count=max_count)
    return {
        "result": result,
        "context": context,
        "active_signals_count": len(active_signals),
    }
