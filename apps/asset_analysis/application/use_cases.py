"""
资产分析模块 - Application 层用例

本模块包含用例（Use Case）类，负责编排业务流程。
用例是 Application 层的核心，协调 Domain 层和 Infrastructure 层。
"""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.utils import timezone

from apps.asset_analysis.application.dtos import (
    AssetScoreDTO,
    ScreenRequest,
    ScreenResponse,
    WeightConfigDTO,
    WeightConfigsResponse,
)
from apps.asset_analysis.application.services import AssetMultiDimScorer
from apps.asset_analysis.domain.entities import (
    AssetScore,
    AssetSize,
    AssetStyle,
    AssetType,
)
from apps.asset_analysis.domain.interfaces import (
    AssetRepositoryProtocol,
    WeightConfigRepositoryProtocol,
)
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig

logger = logging.getLogger(__name__)


class _CommonRawScore(Protocol):
    """Common score fields exposed by asset-specific domain entities."""

    style: str | AssetStyle | None
    size: str | AssetSize | None
    sector: str | None
    regime_score: float
    policy_score: float
    sentiment_score: float
    signal_score: float
    total_score: float
    rank: int
    allocation_percent: float
    risk_level: str

    def get_custom_scores(self) -> dict[str, float]:
        """Return asset-specific score dimensions."""


@runtime_checkable
class _FundRawScore(_CommonRawScore, Protocol):
    """Narrow structural boundary for fund score entities."""

    fund_code: str
    fund_name: str
    investment_style: str | None


@runtime_checkable
class _EquityRawScore(_CommonRawScore, Protocol):
    """Narrow structural boundary for equity score entities."""

    stock_code: str
    stock_name: str


@runtime_checkable
class _GenericRawScore(_CommonRawScore, Protocol):
    """Narrow structural boundary for other asset score adapters."""

    asset_code: str
    asset_name: str


@dataclass(frozen=True)
class _NormalizedRawScore:
    """Validated fields used to construct the shared domain entity."""

    code: str
    name: str
    style: AssetStyle | None
    size: AssetSize | None
    sector: str | None
    regime_score: float
    policy_score: float
    sentiment_score: float
    signal_score: float
    custom_scores: dict[str, float]
    total_score: float
    rank: int
    allocation_percent: float
    risk_level: str


class MultiDimScreenUseCase:
    """
    多维度筛选用例

    负责执行完整的资产筛选和评分流程。
    """

    def __init__(
        self,
        weight_repository: WeightConfigRepositoryProtocol,
        asset_repository: AssetRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            weight_repository: 权重配置仓储
            asset_repository: 资产仓储
        """
        self.weight_repo = weight_repository
        self.asset_repo = asset_repository
        self.scorer = AssetMultiDimScorer(weight_repository)

    def execute(self, request: ScreenRequest, context: ScoreContext) -> ScreenResponse:
        """
        执行多维度筛选

        Args:
            request: 筛选请求
            context: 评分上下文

        Returns:
            筛选响应
        """
        try:
            # 1. 获取资产列表（从仓储）
            raw_assets = self.asset_repo.get_assets_by_filter(
                asset_type=request.asset_type,
                filters=request.filters,
                max_count=request.max_count * 2,  # 多取一些，筛选后再截断
            )

            # 2. 转换为 AssetScore 实体
            assets = self._convert_to_asset_scores(raw_assets, request.asset_type)

            # 3. 每个请求只解析一次实际使用的权重
            custom_weights = (
                WeightConfig(
                    regime_weight=request.weights["regime"],
                    policy_weight=request.weights["policy"],
                    sentiment_weight=request.weights["sentiment"],
                    signal_weight=request.weights["signal"],
                )
                if request.weights is not None
                else None
            )
            effective_weights = custom_weights or self.weight_repo.get_active_weights(
                asset_type=request.asset_type,
            )

            # 5. 批量评分
            scored_assets = self.scorer.score_batch(
                assets,
                context,
                filters=request.filters,
                weights_override=effective_weights,
            )

            # 6. 截取前 N 名
            scored_assets = scored_assets[: request.max_count]

            # 7. 转换为 DTO
            asset_dtos = self._convert_to_dtos(scored_assets)

            # 8. 构建响应
            return ScreenResponse(
                success=True,
                timestamp=timezone.now().isoformat(),
                context=context.to_dict(),
                weights=effective_weights.to_dict(),
                assets=asset_dtos,
            )

        except Exception as exc:
            logger.error(
                "Asset screening failed asset_type=%s exception_type=%s",
                request.asset_type,
                type(exc).__name__,
            )
            return ScreenResponse(
                success=False,
                timestamp=timezone.now().isoformat(),
                context=context.to_dict(),
                weights={},
                assets=[],
                message="筛选暂不可用",
            )

    @staticmethod
    def _convert_to_asset_scores(
        raw_assets: list[object],
        asset_type: str,
    ) -> list[AssetScore]:
        """
        将原始资产对象转换为 AssetScore 实体

        支持以下类型：
        - FundAssetScore (from apps.fund.domain.entities)
        - EquityAssetScore (from apps.equity.domain.entities)
        - AssetScore (from apps.asset_analysis.domain.entities)

        Args:
            raw_assets: 原始资产列表
            asset_type: 资产类型

        Returns:
            AssetScore 实体列表
        """
        resolved_asset_type = AssetType(asset_type)
        assets: list[AssetScore] = []

        for raw in raw_assets:
            if isinstance(raw, AssetScore):
                if raw.asset_type is not resolved_asset_type:
                    raise ValueError("资产数据类型与筛选类型不匹配")
                assets.append(raw)
                continue

            normalized = MultiDimScreenUseCase._normalize_raw_score(
                raw,
                resolved_asset_type,
            )
            assets.append(
                AssetScore(
                    asset_type=resolved_asset_type,
                    asset_code=normalized.code,
                    asset_name=normalized.name,
                    style=normalized.style,
                    size=normalized.size,
                    sector=normalized.sector,
                    regime_score=normalized.regime_score,
                    policy_score=normalized.policy_score,
                    sentiment_score=normalized.sentiment_score,
                    signal_score=normalized.signal_score,
                    custom_scores=normalized.custom_scores,
                    total_score=normalized.total_score,
                    rank=normalized.rank,
                    allocation_percent=normalized.allocation_percent,
                    risk_level=normalized.risk_level,
                )
            )

        return assets

    @staticmethod
    def _normalize_raw_score(
        raw: object,
        asset_type: AssetType,
    ) -> _NormalizedRawScore:
        """Validate an asset-specific score object at the dynamic integration boundary."""

        score: _CommonRawScore
        if asset_type is AssetType.FUND and isinstance(raw, _FundRawScore):
            code = raw.fund_code
            name = raw.fund_name
            style_value: object = raw.style or raw.investment_style
            score = raw
        elif asset_type is AssetType.EQUITY and isinstance(raw, _EquityRawScore):
            code = raw.stock_code
            name = raw.stock_name
            style_value = raw.style
            score = raw
        elif isinstance(raw, _GenericRawScore):
            code = raw.asset_code
            name = raw.asset_name
            style_value = raw.style
            score = raw
        else:
            raise ValueError("不支持的资产数据结构")

        return _NormalizedRawScore(
            code=MultiDimScreenUseCase._required_text(code, "asset_code"),
            name=MultiDimScreenUseCase._required_text(name, "asset_name"),
            style=MultiDimScreenUseCase._normalize_style(style_value),
            size=MultiDimScreenUseCase._normalize_size(score.size),
            sector=MultiDimScreenUseCase._optional_text(score.sector, "sector"),
            regime_score=MultiDimScreenUseCase._finite_number(
                score.regime_score,
                "regime_score",
            ),
            policy_score=MultiDimScreenUseCase._finite_number(
                score.policy_score,
                "policy_score",
            ),
            sentiment_score=MultiDimScreenUseCase._finite_number(
                score.sentiment_score,
                "sentiment_score",
            ),
            signal_score=MultiDimScreenUseCase._finite_number(
                score.signal_score,
                "signal_score",
            ),
            custom_scores=MultiDimScreenUseCase._normalize_custom_scores(
                score.get_custom_scores(),
            ),
            total_score=MultiDimScreenUseCase._finite_number(
                score.total_score,
                "total_score",
            ),
            rank=MultiDimScreenUseCase._non_negative_int(score.rank, "rank"),
            allocation_percent=MultiDimScreenUseCase._finite_number(
                score.allocation_percent,
                "allocation_percent",
            ),
            risk_level=MultiDimScreenUseCase._required_text(
                score.risk_level,
                "risk_level",
            ),
        )

    @staticmethod
    def _normalize_style(value: object) -> AssetStyle | None:
        """Normalize one canonical asset-style value."""

        if value is None:
            return None
        if isinstance(value, AssetStyle):
            return value
        if isinstance(value, str):
            try:
                return AssetStyle(value.strip().lower())
            except ValueError:
                return None
        raise ValueError("style 必须是字符串或 AssetStyle")

    @staticmethod
    def _normalize_size(value: object) -> AssetSize | None:
        """Normalize one canonical asset-size value."""

        if value is None:
            return None
        if isinstance(value, AssetSize):
            return value
        if isinstance(value, str):
            try:
                return AssetSize(value.strip().lower())
            except ValueError:
                return None
        raise ValueError("size 必须是字符串或 AssetSize")

    @staticmethod
    def _normalize_custom_scores(values: object) -> dict[str, float]:
        """Validate custom score dimensions without allowing dynamic values downstream."""

        if not isinstance(values, Mapping):
            raise ValueError("custom_scores 必须是映射")
        normalized: dict[str, float] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("custom_scores 键必须是非空字符串")
            normalized[key] = MultiDimScreenUseCase._finite_number(
                value,
                f"custom_scores.{key}",
            )
        return normalized

    @staticmethod
    def _finite_number(value: object, field_name: str) -> float:
        """Return a finite numeric boundary value."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} 必须是数值")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"{field_name} 必须是有限值")
        return normalized

    @staticmethod
    def _non_negative_int(value: object, field_name: str) -> int:
        """Return a non-negative integer boundary value."""

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} 必须是非负整数")
        return value

    @staticmethod
    def _required_text(value: object, field_name: str) -> str:
        """Return one required non-empty text boundary value."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} 必须是非空字符串")
        return value.strip()

    @staticmethod
    def _optional_text(value: object, field_name: str) -> str | None:
        """Return one optional normalized text boundary value."""

        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")
        return value.strip() or None

    @staticmethod
    def _convert_to_dtos(scored_assets: list[AssetScore]) -> list[AssetScoreDTO]:
        """
        将 AssetScore 实体转换为 DTO

        Args:
            scored_assets: 评分后的资产列表

        Returns:
            DTO 列表
        """
        dtos = []

        for asset in scored_assets:
            dtos.append(
                AssetScoreDTO(
                    asset_code=asset.asset_code,
                    asset_name=asset.asset_name,
                    asset_type=asset.asset_type.value,
                    style=asset.style.value if asset.style else None,
                    size=asset.size.value if asset.size else None,
                    sector=asset.sector,
                    regime_score=asset.regime_score,
                    policy_score=asset.policy_score,
                    sentiment_score=asset.sentiment_score,
                    signal_score=asset.signal_score,
                    custom_scores=asset.custom_scores,
                    total_score=asset.total_score,
                    rank=asset.rank,
                    allocation=f"{asset.allocation_percent:.1f}%",
                    risk_level=asset.risk_level,
                )
            )

        return dtos


class GetWeightConfigsUseCase:
    """
    获取权重配置用例
    """

    def __init__(self, weight_repository: WeightConfigRepositoryProtocol):
        """
        初始化用例

        Args:
            weight_repository: 权重配置仓储
        """
        self.weight_repo = weight_repository

    def execute(self) -> WeightConfigsResponse:
        """
        执行获取权重配置

        Returns:
            权重配置字典
        """
        configs = self.weight_repo.list_all_configs()

        # 转换为响应格式
        result: WeightConfigsResponse = {
            "configs": {},
            "active": None,
        }
        active_priority: int | None = None

        for config in configs:
            dto = WeightConfigDTO(
                name=config["name"],
                description=config.get("description"),
                regime_weight=config["regime_weight"],
                policy_weight=config["policy_weight"],
                sentiment_weight=config["sentiment_weight"],
                signal_weight=config["signal_weight"],
                asset_type=config.get("asset_type"),
                market_condition=config.get("market_condition"),
                is_active=config["is_active"],
                priority=config["priority"],
            )
            result["configs"][dto.name] = dto.to_dict()

            if dto.is_active and (active_priority is None or dto.priority > active_priority):
                result["active"] = dto.name
                active_priority = dto.priority

        return result
