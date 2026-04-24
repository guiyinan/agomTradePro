"""Application-side builders for asset-analysis interface endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.asset_analysis.application.dtos import ScreenRequest, ScreenResponse
from apps.asset_analysis.application.use_cases import GetWeightConfigsUseCase, MultiDimScreenUseCase
from apps.equity.application.services import EquityMultiDimScorer
from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
from apps.fund.application.services import FundMultiDimScorer
from apps.fund.infrastructure.repositories import DjangoFundAssetRepository
from apps.asset_analysis.infrastructure.repositories import (
    DjangoAssetRepository,
    DjangoWeightConfigRepository,
)
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from apps.sentiment.infrastructure.repositories import SentimentIndexRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository

from apps.asset_analysis.domain.value_objects import ScoreContext

from .repository_provider import get_asset_pool_query_repository


@dataclass(frozen=True)
class AssetPoolContextPayload:
    """Structured context returned to interface views for pool screening."""

    score_context: ScoreContext
    current_regime: str
    policy_level: str
    sentiment_index: float
    active_signals: list[Any]


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
        latest_policy = DjangoPolicyRepository().get_current_policy_level()
        policy_level = latest_policy.value if latest_policy else "P1"

    if sentiment_index_override is not None:
        sentiment_index = sentiment_index_override
    else:
        latest_sentiment = SentimentIndexRepository().get_latest()
        sentiment_index = latest_sentiment.composite_index * 3 if latest_sentiment else 0.0

    if active_signals_override is not None:
        active_signals = active_signals_override
    else:
        active_signals = DjangoSignalRepository().get_active_signals()

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
    )


def execute_multidim_screen(request: ScreenRequest, context: ScoreContext) -> ScreenResponse:
    """Execute multi-dimensional screening with default repositories."""

    use_case = MultiDimScreenUseCase(
        DjangoWeightConfigRepository(),
        DjangoAssetRepository(),
    )
    return use_case.execute(request, context)


def get_weight_configs() -> dict[str, Any]:
    """Return all weight configs for interface serialization."""

    return GetWeightConfigsUseCase(DjangoWeightConfigRepository()).execute()


def get_current_weight_config(
    *,
    asset_type: str | None = None,
    market_condition: str | None = None,
) -> dict[str, Any]:
    """Return the active weight config for one asset/market context."""

    weights = DjangoWeightConfigRepository().get_active_weights(
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

    repo = DjangoEquityAssetRepository()
    scorer = EquityMultiDimScorer(repo)

    filter_dict: dict[str, Any] = {}
    if filters.get("sector"):
        filter_dict["sector"] = filters["sector"]
    if filters.get("market"):
        filter_dict["market"] = filters["market"]
    if filters.get("min_market_cap") is not None:
        filter_dict["min_market_cap"] = filters["min_market_cap"]
    if filters.get("max_pe") is not None:
        filter_dict["max_pe"] = filters["max_pe"]

    assets = repo.get_assets_by_filter(asset_type="equity", filters=filter_dict)
    return scorer.score_batch(assets, context)


def screen_fund_assets(context: ScoreContext, filters: dict[str, Any]) -> list[Any]:
    """Screen and score fund assets for pool classification."""

    repo = DjangoFundAssetRepository()
    scorer = FundMultiDimScorer(repo)

    filter_dict: dict[str, Any] = {}
    if filters.get("fund_type"):
        filter_dict["fund_type"] = filters["fund_type"]
    if filters.get("investment_style"):
        filter_dict["investment_style"] = filters["investment_style"]
    if filters.get("min_scale") is not None:
        filter_dict["min_scale"] = filters["min_scale"]

    assets = repo.get_assets_by_filter(asset_type="fund", filters=filter_dict)
    return scorer.score_batch(assets, context)


def summarize_asset_pool_counts(asset_type: str | None = None) -> dict[str, int]:
    """Return active asset-pool counts by pool type."""

    return get_asset_pool_query_repository().summarize_pool_counts(asset_type)
