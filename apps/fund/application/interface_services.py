"""Application-facing orchestration helpers for fund interface views."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, TypedDict

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.data_center.application.public import get_published_fund_nav_series
from apps.fund.application.repository_provider import (
    get_fund_asset_repository,
    get_fund_repository,
)
from apps.fund.application.services import FundMultiDimScorer, FundScreenResult
from apps.fund.application.use_cases import (
    AnalyzeFundStyleRequest,
    AnalyzeFundStyleResponse,
    AnalyzeFundStyleUseCase,
    CalculateFundPerformanceRequest,
    CalculateFundPerformanceResponse,
    CalculateFundPerformanceUseCase,
    RankFundsUseCase,
    ScreenFundsRequest,
    ScreenFundsResponse,
    ScreenFundsUseCase,
)
from apps.fund.domain.entities import FundHolding, FundInfo, FundNetValue, FundScore
from apps.policy.application.repository_provider import get_current_policy_repository
from apps.regime.application.current_regime import resolve_current_regime
from apps.sentiment.application.current_sentiment import resolve_current_sentiment
from apps.signal.application.repository_provider import get_signal_repository


class FundMultiDimPayload(TypedDict):
    """Typed result returned to the Fund multi-dimensional API."""

    result: FundScreenResult
    context: ScoreContext
    active_signals_count: int


def build_dashboard_context() -> dict[str, Any]:
    """Build the fund dashboard HTML context."""

    latest_regime = resolve_current_regime(as_of_date=date.today())
    latest_policy = get_current_policy_repository().get_current_policy_level()
    current_sentiment = resolve_current_sentiment()
    latest_sentiment = current_sentiment.index
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

    regime_is_valid = bool(
        latest_regime
        and latest_regime.dominant_regime in regime_display
        and not isinstance(latest_regime.confidence, bool)
        and math.isfinite(latest_regime.confidence)
    )
    sentiment_is_valid = bool(
        latest_sentiment
        and not isinstance(latest_sentiment.composite_index, bool)
        and math.isfinite(latest_sentiment.composite_index)
    )
    sentiment_level = "未知"
    if latest_sentiment and sentiment_is_valid:
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
        "current_regime": (
            latest_regime.dominant_regime if latest_regime and regime_is_valid else "Unknown"
        ),
        "regime_display": (
            regime_display.get(latest_regime.dominant_regime, "未知")
            if latest_regime and regime_is_valid
            else "未知"
        ),
        "regime_confidence": (
            f"{latest_regime.confidence:.1%}" if latest_regime and regime_is_valid else "N/A"
        ),
        "current_policy": latest_policy.value if latest_policy else "Unknown",
        "policy_display": (
            policy_display.get(latest_policy.value, "未知") if latest_policy else "未配置"
        ),
        "sentiment_index": (
            f"{latest_sentiment.composite_index:.2f}"
            if latest_sentiment and sentiment_is_valid
            else "N/A"
        ),
        "sentiment_level": sentiment_level,
        "sentiment_date": (
            latest_sentiment.index_date.strftime("%Y-%m-%d")
            if latest_sentiment and sentiment_is_valid
            else "-"
        ),
        "sentiment_freshness_status": current_sentiment.freshness_status,
        "sentiment_must_not_use_for_decision": current_sentiment.must_not_use_for_decision,
        "sentiment_blocked_reason": current_sentiment.blocked_reason,
        "active_signals_count": len(active_signals),
    }


def screen_funds(screen_request: ScreenFundsRequest) -> ScreenFundsResponse:
    """Execute fund screening."""

    return ScreenFundsUseCase(get_fund_repository()).execute(screen_request)


def analyze_fund_style(
    analyze_request: AnalyzeFundStyleRequest,
) -> AnalyzeFundStyleResponse:
    """Execute fund style analysis."""

    return AnalyzeFundStyleUseCase(get_fund_repository()).execute(analyze_request)


def calculate_fund_performance(
    perf_request: CalculateFundPerformanceRequest,
) -> CalculateFundPerformanceResponse:
    """Execute fund performance calculation."""

    return CalculateFundPerformanceUseCase(get_fund_repository()).execute(perf_request)


def rank_funds(regime: str, max_count: int, as_of_date: date | None = None) -> list[FundScore]:
    """Return ranked funds for the given regime."""

    return RankFundsUseCase(get_fund_repository()).execute(
        regime,
        max_count,
        as_of_date=as_of_date,
    )


def get_fund_score(
    *,
    fund_code: str,
    regime: str,
    as_of_date: date | None = None,
) -> FundScore | None:
    """Return one computed fund score from the canonical ranking use case."""

    normalized = fund_code.strip().upper().removesuffix(".OF")
    if not normalized:
        raise ValueError("fund_code is required")
    scores = RankFundsUseCase(get_fund_repository()).execute(
        regime,
        max_count=None,
        as_of_date=as_of_date,
    )
    for score in scores:
        if score.fund_code.strip().upper().removesuffix(".OF") == normalized:
            return score
    return None


def get_fund_info(fund_code: str) -> FundInfo | None:
    """Return fund info for one code."""

    normalized_code = _normalize_fund_code(fund_code)
    return get_fund_repository().get_fund_info(normalized_code)


def get_fund_nav(
    fund_code: str,
    start_date: date | None,
    end_date: date | None,
) -> list[FundNetValue]:
    """Return fund nav data."""

    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    return get_fund_repository().get_fund_nav(
        _normalize_fund_code(fund_code),
        start_date,
        end_date,
    )


def get_published_fund_nav_payload(
    fund_code: str,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Return the current fund NAV series with publication evidence.

    The default fund NAV screen is a current-data consumer. Historical ranges
    continue to use :func:`get_fund_nav` explicitly, while this port fails
    closed when the current fund publication is missing or stale.
    """

    payload = get_published_fund_nav_series(
        _normalize_fund_code(fund_code),
        publication_key="current",
        limit=limit,
    )
    rows = payload.get("rows")
    normalized_rows: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            normalized_rows.append(
                {
                    "fund_code": str(row.get("fund_code") or _normalize_fund_code(fund_code)),
                    "nav_date": row.get("nav_date"),
                    "unit_nav": row.get("nav"),
                    "accum_nav": row.get("acc_nav"),
                    "daily_return": row.get("daily_return"),
                }
            )
    return {**payload, "rows": normalized_rows}


def get_fund_holdings(fund_code: str, report_date: date | None) -> list[FundHolding]:
    """Return fund holding data."""

    return get_fund_repository().get_fund_holdings(
        _normalize_fund_code(fund_code),
        report_date,
    )


def screen_funds_multidim(
    *,
    filters: Mapping[str, object],
    context_data: Mapping[str, object],
    max_count: int,
) -> FundMultiDimPayload:
    """Execute multi-dimensional fund screening."""

    if isinstance(max_count, bool) or not 1 <= max_count <= 100:
        raise ValueError("max_count must be between 1 and 100")
    allowed_filter_keys = {
        "fund_type",
        "investment_style",
        "min_scale",
        "max_scale",
        "fund_company",
    }
    unknown_filter_keys = set(filters) - allowed_filter_keys
    if unknown_filter_keys:
        raise ValueError("Unsupported fund filters")
    normalized_filters = _normalize_multidim_filters(filters)
    regime = context_data.get("regime")
    policy_level = context_data.get("policy_level")
    sentiment_index = context_data.get("sentiment_index")
    if not isinstance(regime, str) or not isinstance(policy_level, str):
        raise ValueError("regime and policy_level are required")
    if (
        isinstance(sentiment_index, bool)
        or not isinstance(sentiment_index, (int, float))
        or not math.isfinite(float(sentiment_index))
    ):
        raise ValueError("sentiment_index must be finite")

    active_signals = get_signal_repository().get_active_signals()
    context = ScoreContext(
        current_regime=regime,
        policy_level=policy_level,
        sentiment_index=float(sentiment_index),
        active_signals=active_signals,
    )
    scorer = FundMultiDimScorer(get_fund_asset_repository())
    result = scorer.screen_funds(
        filters=normalized_filters,
        context=context,
        max_count=max_count,
    )
    return {
        "result": result,
        "context": context,
        "active_signals_count": len(active_signals),
    }


def _normalize_fund_code(fund_code: str) -> str:
    """Normalize and validate one local/Tushare fund code."""

    normalized = fund_code.strip().upper().removesuffix(".OF")
    if not normalized:
        raise ValueError("fund_code is required")
    return normalized


def _normalize_multidim_filters(
    filters: Mapping[str, object],
) -> dict[str, object]:
    """Validate direct callers before filters reach Django ORM."""

    normalized: dict[str, object] = {}
    for key in ("fund_type", "investment_style", "fund_company"):
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        normalized[key] = value.strip()

    numeric_values: dict[str, Decimal] = {}
    for key in ("min_scale", "max_scale"):
        value = filters.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"{key} must be numeric")
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite() or decimal_value < 0:
            raise ValueError(f"{key} must be finite and non-negative")
        numeric_values[key] = decimal_value
        normalized[key] = decimal_value
    if (
        "min_scale" in numeric_values
        and "max_scale" in numeric_values
        and numeric_values["min_scale"] > numeric_values["max_scale"]
    ):
        raise ValueError("min_scale must not exceed max_scale")
    return normalized
