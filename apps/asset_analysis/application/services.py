"""
资产分析模块 - Application 层服务

本模块包含应用服务，负责编排业务逻辑。
Application 层依赖 Domain 层和 Infrastructure 层的接口。
"""

import time
from typing import List, Optional
from dataclasses import replace

from apps.asset_analysis.domain.entities import AssetScore
from apps.asset_analysis.domain.value_objects import WeightConfig, ScoreContext
from apps.asset_analysis.domain.interfaces import WeightConfigRepositoryProtocol
from apps.asset_analysis.domain.services import (
    RegimeMatcher,
    PolicyMatcher,
    SentimentMatcher,
    SignalMatcher,
)
from apps.asset_analysis.application.logging_service import ScoringLogger, AlertService


class AssetMultiDimScorer:
    """
    通用资产多维度评分器

    负责计算资产的综合得分，基于四个维度：
    - Regime（宏观环境）
    - Policy（政策档位）
    - Sentiment（舆情情绪）
    - Signal（投资信号）

    集成日志记录和告警功能。
    """

    def __init__(
        self,
        weight_repository: WeightConfigRepositoryProtocol,
        enable_logging: bool = True,
        enable_alerts: bool = True,
    ):
        """
        初始化评分器

        Args:
            weight_repository: 权重配置仓储
            enable_logging: 是否启用日志记录
            enable_alerts: 是否启用告警
        """
        self.weight_repo = weight_repository
        self.enable_logging = enable_logging
        self.enable_alerts = enable_alerts

        # 初始化日志和告警服务
        if self.enable_logging:
            self.logger = ScoringLogger()
        if self.enable_alerts:
            self.alert_service = AlertService()

    def score(self, asset: AssetScore, context: ScoreContext) -> AssetScore:
        """
        计算单个资产的综合得分

        Args:
            asset: 资产评分实体
            context: 评分上下文

        Returns:
            更新后的资产评分实体
        """
        # 1. 获取权重配置（从数据库）
        weights = self.weight_repo.get_active_weights(
            asset_type=asset.asset_type.value
        )

        # 2. 计算各维度得分
        regime_score = RegimeMatcher.match(asset, context.current_regime)
        policy_score = PolicyMatcher.match(asset, context.policy_level)
        sentiment_score = SentimentMatcher.match(asset, context.sentiment_index)
        signal_score = SignalMatcher.match(asset, context.active_signals)

        # 3. 加权计算综合得分
        total_score = (
            regime_score * weights.regime_weight +
            policy_score * weights.policy_weight +
            sentiment_score * weights.sentiment_weight +
            signal_score * weights.signal_weight
        )

        # 4. 返回更新后的资产对象（使用 dataclass.replace 创建新实例）
        return replace(
            asset,
            regime_score=regime_score,
            policy_score=policy_score,
            sentiment_score=sentiment_score,
            signal_score=signal_score,
            total_score=total_score,
            score_date=context.score_date,
        )

    def score_batch(
        self,
        assets: List[AssetScore],
        context: ScoreContext,
        request_source: str = "unknown",
        user_id: Optional[int] = None,
        filters: Optional[dict] = None,
    ) -> List[AssetScore]:
        """
        批量评分资产（带日志记录和告警）

        Args:
            assets: 资产评分实体列表
            context: 评分上下文
            request_source: 请求来源
            user_id: 用户ID
            filters: 筛选条件

        Returns:
            评分后的资产列表（已按 total_score 降序排序并设置排名）
        """
        start_time = time.time()
        total_assets = len(assets)
        status = "success"
        error_message = None

        try:
            # 1. 获取权重配置
            weights = self.weight_repo.get_active_weights(
                asset_type=assets[0].asset_type.value if assets else "unknown"
            )

            # 2. 批量计算得分
            scored_assets = [self.score(asset, context) for asset in assets]

            # 3. 按综合得分排序
            scored_assets.sort(key=lambda x: x.total_score, reverse=True)

            # 4. 设置排名和推荐比例
            for rank, asset in enumerate(scored_assets, start=1):
                # 更新排名（frozen dataclass 需要使用 replace）
                asset = replace(asset, rank=rank)

                # 计算推荐比例（前 10 名分配更高比例）
                if rank <= 3:
                    allocation = 20.0  # 前 3 名各 20%
                elif rank <= 10:
                    allocation = 10.0  # 4-10 名各 10%
                else:
                    allocation = 0.0

                # 更新推荐比例和风险等级
                asset = replace(
                    asset,
                    allocation_percent=allocation,
                    risk_level=self._calculate_risk_level(asset)
                )
                scored_assets[rank - 1] = asset

            return scored_assets

        except Exception as e:
            status = "failed"
            error_message = str(e)

            # 创建告警
            if self.enable_alerts:
                asset_type = assets[0].asset_type.value if assets else "unknown"
                self.alert_service.create_scoring_error_alert(
                    asset_type=asset_type,
                    error_message=error_message,
                    context={"total_assets": total_assets},
                    stack_trace=traceback.format_exc(),
                )

            raise

        finally:
            # 记录日志
            if self.enable_logging:
                execution_time_ms = int((time.time() - start_time) * 1000)
                asset_type = assets[0].asset_type.value if assets else "unknown"

                # 获取权重用于日志
                try:
                    weights = self.weight_repo.get_active_weights(asset_type=asset_type)
                except:
                    weights = WeightConfig()  # 使用默认权重

                self.logger.log_scoring_from_context(
                    asset_type=asset_type,
                    request_source=request_source,
                    context=context,
                    weights=weights,
                    filters=filters or {},
                    total_assets=total_assets,
                    filtered_assets=len(assets) if assets else 0,
                    execution_time_ms=execution_time_ms,
                    user_id=user_id,
                    status=status,
                    error_message=error_message,
                )

                # 性能告警
                if self.enable_alerts and execution_time_ms > 5000:
                    self.alert_service.create_performance_alert(
                        asset_type=asset_type,
                        execution_time_ms=execution_time_ms,
                        threshold_ms=5000,
                        context={"total_assets": total_assets},
                    )

    @staticmethod
    def _calculate_risk_level(asset: AssetScore) -> str:
        """
        根据资产属性计算风险等级

        Args:
            asset: 资产评分实体

        Returns:
            风险等级字符串
        """
        # 根据资产类型判断
        if asset.asset_type.value in ["bond"]:
            return "低风险"
        elif asset.asset_type.value in ["equity", "fund", "index"]:
            # 根据风格进一步细分
            if asset.style and asset.style.value in ["defensive", "value"]:
                return "中低风险"
            elif asset.style and asset.style.value == "quality":
                return "中风险"
            else:
                return "高风险"
        elif asset.asset_type.value == "commodity":
            return "高风险"
        else:
            return "未知"
