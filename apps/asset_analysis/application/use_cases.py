"""
资产分析模块 - Application 层用例

本模块包含用例（Use Case）类，负责编排业务流程。
用例是 Application 层的核心，协调 Domain 层和 Infrastructure 层。
"""

from typing import List
from datetime import datetime

from apps.asset_analysis.domain.entities import AssetScore, AssetType, AssetStyle, AssetSize
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig
from apps.asset_analysis.domain.interfaces import WeightConfigRepositoryProtocol, AssetRepositoryProtocol
from apps.asset_analysis.application.services import AssetMultiDimScorer
from apps.asset_analysis.application.dtos import (
    ScreenRequest,
    ScreenResponse,
    AssetScoreDTO,
    WeightConfigDTO,
)


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
                max_count=request.max_count * 2  # 多取一些，筛选后再截断
            )

            # 2. 转换为 AssetScore 实体
            assets = self._convert_to_asset_scores(raw_assets, request.asset_type)

            # 3. 如果请求中指定了权重，创建临时权重配置
            if request.weights:
                weights = WeightConfig(
                    regime_weight=request.weights.get("regime", 0.40),
                    policy_weight=request.weights.get("policy", 0.25),
                    sentiment_weight=request.weights.get("sentiment", 0.20),
                    signal_weight=request.weights.get("signal", 0.15),
                )
                # 注意：这里应该用某种方式设置临时权重
                # 简化处理：假设 weight_repository 支持临时权重覆盖

            # 4. 获取当前使用的权重
            current_weights = self.weight_repo.get_active_weights(
                asset_type=request.asset_type
            )

            # 5. 批量评分
            scored_assets = self.scorer.score_batch(assets, context)

            # 6. 截取前 N 名
            scored_assets = scored_assets[:request.max_count]

            # 7. 转换为 DTO
            asset_dtos = self._convert_to_dtos(scored_assets)

            # 8. 构建响应
            return ScreenResponse(
                success=True,
                timestamp=datetime.now().isoformat(),
                context=context.to_dict(),
                weights=current_weights.to_dict(),
                assets=asset_dtos,
            )

        except Exception as e:
            return ScreenResponse(
                success=False,
                timestamp=datetime.now().isoformat(),
                context=context.to_dict(),
                weights={},
                assets=[],
                message=f"筛选失败: {str(e)}",
            )

    @staticmethod
    def _convert_to_asset_scores(raw_assets: List, asset_type: str) -> List[AssetScore]:
        """
        将原始资产对象转换为 AssetScore 实体

        Args:
            raw_assets: 原始资产列表
            asset_type: 资产类型

        Returns:
            AssetScore 实体列表
        """
        assets = []

        for raw in raw_assets:
            # 提取基本信息
            code = getattr(raw, "code", getattr(raw, "asset_code", ""))
            name = getattr(raw, "name", getattr(raw, "asset_name", ""))

            # 提取风格信息
            style = None
            style_str = getattr(raw, "style", getattr(raw, "investment_style", None))
            if style_str:
                try:
                    style = AssetStyle(style_str.lower())
                except ValueError:
                    pass

            # 提取规模信息
            size = None
            size_str = getattr(raw, "size", None)
            if size_str:
                try:
                    size = AssetSize(size_str.lower())
                except ValueError:
                    pass

            # 提取行业
            sector = getattr(raw, "sector", getattr(raw, "industry", None))

            assets.append(AssetScore(
                asset_type=AssetType(asset_type),
                asset_code=code,
                asset_name=name,
                style=style,
                size=size,
                sector=sector,
            ))

        return assets

    @staticmethod
    def _convert_to_dtos(scored_assets: List[AssetScore]) -> List[AssetScoreDTO]:
        """
        将 AssetScore 实体转换为 DTO

        Args:
            scored_assets: 评分后的资产列表

        Returns:
            DTO 列表
        """
        dtos = []

        for asset in scored_assets:
            dtos.append(AssetScoreDTO(
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
            ))

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

    def execute(self) -> dict:
        """
        执行获取权重配置

        Returns:
            权重配置字典
        """
        configs = self.weight_repo.list_all_configs()

        # 转换为响应格式
        result = {
            "configs": {},
            "active": None,
        }

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

            if dto.is_active and (result["active"] is None or dto.priority > 0):
                result["active"] = dto.name

        return result
