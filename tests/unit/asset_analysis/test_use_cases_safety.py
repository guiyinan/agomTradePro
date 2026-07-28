"""Safety and correctness coverage for asset-analysis screening use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from apps.asset_analysis.application.dtos import ScreenRequest
from apps.asset_analysis.application.services import AssetMultiDimScorer
from apps.asset_analysis.application.use_cases import (
    GetWeightConfigsUseCase,
    MultiDimScreenUseCase,
)
from apps.asset_analysis.domain.entities import (
    AssetScore,
    AssetSize,
    AssetStyle,
    AssetType,
)
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig


class CountingWeightRepository:
    """In-memory weight repository that records active-weight reads."""

    def __init__(
        self,
        weights: WeightConfig | None = None,
        configs: list[dict[str, object]] | None = None,
    ) -> None:
        self.weights = weights or WeightConfig()
        self.configs = configs or []
        self.read_count = 0

    def get_active_weights(
        self,
        asset_type: str | None = None,
        market_condition: str | None = None,
    ) -> WeightConfig:
        del asset_type, market_condition
        self.read_count += 1
        return self.weights

    def list_all_configs(self) -> list[dict[str, object]]:
        return self.configs

    def save_config(
        self,
        name: str,
        regime_weight: float,
        policy_weight: float,
        sentiment_weight: float,
        signal_weight: float,
        asset_type: str | None = None,
        market_condition: str | None = None,
        is_active: bool = True,
        priority: int = 0,
    ) -> None:
        del (
            name,
            regime_weight,
            policy_weight,
            sentiment_weight,
            signal_weight,
            asset_type,
            market_condition,
            is_active,
            priority,
        )


class StaticAssetRepository:
    """Return a fixed set of assets for screening tests."""

    def __init__(self, assets: list[object]) -> None:
        self.assets = assets

    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict[str, object],
        max_count: int = 100,
    ) -> list[object]:
        del asset_type, filters
        return self.assets[:max_count]

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> object | None:
        del asset_type, asset_code
        return None


class FailingAssetRepository(StaticAssetRepository):
    """Raise a secret-bearing exception at the repository boundary."""

    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict[str, object],
        max_count: int = 100,
    ) -> list[object]:
        del asset_type, filters, max_count
        raise RuntimeError("provider failed: token=secret")


@dataclass
class RawFundScore:
    """Minimal fund score shape exposed by the fund integration."""

    fund_code: str = "000001"
    fund_name: str = "测试基金"
    style: str | None = "growth"
    investment_style: str | None = None
    size: str | None = "large"
    sector: str | None = None
    regime_score: float = 10.0
    policy_score: float = 20.0
    sentiment_score: float = 30.0
    signal_score: float = 40.0
    total_score: float = 25.0
    rank: int = 2
    allocation_percent: float = 10.0
    risk_level: str = "中风险"

    def get_custom_scores(self) -> dict[str, float]:
        return {"manager": 88.0}


def _context() -> ScoreContext:
    return ScoreContext(
        current_regime="Recovery",
        policy_level="P0",
        sentiment_index=0.5,
        active_signals=[],
    )


def _asset(code: str = "000001") -> AssetScore:
    return AssetScore(
        asset_type=AssetType.EQUITY,
        asset_code=code,
        asset_name=f"测试股票{code}",
        style=AssetStyle.GROWTH,
    )


def test_custom_request_weights_drive_scoring_and_response() -> None:
    weight_repository = CountingWeightRepository(
        WeightConfig(
            regime_weight=0.0,
            policy_weight=0.0,
            sentiment_weight=0.0,
            signal_weight=1.0,
        )
    )
    use_case = MultiDimScreenUseCase(
        weight_repository,
        StaticAssetRepository([_asset()]),
    )
    use_case.scorer = AssetMultiDimScorer(
        weight_repository,
        enable_logging=False,
        enable_alerts=False,
    )

    response = use_case.execute(
        ScreenRequest(
            asset_type="equity",
            weights={
                "regime": 1.0,
                "policy": 0.0,
                "sentiment": 0.0,
                "signal": 0.0,
            },
        ),
        _context(),
    )

    assert response.success is True
    assert response.weights == {
        "regime": 1.0,
        "policy": 0.0,
        "sentiment": 0.0,
        "signal": 0.0,
    }
    assert response.assets[0].total_score == response.assets[0].regime_score
    assert weight_repository.read_count == 0


def test_batch_scoring_reads_repository_weights_once() -> None:
    weight_repository = CountingWeightRepository()
    scorer = AssetMultiDimScorer(
        weight_repository,
        enable_logging=False,
        enable_alerts=False,
    )

    result = scorer.score_batch(
        [_asset("000001"), _asset("000002"), _asset("000003")],
        _context(),
    )

    assert len(result) == 3
    assert weight_repository.read_count == 1


def test_fund_string_style_and_size_are_normalized_to_enums() -> None:
    converted = MultiDimScreenUseCase._convert_to_asset_scores(
        [RawFundScore()],
        "fund",
    )

    assert converted[0].style is AssetStyle.GROWTH
    assert converted[0].size is AssetSize.LARGE_CAP
    assert converted[0].custom_scores == {"manager": 88.0}


def test_unsupported_raw_asset_fails_closed() -> None:
    with pytest.raises(ValueError, match="不支持的资产数据结构"):
        MultiDimScreenUseCase._convert_to_asset_scores([object()], "fund")


def test_screening_failure_does_not_expose_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case = MultiDimScreenUseCase(
        CountingWeightRepository(),
        FailingAssetRepository([]),
    )

    with caplog.at_level(logging.ERROR):
        response = use_case.execute(ScreenRequest(asset_type="equity"), _context())

    assert response.success is False
    assert response.message == "筛选暂不可用"
    assert "token=secret" not in response.to_dict().__repr__()
    assert "token=secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_highest_priority_active_weight_config_is_selected() -> None:
    repository = CountingWeightRepository(
        configs=[
            {
                "name": "high",
                "description": None,
                "regime_weight": 0.4,
                "policy_weight": 0.25,
                "sentiment_weight": 0.2,
                "signal_weight": 0.15,
                "asset_type": None,
                "market_condition": None,
                "is_active": True,
                "priority": 100,
            },
            {
                "name": "low",
                "description": None,
                "regime_weight": 0.4,
                "policy_weight": 0.25,
                "sentiment_weight": 0.2,
                "signal_weight": 0.15,
                "asset_type": None,
                "market_condition": None,
                "is_active": True,
                "priority": 1,
            },
        ]
    )

    result = GetWeightConfigsUseCase(repository).execute()

    assert result["active"] == "high"


@pytest.mark.parametrize(
    "weights",
    [
        {},
        {"regime": 1.0, "policy": 0.0, "sentiment": 0.0},
        {
            "regime": 1.0,
            "policy": 0.0,
            "sentiment": 0.0,
            "signal": 0.0,
            "unknown": 0.0,
        },
        {"regime": float("nan"), "policy": 0.0, "sentiment": 0.0, "signal": 0.0},
        {"regime": True, "policy": 0.0, "sentiment": 0.0, "signal": 0.0},
    ],
)
def test_internal_screen_request_rejects_invalid_weights(
    weights: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        ScreenRequest(asset_type="equity", weights=weights)


@pytest.mark.parametrize("max_count", [True, 0, 101])
def test_internal_screen_request_rejects_invalid_max_count(max_count: int) -> None:
    with pytest.raises(ValueError):
        ScreenRequest(asset_type="equity", max_count=max_count)
