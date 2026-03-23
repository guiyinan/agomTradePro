"""
Equity 模块 - Application 层服务（资产分析框架集成）

本模块提供个股多维度评分的服务，集成通用资产分析框架。
"""

from dataclasses import replace
from datetime import date
from typing import Dict, List, Optional

from apps.asset_analysis.domain.entities import AssetType
from apps.asset_analysis.domain.services import (
    PolicyMatcher,
    RegimeMatcher,
    SentimentMatcher,
    SignalMatcher,
)
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.equity.domain.entities import EquityAssetScore, StockInfo
from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository


class EquityMultiDimScorer:
    """
    个股多维度评分服务

    整合通用资产分析框架和个股特有的评分逻辑。
    """

    def __init__(self, asset_repository: DjangoEquityAssetRepository):
        """
        初始化评分服务

        Args:
            asset_repository: 个股资产仓储
        """
        self.asset_repo = asset_repository

    def score_batch(
        self,
        stocks: list[EquityAssetScore],
        context: ScoreContext,
    ) -> list[EquityAssetScore]:
        """
        批量评分个股

        Args:
            stocks: 个股资产评分实体列表
            context: 评分上下文

        Returns:
            评分后的个股列表（已排序并设置排名）
        """
        # 1. 计算每个个股的通用维度得分
        scored_stocks = []
        for stock in stocks:
            # 转换为通用 AssetScore 格式计算
            asset_score = self._to_asset_score(stock)

            # 计算四大维度得分
            regime_score = RegimeMatcher.match(asset_score, context.current_regime)
            policy_score = PolicyMatcher.match(asset_score, context.policy_level)
            sentiment_score = SentimentMatcher.match(asset_score, context.sentiment_index)
            signal_score = SignalMatcher.match(asset_score, context.active_signals)

            # 计算综合得分（使用个股专用权重）
            total_score = (
                regime_score * 0.30 +  # equity 专用权重
                policy_score * 0.20 +
                sentiment_score * 0.20 +
                signal_score * 0.10 +
                stock.technical_score * 0.10 +  # 技术面
                stock.fundamental_score * 0.10 +  # 基本面
                stock.valuation_score * 0.10  # 估值
            )

            # 更新个股得分
            scored_stock = replace(
                stock,
                regime_score=regime_score,
                policy_score=policy_score,
                sentiment_score=sentiment_score,
                signal_score=signal_score,
                total_score=total_score,
            )
            scored_stocks.append(scored_stock)

        # 2. 按综合得分排序
        scored_stocks.sort(key=lambda x: x.total_score, reverse=True)

        # 3. 设置排名和推荐比例
        for rank, stock in enumerate(scored_stocks, start=1):
            # 计算推荐比例
            if rank <= 3:
                allocation = 15.0
            elif rank <= 10:
                allocation = 8.0
            else:
                allocation = 0.0

            # 计算风险等级
            risk_level = self._calculate_risk_level(stock)

            scored_stocks[rank - 1] = replace(
                stock,
                rank=rank,
                allocation_percent=allocation,
                risk_level=risk_level,
            )

        return scored_stocks

    def screen_stocks(
        self,
        filters: dict,
        context: ScoreContext,
        max_count: int = 30,
    ) -> dict:
        """
        多维度筛选个股

        Args:
            filters: 过滤条件
            context: 评分上下文
            max_count: 最大返回数量

        Returns:
            筛选结果字典
        """
        # 1. 获取符合条件的个股
        stocks = self.asset_repo.get_assets_by_filter(
            asset_type="equity",
            filters=filters,
            max_count=max_count * 2,  # 多取一些，筛选后再截断
        )

        if not stocks:
            return {
                "success": False,
                "message": "未找到符合条件的个股",
                "stocks": [],
            }

        # 2. 批量评分
        scored_stocks = self.score_batch(stocks, context)

        # 3. 截取前 N 名
        scored_stocks = scored_stocks[:max_count]

        # 4. 转换为响应格式
        return {
            "success": True,
            "count": len(scored_stocks),
            "stocks": [stock.to_dict() for stock in scored_stocks],
        }

    @staticmethod
    def _to_asset_score(stock: EquityAssetScore):
        """将 EquityAssetScore 转换为通用 AssetScore 格式"""
        from apps.asset_analysis.domain.entities import AssetScore, AssetSize, AssetStyle

        # 映射风格
        style_map = {
            "growth": AssetStyle.GROWTH,
            "value": AssetStyle.VALUE,
            "blend": AssetStyle.BLEND,
            "defensive": AssetStyle.DEFENSIVE,
        }
        style = style_map.get(stock.style) if stock.style else None

        # 映射规模
        size_map = {
            "large": AssetSize.LARGE_CAP,
            "mid": AssetSize.MID_CAP,
            "small": AssetSize.SMALL_CAP,
        }
        size = size_map.get(stock.size) if stock.size else None

        return AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code=stock.stock_code,
            asset_name=stock.stock_name,
            style=style,
            size=size,
            sector=stock.sector,
            custom_scores=stock.get_custom_scores(),
        )

    @staticmethod
    def _calculate_risk_level(stock: EquityAssetScore) -> str:
        """
        根据个股属性计算风险等级

        Args:
            stock: 个股资产评分实体

        Returns:
            风险等级字符串
        """
        # 基于行业和市值的综合风险判断
        sector_risk = {
            "银行": "中低风险",
            "交通运输": "中低风险",
            "公用事业": "中低风险",
            "食品饮料": "中风险",
            "医药生物": "中风险",
            "电子": "中高风险",
            "计算机": "中高风险",
            "传媒": "高风险",
            "国防军工": "高风险",
        }

        base_risk = sector_risk.get(stock.sector, "中风险")

        # 根据市值调整
        if stock.size == "small":
            if base_risk == "中低风险":
                base_risk = "中风险"
            elif base_risk == "中风险":
                base_risk = "中高风险"
        elif stock.size == "large":
            if base_risk == "高风险":
                base_risk = "中高风险"
            elif base_risk == "中高风险":
                base_risk = "中风险"

        # 根据财务状况调整（高资产负债率增加风险）
        if stock.debt_ratio and stock.debt_ratio > 70:
            if base_risk == "中低风险":
                base_risk = "中风险"
            elif base_risk == "中风险":
                base_risk = "中高风险"

        return base_risk
