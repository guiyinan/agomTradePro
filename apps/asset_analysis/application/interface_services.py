"""Application-side builders for asset-analysis interface endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.asset_analysis.application.dtos import (
    ScreenRequest,
    ScreenResponse,
    WeightConfigsResponse,
)
from apps.asset_analysis.application.repository_provider import (
    get_asset_pool_query_repository,
    get_asset_repository,
    get_registered_pool_screener,
    get_weight_config_repository,
)
from apps.asset_analysis.application.signal_context_gateway import (
    get_signal_context_gateway,
)
from apps.asset_analysis.application.use_cases import GetWeightConfigsUseCase, MultiDimScreenUseCase
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.policy.application.repository_provider import get_current_policy_repository
from apps.regime.application.current_regime import resolve_current_regime
from apps.sentiment.application.current_sentiment import resolve_current_sentiment


@dataclass(frozen=True)
class AssetPoolContextPayload:
    """Structured context returned to interface views for pool screening."""

    score_context: ScoreContext
    current_regime: str
    policy_level: str
    sentiment_index: float
    active_signals: list[Any]
    sentiment_must_not_use_for_decision: bool = False
    sentiment_blocked_reason: str = ""
    sentiment_observed_at: date | None = None
    sentiment_freshness_status: str = "scenario_override"


def build_asset_pool_context(
    *,
    regime_override: str | None = None,
    policy_level_override: str | None = None,
    sentiment_index_override: float | None = None,
    active_signals_override: list[Any] | None = None,
) -> AssetPoolContextPayload:
    """Build the score context used by pool screening views."""

    resolved_regime = resolve_current_regime()
    current_regime = regime_override or (
        resolved_regime.dominant_regime if resolved_regime else "Recovery"
    )

    if policy_level_override:
        policy_level = policy_level_override
    else:
        latest_policy = get_current_policy_repository().get_current_policy_level()
        policy_level = latest_policy.value if latest_policy else "P1"

    sentiment_observed_at: date | None
    if sentiment_index_override is not None:
        sentiment_index = sentiment_index_override
        sentiment_blocked = False
        sentiment_blocked_reason = ""
        sentiment_observed_at = date.today()
        sentiment_freshness_status = "scenario_override"
    else:
        current_sentiment = resolve_current_sentiment()
        latest_sentiment = current_sentiment.index
        sentiment_index = latest_sentiment.composite_index * 3 if latest_sentiment else 0.0
        sentiment_blocked = current_sentiment.must_not_use_for_decision
        sentiment_blocked_reason = current_sentiment.blocked_reason
        sentiment_observed_at = current_sentiment.observed_at
        sentiment_freshness_status = current_sentiment.freshness_status

    if active_signals_override is not None:
        active_signals = active_signals_override
    else:
        active_signals = get_signal_context_gateway().list_active_signals()

    return AssetPoolContextPayload(
        score_context=ScoreContext(
            current_regime=current_regime,
            policy_level=policy_level,
            sentiment_index=sentiment_index,
            active_signals=active_signals,
            score_date=date.today(),
        ),
        current_regime=current_regime,
        policy_level=policy_level,
        sentiment_index=sentiment_index,
        active_signals=active_signals,
        sentiment_must_not_use_for_decision=sentiment_blocked,
        sentiment_blocked_reason=sentiment_blocked_reason,
        sentiment_observed_at=sentiment_observed_at,
        sentiment_freshness_status=sentiment_freshness_status,
    )


def execute_multidim_screen(request: ScreenRequest, context: ScoreContext) -> ScreenResponse:
    """Execute multi-dimensional screening with default repositories."""

    use_case = MultiDimScreenUseCase(
        get_weight_config_repository(),
        get_asset_repository(),
    )
    return use_case.execute(request, context)


def get_weight_configs() -> WeightConfigsResponse:
    """Return all weight configs for interface serialization."""

    return GetWeightConfigsUseCase(get_weight_config_repository()).execute()


def get_current_weight_config(
    *,
    asset_type: str | None = None,
    market_condition: str | None = None,
) -> dict[str, Any]:
    """Return the active weight config for one asset/market context."""

    weights = get_weight_config_repository().get_active_weights(
        asset_type=asset_type,
        market_condition=market_condition,
    )
    return {
        "success": True,
        "weights": weights.to_dict(),
        "asset_type": asset_type,
        "market_condition": market_condition,
    }


def screen_equity_assets(context: ScoreContext, filters: dict[str, Any]) -> list[Any]:
    """Screen and score equity assets for pool classification."""
    return get_registered_pool_screener("equity")(
        context,
        filters,
    )


def screen_fund_assets(context: ScoreContext, filters: dict[str, Any]) -> list[Any]:
    """Screen and score fund assets for pool classification."""
    return get_registered_pool_screener("fund")(
        context,
        filters,
    )


def summarize_asset_pool_counts(asset_type: str | None = None) -> dict[str, int]:
    """Return active asset-pool counts by pool type."""

    return get_asset_pool_query_repository().summarize_pool_counts(asset_type)
